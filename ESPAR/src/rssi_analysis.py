"""Analiza stabilności RSSI, wykresy radarowe i heatmapy charakterystyk kierunkowych."""

import os as _os
_os.environ.setdefault("QT_LOGGING_RULES", "qt.*=false")

from datetime import datetime
import json
import os
import subprocess
import sys

from config import CHAR_TO_DEG, DATA_DIR, SCRIPT_DIR

SNAPSHOTS_DIR = os.path.join(DATA_DIR, 'rssi_snapshots')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from utils import show_plot


# Zapisuje surowe próbki RSSI zebrane dla beacona do pliku JSON.
def save_snapshot(label: str, beacon_id: int, raw: dict) -> str:
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(SNAPSHOTS_DIR, f'{ts}_{label}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'label': label,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'beacon_id': beacon_id,
            'data': {str(k): v for k, v in raw.items()},
        }, f, indent=2, ensure_ascii=False)
    return path


def load_snapshot(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def list_snapshots() -> list[str]:
    if not os.path.exists(SNAPSHOTS_DIR):
        return []
    return sorted(os.path.join(SNAPSHOTS_DIR, fn) for fn in os.listdir(SNAPSHOTS_DIR) if fn.endswith('.json'))


_PALETTE = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6']


# Generuje wykresy radarowe (dla <=4 punktów) lub zestaw heatmapa + radar (dla większej liczby).
def plot_radar_charts(snapshots: list[dict], out_path: str | None = None) -> str:
    plt.close('all')
    deg_to_char = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
    sorted_degs = sorted(deg_to_char.keys())
    angles_rad = np.deg2rad(np.array(sorted_degs, dtype=float))
    angles_rad_closed = np.append(angles_rad, angles_rad[0])

    # Szacuje dominujący kąt nadejścia sygnału (AoA) sumując wektory kierunkowe ważone mocą RSSI
    def _estimate_direction(rssi_vals, angles):
        rssi_np = np.array(rssi_vals, dtype=float)
        shifted = rssi_np - rssi_np.min()
        weights = np.power(10.0, shifted / 10.0)
        sin_sum = np.sum(weights * np.sin(angles))
        cos_sum = np.sum(weights * np.cos(angles))
        est_rad = np.arctan2(sin_sum, cos_sum)
        return est_rad, round(np.rad2deg(est_rad) % 360, 1)

    plot_data = []
    bids_str = ', '.join(map(str, sorted({s.get('beacon_id') for s in snapshots if s.get('beacon_id')}))) or '?'

    for snap in snapshots:
        label = snap.get('label', 'migawka')
        snap_avgs = {}
        for ch, vals in snap.get('data', {}).items():
            if isinstance(vals, list) and vals:
                snap_avgs[str(ch)] = sum(vals) / len(vals)
            elif vals is not None:
                snap_avgs[str(ch)] = float(vals)
        plot_data.append((label, snap_avgs))

    n_selected = len(plot_data)
    if not n_selected:
        return ''

    # Dla małej liczby próbek rysujemy czytelny, pojedynczy wykres biegunowy
    if n_selected <= 4:
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
        ax.set_theta_offset(np.deg2rad(225))
        ax.set_theta_direction('clockwise')
        radar_plots_data = []

        for pi, (label, avgs) in enumerate(plot_data):
            vals = [float(avgs.get(str(deg_to_char[deg]), -100.0)) for deg in sorted_degs]
            vals_np = np.array(vals)
            vals_closed = np.append(vals_np, vals_np[0])
            best_rad, best_deg = _estimate_direction(vals_np, angles_rad)
            color = _PALETTE[pi % len(_PALETTE)]
            ax.plot(angles_rad_closed, vals_closed, 'o-', color=color, linewidth=2, markersize=5, label=f"{label} (≈{best_deg}°)", alpha=0.85)
            ax.fill(angles_rad_closed, vals_closed, color=color, alpha=0.1)
            radar_plots_data.append((best_rad, color))

        ax.set_xticks(angles_rad)
        ax.set_xticklabels([f'{d}°' for d in sorted_degs], fontsize=9)
        ax.set_ylabel('RSSI [dBm]', fontsize=9, labelpad=20)
        ax.set_title(f'Radar RSSI - Beacon {bids_str}', fontsize=12, pad=20)

        r_min, r_max = ax.get_ylim()
        if r_max > r_min:
            for best_rad, color in radar_plots_data:
                ax.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)

        ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=9)
        ax.grid(True, alpha=0.3)
    else:
        # Przy wielu punktach zestawiamy heatmapę z radarem poglądowym
        fig = plt.figure(figsize=(16, 8))
        ax_heat = fig.add_subplot(121)
        matrix = []
        labels_list = []

        for label, avgs in plot_data:
            matrix.append([float(avgs.get(str(deg_to_char[d]), np.nan)) for d in sorted_degs])
            labels_list.append(label)

        matrix_np = np.array(matrix)
        im = ax_heat.imshow(matrix_np, aspect='auto', cmap='RdYlBu_r')
        ax_heat.set_xticks(range(len(sorted_degs)))
        ax_heat.set_xticklabels([f'{d}°' for d in sorted_degs], rotation=45)
        ax_heat.set_yticks(range(len(labels_list)))
        ax_heat.set_yticklabels(labels_list)
        ax_heat.set_title(f'Heatmap RSSI - Beacon {bids_str}')
        fig.colorbar(im, ax=ax_heat, shrink=0.8)

        if len(labels_list) <= 20:
            for yi in range(matrix_np.shape[0]):
                for xi in range(matrix_np.shape[1]):
                    v = matrix_np[yi, xi]
                    if not np.isnan(v):
                        ax_heat.text(xi, yi, f'{v:.0f}', ha='center', va='center', fontsize=6, color='w' if v < -78 else 'k')

        ax_radar = fig.add_subplot(122, projection='polar')
        ax_radar.set_theta_offset(np.deg2rad(225))
        ax_radar.set_theta_direction('clockwise')

        radar_plots_data = []
        for pi, si in enumerate(list(range(0, n_selected, max(n_selected // 4, 1)))[:4]):
            label, avgs = plot_data[si]
            vals_np = np.array([float(avgs.get(str(deg_to_char[d]), -100.0)) for d in sorted_degs])
            vals_closed = np.append(vals_np, vals_np[0])
            best_rad, best_deg = _estimate_direction(vals_np, angles_rad)
            color = _PALETTE[pi % len(_PALETTE)]
            ax_radar.plot(angles_rad_closed, vals_closed, 'o-', color=color, linewidth=2, markersize=4, label=f"{label} (≈{best_deg}°)", alpha=0.85)
            ax_radar.fill(angles_rad_closed, vals_closed, color=color, alpha=0.08)
            radar_plots_data.append((best_rad, color))

        ax_radar.set_xticks(angles_rad)
        ax_radar.set_xticklabels([f'{d}°' for d in sorted_degs])
        ax_radar.set_title('Radar (wybrane próbki)')
        r_min, r_max = ax_radar.get_ylim()
        if r_max > r_min:
            for best_rad, color in radar_plots_data:
                ax_radar.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)

        ax_radar.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=8)

    fig.tight_layout()
    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(SNAPSHOTS_DIR, f'analiza_{ts}_radar.png')

    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    show_plot(fig, out_path)
    return out_path


def print_stability_table(snapshots: list[dict]) -> None:
    print("\nTabela zablokowana (wyniki prezentowane na radarach).")


# Zbiera próbki RSSI bezpośrednio z anteny i od razu rysuje wykres biegunowy.
def run_rssi_analysis(connect_fn, stream_fn, close_fn, valid_chars: set, beacon_id: int = 28, n_per_config: int = 500) -> None:
    _short = 'sesja'
    session_file = os.path.join(DATA_DIR, 'session.json')
    if os.path.exists(session_file):
        try:
            with open(session_file, encoding='utf-8') as f:
                _short = json.load(f).get('origin_label', 'sesja').split()[0]
        except Exception:
            pass
    label = f'{_short}_{datetime.now().strftime("%H%M")}'

    print(f'\n=== ZBIERANIE RSSI DLA SESJI {label} ===')
    sock = connect_fn()
    raw = {}
    if not sock:
        return

    try:
        for frame in stream_fn(sock):
            if frame.get('ble_channel') == 37 and frame.get('espar_char_int') in valid_chars and frame.get('beacon_num') == beacon_id:
                raw.setdefault(frame['espar_char_int'], []).append(frame['rssi_dbm'])
            if sum(1 for v in raw.values() if len(v) >= n_per_config) >= 12:
                break
    except KeyboardInterrupt:
        pass
    finally:
        close_fn(sock)

    path = save_snapshot(label, beacon_id, {k: v[:n_per_config] for k, v in raw.items()})
    plot_radar_charts([load_snapshot(path)], path.replace(".json", ".png"))
    print(f"Zakończono i zapisano wizualizacje {path}")


# Tryb analizy offline umożliwiający porównanie charakterystyk punktów zaznaczonych na mapie lub z listy.
def run_rssi_offline(beacon_id: int = 28) -> None:
    try:
        from validate import load_test_set
        from wknn import load_radio_map
        radio, test, snaps = load_radio_map(filter_session=True), load_test_set(filter_session=True), list_snapshots()
    except Exception:
        return print("[!] Błąd ładowania danych.")

    entries = []
    for src, typ in [(radio, 'mapa'), (test, 'test')]:
        for pt in src:
            if not pt.get('beacons'):
                continue
            for bid_str, b_data in pt['beacons'].items():
                lbl = pt.get('label', '?')
                entries.append((typ, f"{lbl} [B#{bid_str}]", b_data.get('avg', {}), pt.get('x_m', pt.get('x_true')), pt.get('y_m', pt.get('y_true')), int(bid_str), lbl))

    for s in snaps:
        try:
            entries.append(('migawka', os.path.basename(s), s, None, None, load_snapshot(s).get('beacon_id', 28), ''))
        except Exception:
            pass

    if not entries:
        return print("Brak danych do analizy.")

    print('\n=== ANALIZA OFFLINE ===')
    choice = input('1 - Wybór z mapy, 2 - Wybór z listy [1/2]: ').strip() or '1'
    sel_idx = []

    if choice == '1':
        print("Kliknij interesujące punkty na mapie i kliknij 'Zatwierdź'/zamknij...")
        try:
            res = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "map_viewer.py"), "--select-points"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if 'selected_labels' in line:
                    try:
                        start_idx = line.find('{')
                        if start_idx != -1:
                            line = line[start_idx:]
                        labels = json.loads(line).get('selected_labels', [])
                        for lbl in labels:
                            matched = False
                            for i, e in enumerate(entries):
                                if e[1] == lbl or e[6] == lbl or lbl in e[1]:
                                    sel_idx.append(i)
                                    matched = True
                                    break
                            if not matched:
                                print(f"[!] Nie znaleziono punktu pasującego do etykiety '{lbl}'.")
                    except Exception as e:
                        print(f"[!] Błąd parsowania odpowiedzi (nieprawidłowy JSON): {e}")
        except Exception as e:
            print(f"[!] Błąd uruchamiania podglądu mapy: {e}")

        if not sel_idx:
            print("[!] Nie udało się sparsować żadnych punktów z mapy (może nie zaznaczono?).")

        is_joining = (input("\nCzy połączyć bieżące dane z innymi dostępnymi? [T/n]: ").strip().lower() != 'n')
    else:
        is_joining = False

    if choice == '2' or is_joining:
        # Przy łączeniu bieżących danych z mapy z innymi nie wypisujemy punktów z mapy radiowej
        if is_joining:
            display_entries = [(idx, e) for idx, e in enumerate(entries) if e[0] != 'mapa' and idx not in sel_idx]
            print("\nInne dostępne dane (migawki RSSI / punkty testowe):")
        else:
            display_entries = [(idx, e) for idx, e in enumerate(entries)]
            print("\nDostępne punkty:")

        if not display_entries:
            print("  [!] Brak dodatkowych danych do wyboru.")
        else:
            for num, (orig_idx, e) in enumerate(display_entries, 1):
                if e[0] in ('mapa', 'test'):
                    print(f" {num:>2}. [{e[0].upper()}] {e[1]:<24} ({e[3]}m, {e[4]}m) [B#{e[5]}]")
                else:
                    print(f" {num:>2}. [MIGAWKA] {e[1]} [B#{e[5]}]")

            raw = input('\nPodaj numery po spacji (Enter = pomiń): ').strip()
            if raw:
                for x in raw.split():
                    if x.isdigit():
                        val = int(x)
                        if 1 <= val <= len(display_entries):
                            orig_idx = display_entries[val - 1][0]
                            if orig_idx not in sel_idx:
                                sel_idx.append(orig_idx)

    if not sel_idx:
        return print("Nie wybrano nic.")

    plot_data = []
    for i in sel_idx:
        typ, lbl, dat = entries[i][:3]
        if typ in ('mapa', 'test'):
            plot_data.append({'label': lbl, 'beacon_id': entries[i][5], 'data': dat})
        else:
            plot_data.append(load_snapshot(dat))
        print(f"[+] Dodano do radaru: {lbl}")

    out = plot_radar_charts(plot_data)
    if out:
        print(f"[OK] Wykres został wygenerowany i zapisany w: {out}")


if __name__ == '__main__':
    run_rssi_offline()
