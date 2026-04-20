import socket
import time
import json
import os
from telnet_reader import get_espar_stream

HOST = '153.19.49.102'
#HOST = '127.0.0.1'
PORT = 8893
TIMEOUT = 10

def connect_and_start():
    print(f"\nŁączenie z {HOST}:{PORT}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(b'\r\n')
        time.sleep(0.5)
        s.sendall(b'start\r\n')
        print("Połączono. Odbieranie danych...\n")
        return s
    except ConnectionRefusedError:
        print(f"Nie można nawiązać połączenia z hostem na porcie {PORT}: Połączenie nie powiodło się.")
        return None
    except socket.timeout:
        print(f"Nie można nawiązać połączenia z hostem na porcie {PORT}: Przekroczono czas oczekiwania.")
        return None
    except Exception as e:
        print(f"Wystąpił błąd sieci: {e}")
        return None

def stop_and_close(sock):
    if sock is None:
        return
    try:
        print("\nZatrzymuję transmisję...")
        sock.sendall(b'stop\r\n')
        time.sleep(0.5)
    except Exception:
        pass
    sock.close()

def run_live():
    #Tryb 1: Podgląd na żywo
    sock = connect_and_start()
    if not sock:
        return
    try:
        current_char = None
        print("Naciśnij Ctrl+C, aby zakończyć podgląd.\n")
        
        for frame in get_espar_stream(sock):
            char_int = frame['espar_char_int']
            
            if current_char is not None and char_int != current_char:
                print("-" * 60)
            current_char = char_int
            
            print(f"[{frame['ble_frame_num']:>7}] ESPAR: {frame['map_loc']} | "
                  f"Beacon: {frame['beacon_num']:>2} | RSSI: {frame['rssi_dbm']:>3} dBm | "
                  f"Ch-tyka: {char_int:<4} ({frame['espar_char_bin']})")
                  
    except KeyboardInterrupt:
        print("\n[!] Przerwano podgląd.")
    except socket.timeout:
        print("\n[!] Błąd: Przekroczono czas oczekiwania na dane z serwera.")
    finally:
        stop_and_close(sock)

DB_DIR = 'data'
DB_FILE = os.path.join(DB_DIR, 'radio_map.json')

def load_database():
    """Wczytaj bazę odcisków z pliku JSON. Zwraca pusty słownik jeśli plik nie istnieje."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print("[!] Plik bazy danych jest uszkodzony. Tworzę nową bazę.")
                return {}
    return {}

def save_database(db):
    """Zapisz bazę odcisków do pliku JSON."""
    os.makedirs(DB_DIR, exist_ok=True)
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

def run_average():
    # Tryb 2: Tworzenie bazy danych odcisku

    # --- Wczytanie bazy i pobranie nazwy odcisku ---
    db = load_database()

    if db:
        print(f"\nW bazie znajduje się {len(db)} odcisk(ów): {', '.join(db.keys())}")

    nazwa = input("\nPodaj nazwę/etykietę dla nowego odcisku (np. 'korytarz_A1'): ").strip()
    if not nazwa:
        print("[!] Nazwa nie może być pusta.")
        return

    if nazwa in db:
        nadpisz = input(f"Odcisk '{nazwa}' już istnieje. Nadpisać? (t/n): ").strip().lower()
        if nadpisz != 't':
            print("Anulowano.")
            return

    sock = connect_and_start()
    if not sock:
        return
    try:
        # Struktura: beacons_data[beacon_num][espar_char_int] = [rssi1, rssi2, ...]
        beacons_data = {}
        
        print(f"Zbieranie danych dla odcisku '{nazwa}'...")
        print("Naciśnij Ctrl+C, aby zakończyć, znormalizować wektory i zapisać do bazy.\n")
        
        packet_count = 0
        
        for frame in get_espar_stream(sock):
            b_num = frame['beacon_num']
            char_int = frame['espar_char_int']
            rssi = frame['rssi_dbm']
            
            # Inicjalizacja słowników dla nowego beacona/charakterystyki
            if b_num not in beacons_data:
                beacons_data[b_num] = {}
            if char_int not in beacons_data[b_num]:
                beacons_data[b_num][char_int] = []
                
            # Dodanie pomiaru
            beacons_data[b_num][char_int].append(rssi)
            packet_count += 1
            
            # Prosty wskaźnik postępu (żeby nie zalać konsoli tekstem)
            if packet_count % 50 == 0:
                print(f"Zebrano już {packet_count} pakietów od {len(beacons_data)} beaconów...", end='\r')
            
    except KeyboardInterrupt:
        print("\n\n[!] Zakończono zbieranie pomiarów. Przetwarzanie danych...")
        
        fingerprints = {}
        normalized_fingerprints = {}
        
        # --- UŚREDNIANIE I NORMALIZACJA DLA KAŻDEGO BEACONA ---
        for b_num, chars_data in beacons_data.items():
            fingerprints[b_num] = {}
            
            # 1. Uśrednianie
            for char_int, rssi_list in chars_data.items():
                srednia = sum(rssi_list) / len(rssi_list)
                fingerprints[b_num][char_int] = round(srednia, 2)
            
            # 2. Normalizacja min-max (0.0 - 1.0)
            if fingerprints[b_num]:
                min_rssi = min(fingerprints[b_num].values())
                max_rssi = max(fingerprints[b_num].values())
                
                normalized_fingerprints[b_num] = {}
                
                if max_rssi > min_rssi:
                    for char_int, s_rssi in fingerprints[b_num].items():
                        norm_val = (s_rssi - min_rssi) / (max_rssi - min_rssi)
                        normalized_fingerprints[b_num][char_int] = round(norm_val, 4)
                else:
                    # Zabezpieczenie przed dzieleniem przez zero
                    for char_int in fingerprints[b_num].keys():
                        normalized_fingerprints[b_num][char_int] = 0.0

        # --- WYŚWIETLANIE I ZAPIS DO BAZY ---
        print(f"\n--- ZNORMALIZOWANY ODCISK '{nazwa}' (0.0 - 1.0) ---")
        print(json.dumps(normalized_fingerprints, indent=4))
        
        # Dodanie odcisku do bazy
        db[nazwa] = normalized_fingerprints
        save_database(db)
        print(f"\n[V] Odcisk '{nazwa}' zapisano w bazie ({DB_FILE}). Łącznie odcisków: {len(db)}.")

    except socket.timeout:
        print("\n[!] Błąd: Przekroczono czas oczekiwania na dane z serwera.")
    finally:
        stop_and_close(sock)

def manage_database():
    """Tryb 3: Zarządzanie bazą odcisków."""
    db = load_database()

    if not db:
        print("\n[!] Baza odcisków jest pusta.")
        return

    while True:
        print(f"\n--- BAZA ODCISKÓW ({len(db)} pozycji) ---")
        for i, (nazwa, dane) in enumerate(db.items(), 1):
            beacony = len(dane)
            print(f"  {i}. '{nazwa}' — {beacony} beacon(ów)")

        print("\n  d <numer> — Usuń odcisk")
        print("  s         — Pokaż szczegóły odcisku")
        print("  q         — Powrót do menu głównego")

        cmd = input("\n-> ").strip().lower()

        if cmd == 'q':
            break
        elif cmd.startswith('d '):
            try:
                idx = int(cmd.split()[1]) - 1
                klucze = list(db.keys())
                if 0 <= idx < len(klucze):
                    nazwa_do_usu = klucze[idx]
                    potw = input(f"Na pewno usunąć '{nazwa_do_usu}'? (t/n): ").strip().lower()
                    if potw == 't':
                        del db[nazwa_do_usu]
                        save_database(db)
                        print(f"[V] Usunięto odcisk '{nazwa_do_usu}'.")
                        if not db:
                            print("Baza jest teraz pusta.")
                            break
                else:
                    print("Nieprawidłowy numer.")
            except (ValueError, IndexError):
                print("Użycie: d <numer>")
        elif cmd.startswith('s'):
            try:
                parts = cmd.split()
                if len(parts) < 2:
                    idx = int(input("Podaj numer odcisku: ").strip()) - 1
                else:
                    idx = int(parts[1]) - 1
                klucze = list(db.keys())
                if 0 <= idx < len(klucze):
                    nazwa_s = klucze[idx]
                    print(f"\n--- Odcisk '{nazwa_s}' ---")
                    print(json.dumps(db[nazwa_s], indent=4))
                else:
                    print("Nieprawidłowy numer.")
            except (ValueError, IndexError):
                print("Użycie: s <numer>")
        else:
            print("Nieznane polecenie.")

if __name__ == '__main__':
    while True:
        print("\n=== SYSTEM LOKALIZACJI ESPAR ===")
        print("1 - Podgląd na żywo ")
        print("2 - Nowy odcisk (fingerprint)")
        print("3 - Zarządzanie bazą odcisków")
        print("4 - Wyjście")
        
        wybor = input("Wybierz tryb -> ").strip()
        
        if wybor == '1':
            run_live()
        elif wybor == '2':
            run_average()
        elif wybor == '3':
            manage_database()
        elif wybor == '4':
            print("Zamykanie programu...")
            break
        else:
            print("Nieprawidłowy wybór. Wpisz 1, 2, 3 lub 4.")