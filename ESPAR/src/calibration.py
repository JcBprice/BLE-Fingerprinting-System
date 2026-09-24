"""Moduł kalibracji i zbierania mapy radiowej (pojedyncze punkty, siatka statywowa, punkty testowe)."""

import json
import math
import os
import subprocess
import sys

from config import DEFAULT_BEACON_ID, DEFAULT_TARGET_PACKETS, VALID_CHARS
from espar_client import EsparClient
from session import DATA_DIR, SessionManager
from telnet_reader import get_espar_stream
from utils import (
    build_beacon_candidates,
    get_beacons_from_radio_map,
    get_choice_input,
    get_float_input,
    get_int_input,
    print_available_beacons,
    select_beacon_interactive,
)
from wknn import load_radio_map, save_radio_map


class Calibrator:
    """Zarządza zbieraniem fingerprintów radiowych i tworzeniem bazy punktów kalibracyjnych."""

    def __init__(self, session_manager, client):
        self.session_manager = session_manager
        self.client = client

    # Uruchamia GUI w trybie kalibracji w osobnym procesie i odczytuje zebrany fingerprint ze strumienia stdout.
    def _collect_fingerprint(self, sock, label: str, target_packets: int = 100, beacons_list: list = None) -> dict | None:
        try:
            if sock:
                self.client.stop_and_close(sock)
        except Exception:
            pass

        viewer = os.path.join(self.session_manager.script_dir, "map_viewer.py")
        if not beacons_list:
            beacons_list = [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]

        try:
            result = subprocess.run(
                [sys.executable, viewer, "--calibrate", label, json.dumps(beacons_list), str(target_packets)],
                capture_output=True, text=True, encoding="utf-8"
            )
            for line in reversed(result.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return json.loads(line)
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    # Skanuje pasmo radiowe przez kilka sekund, aby wykryć aktualnie nadające beacony.
    def _scan_available_beacons(self, duration: float = 3.5) -> list[int]:
        import time
        sock = self.client.connect_and_start()
        if not sock:
            return []

        detected = set()
        start_time = time.time()
        try:
            sock.settimeout(duration + 1.0)
            for frame in get_espar_stream(sock, filter_valid_chars=False):
                bid = frame.get("beacon_num")
                if bid is not None:
                    detected.add(bid)
                if time.time() - start_time > duration:
                    break
        except Exception:
            pass
        finally:
            self.client.stop_and_close(sock)
        return sorted(list(detected))

    # Skanuje pasmo radiowe i pobiera listę beaconów z bazy danych sesji.
    def _get_beacon_candidates(self) -> tuple[list[int], list[int], list[int]]:
        print("\n  Skanowanie pasma radiowego w poszukiwaniu beaconow...")
        available = self._scan_available_beacons(duration=3.5)
        db_beacons = get_beacons_from_radio_map()
        candidates = build_beacon_candidates(available, db_beacons)
        return candidates, db_beacons, available

    # Uruchamia interaktywny wybór pojedynczego beacona z podglądem aktywnych urządzeń.
    def _choose_single_beacon(self, prompt: str = "kalibracji") -> int:
        candidates, db_beacons, available = self._get_beacon_candidates()
        return select_beacon_interactive(
            candidates, db_beacons, available, prompt,
            rescan_callback=lambda: self._scan_available_beacons(duration=3.5)
        )

    # Pobiera konfigurację statywu z wieloma beaconami zamontowanymi w liniowym odstępie.
    def _ask_tripod_params(self, candidates: list[int] = None) -> dict | None:
        n = get_int_input("\nIle beaconow w zestawie? (1=pojedynczy): ", default=1, min_val=1)
        if n <= 1:
            return None

        default_ids = ",".join(str(x) for x in candidates[:n]) if candidates and len(candidates) >= n else ""
        while True:
            hint = f" [domyslnie: {default_ids}]" if default_ids else " (np. 1,4,7)"
            ids_raw = input(f"Podaj {n} ID beaconow{hint}: ").strip()
            if not ids_raw and default_ids:
                ids_raw = default_ids
            try:
                beacon_ids = [int(x) for x in ids_raw.replace("-", ",").split(",") if x.strip()]
                if len(beacon_ids) == n:
                    missing = [bid for bid in beacon_ids if candidates and bid not in candidates]
                    if missing:
                        print(f"\n[!] OSTRZEZENIE: Beacon(y) {missing} nie zostaly wykryte w pasmie radiowym ani w bazie!")
                        print(f"    Wykryte aktywne beacony: {candidates}")
                        if get_choice_input("Czy na pewno chcesz uzyc niewykrytych beaconow? (t/n): ", ("t", "n"), default="n") == "n":
                            continue
                    break
            except ValueError:
                pass
            print("Zly format. Podaj liczby oddzielone przecinkami.")

        spacing = get_float_input("Ostep miedzy beaconami [m]: ", default=0.5, min_val=0.01)

        return {
            "n_beacons":  n,
            "beacon_ids": beacon_ids,
            "spacing_m":  spacing,
        }

    # Wylicza współrzędne każdego beacona na ramieniu statywu przy zadanym kącie orientacji.
    def _beacon_positions(self, base_x: float, base_y: float, tripod: dict):
        angle_rad = math.radians(tripod["angle_deg"])
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        return [(bid, round(base_x + i * tripod["spacing_m"] * cos_a, 4),
                 round(base_y + i * tripod["spacing_m"] * sin_a, 4))
                for i, bid in enumerate(tripod["beacon_ids"])]

    def _upsert_point(self, existing: list, label: str, point: dict) -> None:
        x = point.get("x_m")
        y = point.get("y_m")
        bids = set(point.get("beacons", {}).keys())

        for i, fp in enumerate(existing):
            if (fp.get("x_m") is not None and abs(fp["x_m"] - x) < 0.001 and
                fp.get("y_m") is not None and abs(fp["y_m"] - y) < 0.001 and
                "beacons" in fp and set(fp["beacons"].keys()) == bids):
                existing[i] = point
                return
        existing.append(point)

    def _save_fingerprint_points(self, existing: list, label: str, x_local: float, y_local: float,
                                  ox: float, oy: float, beacons: dict, session_label: str, tripod: dict | None = None) -> int:
        if tripod:
            saved = 0
            for bid, bx_local, by_local in self._beacon_positions(x_local, y_local, tripod):
                if str(bid) not in beacons:
                    continue
                bx_global = round(ox + bx_local, 4)
                by_global = round(oy + by_local, 4)
                new_point = {
                    "label":   f"{label}_{bid}", "x_m": bx_global, "y_m": by_global,
                    "_local":  {"x": bx_local, "y": by_local, "session": session_label},
                    "beacons": {str(bid): beacons[str(bid)]},
                }
                self._upsert_point(existing, f"{label}_{bid}", new_point)
                saved += 1
            return saved
        else:
            new_point = {
                "label":   label, "x_m": round(ox + x_local, 4), "y_m": round(oy + y_local, 4),
                "_local":  {"x": x_local, "y": y_local, "session": session_label},
                "beacons": beacons,
            }
            self._upsert_point(existing, label, new_point)
            return 1

    def run_gui_single_fingerprint(self, beacon_id: int = None, target_packets: int = 100) -> None:
        viewer = os.path.join(self.session_manager.script_dir, "map_viewer.py")
        if beacon_id is None:
            beacon_id = self._choose_single_beacon("zbierania")
        try:
            subprocess.run([sys.executable, viewer, "--fingerprint_collect", str(beacon_id), str(target_packets)], check=False)
        except Exception:
            pass

    # Zbiera pojedynczy fingerprint (lub zestaw statywu) z ręcznie podanych współrzędnych i zapisuje do bazy.
    def run_average(self) -> None:
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji pomiarowej.")
            return

        ox = sess["origin_x_m"]
        oy = sess["origin_y_m"]

        candidates, db_beacons, available = self._get_beacon_candidates()
        print_available_beacons(candidates, db_beacons, available)

        tripod = self._ask_tripod_params(candidates)
        if tripod:
            beacon_id = tripod["beacon_ids"][0]
            tripod["angle_deg"] = get_float_input("Kat obrotu statywu [stopnie, 0=wzdluz X, 90=wzdluz Y]: ", default=0.0)
        else:
            beacon_id = select_beacon_interactive(
                candidates, db_beacons, available, "kalibracji",
                rescan_callback=lambda: self._scan_available_beacons(duration=3.5)
            )

        label = input("\nEtykieta punktu (domyslnie 'punkt'): ").strip() or "punkt"

        if tripod:
            x_center = get_float_input("Srodek zestawu lokalne X [m]: ")
            y_center = get_float_input("Srodek zestawu lokalne Y [m]: ")

            tripod_span = (tripod["n_beacons"] - 1) * tripod["spacing_m"]
            angle_rad = math.radians(tripod["angle_deg"])
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            x_local = x_center - (tripod_span / 2.0) * cos_a
            y_local = y_center - (tripod_span / 2.0) * sin_a
        else:
            x_local = get_float_input("Lokalne X [m]: ")
            y_local = get_float_input("Lokalne Y [m]: ")

        x_global = round(ox + x_local, 4)
        y_global = round(oy + y_local, 4)
        target_packets = get_int_input("Liczba pakietow na beacon: ", default=100, min_val=1)

        if tripod:
            beacons_list = [{"id": bid, "x": round(ox + bx, 4), "y": round(oy + by, 4)} for bid, bx, by in self._beacon_positions(x_local, y_local, tripod)]
        else:
            beacons_list = [{"id": beacon_id, "x": x_global, "y": y_global}]

        sock = self.client.connect_and_start()
        if not sock:
            return
        try:
            beacons = self._collect_fingerprint(sock, label, target_packets, beacons_list)
        finally:
            self.client.stop_and_close(sock)

        if not beacons:
            return

        existing = load_radio_map()
        self._save_fingerprint_points(existing, label, x_local, y_local, ox, oy, beacons, sess["origin_label"], tripod)
        save_radio_map(existing)
        print(f"\n[OK] Zapisano. Punkty w mapie: {len(existing)}")

    def run_multi_point_calibration(self, beacon_id: int = None, target_packets: int = 100) -> None:
        if beacon_id is None:
            beacon_id = self._choose_single_beacon("rozplanowania wielu")
            if beacon_id is None:
                return

        try:
            viewer = os.path.join(self.session_manager.script_dir, "map_viewer.py")
            subprocess.run([sys.executable, viewer, "--multi_plan", str(beacon_id), str(target_packets)], check=False)
        except Exception:
            pass
        try:
            print(f"Punkty radio po kalibracji: {len(load_radio_map())}")
        except Exception:
            pass

    # Generuje zaplanowaną siatkę punktów pomiarowych (trajektoria wężykiem) i odpala kreator GUI.
    def run_grid_calibration(self) -> None:
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji pomiarowej.")
            return

        ox, oy = sess["origin_x_m"], sess["origin_y_m"]
        print(f"\n[Sesja] '{sess['origin_label']}' @ global ({ox} m, {oy} m)")

        candidates, db_beacons, available = self._get_beacon_candidates()
        print_available_beacons(candidates, db_beacons, available)

        tripod = self._ask_tripod_params(candidates)
        if tripod:
            beacon_id = tripod["beacon_ids"][0]
        else:
            beacon_id = select_beacon_interactive(
                candidates, db_beacons, available, "kalibracji siatki",
                rescan_callback=lambda: self._scan_available_beacons(duration=3.5)
            )

        prefix = input("\nPrefix etykiet (np. 'p'): ").strip() or "p"
        target_packets = get_int_input("Liczba pakietow na beacon: ", default=100, min_val=1)

        print("\n--- Parametry obszaru i ruchu ---")
        x_start = get_float_input("Lokalne X poczatku [m]: ", default=0.0)
        y_start = get_float_input("Lokalne Y poczatku [m]: ", default=0.0)
        length_x = get_float_input("Dlugosc obszaru X [m]: ", min_val=0.0)
        length_y = get_float_input("Szerokosc obszaru Y [m]: ", min_val=0.0)

        choice_orient = get_choice_input(
            "Orientacja ruchu: 1-Poziomo (wzdluz osi X), 2-Pionowo (wzdluz osi Y): ",
            ("1", "2"), default="1"
        )
        is_horizontal = (choice_orient == "1")

        if is_horizontal:
            step_x = get_float_input("Skok statywu w osi X [m]: ", default=1.0, min_val=0.01)
            step_y = tripod["spacing_m"] if tripod else get_float_input("Skok w osi Y [m]: ", default=0.5, min_val=0.01)
            choice_dir = get_choice_input("Kierunek ruchu: 1-W prawo (+X), 2-W lewo (-X): ", ("1", "2"), default="1")
            scan_direction = "lewo" if choice_dir == "2" else "prawo"
            tripod_angle = 90.0
        else:
            step_y = get_float_input("Skok statywu w osi Y [m]: ", default=1.0, min_val=0.01)
            step_x = tripod["spacing_m"] if tripod else get_float_input("Skok w osi X [m]: ", default=0.5, min_val=0.01)
            choice_dir = get_choice_input("Kierunek ruchu: 1-W gore (+Y), 2-W dol (-Y): ", ("1", "2"), default="1")
            scan_direction = "dol" if choice_dir == "2" else "gora"
            tripod_angle = 0.0

        if tripod:
            tripod["angle_deg"] = tripod_angle
            tripod["scan_direction"] = scan_direction

        n_b = tripod["n_beacons"] if tripod else 1
        spacing = tripod["spacing_m"] if tripod else 0.0

        grid_points = []
        point_num = 1

        # Wyznaczamy współrzędne kolejnych kroków z odwracaniem co drugi wiersz (ruch meandrowy)
        if is_horizontal:
            n_steps_x = int(round(length_x / step_x)) + 1 if length_x > 0 else 1
            xs = [round(x_start + i * step_x, 4) for i in range(n_steps_x)]
            if scan_direction == "lewo":
                xs = list(reversed(xs))

            if tripod:
                tripod_coverage = n_b * spacing
                n_passes = max(1, math.ceil((length_y - 0.001) / tripod_coverage)) if length_y > 0 else 1
                pass_step_y = tripod_coverage
            else:
                n_passes = int(round(length_y / step_y)) + 1 if length_y > 0 else 1
                pass_step_y = step_y

            ys = [round(y_start + p * pass_step_y, 4) for p in range(n_passes)]

            for yi, yv in enumerate(ys):
                row_xs = xs if (yi % 2 == 0) else list(reversed(xs))
                for xv in row_xs:
                    grid_points.append((f"{prefix}{point_num:02d}", xv, yv))
                    point_num += 1
        else:
            n_steps_y = int(round(length_y / step_y)) + 1 if length_y > 0 else 1
            ys = [round(y_start + i * step_y, 4) for i in range(n_steps_y)]
            if scan_direction == "dol":
                ys = list(reversed(ys))

            if tripod:
                tripod_coverage = n_b * spacing
                n_passes = max(1, math.ceil((length_x - 0.001) / tripod_coverage)) if length_x > 0 else 1
                pass_step_x = tripod_coverage
            else:
                n_passes = int(round(length_x / step_x)) + 1 if length_x > 0 else 1
                pass_step_x = step_x

            xs = [round(x_start + p * pass_step_x, 4) for p in range(n_passes)]

            for xi, xv in enumerate(xs):
                col_ys = ys if (xi % 2 == 0) else list(reversed(ys))
                for yv in col_ys:
                    grid_points.append((f"{prefix}{point_num:02d}", xv, yv))
                    point_num += 1

        print(f"\n[ANALIZA SIATKI]")
        print(f"  Wymiary obszaru: {length_x:.2f} m (X) x {length_y:.2f} m (Y)")
        print(f"  Ruch: {'POZIOMY (w osi X)' if is_horizontal else 'PIONOWY (w osi Y)'} | Kierunek: {scan_direction}")
        if tripod:
            step_along = step_x if is_horizontal else step_y
            print(f"  Krok statywu w osi ruchu: {step_along:.2f} m")
            print(f"  Statyw: {n_b} beacony (odstep {spacing:.2f} m -> pas o szerokosci {n_b * spacing:.2f} m)")
            print(f"  -> Wywnioskowano liczbe przelotow statywu: {n_passes} przelot(y)")
            print(f"  Lacznie pozycji statywu: {len(grid_points)} przystankow (x{n_b} beaconow = {len(grid_points)*n_b} odciskow w bazie)")
        else:
            print(f"  Kroki siatki: skok X = {step_x:.2f} m, skok Y = {step_y:.2f} m")
            print(f"  -> Wywnioskowana liczba pasow: {n_passes}")
            print(f"  Lacznie punktow pomiarowych: {len(grid_points)}")

        self._print_ascii_map(grid_points, tripod)

        if get_choice_input(f"\nStart {len(grid_points)} punktow? (t/n): ", ("t", "n"), default="t") == "n":
            return

        grid_data = {
            "origin_label": sess["origin_label"],
            "ox": ox,
            "oy": oy,
            "target_packets": target_packets,
            "tripod": tripod,
            "points": []
        }
        seen = set()

        for label, x_local, y_local in grid_points:
            x_global = round(ox + x_local, 4)
            y_global = round(oy + y_local, 4)

            blist_raw = [{"id": bid, "x": round(ox+bx, 4), "y": round(oy+by, 4), "local_x": bx, "local_y": by}
                         for bid, bx, by in (self._beacon_positions(x_local, y_local, tripod) if tripod
                                             else [(beacon_id, x_local, y_local)])]
            blist = []
            for b in blist_raw:
                key = (b["id"], b["x"], b["y"])
                if key not in seen:
                    seen.add(key)
                    blist.append(b)

            if not blist:
                continue

            grid_data["points"].append({
                "label": label, "x_local": x_local, "y_local": y_local,
                "x_global": x_global, "y_global": y_global, "beacons": blist
            })

        planned_grid_path = os.path.join(DATA_DIR, "planned_grid.json")
        with open(planned_grid_path, "w", encoding="utf-8") as f:
            json.dump(grid_data, f, indent=2)

        try:
            viewer = os.path.join(self.session_manager.script_dir, "map_viewer.py")
            subprocess.run([sys.executable, viewer, "--grid_collect", planned_grid_path], check=False)
        except Exception:
            pass

    def _print_ascii_map(self, grid_points, tripod):
        n_pts = len(grid_points)
        b_count = tripod["n_beacons"] if tripod else 1
        total_fps = n_pts * b_count
        if b_count > 1:
            print(f"\n[MAPA] Wygenerowano {n_pts} pozycji statywu (lacznie {total_fps} punktow w bazie dla {b_count} beaconow).")
        else:
            print(f"\n[MAPA] Wygenerowano {n_pts} punktow kalibracyjnych w siatce.")
        if grid_points:
            p1 = grid_points[0]
            pn = grid_points[-1]
            print(f"       Start: {p1[0]} ({p1[1]:.2f}, {p1[2]:.2f})")
            print(f"       Koniec: {pn[0]} ({pn[1]:.2f}, {pn[2]:.2f})")
        print("       (Wizualizacja zostanie otwarta w gui po uruchomieniu)\n")

    # Zbiera fingerprint w znanym punkcie kontrolnym do zbioru walidacyjnego ground truth.
    def run_collect_test_point(self) -> None:
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji.")
            return

        ox, oy = sess["origin_x_m"], sess["origin_y_m"]
        beacon_id = self._choose_single_beacon("punktu testowego")

        label = input("\nEtykieta (domyslnie 'test_pt'): ").strip() or "test_pt"
        x_local = get_float_input("Lokalne X [m]: ")
        y_local = get_float_input("Lokalne Y [m]: ")
        target_packets = get_int_input("Liczba pakietow: ", default=100, min_val=1)

        sock = self.client.connect_and_start()
        if not sock:
            return
        try:
            beacons = self._collect_fingerprint(sock, label, target_packets, [{"id": beacon_id, "x": round(ox + x_local, 4), "y": round(oy + y_local, 4)}])
        finally:
            self.client.stop_and_close(sock)
        if not beacons:
            return

        new_point = {
            "label":   label,
            "x_true":  round(ox + x_local, 4),
            "y_true":  round(oy + y_local, 4),
            "_local":  {"x": x_local, "y": y_local, "session": sess["origin_label"]},
            "beacons": beacons,
        }

        from validate import load_test_set, save_test_set
        existing = [tp for tp in load_test_set() if tp.get("label") != label]
        existing.append(new_point)
        save_test_set(existing)
