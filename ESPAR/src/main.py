"""
main.py — Główny moduł systemu lokalizacji ESPAR (Refactored).

Menu:
    ── Kalibracja ───────────────────────────────────────────
    1 – Punkt orientacyjny     (ustaw origin siatki)
    2 – Mapa odcisków radiowych (zbierz fingerprint)
    ── Diagnostyka ─────────────────────────────────────────
    3 – Podgląd mapy           (punkty kalibracyjne)
    4 – Analiza RSSI           (histogramy + stabilność)
    ── Walidacja ───────────────────────────────────────────
    5 – Zbieranie punktów testowych (ground truth)
    6 – Dobór parametru K      : ręczny / automatyczny
    7 – Analiza błędów         : RMSE, P90, CDF
    0 – Wyjście
"""

import os
import signal
import subprocess
import sys
import json

from session import SessionManager, DATA_DIR, SCRIPT_DIR
from espar_client import EsparClient
from calibration import Calibrator

from wknn import load_radio_map, save_distance_metric
import wknn
from validate import load_test_set, load_optimal_k, load_optimal_beacon_id, optimize_k, run_validation
from telnet_reader import get_espar_stream
from config import OPTIMAL_K_PATH, PORT_NAMES
from utils import (
    get_beacons_from_radio_map, build_beacon_candidates,
    select_beacon_interactive
)


def _select_beacon(calibrator, purpose: str, scan: bool = True) -> int:
    """Pomocnik: pobiera beacony z bazy, opcjonalnie skanuje aktywne, i pyta użytkownika.

    Args:
        calibrator: instancja Calibrator (potrzebna do skanowania)
        purpose: opis celu (wyświetlany w promptach, np. 'podglądu')
        scan: czy skanować aktywne beacony (False = tryb offline)
    Returns:
        wybrany beacon_id
    """
    db_beacons = get_beacons_from_radio_map()
    available = []
    if scan:
        try:
            available = calibrator._scan_available_beacons()
        except Exception as e:
            print(f"  [!] Błąd skanowania: {e}")
    candidates = build_beacon_candidates(available, db_beacons) if scan else db_beacons
    return select_beacon_interactive(candidates, db_beacons, available, purpose)


