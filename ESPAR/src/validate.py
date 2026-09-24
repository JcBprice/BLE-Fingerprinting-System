"""Moduł walidacji dokładności lokalizacji ESPAR WkNN."""

import json
import math
import os
import sys

from config import SCRIPT_DIR, DATA_DIR, OPTIMAL_K_PATH, get_test_set_path
sys.path.insert(0, SCRIPT_DIR)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D

from wknn import load_radio_map, wknn_estimate, DISTANCE_METRIC
from utils import show_plot


def load_test_set(filter_session: bool = False, path: str = None) -> list:
    path = path or get_test_set_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []

def save_test_set(test_set: list, path: str = None) -> None:
    path = path or get_test_set_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(test_set, f, indent=2, ensure_ascii=False)

def avg_to_window_data(beacons_avg: dict, beacon_id: int = None) -> dict:
    if not beacons_avg:
        return {}
    b_entry = beacons_avg.get(str(beacon_id)) if beacon_id is not None else None
    if not b_entry and beacons_avg:
        b_entry = next(iter(beacons_avg.values()))
    avg = b_entry.get('avg', {}) if isinstance(b_entry, dict) else {}
    return {1: {ch: [rssi] for ch, rssi in avg.items()}} if avg else {}

def compute_stats(errors: list) -> dict:
    if not errors:
        return {}
    s = sorted(errors)
    n = len(s)
    
    def p(frac): 
        return s[min(int(math.ceil(frac * n)) - 1, n - 1)]

    return {
        'n': n,
        'mean': sum(s) / n,
        'rmse': math.sqrt(sum(e**2 for e in s) / n),
        'max': s[-1],
        'min': s[0],
        'p50': p(0.50),
        'p75': p(0.75),
        'p90': p(0.90),
    }

def _plot_cdf(results: list, stats: dict, k: int, beacon_id: int = None) -> str:
    s_res = sorted(results, key=lambda r: r['error_m'])
    errors, n = [r['error_m'] for r in s_res], len(s_res)
    cdf = [(i + 1) / n for i in range(n)]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(errors, cdf, color='#3b82f6', lw=2, marker='o', label=f'CDF (n={n})')

    for i, r in enumerate(s_res):
        offset = 0.025 if i % 2 == 0 else -0.045
        ax.text(r['error_m'] + 0.05, cdf[i] + offset, r['label'], fontsize=8, color='#475569')

    lines = [
        (stats['p50'], 'P50', '#10b981', 0.5),
        (stats['p75'], 'P75', '#f59e0b', 0.75),
        (stats['p90'], 'P90', '#ef4444', 0.9)
    ]
    for p_val, p_lbl, col, y_line in lines:
        ax.axvline(p_val, color=col, ls='--', lw=1.2, label=f'{p_lbl} = {p_val:.3f} m')
        ax.axhline(y_line, color=col, ls=':', lw=0.8, alpha=0.5)

    ax.set(xlabel='Błąd lokalizacji [m]', ylabel='CDF', ylim=(0, 1.05), xlim=(0, None),
           title=f'CDF WkNN | K={k} | metryka={DISTANCE_METRIC} | Mean={stats["mean"]:.3f}m | RMSE={stats["rmse"]:.3f}m')
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=10)
    fig.tight_layout()
    
    out = os.path.join(DATA_DIR, 'validation_cdf.png')
    show_plot(fig, out)
    return out

def _plot_scatter(results: list, stats: dict) -> str:
    fig, ax = plt.subplots(figsize=(8, 8))
    for r in results:
        xt, yt, xe, ye = r['x_true'], r['y_true'], r['x_est'], r['y_est']
        ax.annotate('', xy=(xe, ye), xytext=(xt, yt), arrowprops=dict(arrowstyle='->', color='#94a3b8'))
        ax.plot(xt, yt, 'o', color='#3b82f6', markersize=7, zorder=5)
        ax.plot(xe, ye, 's', color='#ef4444', markersize=7, zorder=5, alpha=0.8)
        ax.text(xt, yt + 0.08, r.get('label', ''), fontsize=8, ha='center', va='bottom')

    handles = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#3b82f6', markersize=9, label='Prawdziwa'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#ef4444', markersize=9, label='Estymowana')
    ]
    ax.set(xlabel='X [m]', ylabel='Y [m]', aspect='equal', title=f'Prawdziwe vs Estymowane\nMean={stats["mean"]:.3f} m | RMSE={stats["rmse"]:.3f} m')
    ax.grid(True, alpha=0.25)
    ax.legend(handles=handles, fontsize=10)
    
    out = os.path.join(DATA_DIR, 'validation_scatter.png')
    show_plot(fig, out)
    return out

def _plot_k_optimization(k_vals: list, stats_dict: dict, best_k: int) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    metrics = [('mean', 'Średni błąd', '#3b82f6', '-o'), ('rmse', 'RMSE', '#ef4444', '-s'), ('p90', 'P90', '#10b981', '-^')]
    
    for key, label, color, fmt in metrics:
        ax.plot(k_vals, [stats_dict[k][key] for k in k_vals], fmt, label=label, color=color, lw=1.5)
        
    ax.axvline(best_k, color='#8b5cf6', ls='--', lw=1.5, label=f'Najlepsze K = {best_k}')
    ax.set(xlabel='K (liczba sąsiadów)', ylabel='Błąd [m]', xticks=k_vals, title='Optymalizacja parametru K')
    ax.legend()
    ax.grid(True, alpha=0.25)
    
    out = os.path.join(DATA_DIR, 'k_optimization.png')
    show_plot(fig, out)
    return out

