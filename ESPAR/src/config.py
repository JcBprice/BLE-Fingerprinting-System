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
    """Zamienia tekst (np. nazwę sesji) na bezpieczną nazwę pliku (lowercase, bez polskich znaków)."""
    import re
    pl_chars = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    text = text.translate(pl_chars)
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text.lower()


def get_active_session_label() -> str:
    """Zwraca surową etykietę aktywnej sesji (np. 'espar37') lub pusty string.

    Obsługuje zarówno stary format (płaski) jak i nowy (z kluczem active_session).
    Używana przez wknn.py, validate.py i config.py do filtrowania po sesji.
    """
    import json
    session_path = os.path.join(DATA_DIR, 'session.json')
    if not os.path.exists(session_path):
        return ''
    try:
        with open(session_path, encoding='utf-8') as f:
            sess = json.load(f)
        # Stary format: {"origin_label": "espar37", ...}
        if "origin_label" in sess:
            return sess["origin_label"]
        # Nowy format: {"active_session": {"origin_label": "espar37", ...}}
        active = sess.get("active_session")
        if isinstance(active, dict):
            return active.get("origin_label", "")
    except Exception:
        pass
    return ''


def _find_data_file(prefix: str, sess_name: str) -> str:
    """Szuka pliku danych o podanym prefixie (np. 'radio_map' lub 'test_set')
    w katalogach data/ i old_fingerprints/. Zwraca pierwszą istniejącą ścieżkę.

    Próbuje warianty nazw: z podkreślnikami, bez, z sufiksem 'dziala', '_final'.
    """
    no_under = sess_name.replace('_', '')
    # Sufiksy do sprawdzenia (pusty = dokładna nazwa sesji)
    suffixes = ['', '_final', 'dziala']
    # Katalogi do przeszukania
    dirs = [
        DATA_DIR,
        os.path.normpath(os.path.join(DATA_DIR, '..', '..', 'old_fingerprints')),
    ]
    # Warianty nazwy sesji (ze spacjami jako _ i bez _)
    name_variants = [sess_name, no_under] if no_under != sess_name else [sess_name]

    for search_dir in dirs:
        for name in name_variants:
            for suffix in suffixes:
                path = os.path.normpath(os.path.join(search_dir, f'{prefix}_{name}{suffix}.json'))
                if os.path.exists(path):
                    return path

    # Nie znaleziono — zwróć domyślną ścieżkę w data/
    return os.path.normpath(os.path.join(DATA_DIR, f'{prefix}_{sess_name}.json'))


def get_radio_map_path() -> str:
    """Zwraca ścieżkę do pliku mapy radiowej dopasowaną do aktywnej sesji."""
    sess_name = slugify(get_active_session_label())
    if sess_name:
        return _find_data_file('radio_map', sess_name)
    return os.path.normpath(os.path.join(DATA_DIR, 'radio_map.json'))


def get_test_set_path() -> str:
    """Zwraca ścieżkę do pliku zbioru testowego dopasowaną do aktywnej sesji."""
    sess_name = slugify(get_active_session_label())
    if sess_name:
        return _find_data_file('test_set', sess_name)
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
