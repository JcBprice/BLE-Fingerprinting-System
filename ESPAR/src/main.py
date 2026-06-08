"""
main.py — Główny moduł systemu lokalizacji ESPAR.

Menu:
    ── Kalibracja ──────────────────────────────────────────
    1 – Punkt orientacyjny     : ustaw origin siatki pomiarowej
    2 – Mapa odcisków radiowych: zbierz fingerprint do radio_map
    ── Diagnostyka ─────────────────────────────────────────
    3 – Podgląd mapy           : punkty kalibracyjne na SVG
    4 – Analiza RSSI           : histogramy + stabilność sygnału
    ── Walidacja ───────────────────────────────────────────
    5 – Zbieranie punktów testowych (ground truth)
    6 – Dobór parametru K      : ręczny / automatyczny
    7 – Analiza błędów         : RMSE, P90, CDF
    0 – Wyjście

Układ współrzędnych:
    Globalny (0,0) = lewy górny narożnik budynku.
    Lokalny  (0,0) = dowolny punkt siatki pomiarowej (ustawiony w opcji 1).
    x_global = session.origin_x + x_local
    y_global = session.origin_y + y_local

Filtrowanie ramek:
    a) kanał BLE = 37      — eliminuje frequency fading
    b) char_int ∈ VALID_CHARS — odrzuca stany przejściowe anteny
"""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime

from telnet_reader import get_espar_stream
from wknn import load_radio_map, save_radio_map


# ══════════════════════════════════════════════════════════════════════════
# Konfiguracja połączenia
# ══════════════════════════════════════════════════════════════════════════

HOST    = "153.19.49.102"
PORT    = 8893
TIMEOUT = 10

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data"))
SESSION_PATH = os.path.join(DATA_DIR, "session.json")


# ══════════════════════════════════════════════════════════════════════════
# Prawidłowe konfiguracje anteny ESPAR
# ══════════════════════════════════════════════════════════════════════════

# 12 wektorów sterujących (char_int). Wartości 0 i 4095 to stany przejściowe.
#  char_int │ wiązka (φ)      char_int │ wiązka (φ)
#  ─────────┼──────────       ─────────┼──────────
#        31 │  90°                3968 │ 300°
#        62 │ 120°                3841 │ 330°
#       124 │ 150°                3587 │   0°
#       248 │ 180°                3079 │  30°
#       496 │ 210°                2063 │  60°
#       992 │ 240°
#      1984 │ 270°
VALID_CHARS = {31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}


# ══════════════════════════════════════════════════════════════════════════
# Zarządzanie sesją pomiarową
# ══════════════════════════════════════════════════════════════════════════

