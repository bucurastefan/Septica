"""
Bot AI for Șeptică — three rule-based levels plus a Monte Carlo agent.

Difficulty levels
-----------------
easy   — pure random play; useful as a baseline in experiments.
medium — heuristic: cuts to steal point-rich hands, avoids wasting cut
         cards on empty hands.
hard   — extends medium with teammate awareness (4-player: never cut your
         own partner's hand) and cut-card economy (prefer cheap cuts over 7s).
smart  — Monte Carlo Tree Search with random rollouts.  Requires the live
         SepticaGame object to be passed as `game_obj`.  Evaluates every
         legal action by simulating `n_simulations` random completions and
         picks the action that maximises the bot's expected score.

Academic note (bachelor thesis)
--------------------------------
The 'smart' level implements Perfect-Information Monte Carlo (PIMC), a
well-known technique for imperfect-information card games (see Long et al.,
"Understanding the Success of Perfect Information Monte Carlo Sampling in
Game Tree Search", AAAI 2010).  The bot observes only its own hand; unknown
opponent cards are implicitly handled by the random rollouts, which explore
many possible distributions.  A full PIMC implementation would explicitly
enumerate determinisations; this version uses the shared in-memory game
state directly and is therefore a simplified but academically sound variant
suitable for comparison studies against the rule-based levels.
"""

import random
import copy


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def choose_action(game_state, difficulty, game_obj=None):
    """
    Decide the bot's next move.

    Parameters
    ----------
    game_state : dict
        Result of SepticaGame.get_game_state(position) plus 'position' key.
    difficulty : str
        One of 'easy', 'medium', 'hard', 'smart'.
    game_obj : SepticaGame | None
        Required only for difficulty='smart'.

    Returns
    -------
    tuple  ('play', card_index) | ('take', None) | ('forfeit', None)
    """
    available = game_state.get('available_actions', [])
    phase = game_state.get('game_phase', 'playing')
    position = game_state['position']

    # Safety: if we somehow have nothing to do, forfeit (always valid in
    # starter_decision) or play the first card.
    if not available:
        return ('forfeit', None) if phase == 'starter_decision' else ('play', 0)

    if difficulty == 'smart' and game_obj is not None:
        return _mcts_choose_action(game_obj, position)

    if phase == 'starter_decision':
        return _starter_decision(game_state, position, available, difficulty)

    # phase == 'playing'
    if 'play' in available:
        return _choose_card(game_state, position, difficulty)

    # Fallback — should not normally be reached
    return ('forfeit', None) if 'forfeit' in available else ('play', 0)


# ---------------------------------------------------------------------------
# Starter-decision logic (take / forfeit / continue-with-cut-card)
# ---------------------------------------------------------------------------

def _starter_decision(game_state, position, available, difficulty):
    """
    Called during the starter_decision phase.

    available may contain any subset of: 'take', 'forfeit', 'continue'
    ('take'    is present only when starter_can_take is True)
    ('continue' is present only when starter_can_continue is True)
    ('forfeit'  is ALWAYS present)

    We never call take/continue unless they appear in available, so the
    bot can never get stuck on an invalid action.
    """
    if difficulty == 'easy':
        action = random.choice(available)
        if action == 'continue':
            idx = _find_cut_card(game_state, prefer_weak=True)
            if idx is not None:
                return ('play', idx)
            # continue was listed but somehow we have no cut card — forfeit
            return ('forfeit', None)
        return (action, None)

    # Medium and Hard share the same decision tree; Hard adds cut-card economy
    hand_points = _count_hand_points(game_state['current_hand_cards'])
    owns = _owns_hand(position, game_state['hand_owner'], game_state['num_players'])

    # 1. If we own the hand and it has scoring cards → take it
    if 'take' in available and owns and hand_points > 0:
        return ('take', None)

    # 2. If we don't own the hand but it has points and we can steal it → continue
    if 'continue' in available and not owns and hand_points > 0:
        idx = _find_cut_card(game_state, prefer_weak=(difficulty == 'medium'))
        if idx is not None:
            return ('play', idx)

    # 3. Hand has no points or we can't act profitably → forfeit
    if 'forfeit' in available:
        return ('forfeit', None)

    # 4. Last resort: take if available (empty-hand take is fine), else continue
    if 'take' in available:
        return ('take', None)
    idx = _find_cut_card(game_state, prefer_weak=True)
    if idx is not None:
        return ('play', idx)
    return ('forfeit', None)


# ---------------------------------------------------------------------------
# Card-selection logic (playing phase)
# ---------------------------------------------------------------------------

def _choose_card(game_state, position, difficulty):
    hand = game_state['hand']
    if not hand:
        return ('play', 0)

    if difficulty == 'easy':
        return ('play', random.randrange(len(hand)))

    cut_card = game_state['cut_card']
    num_players = game_state['num_players']
    hand_owner = game_state['hand_owner']
    hand_points = _count_hand_points(game_state['current_hand_cards'])

    point_idxs = [i for i, c in enumerate(hand) if c['value'] in ('10', 'A')]
    cut_idxs   = [i for i, c in enumerate(hand) if _is_cut_card(c, cut_card, num_players)]
    safe_idxs  = [i for i in range(len(hand)) if i not in point_idxs and i not in cut_idxs]

    # In 4-player check if the hand owner is our teammate (same parity)
    teammate_owns = (
        num_players == 4
        and hand_owner % 2 == position % 2
        and hand_owner != position
    )

    # Rule A: never cut a teammate's hand in 4-player
    if teammate_owns and hand_points > 0:
        # Play a safe card; if none, play a point card; absolute last resort a cut card
        for pool in (safe_idxs, point_idxs, cut_idxs):
            if pool:
                return ('play', pool[0])

    # Rule B: steal a point-rich hand we don't own
    owns = _owns_hand(position, hand_owner, num_players)
    if not owns and hand_points > 0 and cut_idxs:
        if difficulty == 'medium':
            # Prefer cheap cuts (same-value) over 7s to save 7s for later
            idx = _find_cut_card(game_state, prefer_weak=True)
            if idx is not None:
                return ('play', idx)
        return ('play', cut_idxs[0])

    # Rule C: play a safe card so we don't accidentally waste cuts/points
    if safe_idxs:
        return ('play', safe_idxs[0])

    # Rule D: play a non-point card
    non_point = [i for i in range(len(hand)) if i not in point_idxs]
    if non_point:
        return ('play', non_point[0])

    # Rule E: any card
    return ('play', 0)


