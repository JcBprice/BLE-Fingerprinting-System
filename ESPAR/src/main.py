"""Główny punkt wejścia do systemu lokalizacji ESPAR (tekstowe menu CLI)."""

import json
import os
import signal
import subprocess
import sys

from beacon_calibration import (
    choose_target_beacon,
    run_beacon_calibration,
    run_live_tracking,
)
from beacon_config import (
    load_beacons,
    print_beacons_table,
    register_beacons_interactive,
    remove_beacon_interactive,
)
from calibration import Calibrator
from config import OPTIMAL_K_PATH, PORT_NAMES, VALID_CHARS, register_antenna
from espar_client import EsparClient
from session import DATA_DIR, SCRIPT_DIR, SessionManager
from telnet_reader import get_espar_stream
from utils import (
    build_beacon_candidates,
    get_beacons_from_radio_map,
    select_beacon_interactive,
)
from validate import (
    load_optimal_config,
    load_test_set,
    optimize_k,
    run_validation,
)
from wknn import load_radio_map, save_distance_metric
import wknn


# Pobiera beacony z bazy oraz opcjonalnie skanuje pasmo radiowe, pozwalając wybrać ID beacona do danej operacji.
def _select_beacon(calibrator, purpose: str, scan: bool = True) -> int:
    db_beacons = get_beacons_from_radio_map()
    available = []
    if scan:
        try:
            available = calibrator._scan_available_beacons(duration=3.5)
        except Exception as e:
            print(f"  [!] Błąd skanowania: {e}")

    candidates = build_beacon_candidates(available, db_beacons) if scan else db_beacons
    rescan_cb = (lambda: calibrator._scan_available_beacons(duration=3.5)) if scan else None
    return select_beacon_interactive(candidates, db_beacons, available, purpose, rescan_callback=rescan_cb)


# Podmenu pozycjonowania opartego na stałych beaconach orientacyjnych (tzw. kotwicach).
def _menu_beacon_localization(calibrator, client):
    while True:
        beacons = load_beacons()
        n_beacons = len(beacons)
        radio = load_radio_map(filter_session=True)
        anchor_pts = sum(1 for pt in radio if pt.get("_beacon_anchor"))

        print("\n" + "─" * 60)
        print("  LOKALIZACJA Z BEACONAMI ORIENTACYJNYMI (KOTWICE)")
        print("─" * 60)
        print(f"  Zarejestrowane beacony: {n_beacons} | Radio mapa: {len(radio)} pkt (kotwiczące: {anchor_pts})\n")
        print("    1. Zarejestruj beacony orientacyjne")
        print("    2. Pokaż listę zarejestrowanych beaconów")
        print("    3. Zbierz radio mapę z beaconów (auto-kalibracja)")
        print("    4. Śledź beacon na żywo")
        print("    5. Usuń beacon orientacyjny")
        print("    0. Powrót do menu głównego")

        sub = input("\n  Wybór -> ").strip()
        if sub in ("0", ""):
            break
        if sub == "1":
            register_beacons_interactive(calibrator._scan_available_beacons)
        elif sub == "2":
            print_beacons_table(beacons)
        elif sub == "3":
            if not beacons:
                print("  [!] Zarejestruj beacony (opcja 1).")
                continue
            print_beacons_table(beacons)
            if input("  Rozpocząć auto-kalibrację? [T/n]: ").strip().lower() != "n":
                run_beacon_calibration(client, beacons, target_packets=100)
        elif sub == "4":
            if not beacons:
                print("  [!] Zarejestruj beacony (opcja 1).")
                continue
            target_bid = choose_target_beacon(calibrator._scan_available_beacons, beacons)
            if target_bid is not None:
                run_live_tracking(client, target_bid)
        elif sub == "5":
            remove_beacon_interactive()


# Wybór trybu tworzenia fingerprintów: pojedynczy punkt, zdefiniowana trasa lub automatyczna siatka.
def _handle_calibration(calibrator):
    print("\n  ┌─ TWORZENIE MAPY ODCISKÓW RADIOWYCH ──────────────────────┐")
    print("  │  p - Pojedynczy punkt (odcisk w danym miejscu)           │")
    print("  │  w - Wiele punktów (sekwencja ze statywem / lista)       │")
    print("  │  s - Siatka automatyczna (grid pomiarowy)                │")
    print("  └──────────────────────────────────────────────────────────┘")
    while True:
        sub = input("  Wybierz tryb [p/w/s] (Enter=Powrót): ").strip().lower()
        if not sub:
            break
        if sub == "w":
            calibrator.run_multi_point_calibration()
            break
        elif sub == "s":
            calibrator.run_grid_calibration()
            break
        elif sub == "p":
            print("    g - Tryb graficzny (celownik na mapie SVG)")
            print("    t - Tryb tekstowy w konsoli")
            while True:
                sub_p = input("    Wybierz [g/t] (Enter=Powrót): ").strip().lower()
                if not sub_p:
                    break
                if sub_p == "g":
                    calibrator.run_gui_single_fingerprint()
                    break
                elif sub_p == "t":
                    calibrator.run_average()
                    break
            break


