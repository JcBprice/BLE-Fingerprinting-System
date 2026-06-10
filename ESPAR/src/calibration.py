import json
import socket
from session import SessionManager
from espar_client import EsparClient
from telnet_reader import get_espar_stream
from wknn import load_radio_map, save_radio_map

class Calibrator:
    """Moduł do zbierania danych kalibracyjnych (fingerprinting)."""
    
    VALID_CHARS = {31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}
    TARGET_PACKETS = 100
    
    def __init__(self, session_manager: SessionManager, client: EsparClient):
        self.session_manager = session_manager
        self.client = client

    def _collect_fingerprint(self, sock: socket.socket, label: str, target_packets: int = 100) -> dict | None:
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
                if frame.get("espar_char_int") not in self.VALID_CHARS:
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

        sock = self.client.connect_and_start()
        if not sock:
            return

        try:
            beacons = self._collect_fingerprint(sock, label, self.TARGET_PACKETS)
        except socket.timeout:
            print("\n[!] Timeout serwera.")
            return
        finally:
            self.client.stop_and_close(sock)

        if not beacons:
            print("[!] Brak zebranych danych.")
            return

        new_point = {
            "label":   label,
            "x_m":     x_global,
            "y_m":     y_global,
            "_local":  {"x": x_local, "y": y_local,
                        "session": sess["origin_label"]},
            "beacons": beacons,
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

        prefix = input("  Prefix etykiet (np. '707_p', domyślnie 'p'): ").strip() or "p"

        # Generowanie siatki
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

            sock = self.client.connect_and_start()
            if not sock:
                print(f"  [!] Nie udało się połączyć. Pomijam {label}.")
                prev_x, prev_y = x_local, y_local
                continue

            beacons = self._collect_fingerprint(sock, label, self.TARGET_PACKETS)
            self.client.stop_and_close(sock)

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

    def run_collect_test_point(self) -> None:
        """Tryb 6: Zbieranie punktów testowych (ground truth)."""
        sess = self.session_manager.load_session()
        if not sess:
            print("\n[!] Brak aktywnej sesji. Ustaw origin siatki (opcja 1).")
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
        y_global = round(oy + y_local, 4)
        print(f"\n  Lokalne:  X={x_local} m, Y={y_local} m")
        print(f"  Globalne: X={x_global} m, Y={y_global} m")

        sock = self.client.connect_and_start()
        if not sock:
            return

        try:
            beacons = self._collect_fingerprint(sock, label, self.TARGET_PACKETS)
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
