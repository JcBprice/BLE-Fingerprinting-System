"""
rssi_analysis.py — Analiza stabilnosci RSSI w czasie.

Cel:
    Zbiera N probek RSSI dla kazdej z 12 konfiguracji anteny ESPAR w jednym
    punkcie pomiarowym, rysuje histogramy z dopasowaniem rozkladu normalnego
    i zapisuje surowe dane z sygnatura czasowa.

    Powtarzany o roznych porach dnia (np. rano / wieczor / nastepnego dnia)
    pozwala ocenic, czy rozklad RSS pozostaje stabilny i czy system wymaga
    czestej rekalibracji.

Pliki wyjsciowe:
    data/rssi_snapshots/<YYYYMMDD_HHMM>_<etykieta>.json  — surowe dane
    data/rssi_snapshots/<etykieta>_histogram.png          — wykres

Uzycie z poziomu main.py:
    from rssi_analysis import run_rssi_analysis
    run_rssi_analysis(sock_factory, beacon_id=28)

Uzycie samodzielne:
    python rssi_analysis.py --compare snapshot1.json snapshot2.json
"""

import os as _os
_os.environ.setdefault("QT_LOGGING_RULES", "qt.*=false")

import json
import math
import os
import signal
import subprocess
import sys
from datetime import datetime

from config import SCRIPT_DIR, DATA_DIR, CHAR_TO_DEG
SNAPSHOTS_DIR = os.path.join(DATA_DIR, 'rssi_snapshots')

# Wymuszamy backend Agg (renderuje do pliku, nie ładuje Qt/Wayland)
# Wykresy otwieramy przez xdg-open w _show_plot()
import matplotlib
matplotlib.use('Agg')


# ══════════════════════════════════════════════════════════════════════════
# I/O migawek
# ══════════════════════════════════════════════════════════════════════════

def save_snapshot(label: str, beacon_id: int, raw: dict) -> str:
    """Zapisuje surowe dane RSSI do pliku JSON. Zwraca sciezke pliku."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts   = datetime.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(SNAPSHOTS_DIR, f'{ts}_{label}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'label':     label,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'beacon_id': beacon_id,
            'data':      {str(k): v for k, v in raw.items()},
        }, f, indent=2, ensure_ascii=False)
    return path


def load_snapshot(path: str) -> dict:
    """Wczytuje migawke RSSI z pliku JSON."""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def list_snapshots() -> list[str]:
    """Zwraca posortowana liste plikow migawek."""
    if not os.path.exists(SNAPSHOTS_DIR):
        return []
    return sorted(
        os.path.join(SNAPSHOTS_DIR, fn)
        for fn in os.listdir(SNAPSHOTS_DIR)
        if fn.endswith('.json')
    )


# ══════════════════════════════════════════════════════════════════════════
# Statystyki
# ══════════════════════════════════════════════════════════════════════════

def _stats(values: list) -> tuple[float, float, float, float]:
    """Zwraca (mean, std, min, max) dla listy wartosci."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    mean = sum(values) / n
    std  = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return mean, std, min(values), max(values)


# ══════════════════════════════════════════════════════════════════════════
# Wizualizacja
# ══════════════════════════════════════════════════════════════════════════

from utils import show_plot

# Paleta kolorow dla kolejnych migawek (porownanie)
_PALETTE = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6']


