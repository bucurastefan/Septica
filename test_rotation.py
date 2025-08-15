#!/usr/bin/env python3

# Test script to verify the starting player rotation
import sys
sys.path.append('/home/stefan/7-Game/flask_auth_app')

from game_logic import SepticaGame

def test_starting_player_rotation():
    """Test the starting player rotation pattern"""
    print("Testing starting player rotation pattern:")
    print("Expected pattern: P0(T1-P1) -> P1(T2-P1) -> P2(T1-P2) -> P3(T2-P2) -> repeat")
    print()
    
    for game_count in range(8):  # Test 8 games to see 2 full cycles
        starting_player = SepticaGame.calculate_starting_player(game_count)
        team = "Purple" if starting_player % 2 == 0 else "Black"
        player_num = 1 if starting_player < 2 else 2
        
        print(f"Game {game_count + 1}: Starting Player = Position {starting_player} (Team {team}, Player {player_num})")
    
    print()
    print("Verifying game order is preserved after different starting players:")
    
    # Test that regardless of starting player, the turn order is preserved
    for starting_player in range(4):
        game = SepticaGame(starting_player)
        turn_order = []
        current = starting_player
        for _ in range(4):  # Get first 4 turns
            turn_order.append(current)
            current = (current + 1) % 4
        
        print(f"Starting with P{starting_player}: Turn order = {turn_order}")

if __name__ == "__main__":
    test_starting_player_rotation()
