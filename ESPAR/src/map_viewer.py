"""
map_viewer.py — Okno wizualizacji pozycji beacona na mapie SVG (PyQt6)

Użycie samodzielne (tryb demo):
    python map_viewer.py

API (do integracji z silnikiem WkNN):
    from map_viewer import MapWindow, launch_viewer

    win = launch_viewer()               # otwiera okno w tle
    win.update_position(x_m, y_m,       # aktualizuje pozycję beacona
                        beacon_id=28,
                        confidence=0.95)

Kalibracja układu współrzędnych:
    (x=0, y=0) = lewy górny kraniec korytarza
    X rośnie w prawo (wzdłuż korytarza), Y rośnie w dół
    Skala: 100 SVG units = 1 metr
"""

import sys
import os
import math
import socket
import threading
import time
import json

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy,
    QPushButton, QStatusBar, QCheckBox,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPointF, QSize, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient,
    QPixmap, QPalette, QFontDatabase, QLinearGradient, QPolygonF,
)

# ── Ścieżki ──────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR   = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'data'))
_CALIB_PATH = os.path.join(_DATA_DIR, 'svg_calibration.json')
SVG_PATH    = os.path.join(SCRIPT_DIR, '..', '..', 'SVG_parser', 'mapaAK_sieciowe_v3.svg')

# Dostęp do modułów sąsiednich (telnet_reader, wknn, validate)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ── Połączenie z serwerem ESPAR (dla trybu live) ─────────────────────────────────
ESPAR_HOST  = '153.19.49.102'
ESPAR_PORT  = 8893
ESPAR_TIMEOUT = 10
VALID_CHARS = {31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}

# ── Kalibracja układu współrzędnych ──────────────────────────────────────────
# SVG pochodzi z Inkscape. Rysunek architektoniczny w skali 1:100:
#   100 SVG units = 1 metr rzeczywisty  →  SCALE = 100
#
# Uwaga: atrybut width="437.35cm" to rozmiar STRONY (papier A0+), nie budynku.
#         Budynek ma ~43.7m × ~26.2m (viewBox 4373 × 2617 units / 100).
#
# Globalne (0,0) = lewy górny narożnik budynku = SVG (0,0).
# Offset origin_x_svg / origin_y_svg kompensuje ewentualny margines (domyślnie 0).
def _load_svg_calibration() -> dict:
    """Wczytuje kalibrację SVG z pliku lub zwraca wartości domyślne."""
    defaults = {"origin_x_svg": 0.0, "origin_y_svg": 0.0, "scale": 100.0}
    if os.path.exists(_CALIB_PATH):
        try:
            with open(_CALIB_PATH, encoding='utf-8') as f:
                return {**defaults, **json.load(f)}
        except Exception:
            pass
    return defaults

_calib       = _load_svg_calibration()
SVG_ORIGIN_X: float = _calib["origin_x_svg"]
SVG_ORIGIN_Y: float = _calib["origin_y_svg"]
SCALE:        float = _calib["scale"]

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