def main():
    # Inicjalizacja modułów
    session_manager = SessionManager(data_dir=DATA_DIR, script_dir=SCRIPT_DIR)
    client = EsparClient()
    calibrator = Calibrator(session_manager, client)

    while True:
        # Przywróć handler SIGINT — matplotlib może go nadpisać
        signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            sess = session_manager.load_session()
            sess_info = (
                f"'{sess['origin_label']}' @ ({sess['origin_x_m']}, {sess['origin_y_m']}) m"
                if sess else "BRAK -- ustaw przed kalibracja (opcja 1)"
            )
            
            n_test  = len(load_test_set(filter_session=True))
            n_radio = len(load_radio_map(filter_session=True))
            best_k  = load_optimal_k(default=3)
            k_info  = str(best_k)

            antenna_info = f"{client.port} ({PORT_NAMES.get(client.port, 'nieznana')})"

            print("\n=== SYSTEM LOKALIZACJI ESPAR ===")
            print(f"  Sesja:     {sess_info}")
            print(f"  Antena:    {antenna_info}")
            print(f"  Metryka:   {wknn.DISTANCE_METRIC}")
            print(f"  Radio map: {n_radio} pkt  |  Zbior testowy: {n_test} pkt  |  K_opt: {k_info}")
            print("  ---- Kalibracja ----------------------------------------")
            print("  1 - Punkt orientacyjny        (ustaw origin siatki)")
            print("  2 - Mapa odciskow radiowych   (zbierz fingerprint)")
            print("  ---- Diagnostyka ---------------------------------------")
            print("  3 - Podglad mapy              (punkty kalibracyjne)")
            print("  4 - Analiza RSSI              (histogramy + stabilnosc)")
            print("  ---- Walidacja -----------------------------------------")
            print("  5 - Zbieranie punktow testowych")
            print(f"  6 - Dobor parametru K         (reczny / automatyczny, aktualne K: {k_info})")
            print("  7 - Analiza bledow            (RMSE, P90, CDF)")
            print("  ---- Konfiguracja --------------------------------------")
            print("  8 - Zmiana portu anteny ESPAR (aktualnie: " + f"{antenna_info})")
            print("  9 - Zmiana metryki odległości (aktualnie: " + f"{wknn.DISTANCE_METRIC})")
            print(" 10 - Detekcja najsilniejszej anteny ESPAR (porównanie RSSI)")
            print("  ---------------------------------------------------------")
            print("  0 - Wyjscie")

            choice = input("\nWybierz tryb -> ").strip()

            if choice == "1":
                session_manager.manage_session()
            elif choice == "2":
                print("\n  Tworzenie mapy odciskow radiowych:")
                print("    p - Pojedynczy punkt  (reczne podanie etykiety i wspolrzednych)")
                print("    s - Siatka automatyczna (plan calego obszaru)")
                while True:
                    sub = input("  Wybierz [p/s] (lub Enter aby powrócić): ").strip().lower()
                    if not sub:
                        break
                    if sub == "s":
                        calibrator.run_grid_calibration()
                        break
                    elif sub == "p":
                        calibrator.run_average()
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz 'p' lub 's' (lub wciśnij Enter aby powrócić).")
            elif choice == "3":
                viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
                selected_beacon = _select_beacon(calibrator, "podglądu")
                print(f"Otwieram mape z punktami kalibracyjnymi dla Beacona #{selected_beacon}...")
                try:
                    subprocess.run([sys.executable, viewer, "--view", str(selected_beacon)], check=False)
                except Exception as e:
                    print(f"[!] Błąd mapy: {e}")
            elif choice == "4":
                print("\n  Analiza RSSI:")
                print("    1 - Analiza istniejacych danych  (z mapy / migawek, offline)")
                print("    2 - Nowy pomiar na zywo          (wymaga polaczenia z serwerem)")
                print("    3 - Detekcja najsilniejszej anteny ESPAR (porownanie RSSI)")
                while True:
                    sub = input("  Wybierz [1/2/3] (lub Enter aby powrócić): ").strip()
                    if not sub:
                        break
                    if sub == "3":
                        from room_detector import run_room_detection
                        run_room_detection()
                        break
                    elif sub == "2":
                        bid = _select_beacon(calibrator, "analizy RSSI")

                        from rssi_analysis import run_rssi_analysis
                        run_rssi_analysis(
                            connect_fn=client.connect_and_start,
                            stream_fn=get_espar_stream,
                            close_fn=client.stop_and_close,
                            valid_chars=Calibrator.VALID_CHARS,
                            beacon_id=bid,
                            n_per_config=500,
                        )
                        break
                    elif sub == "1":
                        db_beacons = get_beacons_from_radio_map()
                        if not db_beacons:
                            print("  [!] Brak beaconów w bazie odcisków.")
                            break
                        # Automatycznie wybierz beacon_id (z pliku optimal_k.json lub pierwszego z bazy) bez pytań
                        bid = load_optimal_beacon_id(default=db_beacons[0])

                        from rssi_analysis import run_rssi_offline
                        run_rssi_offline(beacon_id=bid)
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz '1', '2' lub '3' (lub wciśnij Enter aby powrócić).")
            elif choice == "5":
                print("\n  Zbieranie punktów testowych:")
                print("    g - Tryb graficzny (zaznaczanie na mapie, zalecane)")
                print("    t - Tryb tekstowy  (tradycyjne podawanie współrzędnych w terminalu)")
                while True:
                    sub = input("  Wybierz [g/t] (lub Enter aby powrócić): ").strip().lower()
                    if not sub:
                        break
                    if sub == "g":
                        selected_beacon = _select_beacon(calibrator, "zbierania punktów testowych")

                        print(f"\nOtwieram tryb graficznego zbierania dla Beacona #{selected_beacon}...")
                        viewer = os.path.join(SCRIPT_DIR, "map_viewer.py")
                        try:
                            subprocess.run([sys.executable, viewer, "--test_collect", str(selected_beacon), "100"], check=False)
                        except Exception as e:
                            print(f"[!] Błąd wywołania GUI: {e}")
                        break
                    elif sub == "t":
                        calibrator.run_collect_test_point()
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz 'g' lub 't' (lub wciśnij Enter aby powrócić).")
            elif choice == "6":
                print("\n  Dobor parametru K:")
                print("    a - Automatyczny (grid search, minimalizacja RMSE)")
                print("    r - Reczny (podaj wartosc K)")
                while True:
                    sub = input("  Wybierz [a/r] (lub Enter aby powrócić): ").strip().lower()
                    if not sub:
                        break
                    if sub == "r":
                        while True:
                            try:
                                k_val_raw = input("  Podaj wartosc K (lub Enter aby anulowac): ").strip()
                                if not k_val_raw:
                                    print("  [!] Anulowano.")
                                    break
                                k_val = int(k_val_raw)
                                if k_val < 1:
                                    raise ValueError
                                
                                # Wyznacz automatycznie główny beacon
                                beacons = get_beacons_from_radio_map()
                                bid = beacons[0] if beacons else 28
                                    
                                os.makedirs(DATA_DIR, exist_ok=True)
                                with open(OPTIMAL_K_PATH, "w", encoding="utf-8") as f:
                                    json.dump({"k": k_val, "beacon_id": bid,
                                               "source": "manual"}, f, indent=2)
                                print(f"  [OK] Zapisano K={k_val} (reczny dobor).")
                                break
                            except ValueError:
                                print("  [!] Nieprawidlowa wartosc K. Podaj liczbe dodatnia.")
                        break
                    elif sub == "a":
                        beacons = get_beacons_from_radio_map()
                        bid = beacons[0] if beacons else 28
                        optimize_k(beacon_id=bid)
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz 'a' lub 'r' (lub wciśnij Enter aby powrócić).")
            elif choice == "7":
                db_beacons = get_beacons_from_radio_map()
                if not db_beacons:
                    print("  [!] Brak danych w bazie odcisków. Walidacja niemożliwa.")
                    continue
                # Automatycznie pobierz beacon_id (z pliku optimal_k.json lub pierwszego z bazy) bez pytań w CLI
                bid = load_optimal_beacon_id(default=db_beacons[0])
                run_validation(k=None, beacon_id=bid)
            elif choice == "8":
                print("\n  Wybierz port anteny ESPAR:")
                print("    1 - Port 8893 (espar07)")
                print("    2 - Port 8894 (espar37)")
                print("    3 - Port 8895 (espar35)")
                while True:
                    sub = input("  Wybierz [1/2/3] (lub Enter aby powrócić): ").strip()
                    if not sub:
                        break
                    if sub in ("1", "2", "3"):
                        ports = {"1": 8893, "2": 8894, "3": 8895}
                        names = {"1": "espar07", "2": "espar37", "3": "espar35"}
                        port = ports[sub]
                        client.port = port
                        client.save_port_to_config(port)
                        print(f"  [OK] Zmieniono port na {port} ({names[sub]}).")
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz '1', '2' lub '3' (lub wciśnij Enter aby powrócić).")
            elif choice == "9":
                print("\n  Wybierz metrykę odległości:")
                print("    1 - Pearson (korelacja kształtu sygnału, domyślna)")
                print("    2 - Euclidean (odległość geometryczna, wymaga stabilnego sygnału)")
                while True:
                    sub = input("  Wybierz [1/2] (lub Enter aby powrócić): ").strip()
                    if not sub:
                        break
                    if sub == "1":
                        save_distance_metric("pearson")
                        print("  [OK] Zmieniono metrykę na 'pearson'.")
                        break
                    elif sub == "2":
                        save_distance_metric("euclidean")
                        print("  [OK] Zmieniono metrykę na 'euclidean'.")
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz '1' lub '2' (lub wciśnij Enter aby powrócić).")
            elif choice == "10":
                from room_detector import run_room_detection
                run_room_detection()
            elif choice == "0":
                print("Do widzenia.")
                break
            else:
                print("Nieprawidlowy wybor. Wpisz 0-10.")

        except KeyboardInterrupt:
            print("\n")
            continue

if __name__ == "__main__":
    os.environ["QT_LOGGING_RULES"] = "qt.*=false"
    main()
