import random

class Card:
    def __init__(self, suit, value):
        self.suit = suit
        self.value = value
        
    def to_dict(self):
        return {
            'suit': self.suit,
            'value': self.value
        }
    
    def is_points_card(self):
        return self.value in ['10', 'A']
    
    def is_seven(self):
        return self.value == '7'
    
    def __eq__(self, other):
        return self.suit == other.suit and self.value == other.value

class SepticaGame:
    SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
    VALUES = ['7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    
    @staticmethod
    def calculate_starting_player(total_games_played):
        """
        Calculate the starting player based on the rotation pattern:
        Game 0: Player 0 (Team Purple, Player 1)
        Game 1: Player 1 (Team Black, Player 1) 
        Game 2: Player 2 (Team Purple, Player 2)
        Game 3: Player 3 (Team Black, Player 2)
        Game 4: Player 0 (cycle repeats)
        
        Pattern: first player team one (0), then first player team two (1), 
                then second player team one (2), then second player team two (3)
        """
        return total_games_played % 4
    
    def __init__(self, starting_player=0):
        self.deck = []
        self.players = {i: [] for i in range(4)}  # Player hands
        self.scores = {0: 0, 1: 0}  # Team scores (Team 0: players 0,2; Team 1: players 1,3)
        self.hands_won = {0: 0, 1: 0}  # Track hands won by each team
        
        # Hand state
        self.current_hand_cards = []  # All cards played in current hand
        self.current_round_cards = []  # Cards played in current round (max 4)
        self.starter_player = starting_player  # Player who starts the hand
        self.hand_owner = starting_player  # Current owner of the hand
        self.current_player = starting_player  # Whose turn it is
        self.cut_card = None  # The cut card for current hand (first card played)
        
        # Game state
        self.game_phase = "playing"  # "playing", "starter_decision", "finished"
        self.starter_can_take = False  # If starter can take the hand
        self.starter_can_continue = False  # If starter can continue with cut card
        
        self.initialize_game()
    
    def initialize_game(self):
        # Create and shuffle deck
        self.deck = [Card(s, v) for s in self.SUITS for v in self.VALUES]
        random.shuffle(self.deck)
        
        # Deal initial cards equally
        self.deal_cards()
        
        # Game starts with the specified starting player
        # starter_player, hand_owner, and current_player are already set in __init__
    
    def deal_cards(self):
        """Deal cards so all players have the same number (max 4 each), starting from starter player"""
        # Don't deal if deck is empty
        if not self.deck:
            return
        
        # Find current number of cards each player has (should be same for all)
        current_cards_per_player = len(self.players[0])
        
        # Calculate maximum cards each player can have with remaining deck
        total_available = len(self.deck) + (current_cards_per_player * 4)
        max_cards_per_player = min(4, total_available // 4)
        
        # Calculate how many cards to deal to each player
        cards_to_deal_per_player = max_cards_per_player - current_cards_per_player
        
        # Only deal if we can give the same amount to everyone
        if cards_to_deal_per_player > 0 and len(self.deck) >= (cards_to_deal_per_player * 4):
            # Deal the same number of cards to each player
            for _ in range(cards_to_deal_per_player):
                for i in range(4):
                    player_id = (self.starter_player + i) % 4
                    if self.deck:
                        self.players[player_id].append(self.deck.pop())

    
    def get_team(self, player_id):
        """Get team number for player (0 or 1)"""
        return player_id % 2
    
    def is_cut_card(self, card):
        """Check if card is a cut card (7 or same suit/value as current hand's cut card)"""
        if card.is_seven():
            return True
        if card.value == self.cut_card.value:
            return True
        return False
    
    def has_cut_card(self, player_id):
        """Check if player has any cut cards"""
        for card in self.players[player_id]:
            if self.is_cut_card(card):
                return True
        return False
    
    def play_card(self, player_id, card_index):
        """Play a card"""
        if player_id != self.current_player:
            return False, "Not your turn"
            
        if card_index >= len(self.players[player_id]):
            return False, "Invalid card index"
        
        # Handle different game phases
        if self.game_phase == "starter_decision":
            return self.handle_starter_decision(player_id, card_index)
        elif self.game_phase == "playing":
            return self.handle_regular_play(player_id, card_index)
        else:
            return False, "Game is finished"
    
    def handle_regular_play(self, player_id, card_index):
        """Handle regular card play during hand"""
        card = self.players[player_id].pop(card_index)
        
        # If this is the first card of the hand, it becomes the cut card
        if len(self.current_hand_cards) == 0:
            self.cut_card = card
            self.hand_owner = player_id
        else:
            # Check if this card changes hand ownership (only cut cards change ownership)
            if self.is_cut_card(card):
                self.hand_owner = player_id
        
        # Add card to current round and hand
        self.current_round_cards.append((player_id, card))
        self.current_hand_cards.append((player_id, card))
        
        # Check if round is complete (4 cards played)
        if len(self.current_round_cards) == 4:
            return self.complete_round()
        else:
            # Move to next player
            self.current_player = (self.current_player + 1) % 4
            return True, None
    
    def complete_round(self):
        """Complete current round and check if starter needs to make decision"""
        # Clear current round
        self.current_round_cards = []
        
        # Check if we're back to starter player
        next_player = (self.current_player + 1) % 4
        if next_player == self.starter_player:
            # Starter needs to make decision
            self.game_phase = "starter_decision"
            self.current_player = self.starter_player
            
            # Determine starter's options
            self.starter_can_take = (self.hand_owner == self.starter_player)
            self.starter_can_continue = self.has_cut_card(self.starter_player)
            
            return True, None
        else:
            # Continue with next player
            self.current_player = next_player
            return True, None
    
    def handle_starter_decision(self, player_id, card_index):
        """Handle starter player's decision (take, forfeit, or continue)"""
        if player_id != self.starter_player:
            return False, "Only starter can make this decision"
        
        card = self.players[player_id][card_index]
        
        # Check if playing a cut card to continue
        if self.is_cut_card(card):
            # Continue the hand
            return self.continue_hand(card_index)
        else:
            return False, "You must play Cut Card"
    
    def continue_hand(self, card_index):
        """Starter plays cut card to continue hand"""
        card = self.players[self.starter_player].pop(card_index)
        
        # Add card to hand
        self.current_round_cards.append((self.starter_player, card))
        self.current_hand_cards.append((self.starter_player, card))
        
        # Starter becomes hand owner by playing cut card
        self.hand_owner = self.starter_player
        
        # Switch back to playing phase
        self.game_phase = "playing"
        
        # Next player continues
        self.current_player = (self.current_player + 1) % 4
        
        return True, None
    
    def take_hand(self):
        """Starter takes the current hand"""
        if self.current_player != self.starter_player or self.game_phase != "starter_decision":
            return False, "Can only take hand during starter decision"
        
        if not self.starter_can_take:
            return False, "You are not the hand owner, cannot take hand"
        
        return self.resolve_hand()
    
    def forfeit_hand(self):
        """Starter forfeits the current hand"""
        if self.current_player != self.starter_player or self.game_phase != "starter_decision":
            return False, "Can only forfeit during starter decision"
        
        return self.resolve_hand()
    
    def resolve_hand(self):
        """Resolve current hand - hand owner takes cards and gets points, then deal new cards"""
        # Count points from the hand
        points = 0
        for player_id, card in self.current_hand_cards:
            if card.is_points_card():
                points += 1
        
        # Add points to hand owner's team
        team = self.get_team(self.hand_owner)
        self.scores[team] += points
        
        # Track that this team won a hand
        self.hands_won[team] += 1
        
        # Hand owner becomes starter for next hand (regardless of take/forfeit)
        self.starter_player = self.hand_owner
        self.current_player = self.starter_player
        
        # Clear hand state
        self.current_hand_cards = []
        self.current_round_cards = []
        self.cut_card = None
        self.game_phase = "playing"
        self.starter_can_take = False
        self.starter_can_continue = False
        
        # Always try to deal new cards if deck has any cards
        self.deal_cards()
        
        # Check if game is finished
        if self.is_game_finished():
            self.game_phase = "finished"
        
        return True, None
    
    def is_game_finished(self):
        """Check if game is finished (no cards left anywhere)"""
        if self.deck:
            return False
        
        for player_id in range(4):
            if len(self.players[player_id]) > 0:
                return False
        
        return True
    
    def get_winner(self):
        """Get the winning team (0, 1, or None for tie)"""
        if self.scores[0] > self.scores[1]:
            return 0
        elif self.scores[1] > self.scores[0]:
            return 1
        else:
            return None  # Tie game
    
    def get_game_result(self):
        """Get comprehensive game result information"""
        winner = self.get_winner()
        return {
            'finished': True,
            'winner': winner,
            'scores': self.scores.copy(),
            'hands_won': self.hands_won.copy(),
            'is_tie': winner is None
        }
    
    
    def get_game_state(self, player_id):
        # Get hand sizes for all players
        hand_sizes = [len(self.players[i]) for i in range(4)]
        
        # Determine available actions for current player
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
            'hand': [card.to_dict() for card in self.players[player_id]],
            'current_hand_cards': [(p, card.to_dict()) for p, card in self.current_hand_cards],
            'current_round_cards': [(p, card.to_dict()) for p, card in self.current_round_cards],
            'current_player': self.current_player,
            'starter_player': self.starter_player,
            'hand_owner': self.hand_owner,
            'cut_card': self.cut_card.to_dict() if self.cut_card else None,
            'scores': self.scores,
            'hands_won': self.hands_won,
            'cards_in_deck': len(self.deck),
            'hand_sizes': hand_sizes,
            'game_phase': self.game_phase,
            'available_actions': available_actions,
            'starter_can_take': self.starter_can_take,
            'starter_can_continue': self.starter_can_continue,
            'game_over': self.game_phase == "finished"
        }