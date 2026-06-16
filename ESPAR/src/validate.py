"""
validate.py — Moduł walidacji dokładności lokalizacji ESPAR WkNN.

Workflow:
    1. Zbierz punkty testowe (opcja 7 w main.py lub --collect tu).
       Muszą to być punkty NOWE — niewidoczne wcześniej przez algorytm
       (nie mogą być w radio_map.json).

    2. Uruchom walidację:
           python validate.py

    Skrypt iteruje po test_set.json, ukrywa prawdziwą pozycję przed WkNN,
    pobiera estymację, oblicza błąd euklidesowy i statystyki końcowe.

Statystyki:
    Mean Error  — średni błąd arytmetyczny [m]
    RMSE        — Root Mean Square Error [m], karze za duże odchylenia
    Max Error   — najgorszy przypadek (precyzja gwarantowana)
    P90         — 90. percentyl błędu (90% pomiarów mieści się poniżej)

Wykresy:
    CDF błędu lokalizacji — zapisywany do data/validation_cdf.png
    Scatter plot: prawdziwe vs estymowane pozycje — data/validation_scatter.png
"""

import os as _os
_os.environ.setdefault("QT_LOGGING_RULES", "qt.*=false")

import json
import math
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'data'))
sys.path.insert(0, SCRIPT_DIR)

# Wymuszamy backend Agg (bez Qt/Wayland)
import matplotlib
matplotlib.use('Agg')

from wknn import load_radio_map, wknn_estimate, DISTANCE_METRIC

TEST_SET_PATH   = os.path.join(DATA_DIR, 'test_set.json')
OPTIMAL_K_PATH  = os.path.join(DATA_DIR, 'optimal_k.json')


# ══════════════════════════════════════════════════════════════════════════
# I/O zbioru testowego
# ══════════════════════════════════════════════════════════════════════════

