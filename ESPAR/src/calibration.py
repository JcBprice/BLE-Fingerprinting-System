import os
import sys
import subprocess
import json
import math
import socket

from session import SessionManager, DATA_DIR, SCRIPT_DIR
from espar_client import EsparClient
from telnet_reader import get_espar_stream
from wknn import load_radio_map, save_radio_map
from utils import get_int_input, get_float_input, get_choice_input
from config import VALID_CHARS, DEFAULT_TARGET_PACKETS, DEFAULT_BEACON_ID

class Calibrator:
    """Moduł do zbierania danych kalibracyjnych (fingerprinting)."""
    
    VALID_CHARS = VALID_CHARS
    TARGET_PACKETS = DEFAULT_TARGET_PACKETS
    
    def __init__(self, session_manager: SessionManager, client: EsparClient):
        self.session_manager = session_manager
        self.client = client

    def _collect_fingerprint(self, sock: socket.socket, label: str, target_packets: int = 100, beacons_list: list = None) -> dict | None:
        """
        Uruchamia graficzny edytor kalibracji z radarowym podglądem na żywo.
        Zamyka przekazane gniazdo 'sock' przed otwarciem GUI, aby uniknąć konfliktu portów.
        """
        # Zwolnij połączenie TCP przed otwarciem GUI
        try:
            if sock:
                self.client.stop_and_close(sock)
        except Exception:
            pass

        viewer = os.path.join(self.session_manager.script_dir, "map_viewer.py")
        
        if not beacons_list:
            beacons_list = [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]

        beacons_json = json.dumps(beacons_list)

        print(f"\n  [GUI] Uruchamianie wizualnej kalibracji dla '{label}'...")
        try:
            result = subprocess.run(
                [sys.executable, viewer, "--calibrate", label, beacons_json, str(target_packets)],
                capture_output=True, text=True, encoding="utf-8"
            )
            
            # Wyszukaj i sparsuj JSON z stdout
            found_json = False
            for line in reversed(result.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        found_json = True
                        return data
                    except Exception:
                        pass
            
            if not found_json:
                print("  [!] Nie otrzymano poprawnych danych pomiarowych z GUI (anulowano lub wystąpił błąd).")
                if result.stderr.strip():
                    print(f"  [Debug] Logi błędów GUI:\n{result.stderr.strip()}")
        except Exception as e:
            print(f"[!] Błąd uruchamiania map_viewer: {e}")
        return None

    def _scan_available_beacons(self) -> list[int]:
        """Skanuje strumień przez krótki czas, aby wykryć aktywne beacony w otoczeniu."""
        import time
        print("\n  [Skanowanie] Szukanie aktywnych beaconów w zasięgu (2 sekundy)...")
        sock = self.client.connect_and_start()
        if not sock:
            print("  [!] Nie udało się połączyć w celu skanowania.")
            return []
        
        detected = set()
        start_time = time.time()
        try:
            sock.settimeout(2.0)
            for frame in get_espar_stream(sock):
                if time.time() - start_time > 2.0:
                    break
                bid = frame.get("beacon_num")
                if bid is not None:
                    detected.add(bid)
        except Exception:
            pass
        finally:
            self.client.stop_and_close(sock)
            
        detected_list = sorted(list(detected))
        if not detected_list:
            print("  [!] Nie wykryto żadnych beaconów.")
        return detected_list

    # ── Konfiguracja zestawu beaconów ─────────────────────────

    def _ask_tripod_params(self) -> dict | None:
        """Pyta użytkownika o konfigurację zestawu beaconów.

        Zwraca dict z parametrami lub None (1 beacon = pojedynczy).
        """
        n = get_int_input("\n  Ile beaconów w zestawie? (1 = pojedynczy beacon, domyślnie 1): ", default=1, min_val=1)

        if n <= 1:
            return None

        # Skanowanie aktywnych beaconów w otoczeniu
        available = self._scan_available_beacons()
        if not available:
            print(f"\n  [!] Brak wykrytych beaconów. Wpisz {n} ID beaconów ręcznie (np. '28,33' lub '28'):")
            while True:
                ids_raw = input("  ID beaconów: ").strip()
                try:
                    if "," in ids_raw:
                        beacon_ids = [int(x.strip()) for x in ids_raw.split(",")]
                    elif "-" in ids_raw:
                        parts = ids_raw.split("-")
                        start_id = int(parts[0].strip())
                        end_id = int(parts[1].strip())
                        beacon_ids = list(range(start_id, end_id + 1))
                    elif ids_raw:
                        beacon_ids = [int(ids_raw.strip())]
                    else:
                        print("  [!] Wpisz przynajmniej jedno ID.")
                        continue
                    
                    if len(beacon_ids) != n:
                        print(f"  [!] Podano {len(beacon_ids)} ID zamiast {n}. Spróbuj ponownie.")
                        continue
                    break
                except ValueError:
                    print("  [!] Nieprawidłowy format. Podaj liczby całkowite.")
        else:
            print("\n  Wykryte beacony w zasięgu:")
            for idx, bid in enumerate(available, 1):
                print(f"    {idx} - Beacon ID {bid}")

            print(f"\n  Wybierz {n} beaconów z listy powyżej.")
            print(f"  Formaty: '1,2,3' lub '1-3' lub Enter = pierwsze {n}")
            
            while True:
                ids_raw = input("  Wybór: ").strip()
                try:
                    if not ids_raw:
                        # Auto-select first N beacons
                        selected_indices = list(range(1, n + 1))
                    elif "-" in ids_raw and "," not in ids_raw:
                        # Range format: "1-3"
                        parts = ids_raw.split("-")
                        start_idx = int(parts[0].strip())
                        end_idx = int(parts[1].strip())
                        selected_indices = list(range(start_idx, end_idx + 1))
                    else:
                        # Comma format: "1,2,3"
                        selected_indices = [int(x.strip()) for x in ids_raw.split(",")]

                    if len(selected_indices) != n:
                        print(f"  [!] Podano {len(selected_indices)} pozycji zamiast {n}. Spróbuj ponownie.")
                        continue
                    
                    beacon_ids = []
                    valid_selection = True
                    for idx in selected_indices:
                        if 1 <= idx <= len(available):
                            beacon_ids.append(available[idx - 1])
                        else:
                            print(f"  [!] Numer {idx} poza zakresem [1-{len(available)}].")
                            valid_selection = False
                            break
                    if not valid_selection:
                        continue
                    break
                except (ValueError, IndexError):
                    print("  [!] Nieprawidłowy format. Użyj '1,2,3' lub '1-3'. Spróbuj ponownie.")

        spacing = get_float_input("  Odstęp między kolejnymi beaconami [m]: ", min_val=0.0)

        # ── Wybór orientacji zestawu ──
        print("\n  Jak ustawiony jest zestaw beaconów?")
        print("    1 - Poziomo (wzdłuż osi X)")
        print("    2 - Pionowo (wzdłuż osi Y)")
        choice_orient = get_choice_input("  Wybierz [1-2] (domyślnie 1): ", ("1", "2"), default="1")

        if choice_orient == "2":
            angle = 90.0
            orient_label = "pionowo (oś Y)"
        else:
            angle = 0.0
            orient_label = "poziomo (oś X)"
        print(f"  Orientacja zestawu: {orient_label}")

        # ── Kierunek skanowania (w którą stronę użytkownik się przemieszcza) ──
        print("\n  W którą stronę będziesz robić kolejne odciski (kierunek skanowania)?")
        if choice_orient == "2":  # Pionowo
            print("    1 - W prawo (→)")
            print("    2 - W lewo  (←)")
            scan_choice = get_choice_input("  Wybierz [1-2] (domyślnie 1): ", ("1", "2"), default="1")
            scan_direction = "lewo" if scan_choice == "2" else "prawo"
        else:  # Poziomo
            print("    1 - W dół   (↓)")
            print("    2 - W górę  (↑)")
            scan_choice = get_choice_input("  Wybierz [1-2] (domyślnie 1): ", ("1", "2"), default="1")
            scan_direction = "gora" if scan_choice == "2" else "dol"

        scan_labels = {"prawo": "→ w prawo", "lewo": "← w lewo",
                        "dol": "↓ w dół", "gora": "↑ w górę"}
        print(f"  Kierunek skanowania: {scan_labels[scan_direction]}")

        return {
            "n_beacons":  n,
            "beacon_ids": beacon_ids,
            "spacing_m":  spacing,
            "angle_deg":  angle,
            "scan_direction": scan_direction,
        }

    def _beacon_positions(self, base_x: float, base_y: float,
                          tripod: dict) -> list[tuple[int, float, float]]:
        """Oblicza pozycje beaconów w zestawie (montaż liniowy).

        Zwraca listę krotek (beacon_id, x, y).
        Pierwszy beacon (indeks 0) stoi w pozycji bazowej.
        """
        angle_rad = math.radians(tripod["angle_deg"])
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        return [
            (bid,
             round(base_x + i * tripod["spacing_m"] * cos_a, 4),
             round(base_y + i * tripod["spacing_m"] * sin_a, 4))
            for i, bid in enumerate(tripod["beacon_ids"])
        ]

    def _upsert_point(self, existing: list, label: str, point: dict) -> None:
        """Dodaje lub aktualizuje punkt w liście mapy radiowej."""
        x = point.get("x_m")
        y = point.get("y_m")
        bids = set(point.get("beacons", {}).keys())

        for i, fp in enumerate(existing):
            # Zbieżność współrzędnych (tolerancja 1mm) i identyczność zestawu beaconów
            if (fp.get("x_m") is not None and abs(fp["x_m"] - x) < 0.001 and
                fp.get("y_m") is not None and abs(fp["y_m"] - y) < 0.001 and
                "beacons" in fp and set(fp["beacons"].keys()) == bids):
                existing[i] = point
                return
        existing.append(point)


    def _save_fingerprint_points(self, existing: list, label: str,
                                  x_local: float, y_local: float,
                                  ox: float, oy: float,
                                  beacons: dict, session_label: str,
                                  tripod: dict | None = None) -> int:
        """Zapisuje punkty fingerprint do mapy radiowej.

        Bez zestawu: 1 punkt ze wszystkimi beaconami.
        Z zestawem:   N osobnych punktów (po jednym na beacon),
                      każdy z obliczoną pozycją w zestawie.
        Zwraca liczbę faktycznie zapisanych punktów.
        """
        if tripod:
            positions = self._beacon_positions(x_local, y_local, tripod)
            saved = 0
            for bid, bx_local, by_local in positions:
                bid_str = str(bid)
                if bid_str not in beacons:
                    print(f"  [!] Beacon {bid} nie znaleziony w zebranych danych. Pomijam.")
                    continue

                bx_global = round(ox + bx_local, 4)
                by_global = round(oy + by_local, 4)
                b_label = f"{label}_{bid}"

                new_point = {
                    "label":   b_label,
                    "x_m":     bx_global,
                    "y_m":     by_global,
                    "_local":  {"x": bx_local, "y": by_local,
                                "session": session_label},
                    "beacons": {bid_str: beacons[bid_str]},
                }
                self._upsert_point(existing, b_label, new_point)
                saved += 1
            return saved
        else:
            x_global = round(ox + x_local, 4)
            y_global = round(oy + y_local, 4)
            new_point = {
                "label":   label,
                "x_m":     x_global,
                "y_m":     y_global,
                "_local":  {"x": x_local, "y": y_local,
                            "session": session_label},
                "beacons": beacons,
            }
            self._upsert_point(existing, label, new_point)
            return 1

    def _print_tripod_summary(self, tripod: dict | None) -> None:
        """Wyświetla podsumowanie konfiguracji zestawu."""
        if not tripod:
            return
        ids_str = ", ".join(str(b) for b in tripod["beacon_ids"])
        print(f"\n  ── Zestaw beaconów ─────────────────────────")
        print(f"  Beacony:    {tripod['n_beacons']} szt. (ID: {ids_str})")
        print(f"  Odstęp:     {tripod['spacing_m']:.2f} m,  kąt: {tripod['angle_deg']:.1f}°")

    # ── Tryby kalibracji ───────────────────────────────────────

    def run_average(self) -> None:
        """
        Tryb kalibracji (pojedynczy punkt).
        """
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji pomiarowej.")
            print("    Najpierw ustaw origin siatki (opcja 1 w menu).")
            return

        ox = sess["origin_x_m"]
        oy = sess["origin_y_m"]
        print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")

        label = input("  Etykieta punktu (np. '707_p01', domyślnie 'punkt'): ").strip() or "punkt"

        # ── Konfiguracja zestawu ──
        tripod = self._ask_tripod_params()

        if tripod:
            x_center = get_float_input("  Lokalna wsp. X środka zestawu (0=środek, ujemne=lewo, dodatnie=prawo) [m]: ")
            y_center = get_float_input("  Lokalna wsp. Y środka zestawu (0=środek, ujemne=góra, dodatnie=dół) [m]: ")
            
            tripod_span = (tripod["n_beacons"] - 1) * tripod["spacing_m"]
            angle_rad = math.radians(tripod["angle_deg"])
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            
            shift_x = (tripod_span / 2.0) * cos_a
            shift_y = (tripod_span / 2.0) * sin_a
            
            x_local = x_center - shift_x
            y_local = y_center - shift_y
        else:
            x_local = get_float_input("  Lokalne X [m] (odległość od origin sesji): ")
            y_local = get_float_input("  Lokalne Y [m] (odległość od origin sesji): ")

        x_global = round(ox + x_local, 4)
        y_global = round(oy + y_local, 4)
        
        if tripod:
            x_c_global = round(ox + x_center, 4)
            y_c_global = round(oy + y_center, 4)
            print(f"\n  Środek zestawu (lokalnie): X={x_center:.2f} m, Y={y_center:.2f} m")
            print(f"  Środek zestawu (globalnie): X={x_c_global:.2f} m, Y={y_c_global:.2f} m")
            print(f"  Baza (pierwszy beacon, lokalnie): X={x_local:.2f} m, Y={y_local:.2f} m")
        else:
            print(f"\n  Lokalne:  X={x_local:.2f} m, Y={y_local:.2f} m")
            print(f"  Globalne: X={x_global:.2f} m, Y={y_global:.2f} m")

        # Wybór beacon ID (dla pojedynczego beacona)
        beacon_id = 28
        if not tripod:
            available = self._scan_available_beacons()
            if not available:
                beacon_id = get_int_input("  Podaj ID beacona do kalibracji ręcznie (domyślnie 28): ", default=28, min_val=1)
            else:
                print("\n  Wykryte beacony w zasięgu:")
                for idx, bid in enumerate(available, 1):
                    print(f"    {idx} - Beacon ID {bid}")
                choice_idx = get_int_input(f"  Wybierz beacon do kalibracji (wpisz numer 1-{len(available)}, domyślnie 1): ", default=1, min_val=1)
                if 1 <= choice_idx <= len(available):
                    beacon_id = available[choice_idx - 1]
                else:
                    beacon_id = available[0]
        else:
            beacon_id = tripod["beacon_ids"][0]

        # ── Konfiguracja czasu / liczby pakietów ──
        target_packets = get_int_input("  Liczba pakietów na beacon (domyślnie 100): ", default=100, min_val=1)

        if tripod:
            self._print_tripod_summary(tripod)
            positions = self._beacon_positions(x_local, y_local, tripod)
            print(f"  Pozycje beaconów (lokalne → globalne):")
            for bid, bx, by in positions:
                gx = round(ox + bx, 4)
                gy = round(oy + by, 4)
                print(f"    Beacon {bid}: ({bx:.2f}, {by:.2f}) m → ({gx:.2f}, {gy:.2f}) m")

        if tripod:
            positions = self._beacon_positions(x_local, y_local, tripod)
            beacons_list = [{"id": bid, "x": round(ox + bx, 4), "y": round(oy + by, 4)} for bid, bx, by in positions]
        else:
            beacons_list = [{"id": beacon_id, "x": x_global, "y": y_global}]

        sock = self.client.connect_and_start()
        if not sock:
            return

        try:
            beacons = self._collect_fingerprint(sock, label, target_packets, beacons_list)
        except socket.timeout:
            print("\n[!] Timeout serwera.")
            return
        finally:
            self.client.stop_and_close(sock)

        if not beacons:
            print("[!] Brak zebranych danych.")
            return

        existing = load_radio_map()
        n_saved = self._save_fingerprint_points(
            existing, label, x_local, y_local,
            ox, oy, beacons, sess["origin_label"], tripod
        )
        save_radio_map(existing)

        if tripod:
            print(f"\n[OK] Zapisano {n_saved} punktów (zestaw) z pozycji '{label}'.")
        else:
            print(f"\n[OK] Zapisano '{label}' @ globalnie ({x_global} m, {y_global} m).")
        print(f"     Mapa radiowa: {len(existing)} punktów.")

        # Poglądowo wypisz beacon 28 jeśli jest
        if "28" in beacons:
            print("\nZnormalizowane odciski (beacon 28):")
            print(json.dumps({str(k): v for k, v in beacons["28"]["norm"].items()}, indent=2))

    def run_grid_calibration(self) -> None:
        """Automatyczna kalibracja siatkowa."""
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji pomiarowej.")
            print("    Najpierw ustaw origin siatki (opcja 1 w menu).")
            return

        ox = sess["origin_x_m"]
        oy = sess["origin_y_m"]
        print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")

        prefix = input("\n  Prefix etykiet (np. '707_p', domyślnie 'p'): ").strip() or "p"

        # ── Konfiguracja zestawu ──
        tripod = self._ask_tripod_params()

        # Beacon do podglądu radaru (dane zbierane ze WSZYSTKICH beaconów)
        if tripod:
            beacon_id = tripod["beacon_ids"][0]
        else:
            available = self._scan_available_beacons()
            if not available:
                beacon_id = get_int_input("  Podaj ID beacona do kalibracji (podglądu radaru) ręcznie (domyślnie 28): ", default=28, min_val=1)
            else:
                print("\n  Wykryte beacony w zasięgu:")
                for idx, bid in enumerate(available, 1):
                    print(f"    {idx} - Beacon ID {bid}")
                choice_idx = get_int_input(f"  Wybierz beacon do kalibracji (wpisz numer 1-{len(available)}, domyślnie 1): ", default=1, min_val=1)
                if 1 <= choice_idx <= len(available):
                    beacon_id = available[choice_idx - 1]
                else:
                    beacon_id = available[0]
            print(f"  Podgląd radaru: Beacon {beacon_id} (dane zbierane ze wszystkich)")

        # ── Konfiguracja czasu / liczby pakietów ──
        target_packets = get_int_input("  Liczba pakietów na beacon (domyślnie 100): ", default=100, min_val=1)

        # ── Parametry obszaru ──
        if tripod:
            tripod_angle = tripod["angle_deg"]
            tripod_span = (tripod["n_beacons"] - 1) * tripod["spacing_m"]
            tripod_is_vertical = (tripod_angle == 90.0)
            tripod_is_horizontal = (tripod_angle == 0.0)
            scan_dir = tripod.get("scan_direction", "prawo")
            default_tripod_step = tripod["n_beacons"] * tripod["spacing_m"]
        else:
            tripod_is_vertical = False
            tripod_is_horizontal = False
            tripod_span = 0.0

        while True:
            print("\n  Podaj parametry badanego obszaru (w metrach od origin sesji):")
            if tripod:
                x_start = get_float_input("  Lokalna wsp. X środka zestawu w pkt. pocz. (ujemne=lewo, dodatnie=prawo) [m] (domyślnie 0.0): ", default=0.0)
                y_start = get_float_input("  Lokalna wsp. Y środka zestawu w pkt. pocz. (ujemne=góra, dodatnie=dół) [m] (domyślnie 0.0): ", default=0.0)
            else:
                x_start = get_float_input("  Lokalne X początku siatki [m] (domyślnie 0.0): ", default=0.0)
                y_start = get_float_input("  Lokalne Y początku siatki [m] (domyślnie 0.0): ", default=0.0)

            length_x = get_float_input("  Długość obszaru w osi X [m]: ", min_val=0.0)
            length_y = get_float_input("  Długość obszaru w osi Y [m]: ", min_val=0.0)

            if length_x <= 0 or length_y <= 0:
                print("  [!] Wszystkie wymiary obszaru muszą być dodatnie. Spróbuj ponownie.")
                continue

            if tripod_is_vertical and tripod_span > length_y + 1e-9:
                print(f"  [!] BŁĄD: Rozpiętość zestawu ({tripod_span:.2f} m) nie mieści się w obszarze o szerokości {length_y:.2f} m.")
                print("  Spróbuj ponownie podać parametry obszaru.")
                continue

            if tripod_is_horizontal and tripod_span > length_x + 1e-9:
                print(f"  [!] BŁĄD: Rozpiętość zestawu ({tripod_span:.2f} m) nie mieści się w obszarze o długości {length_x:.2f} m.")
                print("  Spróbuj ponownie podać parametry obszaru.")
                continue

            break

        grid_points = []
        step_x = 0.0
        step_y = 0.0

        if tripod:
            if tripod_is_vertical:
                print(f"\n  Zestaw pionowy — pokrywa {tripod_span:.2f} m wzdłuż osi Y.")
                if length_y < tripod_span + tripod["spacing_m"] - 1e-5:
                    print(f"  Szerokość obszaru w Y ({length_y:.2f} m) pozwala na pokrycie całości jednym przejściem.")
                    y_room_start = y_start - tripod_span / 2.0
                    y_center = y_room_start + length_y / 2.0
                    y_base = y_center - tripod_span / 2.0
                    offset = y_center - y_start
                    
                    print(f"  ➤ Ustaw środek statywu w punkcie Y = {y_center:.2f} m względem punktu orientacyjnego.")
                    print(f"    (To odpowiada odległości {offset:.2f} m od początku badanego obszaru wzdłuż osi Y).")
                    
                    step_x = get_float_input("  Skok skanowania wzdłuż osi X [m]: ", min_val=0.0)
                    
                    # Generowanie pozycji X (baza)
                    xs = []
                    dist = 0.0
                    while dist <= length_x + 1e-9:
                        val = x_start - dist if scan_dir == "lewo" else x_start + dist
                        xs.append(round(val, 4))
                        dist += step_x

                    point_num = 1
                    for xv in xs:
                        label = f"{prefix}{point_num:02d}"
                        grid_points.append((label, xv, y_base))
                        point_num += 1
                else:
                    print(f"  Szerokość obszaru w Y ({length_y:.2f} m) przekracza rozpiętość zestawu ({tripod_span:.2f} m).")
                    print(f"  Zestaw będzie musiał być przestawiany również wzdłuż osi Y.")
                    step_x = get_float_input("  Skok skanowania wzdłuż osi X [m]: ", min_val=0.0)
                    step_y = get_float_input(f"  Skok przestawiania zestawu w osi Y [m] (domyślnie {default_tripod_step:.2f} m): ", default=default_tripod_step, min_val=0.0)

                    # Generowanie pozycji X (baza)
                    xs = []
                    dist = 0.0
                    while dist <= length_x + 1e-9:
                        val = x_start - dist if scan_dir == "lewo" else x_start + dist
                        xs.append(round(val, 4))
                        dist += step_x

                    # Generowanie pozycji Y (baza)
                    ys = []
                    y = y_start
                    while True:
                        y_base = y - tripod_span / 2.0
                        ys.append(round(y_base, 4))
                        y_room_end = (y_start - tripod_span / 2.0) + length_y
                        if y + tripod_span / 2.0 >= y_room_end - 1e-9:
                            break
                        y += step_y

                    # Zygzak (meander)
                    point_num = 1
                    for yi, yv in enumerate(ys):
                        row_xs = xs if (yi % 2 == 0) else list(reversed(xs))
                        for xv in row_xs:
                            label = f"{prefix}{point_num:02d}"
                            grid_points.append((label, xv, yv))
                            point_num += 1

            elif tripod_is_horizontal:
                print(f"\n  Zestaw poziomy — pokrywa {tripod_span:.2f} m wzdłuż osi X.")
                if length_x < tripod_span + tripod["spacing_m"] - 1e-5:
                    print(f"  Długość obszaru w X ({length_x:.2f} m) pozwala na pokrycie całości jednym przejściem.")
                    x_room_start = x_start - tripod_span / 2.0
                    x_center = x_room_start + length_x / 2.0
                    x_base = x_center - tripod_span / 2.0
                    offset = x_center - x_start
                    
                    print(f"  ➤ Ustaw środek statywu w punkcie X = {x_center:.2f} m względem punktu orientacyjnego.")
                    print(f"    (To odpowiada odległości {offset:.2f} m od początku badanego obszaru wzdłuż osi X).")

                    step_y = get_float_input("  Skok skanowania wzdłuż osi Y [m]: ", min_val=0.0)
                    
                    # Generowanie pozycji Y (baza)
                    ys = []
                    dist = 0.0
                    while dist <= length_y + 1e-9:
                        val = y_start - dist if scan_dir == "gora" else y_start + dist
                        ys.append(round(val, 4))
                        dist += step_y

                    point_num = 1
                    for yv in ys:
                        label = f"{prefix}{point_num:02d}"
                        grid_points.append((label, x_base, yv))
                        point_num += 1
                else:
                    print(f"  Długość obszaru w X ({length_x:.2f} m) przekracza rozpiętość zestawu ({tripod_span:.2f} m).")
                    print(f"  Zestaw będzie musiał być przestawiany również wzdłuż osi X.")
                    step_y = get_float_input("  Skok skanowania wzdłuż osi Y [m]: ", min_val=0.0)
                    step_x = get_float_input(f"  Skok przestawiania zestawu w osi X [m] (domyślnie {default_tripod_step:.2f} m): ", default=default_tripod_step, min_val=0.0)

                    # Generowanie pozycji Y (baza)
                    ys = []
                    dist = 0.0
                    while dist <= length_y + 1e-9:
                        val = y_start - dist if scan_dir == "gora" else y_start + dist
                        ys.append(round(val, 4))
                        dist += step_y

                    # Generowanie pozycji X (baza)
                    xs = []
                    x = x_start
                    while True:
                        x_base = x - tripod_span / 2.0
                        xs.append(round(x_base, 4))
                        x_room_end = (x_start - tripod_span / 2.0) + length_x
                        if x + tripod_span / 2.0 >= x_room_end - 1e-9:
                            break
                        x += step_x

                    # Zygzak (meander)
                    point_num = 1
                    for xi, xv in enumerate(xs):
                        row_ys = ys if (xi % 2 == 0) else list(reversed(ys))
                        for yv in row_ys:
                            label = f"{prefix}{point_num:02d}"
                            grid_points.append((label, xv, yv))
                            point_num += 1
        else:
            # ── Bez zestawu: pełna siatka 2D ──
            step_x = get_float_input("  Skok w osi X [m]: ", min_val=0.0)
            step_y = get_float_input("  Skok w osi Y [m]: ", min_val=0.0)

            xs = []
            x = x_start
            while x <= x_start + length_x + 1e-9:
                xs.append(round(x, 4))
                x += step_x
            ys = []
            y = y_start
            while y <= y_start + length_y + 1e-9:
                ys.append(round(y, 4))
                y += step_y

            grid_points = []
            point_num = 1
            for yi, yv in enumerate(ys):
                row_xs = xs if (yi % 2 == 0) else list(reversed(xs))
                for xv in row_xs:
                    label = f"{prefix}{point_num:02d}"
                    grid_points.append((label, xv, yv))
                    point_num += 1

        n_total = len(grid_points)

        # ── Plan kalibracji ──
        print(f"\n{'═' * 60}")
        print(f"  PLAN KALIBRACJI SIATKOWEJ")
        print(f"{'─' * 60}")

        if tripod:
            ids_str = ", ".join(str(b) for b in tripod["beacon_ids"])
            n_map_pts = n_total * tripod["n_beacons"]
            tripod_span_m = (tripod["n_beacons"] - 1) * tripod["spacing_m"]
            scan_labels = {"prawo": "→ w prawo", "lewo": "← w lewo",
                            "dol": "↓ w dół", "gora": "↑ w górę"}
            print(f"  Zestaw:       {tripod['n_beacons']} beaconów (ID: {ids_str})")
            print(f"  Odstęp:       {tripod['spacing_m']:.2f} m,  kąt: {tripod['angle_deg']:.1f}°")
            print(f"  Zasięg zest.: {tripod_span_m:.2f} m")
            print(f"  Skanowanie:   {scan_labels.get(tripod.get('scan_direction', ''), '?')}")
            print(f"  Pozycje skan: {n_total}")
            print(f"  Pkt radiowe:  {n_total} pozycji × {tripod['n_beacons']} beaconów = {n_map_pts}")
        else:
            xs_count = len(set(pt[1] for pt in grid_points))
            ys_count = len(set(pt[2] for pt in grid_points))
            print(f"  Obszar:       {length_x} m × {length_y} m")
            print(f"  Skok:         X={step_x} m,  Y={step_y} m")
            print(f"  Siatka:       {xs_count} kolumn × {ys_count} wierszy = {n_total} pozycji")
            print(f"  Kolejność:    meander (zygzak)")

        print(f"{'─' * 60}")
        print(f"  {'Nr':<5} {'Etykieta':<12} {'Lok. X [m]':>10} {'Lok. Y [m]':>10} {'Glob. X':>9} {'Glob. Y':>9}")
        print(f"  {'─' * 56}")
        for i, (lbl, lx, ly) in enumerate(grid_points, 1):
            gx = round(ox + lx, 4)
            gy = round(oy + ly, 4)
            if tripod:
                tripod_span = (tripod["n_beacons"] - 1) * tripod["spacing_m"]
                angle_rad = math.radians(tripod["angle_deg"])
                cx = lx + (tripod_span / 2.0) * math.cos(angle_rad)
                cy = ly + (tripod_span / 2.0) * math.sin(angle_rad)
                cgx = round(ox + cx, 4)
                cgy = round(oy + cy, 4)
                print(f"  {i:<5} {lbl:<12} Śr: lok ({cx:>5.2f}, {cy:>5.2f}) → glob ({cgx:>5.2f}, {cgy:>5.2f})")
                positions = self._beacon_positions(lx, ly, tripod)
                for bid, bx, by in positions:
                    bgx = round(ox + bx, 4)
                    bgy = round(oy + by, 4)
                    print(f"  {'':5} {'':12}   B{bid}: lok ({bx:.2f}, {by:.2f}) → glob ({bgx:.2f}, {bgy:.2f})")
            else:
                print(f"  {i:<5} {lbl:<12} {lx:>10.2f} {ly:>10.2f} {gx:>9.2f} {gy:>9.2f}")
        print(f"{'═' * 60}")
        
        self._print_ascii_map(grid_points, tripod)

        ans = get_choice_input(f"\n  Rozpocząć kalibrację {n_total} pozycji? (t/n): ", ("t", "n", "y", "o"), default="t")
        if ans not in ("t", "y", "o"):
            print("  Anulowano.")
            return

        # Zbuduj pełny plik JSON z siatką punktów (z deduplikacją beaconów)
        grid_data = {
            "origin_label": sess["origin_label"],
            "ox": ox,
            "oy": oy,
            "target_packets": target_packets,
            "tripod": tripod,
            "points": []
        }

        seen_beacon_coords = set()   # (beacon_id, x_global, y_global)
        n_dup_beacons = 0
        n_dup_points = 0

        for i, (label, x_local, y_local) in enumerate(grid_points, 1):
            x_global = round(ox + x_local, 4)
            y_global = round(oy + y_local, 4)
            
            if tripod:
                positions = self._beacon_positions(x_local, y_local, tripod)
                beacons_list_raw = [{"id": bid, "x": round(ox + bx, 4), "y": round(oy + by, 4), "local_x": bx, "local_y": by} for bid, bx, by in positions]
            else:
                beacons_list_raw = [{"id": beacon_id, "x": x_global, "y": y_global, "local_x": x_local, "local_y": y_local}]

            # Odfiltruj beacony, które już istnieją na tych samych współrzędnych
            beacons_list = []
            for b in beacons_list_raw:
                key = (b["id"], b["x"], b["y"])
                if key in seen_beacon_coords:
                    n_dup_beacons += 1
                else:
                    seen_beacon_coords.add(key)
                    beacons_list.append(b)

            if not beacons_list:
                # Wszystkie beacony w tym punkcie to duplikaty — pomijamy cały punkt
                n_dup_points += 1
                continue

            grid_data["points"].append({
                "label": label,
                "x_local": x_local,
                "y_local": y_local,
                "x_global": x_global,
                "y_global": y_global,
                "beacons": beacons_list
            })

        if n_dup_beacons > 0:
            print(f"\n  [Deduplikacja] Usunięto {n_dup_beacons} zduplikowanych beaconów"
                  f" ({n_dup_points} całych punktów pominięto).")
            print(f"  Pozostało {len(grid_data['points'])} unikalnych pozycji pomiarowych.")

        planned_grid_path = os.path.join(DATA_DIR, "planned_grid.json")
        with open(planned_grid_path, "w", encoding="utf-8") as f:
            json.dump(grid_data, f, indent=2)

        print("\n  Otwieranie mapy z pełnym podglądem siatki...")

        try:
            viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
            subprocess.run([sys.executable, viewer, "--grid_collect", planned_grid_path], check=False)
        except Exception as e:
            print(f"[!] Błąd wywołania GUI: {e}")

        print(f"\n{'═' * 56}")
        try:
            from wknn import load_radio_map
            existing = load_radio_map()
            print(f"  Mapa radiowa: {len(existing)} punktów łącznie po kalibracji")
        except Exception:
            pass
        print(f"{'═' * 56}")

    def _print_ascii_map(self, grid_points, tripod):
        if not grid_points:
            return
            
        print("\n  MAPA ODCISKÓW RADIOWYCH (ASCII):")
        all_positions = []
        for label, base_x, base_y in grid_points:
            if tripod:
                positions = self._beacon_positions(base_x, base_y, tripod)
                for bid, bx, by in positions:
                    all_positions.append((bx, by))
            else:
                all_positions.append((base_x, base_y))

        if not all_positions:
            return

        min_x = min(p[0] for p in all_positions)
        max_x = max(p[0] for p in all_positions)
        min_y = min(p[1] for p in all_positions)
        max_y = max(p[1] for p in all_positions)
        
        # Uwzględnienie punktu orientacyjnego (0,0) lokalnie
        min_x = min(min_x, 0.0)
        max_x = max(max_x, 0.0)
        min_y = min(min_y, 0.0)
        max_y = max(max_y, 0.0)

        span_x = max_x - min_x
        span_y = max_y - min_y
        
        COLS = 50
        if span_x > 0:
            scale_x = COLS / span_x
        else:
            scale_x = 10.0
            
        # Terminal characters are ~2x taller than they are wide.
        # So for Y axis we use half the scale visually.
        scale_y_visual = scale_x * 0.5
        
        # Obliczamy maksymalny index gy
        max_gy_raw = int(round(span_y * scale_y_visual))
        ROWS = max(5, max_gy_raw)
        
        if ROWS > 20:
            scale_y_visual = 20 / span_y
            ROWS = 20
            scale_x = scale_y_visual * 2.0
            if span_x > 0:
                COLS = max(5, int(span_x * scale_x))
            
        if COLS > 70: COLS = 70
        
        grid = [[' ' for _ in range(COLS + 1)] for _ in range(ROWS + 1)]
        
        def to_grid(px, py):
            gx = int(round((px - min_x) * scale_x))
            gy = int(round((py - min_y) * scale_y_visual))
            return gx, gy
            
        # Zaznacz origin lokalny (0,0) względem siatki
        ox_g, oy_g = to_grid(0.0, 0.0)
        if 0 <= oy_g <= ROWS and 0 <= ox_g <= COLS:
            grid[oy_g][ox_g] = 'O'
            
        # Rysuj x
        for i, (px, py) in enumerate(all_positions):
            gx, gy = to_grid(px, py)
            if 0 <= gy <= ROWS and 0 <= gx <= COLS:
                # Omijamy O, ale x nadpisuje puste
                if grid[gy][gx] == ' ':
                    grid[gy][gx] = 'x'
                    
        # Nadpisz S dla pierwszych beaconów (statywu) - pierwsza pozycja to index 0..n_beacons-1
        n_beacs = tripod["n_beacons"] if tripod else 1
        for i in range(min(n_beacs, len(all_positions))):
            px, py = all_positions[i]
            gx, gy = to_grid(px, py)
            if 0 <= gy <= ROWS and 0 <= gx <= COLS:
                grid[gy][gx] = 'S'
                
        print("    " + "-" * (COLS + 1))
        for row in grid:
            print("    |" + "".join(row) + "|")
        print("    " + "-" * (COLS + 1))
        print("    ( 'O' = Origin, 'x' = Odcisk beacona )")

    def run_collect_test_point(self) -> None:
        """Tryb 6: Zbieranie punktów testowych (ground truth)."""
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji. Ustaw origin siatki (opcja 1).")
            return

        ox, oy = sess["origin_x_m"], sess["origin_y_m"]
        print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")
        print("  [PUNKT TESTOWY — zapisywany do test_set.json, NIE do radio_map]")

        label = input("  Etykieta punktu (np. 'test_p01', domyślnie 'test_pt'): ").strip() or "test_pt"
        x_local = get_float_input("  Lokalne X [m] (od origin sesji): ")
        y_local = get_float_input("  Lokalne Y [m] (od origin sesji): ")

        x_global = round(ox + x_local, 4)
        y_global = round(oy + y_local, 4)
        print(f"\n  Lokalne:  X={x_local} m, Y={y_local} m")
        print(f"  Globalne: X={x_global} m, Y={y_global} m")

        # Wybór beacon ID (dla pojedynczego beacona)
        available = self._scan_available_beacons()
        beacon_id = 28
        if not available:
            beacon_id = get_int_input("  Podaj ID beacona do zbierania ręcznie (domyślnie 28): ", default=28, min_val=1)
        else:
            print("\n  Wykryte beacony w zasięgu:")
            for idx, bid in enumerate(available, 1):
                print(f"    {idx} - Beacon ID {bid}")
            choice_idx = get_int_input(f"  Wybierz beacon do zbierania (wpisz numer 1-{len(available)}, domyślnie 1): ", default=1, min_val=1)
            if 1 <= choice_idx <= len(available):
                beacon_id = available[choice_idx - 1]
            else:
                beacon_id = available[0]

        # Wybór czasu / pakietów
        target_packets = get_int_input("  Liczba pakietów na beacon (domyślnie 100): ", default=100, min_val=1)

        sock = self.client.connect_and_start()
        if not sock:
            return

        beacons_list = [{"id": beacon_id, "x": x_global, "y": y_global}]
        try:
            beacons = self._collect_fingerprint(sock, label, target_packets, beacons_list)
        except socket.timeout:
            print("\n[!] Timeout.")
            return
        finally:
            self.client.stop_and_close(sock)

        if not beacons:
            return

        new_point = {
            "label":   label,
            "x_true":  x_global,
            "y_true":  y_global,
            "_local":  {"x": x_local, "y": y_local, "session": sess["origin_label"]},
            "beacons": beacons,
        }

        from validate import load_test_set, save_test_set
        existing = [tp for tp in load_test_set() if tp.get("label") != label]
        existing.append(new_point)
        save_test_set(existing)
        print(f"[OK] Zapisano '{label}' @ ({x_global} m, {y_global} m). Zbior: {len(existing)} pkt.")