def load_session() -> dict | None:
    """Wczytuje aktywną sesję z session.json lub zwraca None."""
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_session(origin_label: str, origin_x: float, origin_y: float) -> None:
    """Zapisuje sesję pomiarową do session.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "origin_label": origin_label,
            "origin_x_m":   round(origin_x, 4),
            "origin_y_m":   round(origin_y, 4),
            "created":      datetime.now().isoformat(timespec="seconds"),
        }, f, indent=2, ensure_ascii=False)


def _pick_on_map(flag: str) -> dict | None:
    """
    Uruchamia map_viewer.py z podanym trybem i czeka na JSON z stdout.
    flag: '--pick-session' lub '--mark-origin' lub '--pick'
    """
    viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
    result = subprocess.run(
        [sys.executable, viewer, flag],
        capture_output=True, text=True, encoding="utf-8",
    )
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return None


def manage_session() -> None:
    """
    Tryb 5: Sesja pomiarowa — ustaw lokalny origin siatki.

    Użytkownik klika na mapie SVG miejsce, od którego będzie mierzyć
    lokalne współrzędne (taśmą). System zapisuje to jako origin sesji.
    Każdy kolejny punkt kalibracyjny jest podawany w metrach od tego origin.
    """
    sess = load_session()
    if sess:
        print(f"\n[Sesja aktywna]")
        print(f"  Origin: '{sess['origin_label']}'")
        print(f"  Pozycja globalna: X={sess['origin_x_m']} m, Y={sess['origin_y_m']} m")
        print(f"  Utworzona: {sess.get('created', '?')}")
        ans = input("\nKontynuować tę sesję? (t=tak / n=nowa sesja): ").strip().lower()
        if ans != "n":
            return

    print("\n[Nowa sesja] Otwieram mapę — kliknij miejsce gdzie zaczyna się Twoja siatka pomiarowa.")
    print("  To będzie lokalny punkt (0,0). Mierz od niego taśmą do kolejnych punktów.\n")

    data = _pick_on_map("--pick-session")
    if not data or not data.get("picked"):
        print("[!] Nie zaznaczono originu. Sesja niezmieniona.")
        return

    x_m = data["x_m"]
    y_m = data["y_m"]
    label = input(f"  Opis tego punktu (np. 'narożnik pok.707 przy drzwiach'): ").strip()
    if not label:
        label = f"origin_{datetime.now().strftime('%Y%m%d_%H%M')}"

    save_session(label, x_m, y_m)
    print(f"\n[OK] Sesja zapisana: '{label}' @ ({x_m} m, {y_m} m)")
    print("     Podczas kalibracji wpisuj lokalne X, Y od tego punktu.")





# ══════════════════════════════════════════════════════════════════════════
# Zarządzanie połączeniem TCP
# ══════════════════════════════════════════════════════════════════════════

def connect_and_start() -> socket.socket | None:
    """Nawiązuje połączenie TCP z serwerem ESPAR i wysyła komendę 'start'."""
    print(f"\nŁączenie z {HOST}:{PORT}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(b"\r\n")
        time.sleep(0.5)
        s.sendall(b"start\r\n")
        print("Połączono. Odbieranie danych...\n")
        return s
    except ConnectionRefusedError:
        print(f"[!] Odmowa połączenia z {HOST}:{PORT}.")
    except socket.timeout:
        print(f"[!] Timeout podczas łączenia z {HOST}:{PORT}.")
    except Exception as e:
        print(f"[!] Błąd sieci: {e}")
    return None


def stop_and_close(sock: socket.socket | None) -> None:
    """Wysyła 'stop' i zamyka gniazdo TCP."""
    if sock is None:
        return
    try:
        print("\nZatrzymuję transmisję...")
        sock.sendall(b"stop\r\n")
        time.sleep(0.5)
    except Exception:
        pass
    sock.close()




# ══════════════════════════════════════════════════════════════════════════
# Tryb 2: Kalibracja — zbieranie fingerprinta
# ══════════════════════════════════════════════════════════════════════════

def run_average() -> None:
    """
    Tryb kalibracji (faza offline fingerprintingu).

    Wymaga aktywnej sesji (opcja 5). Użytkownik podaje lokalne x, y
    od origin sesji. System oblicza globalne = origin + lokalne i zbiera
    TARGET_PACKETS próbek dla każdej z 12 konfiguracji anteny.
    """
    TARGET_PACKETS = 100

    # ── Sprawdź sesję ────────────────────────────────────────────────────
    sess = load_session()
    if not sess:
        print("\n[!] Brak aktywnej sesji pomiarowej.")
        print("    Najpierw ustaw origin siatki (opcja 5 w menu).")
        return

    ox = sess["origin_x_m"]
    oy = sess["origin_y_m"]
    print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")

    # ── Etykieta i lokalne współrzędne ───────────────────────────────────
    label = input("  Etykieta punktu (np. '707_p01'): ").strip() or "punkt"
    try:
        x_local = float(input("  Lokalne X [m] (od origin sesji): ").strip())
        y_local = float(input("  Lokalne Y [m] (od origin sesji): ").strip())
    except ValueError:
        print("[!] Nieprawidłowe współrzędne.")
        return

    x_global = round(ox + x_local, 4)
    y_global = round(oy + y_local, 4)
    print(f"\n  Lokalne:  X={x_local} m, Y={y_local} m")
    print(f"  Globalne: X={x_global} m, Y={y_global} m")

    # ── Zbieranie próbek ─────────────────────────────────────────────────
    sock = connect_and_start()
    if not sock:
        return

    beacons_data: dict[int, dict[int, list[float]]] = {}
    packet_count = 0

    print(f"\nZbieranie danych @ '{label}' ({x_global} m, {y_global} m)")
    print(f"Cel: {TARGET_PACKETS} pakietów × 12 konfiguracji anteny (kanał 37).")
    print("Ctrl+C = przerwij i zapisz zebrane dane.\n")

    try:
        for frame in get_espar_stream(sock):
            if frame.get("ble_channel") != 37:
                continue
            if frame.get("espar_char_int") not in VALID_CHARS:
                continue

            b_num    = frame["beacon_num"]
            char_int = frame["espar_char_int"]
            rssi     = frame["rssi_dbm"]

            beacons_data.setdefault(b_num, {}).setdefault(char_int, []).append(rssi)
            packet_count += 1

            if packet_count % 10 == 0:
                chars_dict = beacons_data[b_num]
                done = sum(1 for v in chars_dict.values() if len(v) >= TARGET_PACKETS)
                print(f"  Beacon #{b_num}: {done}/12 konfiguracji ({packet_count} pkt)...", end="\r")
                if len(chars_dict) >= 12 and done >= 12:
                    print(f"\n\n[OK] Zebrano {TARGET_PACKETS} pkt × 12 konfiguracji!")
                    break

    except KeyboardInterrupt:
        print("\n\n[!] Przerwano ręcznie. Przetwarzam zebrane dane...")
    except socket.timeout:
        print("\n[!] Timeout serwera.")
        return
    finally:
        stop_and_close(sock)

    if not beacons_data:
        print("[!] Brak zebranych danych.")
        return

    # ── Obliczenie fingerprinta ──────────────────────────────────────────
    fingerprints: dict[int, dict] = {}
    norm_fps:     dict[int, dict] = {}

    for b_num, chars_data in beacons_data.items():
        avg = {}
        for ch, values in chars_data.items():
            trimmed = values[:TARGET_PACKETS]
            avg[ch] = round(sum(trimmed) / len(trimmed), 2)
        fingerprints[b_num] = avg

        mn, mx = min(avg.values()), max(avg.values())
        if mx > mn:
            norm_fps[b_num] = {ch: round((v - mn) / (mx - mn), 4) for ch, v in avg.items()}
        else:
            norm_fps[b_num] = {ch: 0.0 for ch in avg}

    # ── Zapis do mapy radiowej ───────────────────────────────────────────
    new_point = {
        "label":   label,
        "x_m":     x_global,
        "y_m":     y_global,
        "_local":  {"x": x_local, "y": y_local,
                    "session": sess["origin_label"]},  # informacja poglądowa
        "beacons": {
            str(b): {
                "avg":  {str(k): v for k, v in fingerprints[b].items()},
                "norm": {str(k): v for k, v in norm_fps[b].items()},
            }
            for b in fingerprints
        },
    }

    existing = load_radio_map()
    updated  = False
    for i, fp in enumerate(existing):
        if fp.get("label") == label:
            existing[i] = new_point
            updated = True
            break
    if not updated:
        existing.append(new_point)
    save_radio_map(existing)

    print(f"\n[OK] Zapisano '{label}' @ globalnie ({x_global} m, {y_global} m).")
    print(f"     Mapa radiowa: {len(existing)} punktów.")

    if 28 in norm_fps:
        print("\nZnormalizowane odciski (beacon 28):")
        print(json.dumps({str(k): v for k, v in norm_fps[28].items()}, indent=2))


def _collect_fingerprint(sock, label: str, target_packets: int = 100) -> dict | None:
    """
    Zbiera fingerprint z podanego gniazda TCP.
    Zwraca słownik {beacon_id: {"avg": {...}, "norm": {...}}} lub None.
    """
    beacons_data: dict[int, dict[int, list[float]]] = {}
    packet_count = 0

    print(f"\n  Zbieranie danych @ '{label}'...")
    print(f"  Cel: {target_packets} pkt × 12 konfiguracji (kanał 37). Ctrl+C = przerwij.\n")

    try:
        for frame in get_espar_stream(sock):
            if frame.get("ble_channel") != 37:
                continue
            if frame.get("espar_char_int") not in VALID_CHARS:
                continue

            b_num    = frame["beacon_num"]
            char_int = frame["espar_char_int"]
            rssi     = frame["rssi_dbm"]

            beacons_data.setdefault(b_num, {}).setdefault(char_int, []).append(rssi)
            packet_count += 1

            if packet_count % 10 == 0:
                chars_dict = beacons_data[b_num]
                done = sum(1 for v in chars_dict.values() if len(v) >= target_packets)
                print(f"  Beacon #{b_num}: {done}/12 konfiguracji ({packet_count} pkt)...", end="\r")
                if len(chars_dict) >= 12 and done >= 12:
                    print(f"\n\n  [OK] Zebrano {target_packets} pkt × 12 konfiguracji!")
                    break

    except KeyboardInterrupt:
        print("\n\n  [!] Przerwano ręcznie. Przetwarzam zebrane dane...")

    if not beacons_data:
        return None

    # Oblicz fingerprint
    fingerprints: dict[int, dict] = {}
    norm_fps:     dict[int, dict] = {}

    for b_num, chars_data in beacons_data.items():
        avg = {}
        for ch, values in chars_data.items():
            trimmed = values[:target_packets]
            avg[ch] = round(sum(trimmed) / len(trimmed), 2)
        fingerprints[b_num] = avg

        mn, mx = min(avg.values()), max(avg.values())
        if mx > mn:
            norm_fps[b_num] = {ch: round((v - mn) / (mx - mn), 4) for ch, v in avg.items()}
        else:
            norm_fps[b_num] = {ch: 0.0 for ch in avg}

    return {
        str(b): {
            "avg":  {str(k): v for k, v in fingerprints[b].items()},
            "norm": {str(k): v for k, v in norm_fps[b].items()},
        }
        for b in fingerprints
    }


# ══════════════════════════════════════════════════════════════════════════
# Kalibracja siatkowa (automatyczna)
# ══════════════════════════════════════════════════════════════════════════

def run_grid_calibration() -> None:
    """
    Automatyczna kalibracja siatkowa.

    Program pyta o wymiary badanego obszaru (szerokość X, głębokość Y)
    oraz skok między punktami pomiarowymi, a następnie:
      1. Generuje plan siatki z automatycznymi etykietami.
      2. Pokazuje użytkownikowi cały plan z listą punktów.
      3. Prowadzi użytkownika punkt po punkcie, informując o kierunku
         i odległości przemieszczenia.
    """
    TARGET_PACKETS = 100

    # ── Sprawdź sesję ────────────────────────────────────────────────────
    sess = load_session()
    if not sess:
        print("\n[!] Brak aktywnej sesji pomiarowej.")
        print("    Najpierw ustaw origin siatki (opcja 1 w menu).")
        return

    ox = sess["origin_x_m"]
    oy = sess["origin_y_m"]
    print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")

    # ── Parametry siatki ─────────────────────────────────────────────────
    print("\n  Podaj parametry badanego obszaru (w metrach od origin sesji):")
    try:
        length_x = float(input("  Długość obszaru w osi X [m]: ").strip())
        length_y = float(input("  Długość obszaru w osi Y [m]: ").strip())
        step_x   = float(input("  Skok w osi X [m]: ").strip())
        step_y   = float(input("  Skok w osi Y [m]: ").strip())
    except ValueError:
        print("[!] Nieprawidłowe wartości.")
        return

    if length_x <= 0 or length_y <= 0 or step_x <= 0 or step_y <= 0:
        print("[!] Wszystkie wartości muszą być dodatnie.")
        return

    # ── Prefix etykiet ───────────────────────────────────────────────────
    prefix = input("  Prefix etykiet (np. '707_p', domyślnie 'p'): ").strip() or "p"

    # ── Generowanie siatki ───────────────────────────────────────────────
    # Punkty od (0,0) do (length_x, length_y) z krokiem step_x / step_y
    xs = []
    x = 0.0
    while x <= length_x + 1e-9:
        xs.append(round(x, 4))
        x += step_x
    ys = []
    y = 0.0
    while y <= length_y + 1e-9:
        ys.append(round(y, 4))
        y += step_y

    # Kolejność: meander (zygzak) — minimalizuje chodzenie
    # Parzyste wiersze Y: X rosnąco, nieparzyste: X malejąco
    grid_points: list[tuple[str, float, float]] = []
    point_num = 1
    for yi, yv in enumerate(ys):
        row_xs = xs if (yi % 2 == 0) else list(reversed(xs))
        for xv in row_xs:
            label = f"{prefix}{point_num:02d}"
            grid_points.append((label, xv, yv))
            point_num += 1

    n_total = len(grid_points)
    n_cols  = len(xs)
    n_rows  = len(ys)

    # ── Wyświetl plan ────────────────────────────────────────────────────
    print(f"\n{'═' * 56}")
    print(f"  PLAN KALIBRACJI SIATKOWEJ")
    print(f"{'─' * 56}")
    print(f"  Obszar:       {length_x} m × {length_y} m")
    print(f"  Skok:         X={step_x} m,  Y={step_y} m")
    print(f"  Siatka:       {n_cols} kolumn × {n_rows} wierszy = {n_total} punktów")
    print(f"  Kolejność:    meander (zygzak) — minimalna droga")
    print(f"{'─' * 56}")
    print(f"  {'Nr':<5} {'Etykieta':<12} {'Lok. X [m]':>10} {'Lok. Y [m]':>10} {'Glob. X':>9} {'Glob. Y':>9}")
    print(f"  {'─' * 52}")
    for i, (lbl, lx, ly) in enumerate(grid_points, 1):
        gx = round(ox + lx, 4)
        gy = round(oy + ly, 4)
        print(f"  {i:<5} {lbl:<12} {lx:>10.2f} {ly:>10.2f} {gx:>9.2f} {gy:>9.2f}")
    print(f"{'═' * 56}")

    ans = input(f"\n  Rozpocząć kalibrację {n_total} punktów? (t/n): ").strip().lower()
    if ans != "t":
        print("  Anulowano.")
        return

    # ── Zbieranie danych punkt po punkcie ────────────────────────────────
    existing = load_radio_map()
    completed = 0
    prev_x, prev_y = None, None

    for i, (label, x_local, y_local) in enumerate(grid_points, 1):
        x_global = round(ox + x_local, 4)
        y_global = round(oy + y_local, 4)

        print(f"\n{'━' * 56}")
        print(f"  PUNKT {i}/{n_total}:  {label}")
        print(f"  Pozycja lokalna:   X={x_local:.2f} m,  Y={y_local:.2f} m")
        print(f"  Pozycja globalna:  X={x_global:.2f} m,  Y={y_global:.2f} m")

        if prev_x is not None:
            dx = round(x_local - prev_x, 4)
            dy = round(y_local - prev_y, 4)
            parts = []
            if abs(dx) > 1e-6:
                direction_x = "w PRAWO" if dx > 0 else "w LEWO"
                parts.append(f"{abs(dx):.2f} m {direction_x} (oś X)")
            if abs(dy) > 1e-6:
                direction_y = "W DÓŁ (dalej)" if dy > 0 else "W GÓRĘ (bliżej)"
                parts.append(f"{abs(dy):.2f} m {direction_y} (oś Y)")
            if parts:
                print(f"  ➤ Przemieść się: {', '.join(parts)}")
            else:
                print(f"  ➤ Zostań w miejscu (ten sam punkt)")
        else:
            if x_local > 0 or y_local > 0:
                print(f"  ➤ Stań w punkcie: {x_local:.2f} m od origin (X), {y_local:.2f} m od origin (Y)")
            else:
                print(f"  ➤ Stań w punkcie origin (0, 0)")
        print(f"{'━' * 56}")

        action = input("  [Enter] = zbieraj  |  [s] = pomiń  |  [q] = zakończ: ").strip().lower()
        if action == "q":
            print(f"\n  Zakończono po {completed} z {n_total} punktach.")
            break
        if action == "s":
            print(f"  Pominięto {label}.")
            prev_x, prev_y = x_local, y_local
            continue

        # Połączenie TCP i zbieranie fingerprinta
        sock = connect_and_start()
        if not sock:
            print(f"  [!] Nie udało się połączyć. Pomijam {label}.")
            prev_x, prev_y = x_local, y_local
            continue

        beacons = _collect_fingerprint(sock, label, TARGET_PACKETS)
        stop_and_close(sock)

        if not beacons:
            print(f"  [!] Brak danych dla {label}. Pomijam.")
            prev_x, prev_y = x_local, y_local
            continue

        new_point = {
            "label":   label,
            "x_m":     x_global,
            "y_m":     y_global,
            "_local":  {"x": x_local, "y": y_local,
                        "session": sess["origin_label"]},
            "beacons": beacons,
        }

        # Zapisz / nadpisz punkt
        updated = False
        for j, fp in enumerate(existing):
            if fp.get("label") == label:
                existing[j] = new_point
                updated = True
                break
        if not updated:
            existing.append(new_point)
        save_radio_map(existing)

        completed += 1
        prev_x, prev_y = x_local, y_local
        print(f"  [OK] Zapisano '{label}' @ ({x_global} m, {y_global} m)")
        print(f"       Postęp: {completed}/{n_total} | Mapa radiowa: {len(existing)} pkt")

    print(f"\n{'═' * 56}")
    print(f"  KALIBRACJA ZAKOŃCZONA")
    print(f"  Zebrano: {completed}/{n_total} punktów")
    print(f"  Mapa radiowa: {len(existing)} punktów łącznie")
    print(f"{'═' * 56}")




# ══════════════════════════════════════════════════════════════════════════
# Tryb 6: Zbieranie punktów testowych (ground truth)
# ══════════════════════════════════════════════════════════════════════════

def run_collect_test_point() -> None:
    """
    Tryb 6: Zbieranie punktów testowych (ground truth).

    Identyczny mechanizm jak kalibracja, ALE wynik trafia do test_set.json
    zamiast radio_map.json. Punkty testowe NIE MOGĄ znaleźć się w radio_map
    (algorytm nie może ich „znać" przed walidacją).
    """
    TARGET_PACKETS = 100

    sess = load_session()
    if not sess:
        print("\n[!] Brak aktywnej sesji. Ustaw origin siatki (opcja 5).")
        return

    ox, oy = sess["origin_x_m"], sess["origin_y_m"]
    print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")
    print("  [PUNKT TESTOWY — zapisywany do test_set.json, NIE do radio_map]")

    label = input("  Etykieta punktu (np. 'test_p01'): ").strip() or "test_pt"
    try:
        x_local = float(input("  Lokalne X [m] (od origin sesji): ").strip())
        y_local = float(input("  Lokalne Y [m] (od origin sesji): ").strip())
    except ValueError:
        print("[!] Nieprawidłowe współrzędne.")
        return

    x_global = round(ox + x_local, 4)
    y_global  = round(oy + y_local, 4)
    print(f"\n  Lokalne:  X={x_local} m, Y={y_local} m")
    print(f"  Globalne: X={x_global} m, Y={y_global} m")

    sock = connect_and_start()
    if not sock:
        return

    beacons_data: dict[int, dict[int, list[float]]] = {}
    packet_count = 0
    print(f"\nZbieranie danych testowych @ '{label}'. Ctrl+C = przerwij.\n")
    try:
        for frame in get_espar_stream(sock):
            if frame.get("ble_channel") != 37:
                continue
            if frame.get("espar_char_int") not in VALID_CHARS:
                continue
            b_num    = frame["beacon_num"]
            char_int = frame["espar_char_int"]
            rssi     = frame["rssi_dbm"]
            beacons_data.setdefault(b_num, {}).setdefault(char_int, []).append(rssi)
            packet_count += 1
            if packet_count % 10 == 0:
                done = sum(1 for v in beacons_data[b_num].values() if len(v) >= TARGET_PACKETS)
                print(f"  Beacon #{b_num}: {done}/12 ({packet_count} pkt)...", end="\r")
                if len(beacons_data[b_num]) >= 12 and done >= 12:
                    print("\n[OK] Zebrano!")
                    break
    except KeyboardInterrupt:
        print("\n[!] Przerwano ręcznie.")
    except socket.timeout:
        print("\n[!] Timeout.")
        return
    finally:
        stop_and_close(sock)

    if not beacons_data:
        return

    fingerprints = {}
    norm_fps     = {}
    for b_num, chars_data in beacons_data.items():
        avg = {ch: round(sum(v[:TARGET_PACKETS]) / len(v[:TARGET_PACKETS]), 2)
               for ch, v in chars_data.items()}
        fingerprints[b_num] = avg
        mn, mx = min(avg.values()), max(avg.values())
        norm_fps[b_num] = (
            {ch: round((v - mn) / (mx - mn), 4) for ch, v in avg.items()}
            if mx > mn else {ch: 0.0 for ch in avg}
        )

    new_point = {
        "label":   label,
        "x_true":  x_global,
        "y_true":  y_global,
        "_local":  {"x": x_local, "y": y_local, "session": sess["origin_label"]},
        "beacons": {
            str(b): {
                "avg":  {str(k): v for k, v in fingerprints[b].items()},
                "norm": {str(k): v for k, v in norm_fps[b].items()},
            } for b in fingerprints
        },
    }

    from validate import load_test_set, save_test_set
    existing = [tp for tp in load_test_set() if tp.get("label") != label]
    existing.append(new_point)
    save_test_set(existing)
    print(f"[OK] Zapisano '{label}' @ ({x_global} m, {y_global} m). Zbior: {len(existing)} pkt.")


# ══════════════════════════════════════════════════════════════════════════
# Menu główne
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    while True:
        sess = load_session()
        sess_info = (
            f"'{sess['origin_label']}' @ ({sess['origin_x_m']}, {sess['origin_y_m']}) m"
            if sess else "BRAK -- ustaw przed kalibracja (opcja 1)"
        )
        from validate import load_test_set as _lts, load_optimal_k as _lok
        n_test  = len(_lts())
        n_radio = len(load_radio_map())
        best_k  = _lok(default=None)
        k_info  = str(best_k) if best_k is not None else "niewyznaczone"

        print("\n=== SYSTEM LOKALIZACJI ESPAR ===")
        print(f"  Sesja:     {sess_info}")
        print(f"  Radio map: {n_radio} pkt  |  Zbior testowy: {n_test} pkt  |  K_opt: {k_info}")
        print("  ---- Kalibracja ----------------------------------------")
        print("  1 - Punkt orientacyjny        (ustaw origin siatki)")
        print("  2 - Mapa odciskow radiowych   (zbierz fingerprint)")
        print("  ---- Diagnostyka ---------------------------------------")
        print("  3 - Podglad mapy              (punkty kalibracyjne)")
        print("  4 - Analiza RSSI              (histogramy + stabilnosc)")
        print("  ---- Walidacja -----------------------------------------")
        print("  5 - Zbieranie punktow testowych")
        print("  6 - Dobor parametru K         (reczny / automatyczny)")
        print("  7 - Analiza bledow            (RMSE, P90, CDF)")
        print("  ---------------------------------------------------------")
        print("  0 - Wyjscie")

        choice = input("\nWybierz tryb -> ").strip()

        if choice == "1":
            manage_session()
        elif choice == "2":
            print("\n  Tworzenie mapy odciskow radiowych:")
            print("    p - Pojedynczy punkt  (reczne podanie etykiety i wspolrzednych)")
            print("    s - Siatka automatyczna (plan calego obszaru)")
            sub = input("  Wybierz [p/s] -> ").strip().lower()
            if sub == "s":
                run_grid_calibration()
            else:
                run_average()
        elif choice == "3":
            viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
            print("Otwieram mape z punktami kalibracyjnymi...")
            subprocess.run([sys.executable, viewer, "--view"], check=False)
        elif choice == "4":
            print("\n  Analiza RSSI:")
            print("    1 - Analiza istniejacych danych  (z mapy / migawek, offline)")
            print("    2 - Nowy pomiar na zywo          (wymaga polaczenia z serwerem)")
            sub = input("  Wybierz [1/2] -> ").strip()
            if sub == "2":
                from rssi_analysis import run_rssi_analysis
                run_rssi_analysis(
                    connect_fn=connect_and_start,
                    stream_fn=get_espar_stream,
                    close_fn=stop_and_close,
                    valid_chars=VALID_CHARS,
                    beacon_id=28,
                    n_per_config=500,
                )
            else:
                from rssi_analysis import run_rssi_offline
                run_rssi_offline(beacon_id=28)
        elif choice == "5":
            run_collect_test_point()
        elif choice == "6":
            from validate import optimize_k
            print("\n  Dobor parametru K:")
            print("    a - Automatyczny (grid search, minimalizacja RMSE)")
            print("    r - Reczny (podaj wartosc K)")
            sub = input("  Wybierz [a/r] -> ").strip().lower()
            if sub == "r":
                try:
                    k_val = int(input("  Podaj wartosc K: ").strip())
                    if k_val < 1:
                        raise ValueError
                    os.makedirs(DATA_DIR, exist_ok=True)
                    import json as _json
                    with open(os.path.join(DATA_DIR, "optimal_k.json"), "w",
                              encoding="utf-8") as _f:
                        _json.dump({"k": k_val, "beacon_id": 28,
                                    "source": "manual"}, _f, indent=2)
                    print(f"  [OK] Zapisano K={k_val} (reczny dobor).")
                except ValueError:
                    print("  [!] Nieprawidlowa wartosc K.")
            else:
                optimize_k(beacon_id=28)
        elif choice == "7":
            from validate import run_validation
            run_validation(k=None, beacon_id=28)
        elif choice == "0":
            print("Do widzenia.")
            break
        else:
            print("Nieprawidlowy wybor. Wpisz 0-7.")