def load_test_set() -> list:
    """Wczytuje zbiór testowy z test_set.json."""
    if not os.path.exists(TEST_SET_PATH):
        return []
    with open(TEST_SET_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_test_set(test_set: list) -> None:
    """Zapisuje zbiór testowy do test_set.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TEST_SET_PATH, 'w', encoding='utf-8') as f:
        json.dump(test_set, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════
# Konwersja formatu
# ══════════════════════════════════════════════════════════════════════════

def avg_to_window_data(beacons_avg: dict, beacon_id: int) -> dict:
    """
    Konwertuje uśredniony fingerprint (z test_set.json) na format window_data
    wymagany przez wknn_estimate().

    wknn_estimate oczekuje: {beacon_id: {char_int_str: [rssi_val, ...]}}
    Test set przechowuje:   {"28": {"avg": {"31": -80.7, ...}}}

    Każde avg_rssi jest owijane w jednoelementową listę — symuluje "okno"
    z jednej próbki (odpowiada idealnemu, bezszumowemu odczytowi).
    """
    b_str = str(beacon_id)
    avg   = beacons_avg.get(b_str, {}).get('avg', {})
    if not avg:
        return {}
    window = {ch: [rssi] for ch, rssi in avg.items()}
    return {beacon_id: window}


# ══════════════════════════════════════════════════════════════════════════
# Statystyki
# ══════════════════════════════════════════════════════════════════════════

def _percentile(sorted_vals: list, p: float) -> float:
    """Percentyl p ∈ [0,1] z posortowanej listy."""
    if not sorted_vals:
        return 0.0
    idx = min(int(math.ceil(p * len(sorted_vals))) - 1, len(sorted_vals) - 1)
    return sorted_vals[idx]


def compute_stats(errors: list) -> dict:
    """Oblicza zestaw statystyk błędów lokalizacji."""
    n = len(errors)
    if n == 0:
        return {}
    s = sorted(errors)
    mean  = sum(s) / n
    rmse  = math.sqrt(sum(e**2 for e in s) / n)
    return {
        'n':     n,
        'mean':  mean,
        'rmse':  rmse,
        'max':   s[-1],
        'min':   s[0],
        'p50':   _percentile(s, 0.50),
        'p75':   _percentile(s, 0.75),
        'p90':   _percentile(s, 0.90),
    }


# ══════════════════════════════════════════════════════════════════════════
# Wizualizacja
# ══════════════════════════════════════════════════════════════════════════

def _show_plot(fig, out_path: str) -> None:
    """Zapisuje wykres, zamyka figurę i otwiera PNG w systemowej przeglądarce."""
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    import matplotlib.pyplot as plt
    plt.close(fig)
    try:
        env = dict(os.environ)
        env["QT_LOGGING_RULES"] = "qt.*=false"
        subprocess.Popen(['xdg-open', out_path],
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True,
                         env=env)
    except Exception:
        pass

def _plot_cdf(errors: list, stats: dict, k: int, beacon_id: int) -> str:
    """Generuje wykres CDF i zapisuje do pliku. Zwraca ścieżkę."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print('[!] matplotlib niedostępny — pomijam wykres CDF.')
        return ''

    s = sorted(errors)
    n = len(s)
    cdf = [(i + 1) / n for i in range(n)]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(s, cdf, color='#3b82f6', linewidth=2, marker='o',
            markersize=4, markerfacecolor='white', markeredgewidth=1.5,
            label=f'CDF (n={n})')

    # Linie percentylowe
    for p_val, p_lbl, color in [
        (stats['p50'], 'P50', '#10b981'),
        (stats['p75'], 'P75', '#f59e0b'),
        (stats['p90'], 'P90', '#ef4444'),
    ]:
        ax.axvline(p_val, color=color, linestyle='--', linewidth=1.2,
                   label=f'{p_lbl} = {p_val:.3f} m')
        ax.axhline(0.90 if p_lbl == 'P90' else
                   (0.75 if p_lbl == 'P75' else 0.50),
                   color=color, linestyle=':', linewidth=0.8, alpha=0.5)

    ax.set_xlabel('Błąd lokalizacji [m]', fontsize=12)
    ax.set_ylabel('CDF', fontsize=12)
    ax.set_title(
        f'CDF błędu lokalizacji ESPAR WkNN\n'
        f'K={k} | metryka={DISTANCE_METRIC} | beacon={beacon_id} | '
        f'Mean={stats["mean"]:.3f} m | RMSE={stats["rmse"]:.3f} m',
        fontsize=11,
    )
    ax.set_ylim(0, 1.05)
    ax.set_xlim(left=0)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=10)
    fig.tight_layout()

    out_path = os.path.join(DATA_DIR, 'validation_cdf.png')
    _show_plot(fig, out_path)
    return out_path


def _plot_scatter(results: list, stats: dict) -> str:
    """Generuje scatter plot: prawdziwe vs estymowane pozycje."""
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch
    except ImportError:
        return ''

    fig, ax = plt.subplots(figsize=(8, 8))

    for r in results:
        xt, yt = r['x_true'], r['y_true']
        xe, ye = r['x_est'],  r['y_est']
        # Strzałka: prawdziwy → estymowany
        ax.annotate('', xy=(xe, ye), xytext=(xt, yt),
                    arrowprops=dict(arrowstyle='->', color='#94a3b8',
                                   lw=1.0, mutation_scale=12))
        ax.plot(xt, yt, 'o', color='#3b82f6', markersize=7, zorder=5)
        ax.plot(xe, ye, 's', color='#ef4444', markersize=7, zorder=5,
                alpha=0.8)

    # Legenda
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#3b82f6',
               markersize=9, label='Prawdziwa pozycja'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#ef4444',
               markersize=9, label='Estymowana pozycja'),
    ]
    ax.legend(handles=legend_elements, fontsize=10)
    ax.set_xlabel('X [m]', fontsize=12)
    ax.set_ylabel('Y [m]', fontsize=12)
    ax.set_title(
        f'Prawdziwe vs Estymowane pozycje\n'
        f'Mean Error={stats["mean"]:.3f} m | RMSE={stats["rmse"]:.3f} m',
        fontsize=11,
    )
    ax.grid(True, alpha=0.25)
    ax.set_aspect('equal', adjustable='datalim')
    fig.tight_layout()

    out_path = os.path.join(DATA_DIR, 'validation_scatter.png')
    _show_plot(fig, out_path)
    return out_path


