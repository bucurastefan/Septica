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

class SepticaGame:
    SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
    VALUES = ['7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    
    def __init__(self):
        self.deck = []
        self.players = {i: [] for i in range(4)}  # Player hands
        self.current_player = 0
        self.current_trick = []
        self.scores = {0: 0, 1: 0}  # Team scores
        self.trump_suit = None
        self.first_suit = None  # Suit that must be followed
        self.initialize_game()
    
    def initialize_game(self):
        # Create and shuffle deck
        self.deck = [Card(s, v) for s in self.SUITS for v in self.VALUES]
        random.shuffle(self.deck)
        
        # Deal initial cards (4 each)
        for _ in range(4):
            for player in range(4):
                if self.deck:
                    self.players[player].append(self.deck.pop())
        
        # Set trump suit from next card
        if self.deck:
            trump_card = self.deck[-1]
            self.trump_suit = trump_card.suit
    
    def get_valid_moves(self, player_id):
        if not self.current_trick:
            return [i for i in range(len(self.players[player_id]))]
        
        first_card = self.current_trick[0][1]
        player_hand = self.players[player_id]
        
        # Must follow suit if possible
        valid_moves = [i for i, card in enumerate(player_hand) 
                      if card.suit == first_card.suit]
        
        if not valid_moves:
            # If can't follow suit, any card is valid
            valid_moves = list(range(len(player_hand)))
            
        return valid_moves
    
    def play_card(self, player_id, card_index):
        if player_id != self.current_player:
            return False, "Not your turn"
            
        if card_index >= len(self.players[player_id]):
            return False, "Invalid card index"
            
        if not self.is_valid_move(player_id, card_index):
            return False, "Invalid move - must follow suit if possible"
        
        # Play the card
        card = self.players[player_id].pop(card_index)
        self.current_trick.append((player_id, card))
        
        # If trick is complete, determine winner
        if len(self.current_trick) == 4:
            winner = self.determine_trick_winner()
            self.end_trick(winner)
        else:
            self.current_player = (self.current_player + 1) % 4
            
        return True, None
    
    def is_valid_move(self, player_id, card_index):
        valid_moves = self.get_valid_moves(player_id)
        return card_index in valid_moves
    
    def determine_trick_winner(self):
        first_player, first_card = self.current_trick[0]
        winning_player = first_player
        winning_card = first_card
        
        for player, card in self.current_trick[1:]:
            if card.suit == winning_card.suit:
                if self.VALUES.index(card.value) > self.VALUES.index(winning_card.value):
                    winning_player = player
                    winning_card = card
            elif card.suit == self.trump_suit:
                if winning_card.suit != self.trump_suit:
                    winning_player = player
                    winning_card = card
        
        return winning_player
    
    def end_trick(self, winner):
        # Calculate points
        points = 0
        for _, card in self.current_trick:
            if card.value == '10': points += 10
            elif card.value == 'A': points += 2
            elif card.value == 'J': points += 1
            elif card.value == 'Q': points += 3
            elif card.value == 'K': points += 4
        
        # Add points to winner's team (0 or 1)
        team = winner % 2
        self.scores[team] += points
        
        # Deal new cards if available
        if self.deck:
            for player in range(winner, winner + 4):
                if self.deck:
                    self.players[player % 4].append(self.deck.pop())
        
        # Clear trick and set next player
        self.current_trick = []
        self.current_player = winner
    
    def get_game_state(self, player_id):
        return {
            'hand': [card.to_dict() for card in self.players[player_id]],
            'current_trick': [(p, card.to_dict()) for p, card in self.current_trick],
            'current_player': self.current_player,
            'trump_suit': self.trump_suit,
            'scores': self.scores,
            'cards_in_deck': len(self.deck),
            'game_over': all(len(hand) == 0 for hand in self.players.values())
        }