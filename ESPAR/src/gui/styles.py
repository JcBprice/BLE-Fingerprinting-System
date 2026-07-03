"""
styles.py — Kolory, czcionki i konwersje współrzędnych GUI systemu ESPAR.

Centralizuje:
    - Paletę kolorów (dark theme)
    - Kalibrację układu współrzędnych SVG ↔ metry fizyczne
    - Ścieżkę do pliku SVG mapy budynku
"""

import json
import os

from PyQt6.QtGui import QColor

from config import DATA_DIR, SVG_PATH, SVG_CALIB_PATH

# ── Paleta kolorów (Dark Theme) ──────────────────────────────────────────────

C_BG      = QColor('#0a0e1a')    # Tło główne
C_PANEL   = QColor('#0f1623')    # Tło panelu bocznego
C_PANEL2  = QColor('#141e2f')    # Tło przycisków / inputów
C_BORDER  = QColor('#1e2d45')    # Obramowania
C_ACCENT  = QColor('#3b82f6')    # Kolor akcentu (niebieski)
C_DOT     = QColor('#ef4444')    # Kolor kropki beacona (czerwony)
C_TRAIL   = QColor('#ef4444')    # Kolor śladu ruchu
C_TEXT    = QColor('#e2e8f0')    # Tekst główny
C_MUTED   = QColor('#64748b')    # Tekst wyciszony
C_SUCCESS = QColor('#10b981')    # Kolor sukcesu (zielony)


# ── Kalibracja układu współrzędnych ──────────────────────────────────────────
# SVG pochodzi z Inkscape. Rysunek architektoniczny w skali 1:100:
#   100 SVG units = 1 metr rzeczywisty  →  SCALE = 100
#
# Globalne (0,0) = lewy górny narożnik budynku = SVG (0,0).
# Offset origin_x_svg / origin_y_svg kompensuje ewentualny margines.

def _load_svg_calibration() -> dict:
    """Wczytuje kalibrację SVG z pliku lub zwraca wartości domyślne."""
    defaults = {"origin_x_svg": 0.0, "origin_y_svg": 0.0, "scale": 100.0}
    if os.path.exists(SVG_CALIB_PATH):
        try:
            with open(SVG_CALIB_PATH, encoding='utf-8') as f:
                return {**defaults, **json.load(f)}
        except Exception:
            pass
    return defaults


_calib       = _load_svg_calibration()
SVG_ORIGIN_X: float = _calib["origin_x_svg"]
SVG_ORIGIN_Y: float = _calib["origin_y_svg"]
SCALE:        float = _calib["scale"]


def physical_to_svg(x_m: float, y_m: float) -> tuple[float, float]:
    """Przelicza współrzędne fizyczne [m] → SVG units.

    Układ SVG: Y rośnie w dół, (0,0) = lewy górny róg budynku.
    """
    return (
        SVG_ORIGIN_X + x_m * SCALE,
        SVG_ORIGIN_Y + y_m * SCALE,
    )


def svg_to_physical(svg_x: float, svg_y: float) -> tuple[float, float]:
    """Odwrotna konwersja SVG units → współrzędne fizyczne [m]."""
    return (
        (svg_x - SVG_ORIGIN_X) / SCALE,
        (svg_y - SVG_ORIGIN_Y) / SCALE,
    )
