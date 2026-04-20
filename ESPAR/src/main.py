import socket
import time
import json
import os
import math
from collections import defaultdict
from typing import Dict, Any
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

def load_database() -> Dict[str, Any]:
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

def collect_fingerprint(sock, timeout=None):
    """Zbiera dane z ESPAR i zwraca (map_loc, znormalizowany_odcisk, liczba_pakietów).
    timeout=None → zbiera aż do Ctrl+C, timeout=N → zbiera przez N sekund."""
    beacons_data = defaultdict(lambda: defaultdict(list))
    packet_count = 0
    map_loc = None
    start = time.time()

    if timeout:
        print(f"  Skanowanie przez {timeout}s... Oczekiwanie na dane...")
    else:
        print(f"  Skanowanie... (Ctrl+C aby zakończyć)")

    try:
        for frame in get_espar_stream(sock):
            if map_loc is None:
                map_loc = frame['map_loc']

            b = frame['beacon_num']
            c = frame['espar_char_int']
            beacons_data[b][c].append(frame['rssi_dbm'])
            packet_count += 1

            elapsed = time.time() - start
            if timeout:
                remaining = max(0, timeout - elapsed)
                print(f"  Pakiety: {packet_count} | Beacony: {len(beacons_data)} | Pozostało: {remaining:.0f}s   ", end='\r')
                if elapsed >= timeout:
                    break
            else:
                if packet_count % 20 == 0:
                    print(f"  Pakiety: {packet_count} | Beacony: {len(beacons_data)} | Czas: {elapsed:.0f}s   ", end='\r')

    except KeyboardInterrupt:
        print(f"\n  Przerwano po {packet_count} pakietach.")

    print()  # Nowa linia po \r

    # Uśrednianie + normalizacja min-max
    normalized = {}
    for b, chars in beacons_data.items():
        avg = {c: sum(r)/len(r) for c, r in chars.items()}
        mn, mx = min(avg.values()), max(avg.values())
        if mx > mn:
            normalized[b] = {c: float(f"{((v-mn)/(mx-mn)):.4f}") for c, v in avg.items()}
        else:
            normalized[b] = {c: 0.0 for c in avg}

    return map_loc, normalized, packet_count

def run_average():
    """Tryb 2: Ręczne tworzenie pojedynczego odcisku."""
    db = load_database()
    if db:
        print(f"\nW bazie: {len(db)} odcisk(ów): {', '.join(db.keys())}")

    nazwa = input("\nNazwa odcisku (np. 'korytarz_A1'): ").strip()
    if not nazwa:
        print("[!] Nazwa nie może być pusta.")
        return
    if nazwa in db:
        if input(f"Odcisk '{nazwa}' istnieje. Nadpisać? (t/n): ").strip().lower() != 't':
            return

    sock = connect_and_start()
    if not sock:
        return
    try:
        print(f"Zbieranie danych dla '{nazwa}'... (Ctrl+C aby zakończyć)\n")
        _, fingerprint, pkt = collect_fingerprint(sock)
        print(f"\n--- ODCISK '{nazwa}' ---")
        print(json.dumps(fingerprint, indent=4))
        db[nazwa] = fingerprint
        save_database(db)
        print(f"[V] Zapisano '{nazwa}' ({pkt} pkt). Łącznie: {len(db)}.")
    except socket.timeout:
        print("\n[!] Timeout.")
    finally:
        stop_and_close(sock)

def find_best_step(dimension, desired_step):
    """Optymalny krok dający całkowitą liczbę przedziałów (krok <= desired_step)."""
    if desired_step >= dimension:
        return dimension
    n = math.ceil(dimension / desired_step)
    return round(dimension / n, 4)

