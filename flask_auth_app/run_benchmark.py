#!/usr/bin/env python3
"""
One-time local benchmark runner.
Run from the flask_auth_app/ directory:   python run_benchmark.py
Results are saved to benchmark_results.json and served statically by the app.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from game.logic import SepticaGame
from game.bot_logic import choose_action

DIFF_COLORS = {
    'easy':   '#e63946',
    'medium': '#f9c74f',
    'hard':   '#02c39a',
    'smart':  '#9065ff',
}

PAIRS = [
    ('easy',   'medium', 1000),
    ('easy',   'hard',   1000),
    ('medium', 'hard',   1000),
    ('easy',   'smart',   100),
    ('medium', 'smart',   100),
    ('hard',   'smart',   100),
]

DIFF_ORDER = ['easy', 'medium', 'hard', 'smart']


def simulate(diff_a, diff_b, n_games):
    wins = {diff_a: 0, diff_b: 0, 'tie': 0}
    dot_every = max(1, n_games // 20)
    for i in range(n_games):
        if i % dot_every == 0:
            print('.', end='', flush=True)
        # Rotate starting player so no positional bias
        game = SepticaGame(starting_player=i % 4, num_players=4)
        for _ in range(600):
            if game.game_phase == 'finished':
                break
            pos = game.current_player
            diff = diff_a if pos % 2 == 0 else diff_b
            state = game.get_game_state(pos)
            state['position'] = pos
            action, idx = choose_action(state, diff, game_obj=game)
            if action == 'play':
                game.play_card(pos, idx)
            elif action == 'take':
                game.take_hand()
            else:
                game.forfeit_hand()
        r = game.get_game_result()
        if r['is_tie']:
            wins['tie'] += 1
        elif r['winner'] == 0:
            wins[diff_a] += 1
        else:
            wins[diff_b] += 1
    return wins


def main():
    print("Septica Bot AI Benchmark")
    print("=" * 50)
    rows = []
    total_start = time.time()

    for d1, d2, n in PAIRS:
        print(f"\n{d1:8s} vs {d2:8s}  ({n} games)  ", end='', flush=True)
        t0 = time.time()
        wins = simulate(d1, d2, n)
        elapsed = time.time() - t0
        decisive = n - wins['tie']
        pct1 = round(wins[d1] / n * 100, 1)
        pct2 = round(wins[d2] / n * 100, 1)
        print(f"  {elapsed:.1f}s")
        print(f"  {d1}={wins[d1]} ({pct1}%)  {d2}={wins[d2]} ({pct2}%)  ties={wins['tie']}")
        rows.append({
            'd1': d1, 'd2': d2, 'n': n,
            'w1': wins[d1], 'w2': wins[d2], 'ties': wins['tie'],
            'pct1': pct1, 'pct2': pct2,
            'color1': DIFF_COLORS[d1],
            'color2': DIFF_COLORS[d2],
        })

    # Overall rankings: win % across all matchups (ties excluded)
    totals = {d: {'wins': 0, 'decisive': 0} for d in DIFF_ORDER}
    for row in rows:
        dec = row['n'] - row['ties']
        totals[row['d1']]['wins']     += row['w1']
        totals[row['d1']]['decisive'] += dec
        totals[row['d2']]['wins']     += row['w2']
        totals[row['d2']]['decisive'] += dec

    rankings = []
    for d in DIFF_ORDER:
        dec = totals[d]['decisive']
        pct = round(totals[d]['wins'] / dec * 100, 1) if dec else 0.0
        rankings.append({'diff': d, 'pct': pct, 'color': DIFF_COLORS[d]})
    rankings.sort(key=lambda x: x['pct'], reverse=True)

    print(f"\n{'='*50}")
    print("Overall rankings:")
    for i, r in enumerate(rankings, 1):
        print(f"  #{i} {r['diff']:8s}  {r['pct']}%")

    out = os.path.join(os.path.dirname(__file__), 'benchmark_results.json')
    with open(out, 'w') as f:
        json.dump({'rows': rows, 'rankings': rankings}, f, indent=2)

    print(f"\nSaved → {out}")
    print(f"Total time: {time.time() - total_start:.1f}s")


if __name__ == '__main__':
    main()
