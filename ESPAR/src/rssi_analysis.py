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

import json
import math
import os
import sys
from datetime import datetime

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'data'))
SNAPSHOTS_DIR = os.path.join(DATA_DIR, 'rssi_snapshots')

# Katy wiazki dla kazdego char_int (w stopniach) - do etykiet na wykresie
CHAR_TO_DEG = {
    31:    90,
    62:   120,
    124:  150,
    248:  180,
    496:  210,
    992:  240,
    1984: 270,
    3968: 300,
    3841: 330,
    3587:   0,
    3079:  30,
    2063:  60,
}


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


def _normal_pdf(x: float, mean: float, std: float) -> float:
    """Wartosc gestosci prawdopodobienstwa rozkladu normalnego w punkcie x."""
    if std == 0:
        return 0.0
    return (1.0 / (std * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mean) / std) ** 2)


# ══════════════════════════════════════════════════════════════════════════
# Wizualizacja
# ══════════════════════════════════════════════════════════════════════════

# Paleta kolorow dla kolejnych migawek (porownanie)
_PALETTE = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6']


def plot_histograms(snapshots: list[dict], out_path: str | None = None) -> str:
    """
    Rysuje siatke 12 histogramow (jeden per konfiguracja anteny).

    Kazda migawka (snapshot) jest nalozona odrebnym kolorem.
    Nad histogramem rysowana jest krzywa gestosci normalnej.

    Args:
        snapshots:  Lista slownikow z kluczami 'label', 'timestamp', 'data'.
        out_path:   Sciezka zapisu PNG (None = auto).

    Returns:
        Sciezka do zapisanego pliku PNG.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        import numpy as np
    except ImportError:
        print('[!] matplotlib/numpy niedostepny.')
        return ''

    # Ustal wspolny zbior char_int ze wszystkich migawek
    all_chars = set()
    for snap in snapshots:
        all_chars.update(int(k) for k in snap.get('data', {}))
    chars = sorted(CHAR_TO_DEG.keys() & all_chars)

    n_cols = 4
    n_rows = math.ceil(len(chars) / n_cols)
    fig = plt.figure(figsize=(n_cols * 3.5, n_rows * 2.8))
    gs  = gridspec.GridSpec(n_rows, n_cols, figure=fig,
                            hspace=0.55, wspace=0.35)

    for idx, char_int in enumerate(chars):
        ax  = fig.add_subplot(gs[idx // n_cols, idx % n_cols])
        deg = CHAR_TO_DEG.get(char_int, '?')

        for snap_idx, snap in enumerate(snapshots):
            values = snap['data'].get(str(char_int), snap['data'].get(char_int, []))
            if not values:
                continue

            color = _PALETTE[snap_idx % len(_PALETTE)]
            mean, std, vmin, vmax = _stats(values)

            # Histogram (ggestosc prawdopodobienstwa)
            ax.hist(values, bins=20, density=True,
                    color=color, alpha=0.4, edgecolor='none')

            # Krzywa normalna
            xs  = np.linspace(vmin - 2, vmax + 2, 200)
            pdf = [_normal_pdf(x, mean, std) for x in xs]
            ax.plot(xs, pdf, color=color, lw=1.8,
                    label=f"{snap['label']}\n"
                           r"$\mu$" + f"={mean:.1f}, "
                           r"$\sigma$" + f"={std:.1f}")

        ax.set_title(f'{char_int}  ({deg}\u00b0)', fontsize=9, pad=3)
        ax.set_xlabel('RSSI [dBm]', fontsize=7, labelpad=2)
        ax.set_ylabel('PDF', fontsize=7, labelpad=2)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.2)
        if len(snapshots) <= 3:
            ax.legend(fontsize=6, loc='upper left',
                      framealpha=0.7, handlelength=1)

    # Tytul glowny
    ts_list = ' / '.join(s.get('timestamp', '')[:16] for s in snapshots)
    fig.suptitle(
        f'Stabilnosc RSSI — konfiguracje anteny ESPAR\n'
        f'Beacon {snapshots[0].get("beacon_id", "?")} | {ts_list}',
        fontsize=11, y=1.01,
    )

    if out_path is None:
        labels   = '_vs_'.join(s['label'] for s in snapshots)
        out_path = os.path.join(SNAPSHOTS_DIR, f'{labels}_histogram.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()
    plt.close(fig)
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
        ts = snap.get('timestamp', '')[:16]
        hdr += f"  {snap['label']:>12}(mu/std)"
    print('\n' + hdr)
    print('  ' + '-' * (8 + 6 + n * 24))

    for char_int in all_chars:
        row = f"  {char_int:>8}  {CHAR_TO_DEG.get(char_int, '?'):>3}d  "
        for snap in snapshots:
            vals = snap['data'].get(str(char_int), snap['data'].get(char_int, []))
            if vals:
                m, s, _, _ = _stats(vals)
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
                if vals:
                    means.append(_stats(vals)[0])
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
        ans = input('  Nakladac poprzednia migawke? (numer / Enter = nie): ').strip()
        if ans.isdigit():
            idx = int(ans) - 1
            prev_list = prev[-5:]
            if 0 <= idx < len(prev_list):
                snaps_to_plot.append(load_snapshot(prev_list[idx]))

    if len(snaps_to_plot) >= 2:
        print_stability_table(snaps_to_plot)

    print('\n  Generuje histogramy...')
    out = plot_histograms(snaps_to_plot)
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
        with open(rmap_path, encoding='utf-8') as f:
            radio_points = json.load(f)

    # 2) Istniejące migawki RSSI
    snapshots = list_snapshots()

    if not radio_points and not snapshots:
        print('\n  [!] Brak danych do analizy.')
        print('      Najpierw wykonaj kalibrację (opcja 2) lub zbierz migawkę RSSI.')
        return

    # ── Przygotowanie listy wpisów (entries) ─────────────────────────────
    entries: list[tuple[str, str, dict]] = []  # (typ, label, data)

    if radio_points:
        for pt in radio_points:
            label = pt.get('label', '')
            b_data = pt.get('beacons', {}).get(str(beacon_id), {})
            avg = b_data.get('avg', {})
            entries.append(('mapa', label, avg))

    if snapshots:
        for p in snapshots:
            fname = os.path.basename(p)
            entries.append(('migawka', fname, p))

    # ── Wybór sposobu wyboru punktów ─────────────────────────────────────
    print('\n=== ANALIZA ODCISKÓW RADIOWYCH (offline) ===')
    print('  Wybierz sposób doboru punktów do analizy:')
    print('    1 - Wybór graficzny z mapy (klikaj myszką)')
    print('    2 - Wybór tekstowy z listy (konsola)')
    choice = input('  Wybór [1/2, domyślnie 1] -> ').strip()
    if not choice:
        choice = '1'

    selected_idx = []
    if choice == '1':
        viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
        print("\n  Otwieram mapę do wyboru punktów. Kliknij interesujące Cię punkty,")
        print("  a następnie kliknij zielony przycisk 'Zatwierdź wybór'.")
        try:
            import subprocess
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
        if radio_points:
            print(f'\n  Punkty z mapy radiowej ({len(radio_points)}):')
            for i, entry in enumerate(entries):
                if entry[0] == 'mapa':
                    pt = radio_points[i]
                    x = pt.get('x_m', '?')
                    y = pt.get('y_m', '?')
                    print(f'    {i+1:>3}. {entry[1]:<16} ({x} m, {y} m)')

        snap_start = len(radio_points)
        if snapshots:
            print(f'\n  Migawki RSSI ({len(snapshots)}):')
            for i in range(snap_start, len(entries)):
                print(f'    {i+1:>3}. {entries[i][1]}')

        print(f'\n  Wpisz numery punktów do porównania (np. "1 5 12") lub Enter = pierwszy:')
        raw = input('  Numery -> ').strip()
        if not raw:
            selected_idx = [0]
        else:
            for part in raw.replace(',', ' ').split():
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(entries):
                        selected_idx.append(idx)
                except ValueError:
                    pass

    if not selected_idx:
        print('  [!] Brak prawidłowych wyborów.')
        return

    # ── Przygotuj dane do wykresów ────────────────────────────────────────
    plot_data: list[tuple[str, dict]] = []  # (label, {char_int_str: avg_rssi})

    for idx in selected_idx:
        typ, label, data = entries[idx]
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
            val = avgs.get(str(ch))
            if val is not None:
                row += f'  {float(val):>12.2f}'
            else:
                row += f'  {"—":>12}'
        print(row)

    # ── Wykres biegunowy (radar) — kształt odcisku radiowego ─────────────
    angles_deg = np.array(sorted_degs, dtype=float)
    angles_rad = np.deg2rad(angles_deg)
    # Zamknij pętlę (dodaj pierwszy punkt na koniec)
    angles_rad_closed = np.append(angles_rad, angles_rad[0])

    n_selected = len(plot_data)

    if n_selected <= 4:
        # Pojedyncze porównanie — radar overlay
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
        ax.set_theta_zero_location('N')   # 0° na górze
        ax.set_theta_direction(-1)         # zgodnie z ruchem wskazówek zegara

        radar_plots_data = []

        for pi, (label, avgs) in enumerate(plot_data):
            vals = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                v = avgs.get(str(ch))
                vals.append(float(v) if v is not None else -100.0)
            vals_np = np.array(vals)
            vals_closed = np.append(vals_np, vals_np[0])

            max_idx = np.argmax(vals_np)
            best_rad = angles_rad[max_idx]
            best_deg = sorted_degs[max_idx]

            color = _PALETTE[pi % len(_PALETTE)]
            label_with_dir = f"{label} (max RSSI przy {best_deg}°)"
            ax.plot(angles_rad_closed, vals_closed, 'o-', color=color,
                    linewidth=2, markersize=5, label=label_with_dir, alpha=0.85)
            ax.fill(angles_rad_closed, vals_closed, color=color, alpha=0.1)
            
            radar_plots_data.append((best_rad, best_deg, color))

        ax.set_xticks(angles_rad)
        ax.set_xticklabels([f'{d}°' for d in sorted_degs], fontsize=9)
        ax.set_ylabel('RSSI [dBm]', fontsize=9, labelpad=20)
        ax.set_title(f'Odciski radiowe — Beacon {beacon_id}\n'
                     f'(Linia przerywana = szacowany kierunek beacona)',
                     fontsize=12, pad=20)
        
        # Rysuj strzałki kierunku beacona
        r_min, r_max = ax.get_ylim()
        if r_max > r_min:
            for best_rad, best_deg, color in radar_plots_data:
                ax.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)
                ax.annotate('', xy=(best_rad, r_max), xytext=(best_rad, r_max - 5),
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
                v = avgs.get(str(ch))
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
        ax_heat.set_title(f'Mapa RSSI [dBm] — Beacon {beacon_id}', fontsize=11)
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
        ax_radar.set_theta_zero_location('N')
        ax_radar.set_theta_direction(-1)

        # Wybierz max 4 równomiernie rozłożone
        if n_selected > 4:
            step = max(n_selected // 4, 1)
            show_idx = list(range(0, n_selected, step))[:4]
        else:
            show_idx = list(range(n_selected))

        radar_plots_data = []

        for pi, si in enumerate(show_idx):
            label, avgs = plot_data[si]
            vals = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                v = avgs.get(str(ch))
                vals.append(float(v) if v is not None else -100.0)
            vals_np = np.array(vals)
            vals_closed = np.append(vals_np, vals_np[0])
            
            max_idx = np.argmax(vals_np)
            best_rad = angles_rad[max_idx]
            best_deg = sorted_degs[max_idx]

            color = _PALETTE[pi % len(_PALETTE)]
            label_with_dir = f"{label} (max RSSI przy {best_deg}°)"
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
            for best_rad, best_deg, color in radar_plots_data:
                ax_radar.plot([best_rad, best_rad], [r_min, r_max], color=color, linestyle='--', linewidth=1.5, alpha=0.7)
                ax_radar.annotate('', xy=(best_rad, r_max), xytext=(best_rad, r_max - 5),
                                  arrowprops=dict(arrowstyle="->", color=color, lw=2.5, mutation_scale=12))

        ax_radar.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1), fontsize=8)
        ax_radar.grid(True, alpha=0.3)

    fig.tight_layout()

    out_path = os.path.join(SNAPSHOTS_DIR, 'analiza_odciskow.png')
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.show()
    plt.close(fig)
    print(f'\n  [OK] Wykres zapisano: {out_path}')



# ══════════════════════════════════════════════════════════════════════════

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
        out = plot_histograms(loaded)
        if out:
            print(f'Wykres: {out}')
    else:
        parser.print_help()