def run_room_scan():
    """Tryb 4: Automatyczne skanowanie pomieszczenia — nazwy odcisków generowane automatycznie."""
    db = load_database()

    try:
        width = float(input("\nSzerokość pomieszczenia [m] (oś X, np. 8): ").strip())
        height = float(input("Długość pomieszczenia [m] (oś Y, np. 4): ").strip())
        desired_step = float(input("Pożądany odstęp między odciskami [m] (np. 0.5): ").strip())
        if width <= 0 or height <= 0 or desired_step <= 0:
            print("[!] Wartości muszą być dodatnie.")
            return
    except ValueError:
        print("[!] Nieprawidłowa wartość.")
        return

    step_x = find_best_step(width, desired_step)
    step_y = find_best_step(height, desired_step)
    cols = round(width / step_x) + 1
    rows = round(height / step_y) + 1
    total = cols * rows

    print(f"\n--- PLAN SKANOWANIA ({width}m x {height}m) ---")
    print(f"Krok X: {step_x}m ({cols} pkt) | Krok Y: {step_y}m ({rows} pkt)")
    print(f"Łącznie: {total} odcisków ({cols}x{rows})")

    try:
        scan_time = int(input(f"Czas skanowania na punkt [s] (domyślnie 15): ").strip() or "15")
    except ValueError:
        scan_time = 15

    print(f"\nNumer pomieszczenia zostanie odczytany automatycznie ze strumienia.")
    print(f"Nazwy odcisków: {{map_loc}}_x{{X}}_y{{Y}}")
    print(f"\n--- KIERUNEK SKANOWANIA ---")
    print(f"  Zacznij od LEWEGO GÓRNEGO rogu (X=0, Y=0).")
    print(f"  Idź W PRAWO wzdłuż osi X, potem schodź w dół o krok Y.")
    print(f"")
    print(f"  START(0,0) →  →  →  →  koniec wiersza")
    print(f"  ↓")
    print(f"  (0,{step_y}) →  →  →  →  ...")
    print(f"  ↓")
    print(f"  ...aż do ({width},{height})")
    print(f"\nPrzy każdym punkcie ustaw antenę we właściwej pozycji i naciśnij ENTER.")
    if input(f"Rozpocząć skanowanie {total} punktów? (t/n): ").strip().lower() != 't':
        return

    # Generowanie siatki (lewy górny → prawo, wiersz po wierszu)
    grid = [(round(c * step_x, 4), round(r * step_y, 4))
            for r in range(rows) for c in range(cols)]

    # Jedno połączenie na cały skan
    sock = connect_and_start()
    if not sock:
        return

    map_loc = None
    saved = 0
    saved_labels = []
    stream = get_espar_stream(sock)

    try:
        for i, (x, y) in enumerate(grid, 1):
            print(f"\n{'='*50}")
            print(f"  PUNKT {i}/{total}:  X = {x}m,  Y = {y}m")
            print(f"  Ustaw antenę w tej pozycji i naciśnij ENTER...")
            sock.settimeout(None)  # Wyłącz timeout na czas oczekiwania
            input()
            sock.settimeout(TIMEOUT)  # Przywróć timeout do skanowania

            # Zbieranie danych z tego samego strumienia przez scan_time sekund
            beacons_data = defaultdict(lambda: defaultdict(list))
            packet_count = 0
            start = time.time()
            print(f"  Skanowanie przez {scan_time}s...")

            for frame in stream:
                if map_loc is None:
                    map_loc = frame['map_loc']

                b = frame['beacon_num']
                c = frame['espar_char_int']
                beacons_data[b][c].append(frame['rssi_dbm'])
                packet_count += 1

                elapsed = time.time() - start
                remaining = max(0, scan_time - elapsed)
                print(f"  Pakiety: {packet_count} | Beacony: {len(beacons_data)} | Pozostało: {remaining:.0f}s   ", end='\r')

                if elapsed >= scan_time:
                    break

            print()  # Nowa linia

            if not beacons_data:
                print("  [!] Brak danych, pomijam.")
                continue

            # Uśrednianie + normalizacja
            normalized = {}
            for b, chars in beacons_data.items():
                avg = {c: sum(r)/len(r) for c, r in chars.items()}
                mn, mx = min(avg.values()), max(avg.values())
                if mx > mn:
                    normalized[b] = {c: float(f"{((v-mn)/(mx-mn)):.4f}") for c, v in avg.items()}
                else:
                    normalized[b] = {c: 0.0 for c in avg}

            label = f"{map_loc}_x{x}_y{y}"
            db[label] = normalized
            save_database(db)
            saved += 1
            saved_labels.append(label)
            print(f"  [V] Zapisano: '{label}' ({packet_count} pakietów, {len(normalized)} beaconów)")

        print(f"\n{'='*50}")
        print(f"SKANOWANIE ZAKOŃCZONE")
        print(f"Pomieszczenie (map_loc): {map_loc}")
        print(f"Zapisano {saved}/{total} odcisków do {DB_FILE}.")

    except KeyboardInterrupt:
        print(f"\n\n[!] PRZERWANO SKANOWANIE (Ctrl+C).")
        if saved_labels:
            print(f"  Usuwanie {len(saved_labels)} niedokończonych odcisków z bazy...")
            for label in saved_labels:
                db.pop(label, None)
            save_database(db)
            print(f"  [V] Usunięto: {', '.join(saved_labels)}")
        print(f"  Baza danych przywrócona do stanu sprzed skanowania.")
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