class MapCanvas(QWidget):
    """Widżet z mapą SVG i animowaną kropką beacona."""

    position_picked = pyqtSignal(float, float)

    def __init__(self, svg_path: str, pick_mode: bool = False,
                 mark_origin_mode: bool = False, select_mode: bool = False,
                 existing_points=None, session_origin=None, parent=None):
        super().__init__(parent)
        self._existing_points = existing_points or []
        self._session_origin  = session_origin   # (x_m, y_m) lub None
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._pick_mode        = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._select_mode      = select_mode
        self._selected_labels  = set()
        if pick_mode or mark_origin_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
            tip = ('Kliknij narożnik budynku (globalny 0,0)' if mark_origin_mode
                   else 'Kliknij miejsce gdzie stoi statyw / lokalny origin')
            self.setToolTip(tip)
        elif select_mode:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip('Klikaj punkty na mapie, aby je zaznaczyć/odznaczyć do analizy')
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.setToolTip('Ctrl+klik: pokaż współrzędne SVG tego miejsca')

        self._picked_svg_x: float | None = None
        self._picked_svg_y: float | None = None

        self._renderer = QSvgRenderer(svg_path, self)
        vb = self._renderer.viewBoxF()
        raw_w = vb.width()  if vb.width()  > 10 else 4700.0
        raw_h = vb.height() if vb.height() > 10 else 2800.0
        
        # Rozszerzenie viewBox by objąć przetransformowane obiekty
        self._vb_w = max(raw_w, 4600.0)
        self._vb_h = max(raw_h, 2760.0)

        self._zoom        = 1.0
        self._pan         = QPointF(0.0, 0.0)
        self._drag_start  = None
        self._pan_at_drag = QPointF(0.0, 0.0)

        self._bx: float | None = None
        self._by: float | None = None
        self._bid: int | None  = None
        self._conf: float      = 1.0
        self._trail: list[tuple[float, float]] = []
        self._MAX_TRAIL = 50

        self._pulse  = 0.0
        self._p_dir  = 1.0
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

        self._bg_pix:   QPixmap | None = None
        self._bg_rect:  QRectF  | None = None

        self._show_fingerprints: bool = True

    # ── Public API ───────────────────────────────────────────────────────────
    def update_position(self, x_m: float, y_m: float,
                        beacon_id=None, confidence: float = 1.0):
        """Ustaw nową pozycję beacona (wywołaj z silnika WkNN)."""
        sx, sy = physical_to_svg(x_m, y_m)
        if self._bx is not None:
            self._trail.append((self._bx, self._by))
            if len(self._trail) > self._MAX_TRAIL:
                self._trail.pop(0)
        self._bx   = sx
        self._by   = sy
        self._bid  = beacon_id
        self._conf = confidence

    def fit_view(self):
        """Dopasuj widok do okna."""
        self._zoom = 1.0
        self._pan  = QPointF(0.0, 0.0)
        self._bg_pix = None
        self.update()

    def clear_trail(self):
        self._trail.clear()
        self.update()

    # ── Render rect ──────────────────────────────────────────────────────────
    def _render_rect(self) -> QRectF:
        """Prostokąt (widget-pixels) w którym renderowany jest SVG."""
        w, h   = self.width(), self.height()
        aspect = self._vb_w / self._vb_h
        if w / h > aspect:
            rh = h * self._zoom
            rw = rh * aspect
        else:
            rw = w * self._zoom
            rh = rw / aspect
        # Centre when zoom==1 (no manual pan yet)
        cx = self._pan.x() + (w - rw) / 2.0
        cy = self._pan.y() + (h - rh) / 2.0
        return QRectF(cx, cy, rw, rh)

    def _svg_to_widget(self, sx: float, sy: float) -> QPointF:
        r = self._render_rect()
        return QPointF(
            r.x() + (sx / self._vb_w) * r.width(),
            r.y() + (sy / self._vb_h) * r.height(),
        )

    def _dot_r(self) -> float:
        r = self._render_rect()
        px_per_m = (r.width() / self._vb_w) * SCALE
        return max(7.0, min(18.0, px_per_m * 0.20))

    # ── Mouse / Wheel ────────────────────────────────────────────────────────
    def wheelEvent(self, e):
        factor  = 1.15 if e.angleDelta().y() > 0 else 1.0 / 1.15
        old_z   = self._zoom
        self._zoom = max(0.25, min(12.0, self._zoom * factor))
        mx = float(e.position().x())
        my = float(e.position().y())
        r  = self._render_rect()
        ratio = self._zoom / old_z
        self._pan = QPointF(
            mx - (mx - r.x()) * ratio - (self.width()  - r.width()  * ratio) / 2,
            my - (my - r.y()) * ratio - (self.height() - r.height() * ratio) / 2,
        )
        self._bg_pix = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._drag_start  = e.position()
            self._pan_at_drag = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if e.button() == Qt.MouseButton.LeftButton:
            wx = float(e.position().x())
            wy = float(e.position().y())
            r  = self._render_rect()

            # Tryb pick / mark_origin — każdy klik wybiera pozycję
            if (self._pick_mode or self._mark_origin_mode) and r.width() > 0:
                svg_x = (wx - r.x()) / r.width()  * self._vb_w
                svg_y = (wy - r.y()) / r.height() * self._vb_h
                self._picked_svg_x = svg_x
                self._picked_svg_y = svg_y
                if self._mark_origin_mode:
                    # Emitujemy surowe jednostki SVG — caller zapisuje jako origin
                    self.position_picked.emit(round(svg_x, 2), round(svg_y, 2))
                else:
                    phys_x, phys_y = svg_to_physical(svg_x, svg_y)
                    self.position_picked.emit(round(phys_x, 3), round(phys_y, 3))
                self.update()
                return

            # Tryb select-points — wybór punktów kalibracyjnych
            if self._select_mode and r.width() > 0 and r.height() > 0:
                svg_x = (wx - r.x()) / r.width()  * self._vb_w
                svg_y = (wy - r.y()) / r.height() * self._vb_h
                phys_x, phys_y = svg_to_physical(svg_x, svg_y)
                
                closest_pt = None
                min_dist = float('inf')
                for pt in self._existing_points:
                    px = pt.get('x_m')
                    py = pt.get('y_m')
                    if px is not None and py is not None:
                        dist = math.hypot(phys_x - px, phys_y - py)
                        if dist < min_dist:
                            min_dist = dist
                            closest_pt = pt
                
                if closest_pt is not None and min_dist < 1.5:
                    lbl = closest_pt.get('label')
                    if lbl:
                        if lbl in self._selected_labels:
                            self._selected_labels.remove(lbl)
                        else:
                            self._selected_labels.add(lbl)
                        parent_win = self.window()
                        if hasattr(parent_win, '_on_selection_changed'):
                            parent_win._on_selection_changed()
                        self.update()
                return

            # Ctrl+klik → wypisz współrzędne SVG i fizyczne
            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if r.width() > 0 and r.height() > 0:
                    svg_x = (wx - r.x()) / r.width()  * self._vb_w
                    svg_y = (wy - r.y()) / r.height() * self._vb_h
                    phys_x, phys_y = svg_to_physical(svg_x, svg_y)
                    print(f'[PROBE] widget=({wx:.0f},{wy:.0f})')
                    print(f'        SVG   = ({svg_x:.1f}, {svg_y:.1f})')
                    print(f'        Fizyczne = x={phys_x:.2f}m, y={phys_y:.2f}m')
                    print(f'        SVG_ORIGIN_X={SVG_ORIGIN_X}  SVG_ORIGIN_Y={SVG_ORIGIN_Y}')
                return

            self._drag_start  = e.position()
            self._pan_at_drag = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag_start is not None:
            d = e.position() - self._drag_start
            self._pan = self._pan_at_drag + d
            self._bg_pix = None
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_start = None
            if self._pick_mode or self._mark_origin_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self._select_mode:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

    def resizeEvent(self, _):
        self._bg_pix = None   # invalidate on resize

    # ── Animation tick ───────────────────────────────────────────────────────
    def _tick(self):
        if self._bx is None:
            return
        MAX_P = 28.0
        self._pulse += self._p_dir * 0.9
        if self._pulse >= MAX_P:
            self._p_dir = -1.0
        elif self._pulse <= 0.0:
            self._p_dir =  1.0
            self._pulse = 0.0
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background
        p.fillRect(self.rect(), C_BG)

        # SVG map (cached pixmap)
        r = self._render_rect()
        iw, ih = int(r.width()), int(r.height())
        if iw > 0 and ih > 0:
            if self._bg_pix is None or self._bg_rect != r:
                self._bg_rect = QRectF(r)
                self._bg_pix  = QPixmap(iw, ih)
                self._bg_pix.fill(Qt.GlobalColor.transparent)
                bp = QPainter(self._bg_pix)
                bp.setRenderHint(QPainter.RenderHint.Antialiasing)
                self._renderer.render(bp, QRectF(0, 0, iw, ih))
                bp.end()
            p.drawPixmap(int(r.x()), int(r.y()), self._bg_pix)

        # Rysuj istniejące punkty kalibracyjne (niebieskie lub zielone jeśli wybrane)
        if self._show_fingerprints and self._existing_points:
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for pt in self._existing_points:
                x_m, y_m = pt.get('x_m'), pt.get('y_m')
                lbl = pt.get('label', '')
                if x_m is not None and y_m is not None:
                    sx, sy = physical_to_svg(x_m, y_m)
                    wp = self._svg_to_widget(sx, sy)
                    is_selected = lbl in self._selected_labels
                    if is_selected:
                        p.setBrush(QBrush(QColor('#10b981')))
                        p.setPen(QPen(Qt.GlobalColor.white, 2))
                        p.drawEllipse(wp, 8, 8)
                        p.setPen(QPen(QColor('#34d399')))
                        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
                        p.drawText(int(wp.x()) + 11, int(wp.y()) + 4, lbl)
                    else:
                        p.setBrush(QBrush(QColor('#3b82f6')))
                        p.setPen(QPen(Qt.GlobalColor.white, 1))
                        p.drawEllipse(wp, 5, 5)
                        p.setPen(QPen(QColor('#bfdbfe')))
                        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
                        p.drawText(int(wp.x()) + 8, int(wp.y()) + 4, lbl)

        # Rysuj origin aktualnej sesji (żółty krzyżyk)
        if self._session_origin is not None:
            sox, soy = self._session_origin
            ssx, ssy = physical_to_svg(sox, soy)
            sp = self._svg_to_widget(ssx, ssy)
            p.setPen(QPen(QColor('#facc15'), 2))
            R = 10
            p.drawLine(int(sp.x()) - R, int(sp.y()), int(sp.x()) + R, int(sp.y()))
            p.drawLine(int(sp.x()), int(sp.y()) - R, int(sp.x()), int(sp.y()) + R)
            p.setBrush(QBrush(QColor('#facc15')))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(sp, 4, 4)
            p.setPen(QPen(QColor('#fef08a')))
            p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
            p.drawText(int(sp.x()) + 8, int(sp.y()) - 4, 'origin sesji')

        # Tryb PICK: rysuj zielony celownik w wybranym miejscu
        if self._pick_mode:
            if self._picked_svg_x is not None:
                centre = self._svg_to_widget(self._picked_svg_x, self._picked_svg_y)
                CR = 14
                pen = QPen(QColor('#22c55e'), 2)
                p.setPen(pen)
                p.drawLine(int(centre.x()) - CR - 4, int(centre.y()),
                           int(centre.x()) + CR + 4, int(centre.y()))
                p.drawLine(int(centre.x()), int(centre.y()) - CR - 4,
                           int(centre.x()), int(centre.y()) + CR + 4)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor('#22c55e'), 2))
                p.drawEllipse(centre, CR, CR)
                p.setBrush(QBrush(QColor('#22c55e')))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(centre, 4, 4)
            p.end()
            return

        # Brak pozycji beacona — nic nie rysujemy
        if self._bx is None:
            p.end()
            return

        dot_r  = self._dot_r()
        centre = self._svg_to_widget(self._bx, self._by)

        # Trail
        n = len(self._trail)
        for i, (tx, ty) in enumerate(self._trail):
            tp    = self._svg_to_widget(tx, ty)
            alpha = int(30 + 150 * (i + 1) / max(n, 1))
            tr    = max(2.0, dot_r * 0.45 * (i + 1) / max(n, 1))
            tc    = QColor(C_TRAIL); tc.setAlpha(alpha)
            p.setBrush(QBrush(tc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(tp, tr, tr)

        # Outer glow
        glow = QRadialGradient(centre, dot_r * 3)
        gc   = QColor(C_DOT); gc.setAlpha(70)
        glow.setColorAt(0, gc); glow.setColorAt(1, Qt.GlobalColor.transparent)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centre, dot_r * 3, dot_r * 3)

        # Pulsing ring
        ring_r = dot_r + self._pulse
        alpha  = max(0, int(220 * (1 - self._pulse / 28)))
        rc     = QColor(C_DOT); rc.setAlpha(alpha)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rc, 2.0))
        p.drawEllipse(centre, ring_r, ring_r)

        # Main dot (filled circle with white border)
        p.setBrush(QBrush(C_DOT))
        p.setPen(QPen(Qt.GlobalColor.white, max(1.5, dot_r * 0.18)))
        p.drawEllipse(centre, dot_r, dot_r)

        # Beacon label bubble
        if self._bid is not None:
            lbl  = f'  Beacon #{self._bid}  '
            font = QFont('Segoe UI', max(8, int(dot_r * 0.85)), QFont.Weight.Bold)
            p.setFont(font)
            fm   = p.fontMetrics()
            tw   = fm.horizontalAdvance(lbl)
            th   = fm.height()
            lx   = int(centre.x() - tw / 2)
            ly   = int(centre.y() - dot_r - 8)
            pad  = 4
            bg   = QColor(C_PANEL); bg.setAlpha(230)
            p.setBrush(QBrush(bg))
            p.setPen(QPen(C_ACCENT, 1))
            p.drawRoundedRect(lx - pad, ly - th - pad, tw + 2 * pad, th + 2 * pad, 5, 5)
            p.setPen(QPen(C_TEXT))
            p.drawText(lx, ly - fm.descent(), lbl)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# INFO PANEL