# Narzędzia diagnostyczne: badanie charakterystyki kierunkowej RSSI i test zasięgu anteny.
def _handle_diagnostics(calibrator, client):
    print("\n  ┌─ DIAGNOSTYKA & ANALIZA SYGNAŁU RSSI ─────────────────────┐")
    print("  │  1 - Analiza istniejących danych (charakterystyka bazy)  │")
    print("  │  2 - Nowy pomiar na żywo (rotacja anteny)                │")
    print("  │  3 - Detekcja najsilniejszej anteny / pomieszczenia      │")
    print("  └──────────────────────────────────────────────────────────┘")
    while True:
        sub = input("  Wybierz opcję [1/2/3] (Enter=Powrót): ").strip()
        if not sub:
            break
        if sub == "1":
            from rssi_analysis import run_rssi_offline
            db_beacons = get_beacons_from_radio_map()
            if not db_beacons:
                print("  [!] Brak beaconów w bazie odcisków.")
                break
            _, bid = load_optimal_config()
            run_rssi_offline(beacon_id=bid)
            break
        elif sub == "2":
            from rssi_analysis import run_rssi_analysis
            bid = _select_beacon(calibrator, purpose="analizy RSSI", scan=True)
            if bid is not None:
                try:
                    run_rssi_analysis(
                        connect_fn=client.connect_and_start,
                        stream_fn=get_espar_stream,
                        close_fn=client.stop_and_close,
                        valid_chars=VALID_CHARS,
                        beacon_id=bid,
                        n_per_config=12,
                    )
                except Exception as e:
                    print(f"  [!] Błąd analizy RSSI: {e}")
            break
        elif sub == "3":
            from room_detector import run_room_detection
            run_room_detection()
            break


# Zbieranie punktów walidacyjnych (ground truth) do późniejszego wyliczenia błędu lokalizacji.
def _handle_validation(calibrator):
    print("\n  ┌─ ZBIERANIE PUNKTÓW TESTOWYCH ────────────────────────────┐")
    print("  │  g - Graficzny (zaznaczanie punktu na mapie SVG)         │")
    print("  │  t - Tekstowy (wprowadzanie współrzędnych z klawiatury)  │")
    print("  └──────────────────────────────────────────────────────────┘")
    while True:
        sub = input("  Wybierz [g/t] (Enter=Powrót): ").strip().lower()
        if not sub:
            break
        if sub == "g":
            if (bid := _select_beacon(calibrator, "zbierania testów", scan=True)) is not None:
                subprocess.run(
                    [sys.executable, os.path.join(SCRIPT_DIR, "map_viewer.py"), "--test_collect", str(bid), "100"],
                    check=False,
                )
            break
        elif sub == "t":
            calibrator.run_collect_test_point()
            break


# Uruchamia optymalizację parametru K na zbiorze testowym lub pozwala wpisać go ręcznie.
def _handle_k_optimization():
    while True:
        sub = input("\n  Dobór parametru K: [a]uto / [r]ęczny (Enter=Powrót): ").strip().lower()
        if not sub:
            break
        if sub == "r":
            k_str = input("  Podaj wartość K: ").strip()
            if not k_str:
                break
            try:
                k = int(k_str)
                if k <= 0:
                    raise ValueError()
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(OPTIMAL_K_PATH, "w", encoding="utf-8") as f:
                    json.dump({"k": k, "beacon_id": None, "source": "manual"}, f, indent=2)
                print(f"  [✓] Zapisano optymalne K = {k}")
                break
            except ValueError:
                print("  [!] Wprowadź liczbę całkowitą większą od zera.")
        elif sub == "a":
            optimize_k()
            break


# Pozwala wybrać aktywną antenę z predefiniowanych portów lub dodać nowy port ESPAR.
def _handle_antenna_config(client):
    while True:
        keys_sorted = sorted(PORT_NAMES.keys())
        mapping = {str(i): p for i, p in enumerate(keys_sorted, 1)}
        print("\n  Dostępne anteny ESPAR:")
        for idx, p in mapping.items():
            active_marker = " ◀ [AKTYWNA]" if p == client.port else ""
            print(f"    {idx}. Port {p} ({PORT_NAMES[p]}){active_marker}")
        print("    d. Dodaj nową antenę / port")

        sub = input("\n  Wybierz [1-N / d] (Enter=Powrót): ").strip().lower()
        if not sub:
            break

        if sub == "d":
            espar_num = input("  Numer ESPAR (np. 42 lub espar42): ").strip()
            if not espar_num:
                continue
            label = espar_num if espar_num.startswith("espar") else f"espar{espar_num}"

            port_raw = input("  Numer portu TCP (np. 8894): ").strip()
            if port_raw.isdigit():
                n_port = int(port_raw)
                register_antenna(n_port, label)
                client.port = n_port
                client.save_port_to_config(n_port)
                print(f"  [✓] Wybrano {label} na porcie {n_port}")
                break
            else:
                print("  [!] Nieprawidłowy numer portu.")
        elif sub in mapping:
            port = mapping[sub]
            client.port = port
            client.save_port_to_config(port)
            print(f"  [✓] Zmieniono antenę na port {port} ({PORT_NAMES[port]})")
            break


