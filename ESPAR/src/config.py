"""Centralny moduł konfiguracji systemu i lokalizacji danych (ESPAR IPS)."""

import json
import os
import re
import unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'data'))
SVG_PATH = os.path.join(SCRIPT_DIR, '..', '..', 'SVG_parser', 'mapaAK_sieciowe_v3.svg')

OPTIMAL_K_PATH = os.path.join(DATA_DIR, 'optimal_k.json')
SESSION_PATH = os.path.join(DATA_DIR, 'session.json')
SVG_CALIB_PATH = os.path.join(DATA_DIR, 'svg_calibration.json')
ESPAR_CONFIG_PATH = os.path.join(DATA_DIR, 'espar_config.json')


# Oczyszcza ciąg znaków (np. nazwę sesji) z polskich liter i spacji, by stworzyć bezpieczną nazwę pliku.
def slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    return re.sub(r'_+', '_', text).strip('_').lower()


def get_active_session() -> dict | None:
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, encoding='utf-8') as f:
            data = json.load(f)
            active = data.get("active_session", data)
            if isinstance(active, dict) and "origin_label" in active:
                return active
    except Exception:
        pass
    return None


def get_active_session_label() -> str:
    sess = get_active_session()
    return sess.get("origin_label", "") if isinstance(sess, dict) else ""


# Przeszukuje katalog data/ pod kątem plików sesji z typowymi przyrostkami (_final, dziala).
def _find_data_file(prefix: str, sess_name: str) -> str:
    no_under = sess_name.replace('_', '')
    suffixes = ['', '_final', 'dziala']
    name_variants = [sess_name, no_under] if no_under != sess_name else [sess_name]

    for name in name_variants:
        for suffix in suffixes:
            path = os.path.normpath(os.path.join(DATA_DIR, f'{prefix}_{name}{suffix}.json'))
            if os.path.exists(path):
                return path

    return os.path.normpath(os.path.join(DATA_DIR, f'{prefix}_{sess_name}.json'))


def get_radio_map_path() -> str:
    sess_name = slugify(get_active_session_label())
    return _find_data_file('radio_map', sess_name) if sess_name else os.path.join(DATA_DIR, 'radio_map.json')


def get_test_set_path() -> str:
    sess_name = slugify(get_active_session_label())
    return _find_data_file('test_set', sess_name) if sess_name else os.path.join(DATA_DIR, 'test_set.json')


def get_beacons_config_path() -> str:
    sess_name = slugify(get_active_session_label())
    return os.path.join(DATA_DIR, f'beacons_{sess_name}.json') if sess_name else os.path.join(DATA_DIR, 'beacons.json')


# 12 dozwolonych wartości pola 'char' z anteny ESPAR odpowiadających kolejnym sektorom 30°
VALID_CHARS = {31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}

# Mapowanie wartości dyskretnych z odbiornika na fizyczny kąt kierunku wiązki
CHAR_TO_DEG = {
    3587: 0,
    3841: 30,
    3968: 60,
    1984: 90,
    992: 120,
    496: 150,
    248: 180,
    124: 210,
    62:  240,
    31:  270,
    2063: 300,
    3079: 330,
}

DEG_TO_CHAR = {deg: ch for ch, deg in CHAR_TO_DEG.items()}

DEFAULT_RSSI_PENALTY   = -95.0
DEFAULT_BEACON_ID    = 28
DEFAULT_TARGET_PACKETS = 100
DEFAULT_K            = 3

DEFAULT_PORT_NAMES = {
    8893: "espar07",
    8894: "espar37",
    8895: "espar35",
}


def load_port_names() -> dict[int, str]:
    ports = dict(DEFAULT_PORT_NAMES)
    if os.path.exists(ESPAR_CONFIG_PATH):
        try:
            with open(ESPAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            for p_str, name in cfg.get("antennas", {}).items():
                try:
                    ports[int(p_str)] = str(name)
                except ValueError:
                    pass
        except Exception:
            pass
    return ports


PORT_NAMES = load_port_names()


# Zapisuje nowe powiązanie portu TCP z nazwą anteny do pliku konfiguracyjnego JSON.
def register_antenna(port: int, espar_name: str) -> None:
    global PORT_NAMES
    PORT_NAMES[port] = espar_name

    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = {}

    if os.path.exists(ESPAR_CONFIG_PATH):
        try:
            with open(ESPAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    antennas = cfg.get("antennas")
    if not isinstance(antennas, dict):
        antennas = {str(p): n for p, n in PORT_NAMES.items()}

    antennas[str(port)] = espar_name
    cfg["antennas"] = antennas

    try:
        with open(ESPAR_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[!] Błąd zapisu konfiguracji anteny: {e}")
