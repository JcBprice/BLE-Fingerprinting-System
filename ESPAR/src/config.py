"""
config.py — Stałe konfiguracyjne systemu lokalizacji ESPAR.

Moduł centralizuje ścieżki, stałe anteny i parametry domyślne,
aby uniknąć duplikacji w wielu plikach.
"""

import os

# ── Ścieżki katalogów ────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'data'))
SVG_PATH   = os.path.join(SCRIPT_DIR, '..', '..', 'SVG_parser', 'mapaAK_sieciowe_v3.svg')

# ── Ścieżki plików danych ────────────────────────────────────────────────────

def slugify(text: str) -> str:
    import re
    pl_chars = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    text = text.translate(pl_chars)
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text.lower()

def get_session_name() -> str:
    import json
    session_path = os.path.join(DATA_DIR, 'session.json')
    if os.path.exists(session_path):
        try:
            with open(session_path, encoding='utf-8') as f:
                sess = json.load(f)
                label = ""
                if "origin_label" in sess:
                    label = sess["origin_label"]
                elif "active_session" in sess and isinstance(sess["active_session"], dict):
                    label = sess["active_session"].get("origin_label", "")
                if label:
                    return slugify(label)
        except Exception:
            pass
    return ''

def get_radio_map_path() -> str:
    sess_name = get_session_name()
    if sess_name:
        no_under = sess_name.replace('_', '')
        candidates = [
            os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{sess_name}.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{sess_name}_final.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{sess_name}dziala.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{no_under}.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{no_under}dziala.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'radio_map_{sess_name}.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'radio_map_{sess_name}_final.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'radio_map_{sess_name}dziala.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'radio_map_{no_under}.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'radio_map_{no_under}dziala.json')),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return os.path.normpath(os.path.join(DATA_DIR, f'radio_map_{sess_name}.json'))
    return os.path.normpath(os.path.join(DATA_DIR, 'radio_map.json'))

def get_test_set_path() -> str:
    sess_name = get_session_name()
    if sess_name:
        no_under = sess_name.replace('_', '')
        candidates = [
            os.path.normpath(os.path.join(DATA_DIR, f'test_set_{sess_name}.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'test_set_{sess_name}_final.json')),
            os.path.normpath(os.path.join(DATA_DIR, f'test_set_{no_under}.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'test_set_{sess_name}.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'test_set_{sess_name}_final.json')),
            os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints', f'test_set_{no_under}.json')),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return os.path.normpath(os.path.join(DATA_DIR, f'test_set_{sess_name}.json'))
    return os.path.normpath(os.path.join(DATA_DIR, 'test_set.json'))

OPTIMAL_K_PATH   = os.path.join(DATA_DIR, 'optimal_k.json')
SESSION_PATH     = os.path.join(DATA_DIR, 'session.json')
SVG_CALIB_PATH   = os.path.join(DATA_DIR, 'svg_calibration.json')
ESPAR_CONFIG_PATH = os.path.join(DATA_DIR, 'espar_config.json')

# ── Konfiguracja anteny ESPAR ─────────────────────────────────────────────────

# 12 poprawnych konfiguracji kierunkowych anteny ESPAR.
# Każda wartość to dziesiętna reprezentacja 12-bitowego wektora sterującego.
# Bit = 1 → pręt jest dyrektorem, bit = 0 → pręt jest reflektorem.
VALID_CHARS = {31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}

# Mapowanie konfiguracji anteny (char_int) → kąt wiązki [stopnie].
# Kąt 0° = "przód" anteny, rośnie zgodnie z ruchem wskazówek zegara.
CHAR_TO_DEG = {
    31:    90,
    62:   120,
    124:  150,
    248:  180,
    496:  210,
    992:  240,
    1984: 270,
    3968: 300,
    3841: 330,
    3587:   0,
    3079:  30,
    2063:  60,
}

# Odwrotne mapowanie: kąt → char_int
DEG_TO_CHAR = {deg: ch for ch, deg in CHAR_TO_DEG.items()}

# ── Domyślne wartości ─────────────────────────────────────────────────────────

DEFAULT_RSSI_PENALTY = -95.0   # dBm — spuścizna (legacy), nieużywane po rezygnacji z systemu kar
DEFAULT_BEACON_ID    = 28
DEFAULT_TARGET_PACKETS = 100
DEFAULT_K            = 3

# Mapowanie portów TCP na nazwy anten
PORT_NAMES = {
    8893: "espar07",
    8894: "espar37",
    8895: "espar35",
}
