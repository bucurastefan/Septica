"""
Unit tests for game/bot_logic.py — AI decision validation.

Verifies that every difficulty level always returns a legal action and
that heuristic bots follow their stated priorities (medium/hard prefer
stealing point-rich hands; hard preserves 7s when possible).
"""

import random
import pytest
from game.logic import Card, SepticaGame
from game.bot_logic import choose_action


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(game, pos):
    state = game.get_game_state(pos)
    state['position'] = pos
    return state


def _run_until_action_needed(game, target_pos):
    """Advance until it is target_pos's turn; return state."""
    for _ in range(200):
        if game.game_phase == 'finished':
            return None
        if game.current_player == target_pos:
            return _make_state(game, target_pos)
        pos = game.current_player
        if game.game_phase == 'starter_decision':
            if game.starter_can_take:
                game.take_hand()
            else:
                game.forfeit_hand()
        else:
            hand = game.players[pos]
            game.play_card(pos, random.randrange(len(hand)))
    return None


# ── Validity — every bot returns a legal action ───────────────────────────────

@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_bot_always_returns_valid_action(difficulty):
    """Play 10 complete games; each bot move must be a legal action."""
    for _ in range(10):
        game = SepticaGame(starting_player=0, num_players=4)
        for __ in range(500):
            if game.game_phase == 'finished':
                break
            pos = game.current_player
            state = _make_state(game, pos)
            diff = difficulty if pos % 2 == 0 else 'easy'
            action, idx = choose_action(state, diff)
            assert action in ('play', 'take', 'forfeit'), f"Invalid action '{action}'"
            if action == 'play':
                assert idx is not None
                assert 0 <= idx < len(game.players[pos]), \
                    f"Card index {idx} out of range (hand size {len(game.players[pos])})"
            if action == 'play':
                game.play_card(pos, idx)
            elif action == 'take':
                ok, _ = game.take_hand()
                assert ok, "Bot chose 'take' but it was not allowed"
            else:
                ok, _ = game.forfeit_hand()
                assert ok, "Bot chose 'forfeit' but it was not allowed"


def test_smart_bot_returns_valid_action():
    """Smart bot returns a legal action and that action can be executed."""
    game = SepticaGame(starting_player=0, num_players=4)
    state = _make_state(game, 0)
    action, idx = choose_action(state, 'smart', game_obj=game)
    assert action in ('play', 'take', 'forfeit')
    if action == 'play':
        ok, _ = game.play_card(0, idx)
        assert ok


# ── Heuristic correctness ─────────────────────────────────────────────────────

def test_medium_bot_steals_point_hand():
    """
    Medium bot should play a cut card (to steal ownership) when the current
    hand contains a points card it doesn't own.
    """
    game = SepticaGame(starting_player=0, num_players=4)
    # Put a 10 on the table owned by team 1 (hand_owner = 1)
    game.current_hand_cards = [(1, Card('spades', '10'))]
    game.cut_card = Card('spades', '10')
    game.hand_owner = 1
    game.game_phase = 'playing'
    game.current_player = 2  # team 0 player

    # Give player 2 a 7 (guaranteed cut card)
    game.players[2] = [Card('hearts', '7'), Card('clubs', '9')]
    state = _make_state(game, 2)
    action, idx = choose_action(state, 'medium')
    # Medium bot should cut to steal the hand
    assert action == 'play'
    assert game.players[2][idx].value == '7', "Medium bot should use the 7 to steal a point hand"


def test_easy_bot_is_random():
    """Easy bot makes different choices over repeated calls (not always the same card)."""
    random.seed(42)
    game = SepticaGame(starting_player=0, num_players=4)
    # Give player 0 four different safe cards
    game.players[0] = [
        Card('hearts', '9'), Card('clubs', '9'),
        Card('diamonds', '9'), Card('hearts', 'J'),
    ]
    game.game_phase = 'playing'
    game.current_player = 0
    game.cut_card = None
    state = _make_state(game, 0)

    choices = set()
    for _ in range(20):
        _, idx = choose_action(state, 'easy')
        choices.add(idx)
    # With 4 cards and 20 draws, should pick more than 1 unique index
    assert len(choices) > 1, "Easy bot should randomize card selection"


def test_medium_bot_prefers_weak_cut_over_seven():
    """
    Medium bot should prefer a same-value cut (cheaper) over spending a 7
    when stealing a point-rich hand (cut-card economy).
    """
    game = SepticaGame(starting_player=0, num_players=4)
    game.current_hand_cards = [(1, Card('spades', '10'))]
    game.cut_card = Card('spades', 'K')
    game.hand_owner = 1
    game.game_phase = 'playing'
    game.current_player = 2

    # Player 2 has both a K (same-value cut) and a 7
    game.players[2] = [Card('hearts', '7'), Card('clubs', 'K'), Card('diamonds', '9')]
    state = _make_state(game, 2)
    action, idx = choose_action(state, 'medium')
    assert action == 'play'
    played = game.players[2][idx]
    assert played.value == 'K', "Medium bot should use same-value cut to save the 7"


def test_bot_does_not_cut_teammates_hand():
    """Hard bot must NOT cut a teammate's hand in 4-player mode."""
    game = SepticaGame(starting_player=0, num_players=4)
    # Hand owned by position 0 (team 0), player 2 is also team 0
    game.current_hand_cards = [(0, Card('spades', '10'))]
    game.cut_card = Card('spades', '10')
    game.hand_owner = 0          # team 0 owns the hand
    game.game_phase = 'playing'
    game.current_player = 2     # also team 0

    # Player 2 only has a 7 and a safe card
    game.players[2] = [Card('hearts', '7'), Card('clubs', '9')]
    state = _make_state(game, 2)
    action, idx = choose_action(state, 'hard')
    assert action == 'play'
    played = game.players[2][idx]
    assert played.value != '7', "Hard bot must not cut its own teammate's point hand"


# ── 3-player wild-eight rules ─────────────────────────────────────────────────

def test_wild_eight_is_treated_as_cut_card_in_3player():
    """In 3-player, 8♣ should be recognized as a cut card by is_cut_card()."""
    game = SepticaGame(num_players=3)
    assert game.is_cut_card(Card('clubs', '8'))
    assert game.is_cut_card(Card('spades', '8'))
    assert not game.is_cut_card(Card('hearts', '8'))
    assert not game.is_cut_card(Card('diamonds', '8'))