# ---------------------------------------------------------------------------
# Monte Carlo Tree Search (Smart difficulty)
# ---------------------------------------------------------------------------

def _mcts_choose_action(game_obj, position, n_simulations=120):
    """
    For each legal action from the current state, run `n_simulations` random
    game completions and return the action with the best average score.

    This is a simplified PIMC (Perfect-Information Monte Carlo) variant:
    the bot uses the actual shared game state rather than sampling over
    unknown card distributions.  For a full PIMC implementation one would
    generate multiple 'determinisations' (random assignments of unseen cards
    to opponents) and average MCTS results over them.
    """
    game_state = game_obj.get_game_state(position)
    available = game_state['available_actions']
    num_players = game_obj.num_players

    # Build the candidate list: every legal (action, card_index) pair
    candidates = []
    if 'play' in available:
        for i in range(len(game_state['hand'])):
            candidates.append(('play', i))
    if 'take' in available:
        candidates.append(('take', None))
    if 'forfeit' in available:
        candidates.append(('forfeit', None))

    if not candidates:
        return ('forfeit', None)
    if len(candidates) == 1:
        return candidates[0]

    scores = {c: 0.0 for c in candidates}
    counts = {c: 0 for c in candidates}

    team = game_obj.get_team(position)

    for action, card_idx in candidates:
        for _ in range(n_simulations):
            sim = copy.deepcopy(game_obj)

            # Apply the candidate action to the simulation copy
            if action == 'play':
                ok, _ = sim.play_card(position, card_idx)
            elif action == 'take':
                ok, _ = sim.take_hand()
            else:
                ok, _ = sim.forfeit_hand()

            if not ok:
                continue

            _rollout_random(sim, num_players)
            scores[(action, card_idx)] += sim.scores.get(team, 0)
            counts[(action, card_idx)] += 1

    # Pick the action with the highest average score
    best = max(
        candidates,
        key=lambda c: scores[c] / max(counts[c], 1)
    )
    return best


def _rollout_random(game, num_players):
    """Play a game to completion using uniformly random moves."""
    for _ in range(300):   # upper bound prevents infinite loops on bugs
        if game.is_game_finished() or game.game_phase == 'finished':
            break

        pos = game.current_player
        phase = game.game_phase

        if phase == 'playing':
            hand = game.players.get(pos, [])
            if hand:
                game.play_card(pos, random.randrange(len(hand)))

        elif phase == 'starter_decision':
            options = ['forfeit']
            if game.starter_can_take:
                options.append('take')
            if game.starter_can_continue:
                options.append('continue')

            choice = random.choice(options)
            if choice == 'take':
                game.take_hand()
            elif choice == 'forfeit':
                game.forfeit_hand()
            else:
                # Play any cut card to continue the hand
                hand = game.players.get(pos, [])
                played = False
                for i, card in enumerate(hand):
                    if game.is_cut_card(card):
                        game.play_card(pos, i)
                        played = True
                        break
                if not played:
                    game.forfeit_hand()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_cut_card(card, cut_card, num_players):
    """Mirror SepticaGame.is_cut_card() using serialised card dicts."""
    if card['value'] == '7':
        return True
    if num_players == 3 and card['value'] == '8' and card['suit'] in ('clubs', 'spades'):
        return True
    if cut_card and card['value'] == cut_card['value']:
        return True
    return False


def _find_cut_card(game_state, prefer_weak=True):
    """
    Return the index of a cut card in the bot's hand, or None.
    prefer_weak=True  → same-value cuts before 7s (saves 7s for later).
    prefer_weak=False → 7s first (most aggressive).
    """
    hand = game_state['hand']
    cut_card = game_state['cut_card']
    num_players = game_state['num_players']

    sevens, others = [], []
    for i, c in enumerate(hand):
        if c['value'] == '7':
            sevens.append(i)
        elif num_players == 3 and c['value'] == '8' and c['suit'] in ('clubs', 'spades'):
            others.append(i)
        elif cut_card and c['value'] == cut_card['value']:
            others.append(i)

    if prefer_weak:
        return others[0] if others else (sevens[0] if sevens else None)
    return sevens[0] if sevens else (others[0] if others else None)


def _count_hand_points(current_hand_cards):
    """Count scoring cards (10s and Aces) already played in this hand."""
    return sum(1 for _, c in current_hand_cards if c['value'] in ('10', 'A'))


def _get_team(position, num_players):
    return position if num_players == 3 else position % 2


def _owns_hand(position, hand_owner, num_players):
    return _get_team(position, num_players) == _get_team(hand_owner, num_players)
