"""
Unit tests for game/logic.py — SepticaGame core rules.

These tests cover: deck setup, dealing, cut-card detection, hand resolution,
scoring, winner detection, and 3-player vs 4-player differences.  All tests
run without Flask or a database (pure Python).
"""

import pytest
from game.logic import Card, SepticaGame


# ── Card ──────────────────────────────────────────────────────────────────────

class TestCard:
    def test_is_points_card_ten(self):
        assert Card('spades', '10').is_points_card()

    def test_is_points_card_ace(self):
        assert Card('hearts', 'A').is_points_card()

    def test_non_points_card(self):
        assert not Card('clubs', '7').is_points_card()
        assert not Card('diamonds', 'K').is_points_card()

    def test_is_seven(self):
        assert Card('spades', '7').is_seven()
        assert not Card('spades', '8').is_seven()

    def test_equality(self):
        assert Card('hearts', 'K') == Card('hearts', 'K')
        assert Card('hearts', 'K') != Card('spades', 'K')

    def test_to_dict(self):
        d = Card('clubs', 'J').to_dict()
        assert d == {'suit': 'clubs', 'value': 'J'}


# ── Deck & dealing ────────────────────────────────────────────────────────────

class TestDeckSetup:
    def test_4player_deck_size(self):
        # Deck is 7-through-Ace in 4 suits = 8 values × 4 suits = 32 cards
        game = SepticaGame(num_players=4)
        total = len(game.deck) + sum(len(game.players[i]) for i in range(4))
        assert total == 32

    def test_3player_deck_size(self):
        game = SepticaGame(num_players=3)
        total = len(game.deck) + sum(len(game.players[i]) for i in range(3))
        assert total == 30  # 52 - 2 removed eights

    def test_4player_initial_hand_size(self):
        game = SepticaGame(num_players=4)
        for i in range(4):
            assert len(game.players[i]) == 4

    def test_3player_initial_hand_size(self):
        game = SepticaGame(num_players=3)
        for i in range(3):
            assert len(game.players[i]) == 4

    def test_3player_no_removed_eights(self):
        game = SepticaGame(num_players=3)
        removed = {('hearts', '8'), ('diamonds', '8')}
        all_cards = list(game.deck)
        for i in range(3):
            all_cards.extend(game.players[i])
        for card in all_cards:
            assert (card.suit, card.value) not in removed

    def test_starting_player_rotation(self):
        assert SepticaGame.calculate_starting_player(0, 4) == 0
        assert SepticaGame.calculate_starting_player(1, 4) == 1
        assert SepticaGame.calculate_starting_player(4, 4) == 0
        assert SepticaGame.calculate_starting_player(0, 3) == 0
        assert SepticaGame.calculate_starting_player(3, 3) == 0


# ── Cut-card detection ────────────────────────────────────────────────────────

class TestCutCard:
    def test_seven_always_cuts(self):
        game = SepticaGame(num_players=4)
        assert game.is_cut_card(Card('clubs', '7'))
        assert game.is_cut_card(Card('hearts', '7'))

    def test_wild_eight_cuts_in_3player(self):
        game = SepticaGame(num_players=3)
        assert game.is_cut_card(Card('clubs', '8'))
        assert game.is_cut_card(Card('spades', '8'))

    def test_wild_eight_does_not_cut_in_4player(self):
        game = SepticaGame(num_players=4)
        assert not game.is_cut_card(Card('clubs', '8'))

    def test_removed_eight_does_not_cut_in_3player(self):
        game = SepticaGame(num_players=3)
        assert not game.is_cut_card(Card('hearts', '8'))
        assert not game.is_cut_card(Card('diamonds', '8'))

    def test_same_value_cuts_when_cut_card_set(self):
        game = SepticaGame(num_players=4)
        game.cut_card = Card('hearts', 'K')
        assert game.is_cut_card(Card('spades', 'K'))
        assert not game.is_cut_card(Card('spades', 'Q'))

    def test_no_cut_without_cut_card(self):
        game = SepticaGame(num_players=4)
        game.cut_card = None
        assert not game.is_cut_card(Card('spades', 'K'))


# ── Team mapping ──────────────────────────────────────────────────────────────

class TestTeams:
    def test_4player_teams(self):
        game = SepticaGame(num_players=4)
        assert game.get_team(0) == 0
        assert game.get_team(1) == 1
        assert game.get_team(2) == 0
        assert game.get_team(3) == 1

    def test_3player_each_own_team(self):
        game = SepticaGame(num_players=3)
        for i in range(3):
            assert game.get_team(i) == i


# ── Game flow helpers ─────────────────────────────────────────────────────────