# ─────────────────────────────────────────────────────────────────────────────
class InfoPanel(QFrame):
    """Lewy panel z informacjami o pozycji beacona."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C_PANEL.name()};
                border-right: 1px solid {C_BORDER.name()};
            }}
            QLabel {{ color: {C_TEXT.name()}; background: transparent; border: none; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(0)

        # Title
        title = QLabel('📡  ESPAR IPS')
        title.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        title.setStyleSheet(f'color: {C_ACCENT.name()};')
        lay.addWidget(title)
        lay.addSpacing(4)

        sub = QLabel('Indoor Positioning System')
        sub.setFont(QFont('Segoe UI', 8))
        sub.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(sub)

        lay.addSpacing(20)
        lay.addWidget(self._divider())

        # Section: Beacon
        lay.addSpacing(14)
        lay.addWidget(self._section_label('ŚLEDZONY OBIEKT'))
        lay.addSpacing(8)
        self._lbl_id = self._value_label('—')
        self._lbl_id.setFont(QFont('Segoe UI', 20, QFont.Weight.Bold))
        self._lbl_id.setStyleSheet(f'color: {C_DOT.name()};')
        lay.addWidget(self._lbl_id)

        lay.addSpacing(18)
        lay.addWidget(self._divider())

        # Section: Coordinates
        lay.addSpacing(14)
        lay.addWidget(self._section_label('POZYCJA (METRY)'))
        lay.addSpacing(8)
        self._lbl_x = self._coord_row(lay, 'X (wzdłuż)')
        self._lbl_y = self._coord_row(lay, 'Y (w poprzek)')

        lay.addSpacing(18)
        lay.addWidget(self._divider())

        # Section: Confidence
        lay.addSpacing(14)
        lay.addWidget(self._section_label('PEWNOŚĆ'))
        lay.addSpacing(6)
        self._lbl_conf = self._value_label('—')
        self._lbl_conf.setFont(QFont('JetBrains Mono', 14, QFont.Weight.Medium))
        lay.addWidget(self._lbl_conf)

        # Confidence bar
        self._conf_bar = QFrame()
        self._conf_bar.setFixedHeight(4)
        self._conf_bar.setFixedWidth(0)
        self._conf_bar.setStyleSheet(
            'background: qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            'stop:0 #10b981, stop:1 #3b82f6);'
            'border-radius: 2px;'
        )
        bar_wrap = QFrame()
        bar_wrap.setFixedHeight(4)
        bar_wrap.setStyleSheet(f'background: {C_PANEL2.name()}; border-radius: 2px;')
        bar_lay = QHBoxLayout(bar_wrap)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.addWidget(self._conf_bar)
        bar_lay.addStretch()
        lay.addSpacing(6)
        lay.addWidget(bar_wrap)

        lay.addSpacing(18)
        lay.addWidget(self._divider())

        # Section: SVG coords (debug)
        lay.addSpacing(14)
        lay.addWidget(self._section_label('SVG UNITS'))
        lay.addSpacing(6)
        self._lbl_svg = QLabel('—')
        self._lbl_svg.setFont(QFont('Cascadia Code', 9))
        self._lbl_svg.setWordWrap(True)
        self._lbl_svg.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(self._lbl_svg)

        lay.addStretch()

        # Zoom controls at bottom
        lay.addWidget(self._divider())
        lay.addSpacing(12)
        lay.addWidget(self._section_label('WIDOK'))
        lay.addSpacing(6)
        self._btn_fit = self._btn('Dopasuj (F)')
        lay.addWidget(self._btn_fit)
        lay.addSpacing(6)
        self._btn_clear = self._btn('Wyczyść ślad')
        lay.addWidget(self._btn_clear)

        # Section: Options (checkboxes)
        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(12)
        lay.addWidget(self._section_label('OPCJE'))
        lay.addSpacing(6)

        chk_style = f"""
            QCheckBox {{
                color: {C_TEXT.name()};
                font-size: 11px;
                spacing: 6px;
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {C_BORDER.name()};
                border-radius: 3px;
                background: {C_PANEL2.name()};
            }}
            QCheckBox::indicator:checked {{
                background: {C_ACCENT.name()};
                border-color: {C_ACCENT.name()};
            }}
            QCheckBox::indicator:hover {{
                border-color: {C_ACCENT.name()};
            }}
        """

        self._chk_beacons = QCheckBox('Pokaż odciski radiowe')
        self._chk_beacons.setChecked(True)
        self._chk_beacons.setStyleSheet(chk_style)
        lay.addWidget(self._chk_beacons)
        lay.addSpacing(4)

        self._chk_live = QCheckBox('Pozycja na żywo')
        self._chk_live.setStyleSheet(chk_style)
        lay.addWidget(self._chk_live)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _divider(self):
        d = QFrame()
        d.setFixedHeight(1)
        d.setStyleSheet(f'background: {C_BORDER.name()};')
        return d

    def _section_label(self, txt):
        l = QLabel(txt)
        l.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
        l.setStyleSheet(f'color: {C_MUTED.name()}; letter-spacing: 1px;')
        return l

    def _value_label(self, txt):
        l = QLabel(txt)
        l.setFont(QFont('JetBrains Mono', 13, QFont.Weight.Medium))
        return l

    def _coord_row(self, lay, name):
        lbl_name = QLabel(name)
        lbl_name.setFont(QFont('Segoe UI', 8))
        lbl_name.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(lbl_name)
        val = QLabel('—')
        val.setFont(QFont('JetBrains Mono', 14, QFont.Weight.Medium))
        val.setStyleSheet(f'color: {C_TEXT.name()};')
        lay.addWidget(val)
        lay.addSpacing(8)
        return val

    def _btn(self, txt):
        b = QPushButton(txt)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 5px;
                padding: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {C_BORDER.name()};
                border-color: {C_ACCENT.name()};
            }}
        """)
        return b

    # ── Update ────────────────────────────────────────────────────────────────
    def refresh(self, x_m, y_m, svg_x, svg_y, beacon_id, confidence):
        id_txt = f'#{beacon_id}' if beacon_id is not None else '—'
        self._lbl_id.setText(id_txt)
        self._lbl_x.setText(f'{x_m:.2f} m')
        self._lbl_y.setText(f'{y_m:.2f} m')
        pct = int(confidence * 100)
        self._lbl_conf.setText(f'{pct} %')
        bar_w = int((160) * confidence)
        self._conf_bar.setFixedWidth(bar_w)
        self._lbl_svg.setText(f'x={svg_x:.0f}\ny={svg_y:.0f}')


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class MapWindow(QMainWindow):
    """Główne okno wizualizacji systemu ESPAR IPS."""

    _sig_pos = pyqtSignal(float, float, object, float)

    def __init__(self, svg_path: str = SVG_PATH, pick_mode: bool = False,
                 show_points: bool = False, mark_origin_mode: bool = False,
                 select_mode: bool = False):
        super().__init__()

        # Wczytaj istniejące punkty kalibracyjne do wyświetlenia
        existing_points = []
        if pick_mode or show_points or mark_origin_mode or select_mode:
            try:
                radio_path = os.path.join(_DATA_DIR, 'radio_map.json')
                with open(radio_path, encoding='utf-8') as f:
                    existing_points = json.load(f)
            except Exception:
                pass

        # Wczytaj origin aktywnej sesji (żółty marker)
        session_origin = None
        sess_path = os.path.join(_DATA_DIR, 'session.json')
        if os.path.exists(sess_path):
            try:
                with open(sess_path, encoding='utf-8') as f:
                    s = json.load(f)
                session_origin = (s['origin_x_m'], s['origin_y_m'])
            except Exception:
                pass

        self._pick_mode        = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._show_points      = show_points
        self._select_mode      = select_mode

        if mark_origin_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz globalny narożnik budynku (0,0)')
        elif pick_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz lokalny origin sesji pomiarowej')
        elif show_points:
            self.setWindowTitle('ESPAR IPS — Baza Punktów Kalibracyjnych')
        elif select_mode:
            self.setWindowTitle('ESPAR IPS — Wybierz punkty kalibracyjne do analizy')
        else:
            self.setWindowTitle('ESPAR IPS — Mapa Pozycjonowania')
        self.resize(1300, 740)
        self._setup_style()
        self._picked: tuple | None = None  # (svg_x, svg_y) lub (x_m, y_m)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Info panel
        self._panel = InfoPanel()
        root.addWidget(self._panel)

        # Map canvas
        svg = os.path.normpath(svg_path)
        self._canvas = MapCanvas(svg, pick_mode=pick_mode,
                                 mark_origin_mode=mark_origin_mode,
                                 select_mode=select_mode,
                                 existing_points=existing_points,
                                 session_origin=session_origin)
        root.addWidget(self._canvas)

        # Connect buttons
        self._panel._btn_fit.clicked.connect(self._canvas.fit_view)
        self._panel._btn_clear.clicked.connect(self._canvas.clear_trail)

        # Status bar (must be created before select_mode branch uses it)
        self._sb = QStatusBar()
        self._sb.setStyleSheet(
            f'background: {C_PANEL.name()}; color: {C_MUTED.name()};'
            f'border-top: 1px solid {C_BORDER.name()};'
        )
        self.setStatusBar(self._sb)
        self._sb.showMessage(
            'Kliknij na mapie miejsce gdzie stoi statyw  |  F: dopasuj  |  Scroll: zoom'
            if pick_mode else
            'Oczekiwanie na dane pozycji…  |  Kółko myszy: zoom  |  Przeciągnij: przesuń  |  F: dopasuj'
        )

        # Pick / mark-origin mode: confirm button + live status
        if pick_mode or mark_origin_mode:
            self._canvas.position_picked.connect(self._on_picked)
            btn_label = ('Zatwierdź origin budynku' if mark_origin_mode
                         else 'Zatwierdź origin sesji')
            self._panel._btn_clear.setText(btn_label)
            self._panel._btn_clear.setStyleSheet(
                'QPushButton { background: #166534; color: #86efac; '
                'border: 1px solid #22c55e; border-radius: 5px; padding: 8px; font-size: 12px; font-weight: bold; }'
                'QPushButton:hover { background: #15803d; }'
            )
            self._panel._btn_clear.clicked.disconnect()
            self._panel._btn_clear.clicked.connect(self._confirm_pick)
        elif select_mode:
            btn_label = 'Zatwierdź wybór'
            self._panel._btn_clear.setText(btn_label)
            self._panel._btn_clear.setStyleSheet(
                'QPushButton { background: #166534; color: #86efac; '
                'border: 1px solid #22c55e; border-radius: 5px; padding: 8px; font-size: 12px; font-weight: bold; }'
                'QPushButton:hover { background: #15803d; }'
            )
            self._panel._btn_clear.clicked.disconnect()
            self._panel._btn_clear.clicked.connect(self._confirm_select)
            self._panel._btn_fit.setText('Wyczyść wybór')
            self._panel._btn_fit.clicked.disconnect()
            self._panel._btn_fit.clicked.connect(self._clear_selection)
            self._on_selection_changed()

        self._fit_key = Qt.Key.Key_F
        self._sig_pos.connect(self._on_position)
        self._last_x = 0.0
        self._last_y = 0.0

        # Live thread (pozycjonowanie na żywo)
        self._live_thread: LiveThread | None = None

        # Podłącz checkboxy
        self._panel._chk_beacons.toggled.connect(self._on_toggle_beacons)
        self._panel._chk_live.toggled.connect(self._on_toggle_live)

    def _on_picked(self, a: float, b: float):
        """Obsługuje wybór pozycji.
        W trybie mark_origin: a=svg_x, b=svg_y (surowe jednostki SVG).
        W trybie pick:        a=x_m,   b=y_m   (metry fizyczne).
        """
        self._picked = (a, b)
        if self._mark_origin_mode:
            self._sb.showMessage(
                f'Narożnik budynku: SVG=({a:.1f}, {b:.1f})  —  '
                f'Kliknij "Zatwierdź origin budynku" lub wybierz inne miejsce'
            )
        else:
            self._sb.showMessage(
                f'Origin sesji: X={a:.3f} m, Y={b:.3f} m  —  '
                f'Kliknij "Zatwierdź origin sesji" lub wybierz inne miejsce'
            )
            self._panel.refresh(a, b, SVG_ORIGIN_X + a * SCALE,
                                SVG_ORIGIN_Y + b * SCALE, 'origin', 1.0)

    def _confirm_pick(self):
        """Zatwierdza wybór i zamyka okno."""
        if self._picked is None:
            self._sb.showMessage('Najpierw kliknij na mapie!')
            return
        a, b = self._picked
        if self._mark_origin_mode:
            # Zapisz kalibrację SVG bezpośrednio do pliku
            calib = {"origin_x_svg": a, "origin_y_svg": b, "scale": SCALE,
                     "_note": "SVG 1 unit = 1 mm, SCALE = 1000 units/metr"}
            os.makedirs(_DATA_DIR, exist_ok=True)
            with open(_CALIB_PATH, 'w', encoding='utf-8') as f:
                json.dump(calib, f, indent=2)
            print(json.dumps({'svg_x': a, 'svg_y': b, 'saved': True}), flush=True)
        else:
            print(json.dumps({'x_m': a, 'y_m': b, 'picked': True}), flush=True)
        self.close()

    def _clear_selection(self):
        """Czyści zaznaczenie."""
        self._canvas._selected_labels.clear()
        self._on_selection_changed()
        self._canvas.update()

    def _confirm_select(self):
        """Zatwierdza wybrane punkty i zamyka okno."""
        labels = list(self._canvas._selected_labels)
        print(json.dumps({'selected_labels': labels, 'confirmed': True}), flush=True)
        self.close()

    def _on_selection_changed(self):
        count = len(self._canvas._selected_labels)
        self._sb.showMessage(f'Wybrano {count} punktów do analizy. Kliknij "Zatwierdź wybór", aby zakończyć.')
        self._panel._lbl_id.setText(str(count))
        self._panel._lbl_x.setText('wybranych')
        self._panel._lbl_y.setText('punktów')

    def keyPressEvent(self, e):
        if e.key() == self._fit_key:
            self._canvas.fit_view()

    # ── Checkbox handlers ─────────────────────────────────────────────────────
    def _on_toggle_beacons(self, checked: bool):
        """Włącza/wyłącza wyświetlanie odcisków radiowych na mapie."""
        self._canvas._show_fingerprints = checked
        self._canvas.update()

    def _on_toggle_live(self, checked: bool):
        """Włącza/wyłącza pozycjonowanie na żywo."""
        if checked:
            self._start_live()
        else:
            self._stop_live()

    def _start_live(self):
        """Uruchamia LiveThread."""
        if self._live_thread is not None:
            return
        self._live_thread = LiveThread(self)
        self._live_thread.position.connect(self.update_position)
        self._live_thread.status_msg.connect(self._on_live_status)
        self._live_thread.finished.connect(self._on_live_finished)
        self._live_thread.start()
        self._sb.showMessage('Uruchamianie pozycjonowania na żywo…')

    def _stop_live(self):
        """Zatrzymuje LiveThread."""
        if self._live_thread is None:
            return
        self._live_thread.requestInterruption()
        self._live_thread.wait(3000)
        self._live_thread = None
        # Wyczyść pozycję beacona
        self._canvas._bx = None
        self._canvas._by = None
        self._canvas._trail.clear()
        self._canvas.update()
        self._panel.refresh(0, 0, 0, 0, None, 0)
        self._sb.showMessage('Pozycjonowanie na żywo zatrzymane')

    def _on_live_status(self, msg: str):
        """Wyświetla statusy z LiveThread w status barze."""
        self._sb.showMessage(msg)

    def _on_live_finished(self):
        """Reakcja na zakończenie LiveThread (np. utrata połączenia)."""
        self._live_thread = None
        # Odznacz checkbox bez re-triggerowania sygnału
        self._panel._chk_live.blockSignals(True)
        self._panel._chk_live.setChecked(False)
        self._panel._chk_live.blockSignals(False)

    def closeEvent(self, event):
        """Zamyka LiveThread przed zamknięciem okna."""
        self._stop_live()
        super().closeEvent(event)

    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {C_BG.name()}; }}
            QStatusBar  {{ color: {C_MUTED.name()}; font-size: 11px; }}
        """)

    # ── Thread-safe API ───────────────────────────────────────────────────────
    def update_position(self, x_m: float, y_m: float,
                        beacon_id=None, confidence: float = 1.0):
        """Wywołaj z dowolnego wątku — bezpieczne dzięki sygnałom Qt."""
        self._sig_pos.emit(float(x_m), float(y_m), beacon_id, float(confidence))

    def _on_position(self, x_m: float, y_m: float, beacon_id, confidence: float):
        self._last_x = x_m
        self._last_y = y_m
        self._canvas.update_position(x_m, y_m, beacon_id, confidence)
        sx, sy = physical_to_svg(x_m, y_m)
        self._panel.refresh(x_m, y_m, sx, sy, beacon_id, confidence)
        status = (f'Beacon #{beacon_id}  |  '
                  f'X={x_m:.2f} m   Y={y_m:.2f} m  |  '
                  f'Pewność: {int(confidence*100)} %')
        self._sb.showMessage(status)

# ─────────────────────────────────────────────────────────────────────────────
# DEMO THREAD
# ─────────────────────────────────────────────────────────────────────────────
class DemoThread(QThread):
    """Symuluje beacon stojący w jednym miejscu — realistyczny szum WkNN.
    Odpowiada sytuacji: antena ESPAR jest włączona w jednym z pokoi,
    a algorytm WkNN estymuje pozycję z naturalnym rozrzutem ok. ±0.4m.
    """
    position = pyqtSignal(float, float, int, float)

    # Pozycja anteny ESPAR — pokój 707
    # Ctrl+klik na mapie (kartezjański, Y w górę):
    #   Poprzednio: x=27.26m, y=-4.46m (stary układ Y w dół)
    #   Teraz odwrócone Y: TRUE_Y = +4.46m
    TRUE_X    = 30.97  # (3119.5-22.0)/100
    TRUE_Y    = 10.49  # (1082.0-32.4)/100 - SVG Y w dol
    BEACON_ID = 28
    NOISE_STD = 0.35   # odchylenie standardowe szumu pozycji [m]

    def run(self):
        t = 0
        while not self.isInterruptionRequested():
            # Symulowany szum pomiaru WkNN (suma dwóch sinusoid ≠ biały szum,
            # ale wygląda bardziej realistycznie niż random)
            nx = self.NOISE_STD * (0.6 * math.sin(t * 0.11) +
                                   0.4 * math.sin(t * 0.31 + 1.2))
            ny = self.NOISE_STD * (0.6 * math.sin(t * 0.09 + 0.7) +
                                   0.4 * math.sin(t * 0.27 + 2.1))
            conf = 0.82 + 0.16 * abs(math.cos(t * 0.05))
            self.position.emit(
                self.TRUE_X + nx,
                self.TRUE_Y + ny,
                self.BEACON_ID,
                conf,
            )
            t += 1
            time.sleep(0.20)


# ─────────────────────────────────────────────────────────────────────────────
# LIVE THREAD — pozycjonowanie na żywo z serwera ESPAR
# ─────────────────────────────────────────────────────────────────────────────
class LiveThread(QThread):
    """Łączy się z serwerem ESPAR, zbiera ramki BLE i estymuje pozycję WkNN."""

    position = pyqtSignal(float, float, int, float)
    status_msg = pyqtSignal(str)

    WINDOW_SEC = 5.0     # czas okna zbierania danych
    BEACON_ID  = 28
    BLE_CHANNEL = 37

    def run(self):
        # Importy lokalne — moduły w tym samym katalogu
        from telnet_reader import get_espar_stream
        from wknn import load_radio_map, wknn_estimate
        from validate import load_optimal_k

        radio_map = load_radio_map()
        if not radio_map:
            self.status_msg.emit('Brak radio_map.json — najpierw wykonaj kalibrację')
            return

        k = load_optimal_k(default=3)
        self.status_msg.emit(f'Łączenie z {ESPAR_HOST}:{ESPAR_PORT}… (K={k})')

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(ESPAR_TIMEOUT)
            sock.connect((ESPAR_HOST, ESPAR_PORT))
        except Exception as e:
            self.status_msg.emit(f'Nie można połączyć: {e}')
            return

        self.status_msg.emit(f'Połączono — zbieram dane (okno {self.WINDOW_SEC}s, K={k})…')

        try:
            window_data: dict = {}
            window_start = time.time()

            for frame in get_espar_stream(sock):
                if self.isInterruptionRequested():
                    break

                # Filtruj: kanał 37 + prawidłowe konfiguracje ESPAR
                if frame['ble_channel'] != self.BLE_CHANNEL:
                    continue
                if frame['espar_char_int'] not in VALID_CHARS:
                    continue
                if frame['beacon_num'] != self.BEACON_ID:
                    continue

                bid = frame['beacon_num']
                char_key = str(frame['espar_char_int'])
                rssi = frame['rssi_dbm']

                b_data = window_data.setdefault(bid, {})
                b_data.setdefault(char_key, []).append(rssi)

                # Koniec okna — estymuj pozycję
                elapsed = time.time() - window_start
                if elapsed >= self.WINDOW_SEC:
                    result = wknn_estimate(window_data, radio_map,
                                           k=k, beacon_id=self.BEACON_ID)
                    if result is not None:
                        x_est, y_est, conf = result
                        self.position.emit(x_est, y_est, self.BEACON_ID, conf)
                        self.status_msg.emit(
                            f'Pozycja: X={x_est:.2f}m  Y={y_est:.2f}m  '
                            f'Pewność: {int(conf*100)}%  (K={k})'
                        )
                    else:
                        self.status_msg.emit('Za mało danych w oknie — czekam…')

                    window_data.clear()
                    window_start = time.time()
        except Exception as e:
            self.status_msg.emit(f'Błąd strumienia: {e}')
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self.status_msg.emit('Rozłączono z serwerem ESPAR')


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — integracja z silnikiem WkNN
# ─────────────────────────────────────────────────────────────────────────────
_app: QApplication | None = None
_win: MapWindow     | None = None


def launch_viewer(svg_path: str = SVG_PATH,
                  demo_mode: bool = False) -> MapWindow:
    """Uruchamia okno mapy w głównym wątku.
    Zwraca instancję MapWindow — wywołuj win.update_position(x, y, id, conf).
    UWAGA: QApplication musi działać w głównym wątku.
    """
    global _app, _win
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    _win = MapWindow(svg_path)
    _win.show()
    if demo_mode:
        demo = DemoThread(_win)
        demo.position.connect(_win.update_position)
        demo.start()
    return _win


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')

        # --pick-session : wybór lokalnego originu sesji pomiarowej
        if '--pick-session' in sys.argv:
            win = MapWindow(pick_mode=True)
            win.show()
            sys.exit(app.exec())

        # --mark-origin : jednorazowe wyznaczenie narożnika budynku (SVG origin)
        if '--mark-origin' in sys.argv:
            win = MapWindow(mark_origin_mode=True)
            win.show()
            sys.exit(app.exec())

        # --view : podgląd bazy punktów kalibracyjnych
        if '--view' in sys.argv:
            win = MapWindow(show_points=True)
            win.show()
            sys.exit(app.exec())

        # --select-points : graficzny wybór wielu punktów
        if '--select-points' in sys.argv:
            win = MapWindow(select_mode=True)
            win.show()
            sys.exit(app.exec())

        # --pick (legacy, zachowany dla kompatybilności)
        if '--pick' in sys.argv:
            win = MapWindow(pick_mode=True)
            win.show()
            sys.exit(app.exec())

        # Tryb demo
        win = MapWindow()
        win.show()
        demo = DemoThread(win)
        demo.position.connect(win.update_position)
        demo.start()
        ret = app.exec()
        demo.requestInterruption()
        demo.wait(2000)
        sys.exit(ret)

    except SystemExit:
        pass
    except Exception as e:
        print(f'[!] Błąd map_viewer: {e}', file=sys.stderr)
        sys.exit(0)
