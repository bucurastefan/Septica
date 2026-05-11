import random


class Card:
    def __init__(self, suit, value):
        self.suit = suit
        self.value = value

    def to_dict(self):
        return {'suit': self.suit, 'value': self.value}

    def is_points_card(self):
        return self.value in ['10', 'A']

    def is_seven(self):
        return self.value == '7'

    def __eq__(self, other):
        return self.suit == other.suit and self.value == other.value


class SepticaGame:
    SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
    VALUES = ['7', '8', '9', '10', 'J', 'Q', 'K', 'A']

    # In 3-player mode these two eights are removed from the deck entirely
    REMOVED_EIGHTS = {('hearts', '8'), ('diamonds', '8')}
    # The remaining two eights act exactly like 7s — they cut any card
    WILD_EIGHTS = {('clubs', '8'), ('spades', '8')}

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_starting_player(total_games_played, num_players=4):
        return total_games_played % num_players

    def __init__(self, starting_player=0, num_players=4):
        self.num_players = num_players

        self.deck = []
        self.players = {i: [] for i in range(num_players)}
        # In 3-player each key is a player index (they are their own team).
        # In 4-player keys 0/1 represent the two teams (positions 0,2 → team 0;
        # positions 1,3 → team 1).
        self.scores = {i: 0 for i in range(num_players if num_players == 3 else 2)}
        self.hands_won = {i: 0 for i in range(num_players if num_players == 3 else 2)}

        self.current_hand_cards = []
        self.current_round_cards = []
        self.starter_player = starting_player
        self.hand_owner = starting_player
        self.current_player = starting_player
        self.cut_card = None

        self.game_phase = "playing"
        self.starter_can_take = False
        self.starter_can_continue = False

        self.initialize_game()

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def initialize_game(self):
        if self.num_players == 3:
            # 30-card deck: remove 8♥ and 8♦
            self.deck = [
                Card(s, v) for s in self.SUITS for v in self.VALUES
                if (s, v) not in self.REMOVED_EIGHTS
            ]
        else:
            self.deck = [Card(s, v) for s in self.SUITS for v in self.VALUES]
        random.shuffle(self.deck)
        self.deal_cards()

    def deal_cards(self):
        """Deal cards up to the per-player cap, starting from the starter."""
        if not self.deck:
            return

        current = len(self.players[0])
        total = len(self.deck) + current * self.num_players

        # Both modes use the same rule: max 4 cards per player.
        # Deal 4 at the start, then top-up by 1 after each hand until the deck runs out.
        cap = 4
        target = min(cap, total // self.num_players)
        to_deal = target - current

        if to_deal > 0 and len(self.deck) >= to_deal * self.num_players:
            for _ in range(to_deal):
                for i in range(self.num_players):
                    pid = (self.starter_player + i) % self.num_players
                    if self.deck:
                        self.players[pid].append(self.deck.pop())

    # ------------------------------------------------------------------ #
    # Team / cut-card helpers                                              #
    # ------------------------------------------------------------------ #

    def get_team(self, player_id):
        """
        4-player: players 0,2 share team 0; players 1,3 share team 1.
        3-player: every player is their own team — no shared scoring.
        """
        if self.num_players == 3:
            return player_id
        return player_id % 2

    def is_cut_card(self, card):
        """
        A card cuts if it is:
          - any 7 (always, both modes)
          - 8♣ or 8♠ (3-player only — wild eights that act like 7s)
          - the same value as the current hand's cut card
        """
        if card.is_seven():
            return True
        if self.num_players == 3 and (card.suit, card.value) in self.WILD_EIGHTS:
            return True
        if self.cut_card and card.value == self.cut_card.value:
            return True
        return False

    def has_cut_card(self, player_id):
        return any(self.is_cut_card(c) for c in self.players[player_id])

    # ------------------------------------------------------------------ #
    # Card play                                                            #
    # ------------------------------------------------------------------ #

    def play_card(self, player_id, card_index):
        if player_id != self.current_player:
            return False, "Not your turn"
        if card_index >= len(self.players[player_id]):
            return False, "Invalid card index"

        if self.game_phase == "starter_decision":
            return self.handle_starter_decision(player_id, card_index)
        elif self.game_phase == "playing":
            return self.handle_regular_play(player_id, card_index)
        return False, "Game is finished"

    def handle_regular_play(self, player_id, card_index):
        card = self.players[player_id].pop(card_index)

        if len(self.current_hand_cards) == 0:
            # First card of the hand sets the cut card and initial owner
            self.cut_card = card
            self.hand_owner = player_id
        elif self.is_cut_card(card):
            # Any cut card (7, wild 8 in 3-player, or same-value) transfers ownership
            self.hand_owner = player_id

        self.current_round_cards.append((player_id, card))
        self.current_hand_cards.append((player_id, card))

        if len(self.current_round_cards) == self.num_players:
            return self.complete_round()

        self.current_player = (self.current_player + 1) % self.num_players
        return True, None

    def complete_round(self):
        self.current_round_cards = []
        next_player = (self.current_player + 1) % self.num_players

        if next_player == self.starter_player:
            # Full rotation done — starter decides what to do with the hand
            self.game_phase = "starter_decision"
            self.current_player = self.starter_player
            self.starter_can_take = (self.hand_owner == self.starter_player)
            self.starter_can_continue = self.has_cut_card(self.starter_player)
        else:
            self.current_player = next_player

        return True, None

    def handle_starter_decision(self, player_id, card_index):
        if player_id != self.starter_player:
            return False, "Only the starter can make this decision"

        card = self.players[player_id][card_index]
        if self.is_cut_card(card):
            return self.continue_hand(card_index)
        return False, "You must play a cut card (7, wild 8, or matching value)"

    def continue_hand(self, card_index):
        """Starter plays a cut card — they retake ownership and the round continues."""
        card = self.players[self.starter_player].pop(card_index)
        self.current_round_cards.append((self.starter_player, card))
        self.current_hand_cards.append((self.starter_player, card))
        self.hand_owner = self.starter_player
        self.game_phase = "playing"
        self.current_player = (self.current_player + 1) % self.num_players
        return True, None

    # ------------------------------------------------------------------ #
    # Hand resolution                                                      #
    # ------------------------------------------------------------------ #

    def take_hand(self):
        if self.current_player != self.starter_player or self.game_phase != "starter_decision":
            return False, "Can only take hand during starter decision"
        if not self.starter_can_take:
            return False, "You are not the hand owner, cannot take hand"
        return self.resolve_hand()

    def forfeit_hand(self):
        if self.current_player != self.starter_player or self.game_phase != "starter_decision":
            return False, "Can only forfeit during starter decision"
        return self.resolve_hand()

    def resolve_hand(self):
        """Award points to the hand owner's team (or the owner themselves in 3-player)."""
        points = sum(1 for _, card in self.current_hand_cards if card.is_points_card())
        team = self.get_team(self.hand_owner)   # player index in 3-player, team index in 4-player
        self.scores[team] += points
        self.hands_won[team] += 1

        # Hand owner always starts the next hand
        self.starter_player = self.hand_owner
        self.current_player = self.starter_player

        self.current_hand_cards = []
        self.current_round_cards = []
        self.cut_card = None
        self.game_phase = "playing"
        self.starter_can_take = False
        self.starter_can_continue = False

        self.deal_cards()

        if self.is_game_finished():
            self.game_phase = "finished"

        return True, None

    # ------------------------------------------------------------------ #
    # End-game                                                             #
    # ------------------------------------------------------------------ #

    def is_game_finished(self):
        if self.deck:
            return False
        return all(len(self.players[i]) == 0 for i in range(self.num_players))

    def get_winner(self):
        """
        4-player: returns 0 (team purple) or 1 (team black) or None for tie.
        3-player: returns the winning player index (0, 1, or 2) or None for tie.
        """
        max_score = max(self.scores.values())
        winners = [k for k, v in self.scores.items() if v == max_score]
        if len(winners) > 1:
            return None  # tie
        return winners[0]

    def get_game_result(self):
        winner = self.get_winner()
        return {
            'finished': True,
            'winner': winner,
            'scores': self.scores.copy(),
            'hands_won': self.hands_won.copy(),
            'is_tie': winner is None,
            'num_players': self.num_players,
        }

    # ------------------------------------------------------------------ #
    # State serialisation                                                  #
    # ------------------------------------------------------------------ #

    def get_game_state(self, player_id):
        available_actions = []
        if self.current_player == player_id:
            if self.game_phase == "starter_decision":
                if self.starter_can_take:
                    available_actions.append("take")
                available_actions.append("forfeit")
                if self.starter_can_continue:
                    available_actions.append("continue")
            elif self.game_phase == "playing":
                available_actions.append("play")

        return {
            'hand': [c.to_dict() for c in self.players[player_id]],
            'current_hand_cards': [(p, c.to_dict()) for p, c in self.current_hand_cards],
            'current_round_cards': [(p, c.to_dict()) for p, c in self.current_round_cards],
            'current_player': self.current_player,
            'starter_player': self.starter_player,
            'hand_owner': self.hand_owner,
            'cut_card': self.cut_card.to_dict() if self.cut_card else None,
            'scores': self.scores,
            'hands_won': self.hands_won,
            'cards_in_deck': len(self.deck),
            'hand_sizes': [len(self.players[i]) for i in range(self.num_players)],
            'game_phase': self.game_phase,
            'available_actions': available_actions,
            'starter_can_take': self.starter_can_take,
            'starter_can_continue': self.starter_can_continue,
            'game_over': self.game_phase == "finished",
            'num_players': self.num_players,
        }