# Główna pętla konsolowa – odświeża stan bazy, rysuje pulpit i kieruje do wybranego modułu.
def main():
    session_manager = SessionManager(data_dir=DATA_DIR, script_dir=SCRIPT_DIR)
    client = EsparClient()
    calibrator = Calibrator(session_manager, client)

    while True:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            sess = session_manager.load_session()
            sess_info = f"'{sess['origin_label']}' @ ({sess['origin_x_m']:.2f}, {sess['origin_y_m']:.2f}) m" if sess else "Brak (skonfiguruj w opcji 1)"

            n_test = len(load_test_set(filter_session=True))
            n_radio = len(load_radio_map(filter_session=True))
            antenna_info = f"{client.port} ({PORT_NAMES.get(client.port, 'nieznana')})"
            n_beacons = len(load_beacons())
            opt_k, _ = load_optimal_config(default_k=3)

            # Pomocnik formatujący wiersze do stałej szerokości, by ramka się nie rozjeżdżała
            w = 66
            def _box_row(text: str = "") -> str:
                return f"║  {text[:w]:<{w}}  ║"

            border_top = f"╔{'═' * 70}╗"
            border_mid = f"╠{'═' * 70}╣"
            border_bot = f"╚{'═' * 70}╝"

            print()
            print(border_top)
            print(_box_row("SYSTEM LOKALIZACJI ESPAR".center(w)))
            print(border_mid)
            print(_box_row(f"Sesja:    {sess_info}"))
            print(_box_row(f"Konf:     Antena {antenna_info} │ Metryka: {wknn.DISTANCE_METRIC} │ K: {opt_k}"))
            print(_box_row(f"Baza:     Odciski: {n_radio} pkt │ Testowe: {n_test} pkt │ Beacony: {n_beacons}"))
            print(border_mid)
            print(_box_row("[KALIBRACJA]"))
            print(_box_row("  1. Zmiana pokoju (sesji)       2. Tworzenie mapy radiowej"))
            print(_box_row())
            print(_box_row("[DIAGNOSTYKA & MAPA]"))
            print(_box_row("  3. Podgląd mapy na żywo        4. Analiza RSSI & wizualizacje"))
            print(_box_row())
            print(_box_row("[WALIDACJA & TESTY]"))
            print(_box_row("  5. Punkty testowe              6. Optymalizacja parametru K"))
            print(_box_row("  7. Raport walidacji błędów"))
            print(_box_row())
            print(_box_row("[USTAWIENIA & SYSTEM]"))
            print(_box_row("  8. Wybór anteny i portu        9. Zmiana metryki odległości"))
            print(_box_row(" 10. Zbadaj RSSI beaconów       11. System kotwicowy - anchors"))
            print(_box_row(" 12. Monitor pakietów - podgląd strumienia danych"))
            print(_box_row())
            print(_box_row("  0. Zakończ program"))
            print(border_bot)

            choice = input("  Wybierz opcję -> ").strip()

            if choice == "1":
                session_manager.manage_session()
            elif choice == "2":
                _handle_calibration(calibrator)
            elif choice == "3":
                if (bid := _select_beacon(calibrator, "podglądu", scan=True)) is not None:
                    subprocess.run(
                        [sys.executable, os.path.join(SCRIPT_DIR, "map_viewer.py"), "--view", str(bid)],
                        check=False,
                    )
            elif choice == "4":
                _handle_diagnostics(calibrator, client)
            elif choice == "5":
                _handle_validation(calibrator)
            elif choice == "6":
                _handle_k_optimization()
            elif choice == "7":
                run_validation()
            elif choice == "8":
                _handle_antenna_config(client)
            elif choice == "9":
                print("\n  Dostępne metryki:")
                print("    1 - Pearson (korelacja)")
                print("    2 - Euclidean (odległość euklidesowa)")
                print("    3 - Hybrid (połączenie kształtu i amplitudy)")
                print("    4 - Weighted Pattern (wzorzec ważony)")
                if sub := input("\n  Wybierz [1-4] (Enter=Powrót): ").strip():
                    mtr = {"1": "pearson", "2": "euclidean", "3": "hybrid", "4": "weighted_pattern"}.get(sub)
                    if mtr:
                        save_distance_metric(mtr)
                        print(f"  [✓] Zmieniono metrykę na: {mtr}")
            elif choice == "10":
                from room_detector import run_room_detection
                run_room_detection()
            elif choice == "11":
                _menu_beacon_localization(calibrator, client)
            elif choice == "12":
                from counter import run_sample_counter
                run_sample_counter(client)
            elif choice == "0":
                print("\n  Do widzenia!\n")
                break

        except KeyboardInterrupt:
            print("\n")
            continue


if __name__ == "__main__":
    main()
