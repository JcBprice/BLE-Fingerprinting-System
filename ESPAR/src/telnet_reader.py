import json

def parse_beacon_data(json_line):
    try:
        data = json.loads(json_line.strip())
        raw_values = data.get("d", "").split(",")
        
        if len(raw_values) >= 6:
            lat, lon, alt = 0.0, 0.0, 0.0
            if len(raw_values) >= 9:
                lat, lon, alt = float(raw_values[6]), float(raw_values[7]), float(raw_values[8])
                
            return {
                "device": data.get("v", "unknown"),
                "map_loc": 700 + int(raw_values[0]),
                "beacon_num": int(raw_values[1]),
                "rssi_dbm": -1 * int(raw_values[2]),
                "espar_char_int": int(raw_values[3]),
                "espar_char_bin": bin(int(raw_values[3])),
                "ble_channel": int(raw_values[4]),
                "ble_frame_num": int(raw_values[5]),
                "gps": {"lat": lat, "lon": lon, "alt": alt}
            }
    except Exception:
        pass
    return None

def get_espar_stream(sock):
    buffer = ""
    while True:
        chunk = sock.recv(4096).decode('utf-8', errors='ignore')
        if not chunk:
            break
        buffer += chunk
        
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            line = line.strip()
            
            if line.startswith('{'):
                parsed_data = parse_beacon_data(line)
                if parsed_data:
                    yield parsed_data 