def plot_radar_charts(snapshots: list[dict], out_path: str | None = None) -> str:
    """
    Rysuje wykresy radarowe (polar) dla migawek RSSI.
    Zastępuje dawne histogramy.
    
    Jeśli wybrano <= 4 migawki/punkty, nakłada je na jeden wykres radarowy (overlay).
    Jeśli wybrano > 4, rysuje heatmapę po lewej i radar wybranych po prawej.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print('[!] matplotlib/numpy niedostępny.')
        return ''

    plt.close('all')

    # Kąty i konfiguracje
    deg_to_char = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
    sorted_degs = sorted(deg_to_char.keys())  # 0, 30, 60, ..., 330
    angles_deg = np.array(sorted_degs, dtype=float)
    angles_rad = np.deg2rad(angles_deg)
    angles_rad_closed = np.append(angles_rad, angles_rad[0])

    def _estimate_direction(rssi_vals, angles):
        rssi_np = np.array(rssi_vals, dtype=float)
        shifted = rssi_np - rssi_np.min()
        weights = np.power(10.0, shifted / 10.0)
        sin_sum = np.sum(weights * np.sin(angles))
        cos_sum = np.sum(weights * np.cos(angles))
        est_rad = np.arctan2(sin_sum, cos_sum)
        est_deg = np.rad2deg(est_rad) % 360
        return est_rad, round(est_deg, 1)

    # Przygotuj dane do wykresu: list of (label, {char_int_str: avg_rssi})
    plot_data = []
    bids = sorted(list(set(snap.get('beacon_id') for snap in snapshots if snap.get('beacon_id') is not None)))
    bids_str = ', '.join(map(str, bids)) if bids else 'nieznany'
    for snap in snapshots:
        label = snap.get('label', 'migawka')
        data = snap.get('data', {})
        snap_avgs = {}
        for ch, vals in data.items():
            if isinstance(vals, list):
                if vals:
                    snap_avgs[str(ch)] = sum(vals) / len(vals)
            elif vals is not None:
                snap_avgs[str(ch)] = float(vals)
        plot_data.append((label, snap_avgs))

    n_selected = len(plot_data)
    if n_selected == 0:
        return ''

    if n_selected <= 1:
        # Pojedynczy punkt — radar overlay
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
        ax.set_theta_zero_location('N', offset=0)   # 0° na górze, obrócone o 226.77° w prawo
        ax.set_theta_direction(-1)         # zgodnie z ruchem wskazówek zegara

        radar_plots_data = []

        for pi, (label, avgs) in enumerate(plot_data):
            vals = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                v = avgs.get(str(ch)) if str(ch) in avgs else avgs.get(ch)
                vals.append(float(v) if v is not None else -100.0)
            vals_np = np.array(vals)
            vals_closed = np.append(vals_np, vals_np[0])

            best_rad, best_deg = _estimate_direction(vals_np, angles_rad)

            color = _PALETTE[pi % len(_PALETTE)]
            label_with_dir = f"{label} (kierunek ≈{best_deg}°)"
            ax.plot(angles_rad_closed, vals_closed, 'o-', color=color,
                    linewidth=2, markersize=5, label=label_with_dir, alpha=0.85)
            ax.fill(angles_rad_closed, vals_closed, color=color, alpha=0.1)
            
            radar_plots_data.append((best_rad, best_deg, color))

        ax.set_xticks(angles_rad)
        ax.set_xticklabels([f'{d}°' for d in sorted_degs], fontsize=9)
        ax.set_ylabel('RSSI [dBm]', fontsize=9, labelpad=20)
        ax.set_title(f'Odciski radiowe (radar) — Beacon(s) {bids_str}\n'
                     f'(Linia przerywana = szacowany kierunek beacona)',
                     fontsize=12, pad=20)
        
        # Rysuj strzałki kierunku beacona
        r_min, r_max = ax.get_ylim()
        if r_max > r_min:
            r_range = r_max - r_min
            for best_rad, best_deg, color in radar_plots_data:
                ax.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)
                arrow_text_r = r_max - 0.1 * r_range
                ax.annotate('', xy=(best_rad, r_max), xytext=(best_rad, arrow_text_r),
                            arrowprops=dict(arrowstyle="->", color=color, lw=2.5, mutation_scale=15))

        ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=9)
        ax.grid(True, alpha=0.3)
    else:
        # Wiele punktów — heatmapa + radar wybranych
        fig = plt.figure(figsize=(16, 8))

        # Panel lewy: heatmapa
        ax_heat = fig.add_subplot(121)
        matrix = []
        labels_list = []
        for label, avgs in plot_data:
            row = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                v = avgs.get(str(ch)) if str(ch) in avgs else avgs.get(ch)
                row.append(float(v) if v is not None else np.nan)
            matrix.append(row)
            labels_list.append(label)

        matrix_np = np.array(matrix)
        im = ax_heat.imshow(matrix_np, aspect='auto', cmap='RdYlBu_r',
                            interpolation='nearest')
        ax_heat.set_xticks(range(len(sorted_degs)))
        ax_heat.set_xticklabels([f'{d}°' for d in sorted_degs], fontsize=8,
                                rotation=45, ha='right')
        ax_heat.set_yticks(range(len(labels_list)))
        ax_heat.set_yticklabels(labels_list, fontsize=8)
        ax_heat.set_xlabel('Kąt wiązki anteny ESPAR')
        ax_heat.set_ylabel('Punkt kalibracyjny')
        ax_heat.set_title(f'Mapa RSSI [dBm] — Beacon(s) {bids_str}', fontsize=11)
        cbar = fig.colorbar(im, ax=ax_heat, shrink=0.8)
        cbar.set_label('RSSI [dBm]', fontsize=9)

        # Adnotacja wartości w komórkach (jeśli <20 punktów)
        if len(labels_list) <= 20:
            for yi in range(matrix_np.shape[0]):
                for xi in range(matrix_np.shape[1]):
                    v = matrix_np[yi, xi]
                    if not np.isnan(v):
                        ax_heat.text(xi, yi, f'{v:.0f}', ha='center', va='center',
                                     fontsize=6, color='white' if v < -78 else 'black')

        # Panel prawy: radar wybranych (max 4, co kwartał)
        ax_radar = fig.add_subplot(122, projection='polar')
        ax_radar.set_theta_zero_location('N', offset=0)
        ax_radar.set_theta_direction(-1)

        # Wybierz max 4 równomiernie rozłożone
        step = max(n_selected // 4, 1)
        show_idx = list(range(0, n_selected, step))[:4]

        radar_plots_data = []

        for pi, si in enumerate(show_idx):
            label, avgs = plot_data[si]
            vals = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                v = avgs.get(str(ch)) if str(ch) in avgs else avgs.get(ch)
                vals.append(float(v) if v is not None else -100.0)
            vals_np = np.array(vals)
            vals_closed = np.append(vals_np, vals_np[0])
            
            best_rad, best_deg = _estimate_direction(vals_np, angles_rad)

            color = _PALETTE[pi % len(_PALETTE)]
            label_with_dir = f"{label} (kierunek ≈{best_deg}°)"
            ax_radar.plot(angles_rad_closed, vals_closed, 'o-', color=color,
                          linewidth=2, markersize=4, label=label_with_dir, alpha=0.85)
            ax_radar.fill(angles_rad_closed, vals_closed, color=color, alpha=0.08)
            radar_plots_data.append((best_rad, best_deg, color))

        ax_radar.set_xticks(angles_rad)
        ax_radar.set_xticklabels([f'{d}°' for d in sorted_degs], fontsize=8)
        ax_radar.set_title('Odciski radiowe (radar)\n(Linia przerywana = szacowany kierunek beacona)', fontsize=11, pad=15)
        
        # Rysuj strzałki kierunku beacona
        r_min, r_max = ax_radar.get_ylim()
        if r_max > r_min:
            r_range = r_max - r_min
            for best_rad, best_deg, color in radar_plots_data:
                ax_radar.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)
                arrow_text_r = r_max - 0.1 * r_range
                ax_radar.annotate('', xy=(best_rad, r_max), xytext=(best_rad, arrow_text_r),
                                  arrowprops=dict(arrowstyle="->", color=color, lw=2.5, mutation_scale=12))

        ax_radar.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=8)
        ax_radar.grid(True, alpha=0.3)

    fig.tight_layout()

    if out_path is None:
        labels   = '_vs_'.join(s['label'] for s in snapshots)
        ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = os.path.join(SNAPSHOTS_DIR, f'{labels}_{ts}_radar.png')
    
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    show_plot(fig, out_path)
    return out_path


def print_stability_table(snapshots: list[dict]) -> None:
    """
    Wypisuje tabele porownawcza srednia / odchylenie standardowe
    dla kazdej konfiguracji anteny i kazdej migawki.

    Duze roznice mean (> ~3 dBm) miedzy migawkami sugeruja potrzebe rekalibracji.
    """
    all_chars = sorted(CHAR_TO_DEG.keys())
    n = len(snapshots)

    # Naglowek
    hdr = f"{'char_int':>8}  {'deg':>4}  "
    for snap in snapshots:
        ts = snap.get('timestamp', '')[:16] or snap.get('label', '')[:16]
        hdr += f"  {snap['label']:>12}(mu/std)"
    print('\n' + hdr)
    print('  ' + '-' * (8 + 6 + n * 24))

    for char_int in all_chars:
        row = f"  {char_int:>8}  {CHAR_TO_DEG.get(char_int, '?'):>3}d  "
        for snap in snapshots:
            vals = snap['data'].get(str(char_int), snap['data'].get(char_int, []))
            if vals is not None and vals != []:
                if isinstance(vals, list):
                    m, s, _, _ = _stats(vals)
                else:
                    m, s = float(vals), 0.0
                row += f"  {m:>7.2f} / {s:>5.2f}    "
            else:
                row += f"  {'BRAK':>7}           "
        print(row)

    # Ocena stabilnosci: max roznica mean dla kazdego char_int
    if n >= 2:
        print('\n  Roznica mean miedzy sesjami (max delta [dBm]):')
        for char_int in all_chars:
            means = []
            for snap in snapshots:
                vals = snap['data'].get(str(char_int), snap['data'].get(char_int, []))
                if vals is not None and vals != []:
                    if isinstance(vals, list):
                        means.append(_stats(vals)[0])
                    else:
                        means.append(float(vals))
            if len(means) >= 2:
                delta = max(means) - min(means)
                flag  = '  <<< REKALIBRACJA?' if delta > 3.0 else ''
                print(f"    {char_int:>8} ({CHAR_TO_DEG.get(char_int, '?'):>3}d): "
                      f"delta = {delta:>5.2f} dBm{flag}")


# ══════════════════════════════════════════════════════════════════════════
# Funkcja glowna (wywolywana z main.py)
# ══════════════════════════════════════════════════════════════════════════

def run_rssi_analysis(connect_fn, stream_fn, close_fn,
                      valid_chars: set,
                      beacon_id: int = 28,
                      n_per_config: int = 500) -> None:
    """
    Tryb analizy stabilnosci RSSI.

    Args:
        connect_fn:   Funkcja connect_and_start() z main.py.
        stream_fn:    Funkcja get_espar_stream() z telnet_reader.
        close_fn:     Funkcja stop_and_close() z main.py.
        valid_chars:  Zbior prawidlowych char_int (VALID_CHARS z main.py).
        beacon_id:    ID beacona BLE.
        n_per_config: Liczba probek na konfiguracje anteny.
    """
    print('\n=== ANALIZA STABILNOSCI RSSI ===')

    # Automatyczna etykieta — zero wpisywania
    _sess_path = os.path.join(DATA_DIR, 'session.json')
    _short = 'sesja'
    if os.path.exists(_sess_path):
        try:
            with open(_sess_path, encoding='utf-8') as _sf:
                _sess = json.load(_sf)
            _origin = _sess.get('origin_label', '')
            _short = _origin.split()[0] if _origin else 'sesja'
        except Exception:
            pass
    label = f'{_short}_{datetime.now().strftime("%H%M")}'
    print(f'  Sesja:    {label}')

    existing = list_snapshots()
    if existing:
        print(f'\n  Zapisane migawki ({len(existing)}):')
        for i, p in enumerate(existing[-8:], 1):
            print(f'    {i}. {os.path.basename(p)}')

    # Zbieranie danych
    sock = connect_fn()
    if not sock:
        return

    raw: dict[int, list[float]] = {}
    print(f'\n  Zbieranie {n_per_config} probek x 12 konfiguracji '
          f'(beacon {beacon_id}, kanal 37). Ctrl+C = przerwij.\n')

    try:
        for frame in stream_fn(sock):
            if frame.get('ble_channel') != 37:
                continue
            if frame.get('espar_char_int') not in valid_chars:
                continue
            if frame.get('beacon_num') != beacon_id:
                continue

            char_int = frame['espar_char_int']
            rssi     = frame['rssi_dbm']
            raw.setdefault(char_int, []).append(rssi)

            done  = sum(1 for v in raw.values() if len(v) >= n_per_config)
            total = sum(min(len(v), n_per_config) for v in raw.values())
            print(f'  [{done:>2}/12 kompletnych]  {total:>5}/{n_per_config * 12} probek', end='\r')

            if len(raw) >= 12 and done >= 12:
                print(f'\n\n  [OK] Zebrano {n_per_config} x 12!')
                break
    except KeyboardInterrupt:
        print('\n  [!] Przerwano recznie.')
    except Exception as e:
        print(f'\n  [!] Blad: {e}')
        return
    finally:
        close_fn(sock)

    if not raw:
        print('  [!] Brak zebranych danych.')
        return

    # Przytnij do n_per_config
    raw_trimmed = {k: v[:n_per_config] for k, v in raw.items()}

    # Zapis migawki
    path = save_snapshot(label, beacon_id, raw_trimmed)
    print(f'  Zapisano: {path}')

    # Statystyki w konsoli
    print()
    for char_int in sorted(raw_trimmed):
        m, s, mn, mx = _stats(raw_trimmed[char_int])
        print(f'    {char_int:>4} ({CHAR_TO_DEG.get(char_int, "?"):>3}d): '
              f'mean={m:>7.2f}  std={s:>5.2f}  '
              f'min={mn:.1f}  max={mx:.1f}  n={len(raw_trimmed[char_int])}')

    # Histogram biezacej migawki
    snap_now = load_snapshot(path)
    snaps_to_plot = [snap_now]

    # Porownanie z poprzednia migawka?
    existing_now = list_snapshots()
    prev = [p for p in existing_now if p != path]
    if prev:
        print(f'\n  Dostepne poprzednie migawki:')
        for i, p in enumerate(prev[-5:], 1):
            print(f'    {i}. {os.path.basename(p)}')
        
        prev_list = prev[-5:]
        while True:
            ans = input('  Nakladac poprzednia migawke? (numer / Enter = nie): ').strip()
            if not ans:
                break
            try:
                idx = int(ans) - 1
                if 0 <= idx < len(prev_list):
                    snaps_to_plot.append(load_snapshot(prev_list[idx]))
                    break
                else:
                    print(f"  [!] Numer poza zakresem [1-{len(prev_list)}]. Spróbuj ponownie.")
            except ValueError:
                print("  [!] Nieprawidłowy format. Podaj numer lub wciśnij Enter.")

    if len(snaps_to_plot) >= 2:
        print_stability_table(snaps_to_plot)

    print('\n  Generuje wykresy radarowe...')
    out = plot_radar_charts(snaps_to_plot)
    if out:
        print(f'  Wykres: {out}')



# ══════════════════════════════════════════════════════════════════════════
# Analiza offline (z radio_map.json / istniejących migawek)
# ══════════════════════════════════════════════════════════════════════════

def run_rssi_offline(beacon_id: int = 28) -> None:
    """
    Analiza odcisków radiowych z istniejących danych (bez połączenia z serwerem).

    Wyświetla numerowaną listę źródeł danych:
      - punkty z radio_map.json (uśrednione RSSI per konfiguracja)
      - istniejące migawki RSSI (surowe dane)
    Użytkownik wybiera cyfrą, program rysuje wykresy.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print('[!] matplotlib/numpy niedostępny.')
        return

    # ── Wczytaj źródła danych ────────────────────────────────────────────
    # 1) Punkty z radio_map.json
    rmap_path = os.path.join(DATA_DIR, 'radio_map.json')
    radio_points: list[dict] = []
    if os.path.exists(rmap_path):
        try:
            with open(rmap_path, encoding='utf-8') as f:
                radio_points = json.load(f)
        except (json.JSONDecodeError, ValueError):
            radio_points = []

    # 2) Istniejące migawki RSSI
    snapshots = list_snapshots()

    if not radio_points and not snapshots:
        print('\n  [!] Brak danych do analizy.')
        print('      Najpierw wykonaj kalibrację (opcja 2) lub zbierz migawkę RSSI.')
        return

    # ── Przygotowanie listy wpisów (entries) ─────────────────────────────
    entries: list[tuple[str, str, any, any, any, int]] = []  # (typ, label, data, x, y, beacon_id)

    if radio_points:
        for pt in radio_points:
            label = pt.get('label', '')
            b_dict = pt.get('beacons', {})
            if b_dict:
                # Find the first available beacon in the point's beacons dict
                bid_key = list(b_dict.keys())[0]
                b_data = b_dict[bid_key]
                avg = b_data.get('avg', {})
                try:
                    bid_val = int(bid_key)
                except ValueError:
                    bid_val = 28
                entries.append(('mapa', label, avg, pt.get('x_m', '?'), pt.get('y_m', '?'), bid_val))

    if snapshots:
        for p in snapshots:
            try:
                snap = load_snapshot(p)
                fname = os.path.basename(p)
                bid_val = snap.get('beacon_id', 28)
                entries.append(('migawka', fname, p, None, None, bid_val))
            except Exception:
                pass

    if not entries:
        print(f'\n  [!] Brak danych do analizy.')
        return

    # ── Wybór sposobu wyboru punktów ─────────────────────────────────────
    print('\n=== ANALIZA ODCISKÓW RADIOWYCH (offline) ===')
    print('  Wybierz sposób doboru punktów do analizy:')
    print('    1 - Wybór graficzny z mapy (max 4 punkty na wykresie radarowym)')
    print('    2 - Wybór tekstowy z listy (konsola)')
    while True:
        choice = input('  Wybór [1/2, domyślnie 1] -> ').strip()
        if not choice:
            choice = '1'
        if choice in ('1', '2'):
            break
        print("  [!] Nieprawidłowy wybór. Wpisz 1 lub 2 (lub Enter dla domyślnego 1).")

    selected_idx = []
    if choice == '1':
        viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
        print("\n  Otwieram mapę do wyboru punktów. Kliknij interesujące Cię punkty,")
        print("  a następnie kliknij zielony przycisk 'Zatwierdź wybór'.")
        try:
            import subprocess
            # Pass all points to select-points; no filtering by beacon_id in GUI
            res = subprocess.run([sys.executable, viewer, "--select-points"], capture_output=True, text=True, check=False)
            selected_labels = []
            for line in res.stdout.splitlines():
                if 'selected_labels' in line:
                    try:
                        data = json.loads(line)
                        if data.get('confirmed'):
                            selected_labels = data.get('selected_labels', [])
                            break
                    except Exception:
                        pass
            if selected_labels:
                for label in selected_labels:
                    for i, entry in enumerate(entries):
                        if entry[1] == label:
                            selected_idx.append(i)
                            break
        except Exception as e:
            print(f'  [!] Nie udało się otworzyć mapy: {e}')
            
        if not selected_idx:
            print('  [!] Nie wybrano żadnych punktów z mapy. Przełączam na wybór tekstowy.')
            choice = '2'

    if choice == '2':
        map_entries_count = sum(1 for e in entries if e[0] == 'mapa')
        if map_entries_count > 0:
            print(f'\n  Punkty z mapy radiowej ({map_entries_count}):')
            for i, entry in enumerate(entries):
                if entry[0] == 'mapa':
                    x = entry[3]
                    y = entry[4]
                    bid = entry[5]
                    print(f'    {i+1:>3}. {entry[1]:<16} ({x} m, {y} m) [Beacon #{bid}]')

        snap_start = map_entries_count
        if len(entries) > snap_start:
            print(f'\n  Migawki RSSI ({len(entries) - snap_start}):')
            for i in range(snap_start, len(entries)):
                bid = entries[i][5]
                print(f'    {i+1:>3}. {entries[i][1]} [Beacon #{bid}]')

        while True:
            print(f'\n  Wpisz numery punktów do porównania (np. "1 5 12") lub Enter = pierwszy:')
            raw = input('  Numery -> ').strip()
            if not raw:
                selected_idx = [0]
                break
            
            parts = raw.replace(',', ' ').split()
            valid = True
            temp_idx = []
            for part in parts:
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(entries):
                        temp_idx.append(idx)
                    else:
                        print(f"  [!] Numer {part} poza zakresem [1-{len(entries)}].")
                        valid = False
                        break
                except ValueError:
                    print(f"  [!] '{part}' nie jest poprawną liczbą.")
                    valid = False
                    break
            
            if valid and temp_idx:
                selected_idx = temp_idx
                break

    if not selected_idx:
        print('  [!] Brak prawidłowych wyborów.')
        return

    # ── Przygotuj dane do wykresów ────────────────────────────────────────
    plot_data: list[tuple[str, dict]] = []  # (label, {char_int_str: avg_rssi})

    for idx in selected_idx:
        typ, label, data = entries[idx][:3]
        if typ == 'mapa':
            # data = {str(char_int): avg_rssi}
            plot_data.append((label, data))
        elif typ == 'migawka':
            # data = ścieżka pliku, wczytaj i oblicz średnie
            snap = load_snapshot(data)
            snap_avgs = {}
            for ch_str, values in snap.get('data', {}).items():
                if isinstance(values, list) and values:
                    snap_avgs[ch_str] = sum(values) / len(values)
                else:
                    snap_avgs[ch_str] = values
            plot_data.append((snap.get('label', label), snap_avgs))

    if not plot_data:
        print('  [!] Brak danych do wyświetlenia.')
        return

    # ── Wyświetl tabelę w konsoli ────────────────────────────────────────
    # Sortuj kąty rosnąco (0°, 30°, 60°, ..., 330°)
    deg_to_char = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
    sorted_degs = sorted(deg_to_char.keys())  # 0, 30, 60, ..., 330

    hdr = f'  {"kąt":>5}  {"char":>6}  '
    for label, _ in plot_data:
        hdr += f'  {label:>12}'
    print(f'\n{hdr}')
    print('  ' + '─' * (14 + len(plot_data) * 14))

    for deg in sorted_degs:
        ch = deg_to_char[deg]
        row = f'  {deg:>4}°  {ch:>6}  '
        for _, avgs in plot_data:
            val = avgs.get(str(ch)) if str(ch) in avgs else avgs.get(ch)
            if val is not None:
                row += f'  {float(val):>12.2f}'
            else:
                row += f'  {"—":>12}'
        print(row)

    # ── Wygeneruj wykresy radarowe ────────────────────────────────────────
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(SNAPSHOTS_DIR, f'analiza_odciskow_{ts}.png')
    
    selected_snaps = []
    for idx in selected_idx:
        entry = entries[idx]
        typ, label, data = entry[0], entry[1], entry[2]
        if typ == 'mapa':
            selected_snaps.append({
                'label': label,
                'beacon_id': entry[5],
                'data': data
            })
        elif typ == 'migawka':
            selected_snaps.append(load_snapshot(data))
            
    plot_radar_charts(selected_snaps, out_path)
    print(f'\n  [OK] Wykres zapisano: {out_path}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Analiza stabilnosci RSSI')
    parser.add_argument('--compare', nargs='+', metavar='FILE',
                        help='Porownaj 2-5 plikow migawek (JSON)')
    parser.add_argument('--list', action='store_true',
                        help='Wylistuj dostepne migawki')
    args = parser.parse_args()

    if args.list:
        snaps = list_snapshots()
        print(f'Migawki ({len(snaps)}):')
        for p in snaps:
            print(f'  {os.path.basename(p)}')

    elif args.compare:
        loaded = []
        for p in args.compare[:5]:
            if not os.path.exists(p):
                p2 = os.path.join(SNAPSHOTS_DIR, p)
                p  = p2 if os.path.exists(p2) else p
            loaded.append(load_snapshot(p))
        if len(loaded) >= 2:
            print_stability_table(loaded)
        out = plot_radar_charts(loaded)
        if out:
            print(f'Wykres: {out}')
    else:
        parser.print_help()
