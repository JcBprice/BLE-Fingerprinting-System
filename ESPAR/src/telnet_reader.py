"""Odbieranie i parsowanie strumienia telnet z anteny ESPAR."""

import json

from config import VALID_CHARS


# Rozbija surowy format CSV z pola 'd' pakietu JSON na parametry ramki (ID beacona, RSSI w dBm, kąt wiązki).
def parse_beacon_data(json_line: str, filter_valid_chars: bool = True) -> dict | None:
    try:
        start_idx = json_line.find("{")
        if start_idx == -1:
            return None

        clean_line = json_line[start_idx:].strip()
        data = json.loads(clean_line)

        d_string = data.get("d", "")
        fields = d_string.split(",")

        if len(fields) < 6:
            return None

        for i in range(6):
            if not fields[i].strip():
                return None

        try:
            espar_val = int(fields[0])
            beacon_id = int(fields[1])
            rssi_abs  = int(fields[2])
            char_val  = int(fields[3])
            ble_chan  = int(fields[4])
            frame_num = int(fields[5])
        except ValueError:
            return None

        if filter_valid_chars:
            if char_val not in VALID_CHARS:
                return None

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
            "map_loc":        700 + espar_val,
            "beacon_num":     beacon_id,
            "rssi_dbm":       -rssi_abs,
            "espar_char_int": char_val,
            "espar_char_bin": bin(char_val),
            "ble_channel":    ble_chan,
            "ble_frame_num":  frame_num,
            "gps":            {"lat": lat, "lon": lon, "alt": alt},
        }
    except Exception:
        return None


# Generator odczytujący dane z gniazda TCP i emitujący sparsowane rekordy pomiarowe po znaku nowej linii.
def get_espar_stream(sock, filter_valid_chars: bool = True):
    buffer = ""
    while True:
        chunk = sock.recv(4096).decode("utf-8", errors="ignore")
        if chunk == "":
            break

        buffer += chunk
        while "\n" in buffer:
            parts = buffer.split("\n", 1)
            line = parts[0]
            buffer = parts[1]

            parsed = parse_beacon_data(line, filter_valid_chars)
            if parsed is not None:
                yield parsed