# ══════════════════════════════════════════════════════════════════════
# Optymalizacja parametru K
# ══════════════════════════════════════════════════════════════════════

def load_optimal_k(default: int = 3) -> int:
    """
    Wczytuje optymalne K z optimal_k.json (wyznaczone przez optimize_k()).
    Zwraca wartość domyślną, jeśli plik nie istnieje.
    """
    if os.path.exists(OPTIMAL_K_PATH):
        try:
            with open(OPTIMAL_K_PATH, encoding='utf-8') as f:
                return int(json.load(f).get('k', default))
        except Exception:
            pass
    return default


def _plot_k_optimization(k_values: list, k_stats: dict, best_k: int) -> str:
    """
    Generuje wykres K vs. błąd lokalizacji (Mean, RMSE, P90).
    Zapisuje do data/k_optimization.png.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print('[!] matplotlib niedostępny — pomijam wykres.')
        return ''

    means = [k_stats[k]['mean'] for k in k_values]
    rmses = [k_stats[k]['rmse'] for k in k_values]
    p90s  = [k_stats[k]['p90']  for k in k_values]

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(k_values, means, 'o-', color='#3b82f6', lw=2.0, markersize=7,
            markerfacecolor='white', markeredgewidth=2, label='Mean Error')
    ax.plot(k_values, rmses, 's-', color='#ef4444', lw=2.0, markersize=7,
            markerfacecolor='white', markeredgewidth=2, label='RMSE')
    ax.plot(k_values, p90s,  '^-', color='#f59e0b', lw=2.0, markersize=7,
            markerfacecolor='white', markeredgewidth=2, label='P90')

    # Oznacz optymalne K
    ax.axvline(best_k, color='#10b981', linestyle='--', lw=1.5,
               label=f'Kₙₕₜ = {best_k}  (RMSE = {k_stats[best_k]["rmse"]:.3f} m)')
    ax.scatter([best_k], [k_stats[best_k]['rmse']],
               color='#10b981', s=120, zorder=6, marker='*')

    ax.set_xlabel('K  (liczba sąsiadów WkNN)', fontsize=12)
    ax.set_ylabel('Błąd lokalizacji  [m]', fontsize=12)
    ax.set_title(
        f'Optymalizacja parametru K — WkNN ESPAR\n'
        f'metryka={DISTANCE_METRIC} | n_test={k_stats[k_values[0]]["n"]} punktów',
        fontsize=11,
    )
    ax.set_xticks(k_values)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()

    out_path = os.path.join(DATA_DIR, 'k_optimization.png')
    _show_plot(fig, out_path)
    return out_path


def optimize_k(beacon_id: int = 28, k_max: int = 11) -> int:
    """
    Wyznacza optymalne K dla WkNN metodą grid search na zbiorze testowym.

    Dla każdego K z zakresu [1, min(k_max, N-1)] (gdzie N = rozmiar radio_map)
    uruchamia pełną pętlę walidacyjną, oblicza Mean Error, RMSE i P90.
    Wybiera K minimalizujące RMSE i zapisuje wynik do optimal_k.json.

    Args:
        beacon_id: ID beacona BLE.
        k_max:     Maksymalne K do przeszukania (domyślnie 11).

    Returns:
        Optymalne K.
    """
    test_set  = load_test_set()
    radio_map = load_radio_map()

    if not test_set:
        print('[!] Brak zbioru testowego. Zbierz punkty (opcja 6 w menu).')
        return load_optimal_k()

    if len(radio_map) < 2:
        print(f'[!] Za mało punktów kalibracyjnych ({len(radio_map)}).')
        return load_optimal_k()

    # Zakres K: od 1 do min(k_max, N-1)
    k_max_real = min(k_max, len(radio_map) - 1)
    k_values   = list(range(1, k_max_real + 1))

    print(f'\n=== OPTYMALIZACJA K ===')
    print(f'  Zbiór testowy: {len(test_set)} punktów')
    print(f'  Radio map:      {len(radio_map)} punktów')
    print(f'  Zakres K:       1 – {k_max_real}')
    print(f'  Metryka:        {DISTANCE_METRIC}\n')
    print(f'  {"K":>3}  {"Mean":>8}  {"RMSE":>8}  {"P90":>8}  {"N":>4}')
    print('  ' + '-' * 36)

    k_stats: dict[int, dict] = {}

    for k in k_values:
        errors = []
        for point in test_set:
            x_true = point.get('x_true', point.get('x_m'))
            y_true = point.get('y_true', point.get('y_m'))
            if x_true is None or y_true is None:
                continue
            window_data = avg_to_window_data(point.get('beacons', {}), beacon_id)
            if not window_data:
                continue
            result = wknn_estimate(window_data, radio_map, k=k, beacon_id=beacon_id)
            if result is None:
                continue
            x_est, y_est, _ = result
            errors.append(math.sqrt((x_true - x_est) ** 2 + (y_true - y_est) ** 2))

        if not errors:
            continue

        st = compute_stats(errors)
        k_stats[k] = st
        marker = '  '
        print(f'  {k:>3}  {st["mean"]:>8.4f}  {st["rmse"]:>8.4f}  '
              f'{st["p90"]:>8.4f}  {st["n"]:>4}{marker}')

    if not k_stats:
        print('[!] Brak wyników.')
        return load_optimal_k()

    # Optymalne K = min RMSE
    best_k = min(k_stats, key=lambda k: k_stats[k]['rmse'])

    print('  ' + '-' * 36)
    print(f'\n  Optymalne K = {best_k}  '
          f'(RMSE={k_stats[best_k]["rmse"]:.4f} m, '
          f'Mean={k_stats[best_k]["mean"]:.4f} m)')

    # Zapisz do pliku — będzie automatycznie wczytywane przy walidacji i online
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OPTIMAL_K_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            'k':          best_k,
            'beacon_id':  beacon_id,
            'metric':     DISTANCE_METRIC,
            'n_test':     len(test_set),
            'n_radio_map': len(radio_map),
            'k_stats':    {str(k): v for k, v in k_stats.items()},
        }, f, indent=2, ensure_ascii=False)
    print(f'  Zapisano: {OPTIMAL_K_PATH}')

    while True:
        ans = input('\n  Generuj wykres K vs. błąd? (t/n, domyślnie n): ').strip().lower()
        if not ans:
            ans = 'n'
        if ans in ('t', 'y', 'yes', 'tak'):
            p = _plot_k_optimization(list(k_stats.keys()), k_stats, best_k)
            if p:
                print(f'  Wykres: {p}')
            break
        elif ans in ('n', 'no', 'nie'):
            break
        print("  [!] Nieprawidłowy wybór. Wpisz 't' (tak) lub 'n' (nie).")

    return best_k


# ══════════════════════════════════════════════════════════════════════════
# Główna funkcja walidacji
# ══════════════════════════════════════════════════════════════════════════

def run_validation(k: int | None = None, beacon_id: int = 28) -> None:
    """
    Uruchamia pełną walidację na zbiorze testowym.

    Jeśli k=None, automatycznie wczytuje optymalne K z optimal_k.json
    (wyznaczonego przez optimize_k()). Jeśli plik nie istnieje, używa K=3.

    Args:
        k:         Liczba sąsiadów WkNN (None = użyj optymalnego z pliku).
        beacon_id: ID beacona BLE używanego do lokalizacji.
    """
    if k is None:
        k = load_optimal_k(default=3)
        print(f'  [auto] Użwam K={k} (z optimal_k.json)')
    test_set  = load_test_set()
    radio_map = load_radio_map()

    if not test_set:
        print(f'[!] Brak danych testowych w {TEST_SET_PATH}')
        print('    Zbierz punkty testowe (opcja 7 w menu) i uruchom ponownie.')
        return

    if len(radio_map) < 2:
        print(f'[!] Za mało punktów kalibracyjnych ({len(radio_map)}).')
        return

    print(f'\n=== WALIDACJA WkNN ===')
    print(f'  Zbiór testowy:        {len(test_set)} punktów')
    print(f'  Mapa radiowa:         {len(radio_map)} punktów')
    print(f'  K sąsiadów:           {k}')
    print(f'  Metryka odległości:   {DISTANCE_METRIC}')
    print(f'  Beacon ID:            {beacon_id}')
    print()

    errors  = []
    results = []
    skipped = 0

    for point in test_set:
        label  = point.get('label', '?')
        x_true = point.get('x_true', point.get('x_m'))
        y_true = point.get('y_true', point.get('y_m'))

        if x_true is None or y_true is None:
            print(f'  [{label}] POMINIĘTO — brak współrzędnych')
            skipped += 1
            continue

        # Konwertuj fingerprint testowy na format window_data
        window_data = avg_to_window_data(point.get('beacons', {}), beacon_id)
        if not window_data:
            print(f'  [{label}] POMINIĘTO — brak danych RSS dla beacona {beacon_id}')
            skipped += 1
            continue

        result = wknn_estimate(window_data, radio_map, k=k, beacon_id=beacon_id)

        if result is None:
            print(f'  [{label}] BRAK WYNIKU   (za mało konfiguracji anteny)')
            skipped += 1
            continue

        x_est, y_est, conf = result
        error = math.sqrt((x_true - x_est) ** 2 + (y_true - y_est) ** 2)
        errors.append(error)
        results.append({
            'label': label, 'x_true': x_true, 'y_true': y_true,
            'x_est': x_est, 'y_est': y_est,
            'error_m': round(error, 4), 'confidence': round(conf, 4),
        })
        print(f'  [{label:12}] '
              f'true=({x_true:6.2f},{y_true:6.2f})  '
              f'est=({x_est:6.2f},{y_est:6.2f})  '
              f'błąd={error:.3f} m  conf={conf:.2%}')

    if not errors:
        print('\n[!] Brak wyników — sprawdź dane testowe.')
        return

    # ── Statystyki ────────────────────────────────────────────────────────
    stats = compute_stats(errors)
    print(f'\n{"═"*52}')
    print(f'  STATYSTYKI WALIDACJI (N={stats["n"]}, pominięto={skipped})')
    print(f'{"─"*52}')
    print(f'  Mean Error  : {stats["mean"]:.4f} m')
    print(f'  RMSE        : {stats["rmse"]:.4f} m')
    print(f'  Max Error   : {stats["max"]:.4f} m')
    print(f'  Min Error   : {stats["min"]:.4f} m')
    print(f'  P50 (mediana): {stats["p50"]:.4f} m')
    print(f'  P75         : {stats["p75"]:.4f} m')
    print(f'  P90         : {stats["p90"]:.4f} m')
    print(f'{"═"*52}')

    # ── Zapis wyników JSON ────────────────────────────────────────────────
    report = {
        'config': {'k': k, 'beacon_id': beacon_id,
                   'metric': DISTANCE_METRIC,
                   'n_test': len(test_set), 'n_radio_map': len(radio_map)},
        'stats':   stats,
        'results': results,
    }
    report_path = os.path.join(DATA_DIR, 'validation_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f'\n  Raport JSON: {report_path}')

    # ── Wykresy ───────────────────────────────────────────────────────────
    while True:
        ans = input('\n  Generuj wykresy? (t/n, domyślnie n): ').strip().lower()
        if not ans:
            ans = 'n'
        if ans in ('t', 'y', 'yes', 'tak'):
            p1 = _plot_cdf(errors, stats, k, beacon_id)
            p2 = _plot_scatter(results, stats)
            if p1:
                print(f'  CDF:     {p1}')
            if p2:
                print(f'  Scatter: {p2}')
            break
        elif ans in ('n', 'no', 'nie'):
            break
        print("  [!] Nieprawidłowy wybór. Wpisz 't' (tak) lub 'n' (nie).")


# ══════════════════════════════════════════════════════════════════════════
# Entry point (uruchamianie samodzielne)
# ══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Walidacja systemu ESPAR WkNN')
    parser.add_argument('--k',        type=int, default=None, help='Liczba sąsiadów (domyślnie: z optimal_k.json)')
    parser.add_argument('--beacon',   type=int, default=28,   help='ID beacona (domyślnie 28)')
    parser.add_argument('--optimize', action='store_true',     help='Uruchom optymalizację K zamiast walidacji')
    args = parser.parse_args()
    if args.optimize:
        optimize_k(beacon_id=args.beacon)
    else:
        run_validation(k=args.k, beacon_id=args.beacon)
