"""Kolory, motyw ciemny i przeliczanie współrzędnych SVG na metry fizyczne."""

import json
import os

from PyQt6.QtGui import QColor

from config import DATA_DIR, SVG_CALIB_PATH, SVG_PATH

# Paleta kolorów motywu ciemnego (Dark Theme)
C_BG      = QColor('#0a0e1a')
C_PANEL   = QColor('#0f1623')
C_PANEL2  = QColor('#141e2f')
C_BORDER  = QColor('#1e2d45')
C_ACCENT  = QColor('#3b82f6')
C_DOT     = QColor('#ef4444')
C_TRAIL   = QColor('#ef4444')
C_TEXT    = QColor('#e2e8f0')
C_MUTED   = QColor('#64748b')
C_SUCCESS = QColor('#10b981')


# Wczytuje kalibrację współczynnika skali oraz marginesu układu SVG z pliku JSON.
def _load_svg_calibration() -> dict:
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


# Przelicza współrzędne fizyczne w metrach na jednostki wektora SVG (1 m = 100 jednostek SVG).
def physical_to_svg(x_m: float, y_m: float) -> tuple[float, float]:
    return (
        SVG_ORIGIN_X + x_m * SCALE,
        SVG_ORIGIN_Y + y_m * SCALE,
    )


# Odwrotne przeliczenie ze współrzędnych wektora SVG na metry rzeczywiste budynku.
def svg_to_physical(svg_x: float, svg_y: float) -> tuple[float, float]:
    return (
        (svg_x - SVG_ORIGIN_X) / SCALE,
        (svg_y - SVG_ORIGIN_Y) / SCALE,
    )
