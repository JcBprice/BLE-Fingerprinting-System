"""
telnet_reader.py — Odbieranie i parsowanie ramek BLE z lokalizatora ESPAR przez telnet.

Format danych przesyłanych przez telnet (jedna linia = jedna ramka BLE):
    {"v": "cnt_robot", "d": "7,33,50,62,37,12604,0,0,0"}

Pola w polu "d" (rozdzielone przecinkami):
    [0] numer ESPAR          – np. 7  → lokalizacja na mapie: 700+7 = pokój 707
    [1] numer beacona        – np. 33 → unikalny identyfikator nadajnika BLE
    [2] |RSSI| [dBm]         – np. 50 → wartość bezwzględna (znak minus pominięty),
                                         rzeczywiste RSSI = -50 dBm
    [3] char-tyka ESPAR      – np. 62 → dziesiętna reprezentacja 12-bitowego wektora
                                         sterującego anteną (62d = 0b000000111110).
                                         Bit 0 = pręt nr 1, bit 11 = pręt nr 12.
                                         Aktywne (=1) pręty stają się directorami,
                                         nieaktywne (=0) stają się reflectorami.
    [4] kanał BLE            – np. 37 → kanał advertising (37, 38 lub 39)
    [5] numer porządkowy     – np. 12604 → sekwencyjny numer ramki z beacona
    [6] GPS latitude         – 0.0 jeśli beacon nie ma odbiornika GPS
    [7] GPS longitude        – 0.0 jeśli beacon nie ma odbiornika GPS
    [8] GPS altitude         – 0.0 jeśli beacon nie ma odbiornika GPS
"""

import json

from config import VALID_CHARS


def parse_beacon_data(json_line: str) -> dict | None:
    """
    Parsuje jedną linię JSON z telnet i zwraca słownik z polami ramki BLE.

    Args:
        json_line: Surowa linia tekstowa w formacie JSON, np.:
                   '{"v":"cnt_robot","d":"7,33,50,62,37,12604,0,0,0"}'

    Returns:
        Słownik z polami ramki lub None jeśli linia jest nieprawidłowa.

    Przykład zwracanego słownika:
        {
            "device":        "cnt_robot",   # nazwa urządzenia ESPAR
            "map_loc":       707,            # numer pokoju (700 + nr ESPAR)
            "beacon_num":    33,             # numer beacona BLE
            "rssi_dbm":      -50,            # RSSI w dBm (ujemne)
            "espar_char_int": 62,            # wektor sterujący jako int
            "espar_char_bin": "0b111110",    # wektor sterujący jako string binarny
            "ble_channel":   37,             # kanał advertising BLE
            "ble_frame_num": 12604,          # numer porządkowy ramki
            "gps": {"lat": 0.0, "lon": 0.0, "alt": 0.0}
        }
    """
    try:
        data = json.loads(json_line.strip())
        fields = data.get("d", "").split(",")

        if len(fields) < 6:
            return None  # za mało pól — niepełna lub uszkodzona ramka

        # Zadbaj o to, aby pierwsze 6 pól było niepustych
        for i in range(6):
            if not fields[i].strip():
                return None

        # Sprawdź poprawność typów liczbowych w polach
        try:
            room_val  = int(fields[0])
            beacon_id = int(fields[1])
            rssi_abs  = int(fields[2])
            char_val  = int(fields[3])
            ble_chan  = int(fields[4])
            frame_num = int(fields[5])
        except ValueError:
            return None  # uszkodzone pola numeryczne


        rssi_dbm = -1 * rssi_abs

        # Filtruj nieprawidłowe konfiguracje anteny (musi być jeden z 12 kierunków)
        if char_val not in VALID_CHARS:
            return None

        # Opcjonalne pola GPS (dostępne tylko gdy beacon ma odbiornik GPS)
        lat, lon, alt = 0.0, 0.0, 0.0
        if len(fields) >= 9:
            try:
                lat = float(fields[6])
                lon = float(fields[7])
                alt = float(fields[8])
            except ValueError:
                pass

        return {
            "device":         data.get("v", "unknown"),
            "map_loc":        700 + room_val,
            "beacon_num":     beacon_id,
            "rssi_dbm":       rssi_dbm,
            "espar_char_int": char_val,
            "espar_char_bin": bin(char_val),
            "ble_channel":    ble_chan,
            "ble_frame_num":  frame_num,
            "gps":            {"lat": lat, "lon": lon, "alt": alt},
        }

    except Exception:
        return None  # błąd parsowania — ignorujemy uszkodzoną ramkę


def get_espar_stream(sock):
    """
    Generator: odbiera dane z gniazda TCP i zwraca sparsowane ramki BLE
    jedna po drugiej.

    Buforuje niepełne linie między kolejnymi wywołaniami recv(), dzięki
    czemu ramki rozłożone na kilka pakietów TCP są obsługiwane poprawnie.

    Args:
        sock: Aktywne gniazdo TCP (socket.socket) połączone z serwerem ESPAR.

    Yields:
        Słowniki ramek BLE zwrócone przez parse_beacon_data().
        Linie puste lub nieparsowalne są pomijane bez przerwania pętli.
    """
    buffer = ""
    while True:
        chunk = sock.recv(4096).decode("utf-8", errors="ignore")
        if not chunk:
            break  # serwer zamknął połączenie

        buffer += chunk

        # Wycinaj kolejne linie z bufora i parsuj je
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line.startswith("{"):
                parsed = parse_beacon_data(line)
                if parsed:
                    yield parsed