def _play_full_hand_no_points(game):
    """
    Drive the game through one complete hand without scoring:
    each player plays a non-cut, non-points card, then the starter forfeits.
    """
    for i in range(game.num_players):
        pos = game.current_player
        hand = game.players[pos]
        # Find a safe card (not 7, not 10/A)
        idx = next(
            (j for j, c in enumerate(hand)
             if c.value not in ('7', '10', 'A') and not game.is_cut_card(c)),
            0
        )
        game.play_card(pos, idx)
    # After a full round the starter decides
    if game.game_phase == 'starter_decision':
        game.forfeit_hand()


# ── Scoring ───────────────────────────────────────────────────────────────────

class TestScoring:
    def test_initial_scores_zero(self):
        game = SepticaGame(num_players=4)
        assert game.scores == {0: 0, 1: 0}

    def test_points_card_increments_score(self):
        """Hand owner taking a hand with one 10 gets 1 point."""
        game = SepticaGame(starting_player=0, num_players=4)
        # Replace player 0's first card with 10♠ so the hand has a points card
        game.players[0][0] = Card('spades', '10')
        # Player 0 plays the 10 first — becomes cut_card and hand_owner
        game.play_card(0, 0)
        # Everyone else plays a safe non-cut card
        for pos in range(1, 4):
            hand = game.players[pos]
            idx = next(
                (j for j, c in enumerate(hand) if not game.is_cut_card(c) and not c.is_points_card()),
                0
            )
            game.play_card(pos, idx)
        # Starter (pos 0) gets starter_decision; take the hand
        assert game.game_phase == 'starter_decision'
        assert game.starter_can_take
        game.take_hand()
        assert game.scores[0] == 1  # team 0 scored 1 point (the 10)

    def test_empty_hand_scores_nothing(self):
        """Forfeiting a hand with no points cards changes no scores."""
        game = SepticaGame(starting_player=0, num_players=4)
        before = dict(game.scores)
        # Ensure first card is not a points card
        first_card = game.players[0][0]
        if first_card.is_points_card():
            pytest.skip("Random deck gave points card as first; skip this run")
        game.play_card(0, 0)
        for pos in range(1, 4):
            hand = game.players[pos]
            idx = next((j for j, c in enumerate(hand) if not game.is_cut_card(c) and not c.is_points_card()), 0)
            game.play_card(pos, idx)
        game.forfeit_hand()
        assert game.scores == before


# ── Game completion ───────────────────────────────────────────────────────────

class TestGameCompletion:
    def _run_game_to_finish(self, num_players=4):
        """Play a complete game using random-but-valid moves."""
        import random
        game = SepticaGame(starting_player=0, num_players=num_players)
        for _ in range(1000):
            if game.game_phase == 'finished':
                break
            pos = game.current_player
            if game.game_phase == 'starter_decision':
                options = []
                if game.starter_can_take:
                    options.append('take')
                options.append('forfeit')
                choice = random.choice(options)
                if choice == 'take':
                    game.take_hand()
                else:
                    game.forfeit_hand()
            else:
                hand = game.players[pos]
                game.play_card(pos, random.randrange(len(hand)))
        return game

    def test_4player_game_finishes(self):
        game = self._run_game_to_finish(4)
        assert game.game_phase == 'finished'

    def test_3player_game_finishes(self):
        game = self._run_game_to_finish(3)
        assert game.game_phase == 'finished'

    def test_4player_total_points_at_most_8(self):
        # Any 10 or A scores 1 point; 4 tens + 4 aces = 8 points total in the deck
        game = self._run_game_to_finish(4)
        total = sum(game.scores.values())
        assert total <= 8

    def test_winner_or_tie(self):
        game = self._run_game_to_finish(4)
        result = game.get_game_result()
        assert result['finished'] is True
        if result['is_tie']:
            assert result['winner'] is None
        else:
            assert result['winner'] in (0, 1)

    def test_get_game_state_structure(self):
        game = SepticaGame(num_players=4)
        state = game.get_game_state(0)
        expected_keys = {
            'hand', 'current_hand_cards', 'current_round_cards',
            'current_player', 'starter_player', 'hand_owner',
            'cut_card', 'scores', 'hands_won', 'cards_in_deck',
            'hand_sizes', 'game_phase', 'available_actions',
            'starter_can_take', 'starter_can_continue', 'game_over',
            'num_players',
        }
        assert expected_keys.issubset(state.keys())

    def test_not_your_turn_error(self):
        game = SepticaGame(starting_player=0, num_players=4)
        success, msg = game.play_card(1, 0)  # player 1 acts when it's player 0's turn
        assert not success
        assert msg == "Not your turn"
