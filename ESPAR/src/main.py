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

from session import SessionManager, DATA_DIR, SCRIPT_DIR
from espar_client import EsparClient
from calibration import Calibrator

from wknn import load_radio_map
from validate import load_test_set, load_optimal_k, optimize_k, run_validation
from telnet_reader import get_espar_stream


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
            
            n_test  = len(load_test_set())
            n_radio = len(load_radio_map())
            best_k  = load_optimal_k(default=3)
            k_info  = str(best_k)

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
            print(f"  6 - Dobor parametru K         (reczny / automatyczny, aktualne K: {k_info})")
            print("  7 - Analiza bledow            (RMSE, P90, CDF)")
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
                
                # Skanowanie aktywnych beaconów w otoczeniu
                try:
                    available = calibrator._scan_available_beacons()
                except Exception as e:
                    print(f"  [!] Błąd skanowania: {e}")
                    available = [28]
                
                print("\n  Dostępne beacony w okolicy:")
                for idx, bid in enumerate(available, 1):
                    print(f"    {idx} - Beacon #{bid}")
                
                print(f"\n  Wybierz beacon do podglądu (wpisz numer 1-{len(available)} lub bezpośrednio ID beacona, domyślnie {available[0]}):")
                ans = input("  Wybór -> ").strip()
                
                selected_beacon = available[0] if available else 28
                if ans:
                    try:
                        val = int(ans)
                        if 1 <= val <= len(available):
                            selected_beacon = available[val - 1]
                        else:
                            selected_beacon = val
                    except ValueError:
                        print("  [!] Nieprawidłowy wybór. Używam domyślnego beacona.")
                
                print(f"Otwieram mape z punktami kalibracyjnymi dla Beacona #{selected_beacon}...")
                try:
                    subprocess.run([sys.executable, viewer, "--view", str(selected_beacon)], check=False)
                except Exception as e:
                    print(f"[!] Błąd mapy: {e}")
            elif choice == "4":
                print("\n  Analiza RSSI:")
                print("    1 - Analiza istniejacych danych  (z mapy / migawek, offline)")
                print("    2 - Nowy pomiar na zywo          (wymaga polaczenia z serwerem)")
                while True:
                    sub = input("  Wybierz [1/2] (lub Enter aby powrócić): ").strip()
                    if not sub:
                        break
                    if sub == "2":
                        from rssi_analysis import run_rssi_analysis
                        run_rssi_analysis(
                            connect_fn=client.connect_and_start,
                            stream_fn=get_espar_stream,
                            close_fn=client.stop_and_close,
                            valid_chars=Calibrator.VALID_CHARS,
                            beacon_id=28,
                            n_per_config=500,
                        )
                        break
                    elif sub == "1":
                        from rssi_analysis import run_rssi_offline
                        run_rssi_offline(beacon_id=28)
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz '1' lub '2' (lub wciśnij Enter aby powrócić).")
            elif choice == "5":
                calibrator.run_collect_test_point()
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
                                os.makedirs(DATA_DIR, exist_ok=True)
                                import json as _json
                                with open(os.path.join(DATA_DIR, "optimal_k.json"), "w",
                                          encoding="utf-8") as _f:
                                    _json.dump({"k": k_val, "beacon_id": 28,
                                                "source": "manual"}, _f, indent=2)
                                print(f"  [OK] Zapisano K={k_val} (reczny dobor).")
                                break
                            except ValueError:
                                print("  [!] Nieprawidlowa wartosc K. Podaj liczbe dodatnia.")
                        break
                    elif sub == "a":
                        optimize_k(beacon_id=28)
                        break
                    else:
                        print("  [!] Nieprawidłowy wybór. Wpisz 'a' lub 'r' (lub wciśnij Enter aby powrócić).")
            elif choice == "7":
                run_validation(k=None, beacon_id=28)
            elif choice == "0":
                print("Do widzenia.")
                break
            else:
                print("Nieprawidlowy wybor. Wpisz 0-7.")

        except KeyboardInterrupt:
            print("\n")
            continue

if __name__ == "__main__":
    # Wycisz ostrzeżenia Qt/Wayland — dotyczy procesów potomnych (xdg-open, przeglądarki)
    os.environ["QT_LOGGING_RULES"] = "qt.*=false"
    main()