def calculate_distance(fp1, fp2):
    """Oblicza odległość euklidesową między dwoma znormalizowanymi odciskami."""
    dist = 0.0
    fp1_str = {str(k): v for k, v in fp1.items()}
    fp2_str = {str(k): v for k, v in fp2.items()}
    all_beacons = set(fp1_str.keys()).union(fp2_str.keys())
    for b in all_beacons:
        chars1 = fp1_str.get(b, {})
        chars2 = fp2_str.get(b, {})
        chars1_str = {str(k): v for k, v in chars1.items()}
        chars2_str = {str(k): v for k, v in chars2.items()}
        all_chars = set(chars1_str.keys()).union(chars2_str.keys())
        for c in all_chars:
            v1 = chars1_str.get(c, 0.0)
            v2 = chars2_str.get(c, 0.0)
            dist += (v1 - v2) ** 2
    return math.sqrt(dist)

def find_closest_fingerprint(live_fp, db):
    """Zwraca klucz (nazwę) z bazy o najmniejszej odległości do odcisku live."""
    if not db:
        return None
    best_match = None
    min_dist = float('inf')
    for label, db_fp in db.items():
        if "_x" not in label or "_y" not in label:
            continue
        d = calculate_distance(live_fp, db_fp)
        if d < min_dist:
            min_dist = d
            best_match = label
    return best_match

def draw_ascii_map(db, current_label):
    """Rysuje mapę ASCII i oznacza aktualną pozycję."""
    points = []
    map_loc_name = "Nieznane"
    for label in db.keys():
        if "_x" in label and "_y" in label:
            try:
                parts = label.split('_')
                map_loc_name = parts[0]
                x = float(parts[1][1:])
                y = float(parts[2][1:])
                points.append((x, y, label))
            except Exception:
                pass
    
    if not points:
        print("[!] Brak punktów mapy w bazie danych (np. wygenerowanych przez automatyczne skanowanie).")
        return
        
    xs = sorted(list(set(p[0] for p in points)))
    ys = sorted(list(set(p[1] for p in points)))
    
    print(f"\n=== MAPA POMIESZCZENIA ({map_loc_name}) ===")
    print("      " + " ".join([f"{x:4.1f}" for x in xs]))
    for y in ys:
        row_str = f"{y:4.1f} |"
        for x in xs:
            point_label = f"{map_loc_name}_x{x}_y{y}"
            if point_label == current_label:
                row_str += " [X] "
            elif any(p[0] == x and p[1] == y for p in points):
                row_str += "  .  "
            else:
                row_str += "     "
        print(row_str)
    print("===================================\n")

def run_localization_map():
    """Tryb 5: Lokalizacja na mapie na żywo."""
    db = load_database()
    if not db:
        print("\n[!] Baza odcisków jest pusta. Najpierw przeprowadź skanowanie.")
        return
        
    has_map_points = any("_x" in k and "_y" in k for k in db.keys())
    if not has_map_points:
        print("\n[!] Baza nie zawiera punktów ze zdefiniowanymi współrzędnymi X/Y.")
        return

    sock = connect_and_start()
    if not sock:
        return
        
    print("\nRozpoczynanie lokalizacji... (uruchomienie zajmie ok. 2s)\n")
    try:
        while True:
            _, live_fp, pkt = collect_fingerprint(sock, timeout=2)
            
            # Lepsze czyszczenie terminali w IDE (VS Code / PyCharm)5
            
            print('\033[H\033[J', end='')

            if pkt == 0:
                print("Lokalizacja...")
                print("  Brak danych od ESPAR. Przechodzę do kolejnej próbki...")
                continue
                
            best_match = find_closest_fingerprint(live_fp, db)
            
            if best_match:
                draw_ascii_map(db, best_match)
                print(f"Najbliższy punkt: {best_match} ({pkt} odebranych pakietów przez 2s)")
                print("Naciśnij Ctrl+C, aby zakończyć.\n")
            else:
                print("[!] Nie dopasowano żadnego punktu z mapy.")
                
    except KeyboardInterrupt:
        print("\n[!] Lokalizacja zatrzymana.")
    finally:
        stop_and_close(sock)

if __name__ == '__main__':
    while True:
        print("\n=== SYSTEM LOKALIZACJI ESPAR ===")
        print("1 - Podgląd na żywo ")
        print("2 - Nowy odcisk (fingerprint)")
        print("3 - Zarządzanie bazą odcisków")
        print("4 - Skanowanie pomieszczenia (automatyczna baza)")
        print("5 - Lokalizacja na mapie na żywo")
        print("6 - Wyjście")
        
        wybor = input("Wybierz tryb -> ").strip()
        
        if wybor == '1':
            run_live()
        elif wybor == '2':
            run_average()
        elif wybor == '3':
            manage_database()
        elif wybor == '4':
            run_room_scan()
        elif wybor == '5':
            run_localization_map()
        elif wybor == '6':
            print("Zamykanie programu...")
            break
        else:
            print("Nieprawidłowy wybór. Wpisz 1, 2, 3, 4, 5 lub 6.")