def optimize_k(beacon_id: int = None, k_max: int = 20) -> int:
    test_set, radio_map = load_test_set(True), load_radio_map(True)
    if not test_set or len(radio_map) < 2:
        print("[!] Zbyt mało punktów testowych lub kalibracyjnych do optymalizacji.")
        return load_optimal_config()[0]

    k_max_real = min(k_max, len(radio_map) - 1)
    k_stats = {}
    print(f"\n=== OPTYMALIZACJA K (Zakres: 1-{k_max_real}) ===")
    
    for k in range(1, k_max_real + 1):
        errors = []
        for p in test_set:
            xt, yt = p.get('x_true', p.get('x_m')), p.get('y_true', p.get('y_m'))
            wd = avg_to_window_data(p.get('beacons', {}), beacon_id)
            if None in (xt, yt) or not wd:
                continue
            
            res = wknn_estimate(wd, radio_map, k=k, beacon_id=beacon_id)
            if res:
                errors.append(math.dist((xt, yt), (res[0], res[1])))
                
        if errors:
            st = compute_stats(errors)
            k_stats[k] = st
            print(f"  K={k:>2} | Mean: {st['mean']:.3f} | RMSE: {st['rmse']:.3f} | P90: {st['p90']:.3f}")

    if not k_stats:
        return load_optimal_config()[0]
    
    # Warunek K >= 3 dla uniknięcia "snappingu" centralnego w algorytmie wknn
    candidates = [k for k in k_stats if k >= 3] or [k for k in k_stats if k >= 2] or list(k_stats.keys())
    best_k = min(candidates, key=lambda k: k_stats[k]['rmse'])
    
    print(f"\nOptymalne K = {best_k} (RMSE = {k_stats[best_k]['rmse']:.3f}m)")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OPTIMAL_K_PATH, 'w', encoding='utf-8') as f:
        json.dump({'k': best_k, 'beacon_id': beacon_id, 'metric': DISTANCE_METRIC, 'k_stats': k_stats}, f, indent=2)
        
    if input("\nGenerować wykres K vs. błąd? (t/n): ").strip().lower() in ('t', 'y', 'tak'):
        _plot_k_optimization(list(k_stats.keys()), k_stats, best_k)
    return best_k

def run_validation(k: int = None, beacon_id: int = None) -> None:
    if k is None:
        k, _ = load_optimal_config()
        
    test_set, radio_map = load_test_set(True), load_radio_map(True)
    if not test_set or len(radio_map) < 2:
        print("[!] Brak danych (test_set lub radio_map) do walidacji.")
        return

    print(f"\n=== WALIDACJA WkNN (K={k}, metryka={DISTANCE_METRIC}) ===")
    errors, results, skipped = [], [], 0

    for point in test_set:
        lbl = point.get('label', '?')
        xt, yt = point.get('x_true', point.get('x_m')), point.get('y_true', point.get('y_m'))
        wd = avg_to_window_data(point.get('beacons', {}), beacon_id)
        
        if None in (xt, yt) or not wd:
            skipped += 1
            print(f"  [{lbl}] BRAK DANYCH WSPÓŁRZĘDNYCH LUB SYGNAŁU")
            continue

        res = wknn_estimate(wd, radio_map, k=k, beacon_id=beacon_id)
        if not res:
            skipped += 1
            print(f"  [{lbl}] BRAK ESTYMACJI")
            continue

        xe, ye, conf = res
        err = math.dist((xt, yt), (xe, ye))
        errors.append(err)
        results.append({
            'label': lbl, 'x_true': xt, 'y_true': yt, 'x_est': xe, 'y_est': ye,
            'error_m': round(err, 4), 'confidence': round(conf, 4)
        })
        print(f"  [{lbl:10}] err={err:.3f}m | prawdziwa: ({xt:.2f}, {yt:.2f}) -> est: ({xe:.2f}, {ye:.2f})")

    if not errors: return

    stats = compute_stats(errors)
    print(f"\nSTATYSTYKI (N={stats['n']}, pominięto={skipped})\n" + "-"*40)
    for k_s, v_s in stats.items():
        if k_s != 'n': print(f"  {k_s.upper():<10}: {v_s:.4f} m")

    with open(os.path.join(DATA_DIR, 'validation_report.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'config': {'k': k, 'beacon_id': beacon_id, 'metric': DISTANCE_METRIC},
            'stats': stats,
            'results': results
        }, f, indent=2)

    if input("\nGenerować wykresy walidacji? (t/n): ").strip().lower() in ('t', 'y', 'tak'):
        print("\n  Generowanie i zapisywanie wykresów...")
        _plot_cdf(results, stats, k, beacon_id)
        _plot_scatter(results, stats)
        print("  [OK] Wykresy zostały otwarte w przeglądarce obrazów.")

def load_optimal_config(default_k: int = 3, default_beacon: int = 28) -> tuple:
    if os.path.exists(OPTIMAL_K_PATH):
        try:
            with open(OPTIMAL_K_PATH, encoding='utf-8') as f:
                data = json.load(f)
            return data.get('k', default_k), data.get('beacon_id', default_beacon)
        except Exception:
            pass
    return default_k, default_beacon

def load_optimal_k(default: int = 3) -> int:
    return load_optimal_config(default_k=default)[0]

def load_optimal_beacon_id(default: int = 28) -> int:
    return load_optimal_config(default_beacon=default)[1]

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--k', type=int)
    p.add_argument('--beacon', type=int, default=None)
    args = p.parse_args()
    run_validation(k=args.k, beacon_id=args.beacon)
