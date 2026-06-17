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
    QPushButton, QStatusBar, QCheckBox, QProgressBar,
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

from espar_client import EsparClient
_temp_client = EsparClient()

# ── Połączenie z serwerem ESPAR (dla trybu live) ─────────────────────────────────
ESPAR_HOST  = _temp_client.host
ESPAR_PORT  = _temp_client.port
ESPAR_TIMEOUT = _temp_client.timeout
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

        # Tryb kalibracji wizualnej
        self._calibrate_mode = False
        self._calib_x = 0.0
        self._calib_y = 0.0
        self._calib_label = ''
        self._calib_beacon_id = 28
        self._radar_center_svg = QPointF(0.0, 0.0)
        self._radar_drag_active = False
        self._radar_radius_px = 75
        self._radar_rssi_data = {}  # {char_int: avg_rssi}

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

    def set_radar_data(self, data):
        self._radar_rssi_data = data
        self.update()

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

            if self._calibrate_mode:
                radar_pos = self._svg_to_widget(self._radar_center_svg.x(), self._radar_center_svg.y())
                dist = math.hypot(wx - radar_pos.x(), wy - radar_pos.y())
                if dist <= self._radar_radius_px:
                    self._radar_drag_active = True
                    self._radar_drag_offset = e.position() - radar_pos
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return

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
        if self._calibrate_mode and self._radar_drag_active:
            new_widget_pos = e.position() - self._radar_drag_offset
            r = self._render_rect()
            if r.width() > 0 and r.height() > 0:
                svg_x = ((new_widget_pos.x() - r.x()) / r.width()) * self._vb_w
                svg_y = ((new_widget_pos.y() - r.y()) / r.height()) * self._vb_h
                self._radar_center_svg = QPointF(svg_x, svg_y)
                self.update()
            return

        if self._drag_start is not None:
            d = e.position() - self._drag_start
            self._pan = self._pan_at_drag + d
            self._bg_pix = None
            self.update()

    def mouseReleaseEvent(self, e):
        if self._calibrate_mode and self._radar_drag_active:
            self._radar_drag_active = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_start = None
            if self._pick_mode or self._mark_origin_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self._select_mode:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._calibrate_mode:
                self.setCursor(Qt.CursorShape.ArrowCursor)
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

        # Rysuj zaplanowane punkty kalibracji siatkowej (szare kropki dla wszystkich odcisków)
        grid_data = getattr(self, '_grid_data', None)
        if grid_data and grid_data.get('points'):
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            
            # Zbierz wszystkie unikalne pozycje beaconów, żeby narysować siatkę punktów pomiarowych
            all_beacons = set()
            for pt in grid_data['points']:
                for b in pt.get('beacons', []):
                    all_beacons.add((b['x'], b['y']))
                    
            for bx, by in all_beacons:
                sx, sy = physical_to_svg(bx, by)
                wp = self._svg_to_widget(sx, sy)
                p.setBrush(QBrush(QColor('#64748b')))
                p.setPen(QPen(Qt.GlobalColor.white, 1))
                p.drawEllipse(wp, 4, 4)

            # Rysuj aktualny cel dla całego zestawu (środek statywu)
            curr_idx = getattr(self, '_grid_idx', -1)
            if curr_idx >= 0 and curr_idx < len(grid_data['points']):
                pt = grid_data['points'][curr_idx]
                if pt.get('beacons'):
                    bx_avg = sum(b['x'] for b in pt['beacons']) / len(pt['beacons'])
                    by_avg = sum(b['y'] for b in pt['beacons']) / len(pt['beacons'])
                    sx, sy = physical_to_svg(bx_avg, by_avg)
                    wp = self._svg_to_widget(sx, sy)
                    
                    # Pulsująca żółta otoczka i etykieta
                    p.setBrush(QBrush(QColor(234, 179, 8, int(60 + self._pulse * 0.5))))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(wp, 18, 18)
                    
                    p.setBrush(QBrush(QColor('#eab308')))
                    p.setPen(QPen(Qt.GlobalColor.white, 2))
                    p.drawEllipse(wp, 7, 7)
                    
                    p.setPen(QPen(QColor('#fef08a')))
                    p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
                    p.drawText(int(wp.x()) + 12, int(wp.y()) + 4, pt['label'])

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

        # Tryb CALIBRATE: rysuj pomarańczowy celownik celu i przeciągalny radar chart
        if self._calibrate_mode:
            radar_pos = self._svg_to_widget(self._radar_center_svg.x(), self._radar_center_svg.y())

            # Rysuj radar chart (najpierw, żeby nie zasłaniał celów)
            self._draw_radar_chart(p, radar_pos)

            # Rysuj cele (beacony w zestawie) na wierzchu
            for b in getattr(self, '_calib_beacons', []):
                target_svg_x = SVG_ORIGIN_X + b['x'] * SCALE
                target_svg_y = SVG_ORIGIN_Y + b['y'] * SCALE
                target_pos = self._svg_to_widget(target_svg_x, target_svg_y)

                # Rysuj celownik celu
                p.setPen(QPen(QColor('#f97316'), 2))
                p.setBrush(QBrush(QColor('#f97316')))
                p.drawEllipse(target_pos, 6, 6)
                
                # Rysuj linię pomocniczą łączącą cel z radarem
                pen = QPen(QColor('#f97316'), 1.5)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawLine(target_pos, radar_pos)

                # Etykieta celu
                lbl = f"#{b['id']}"
                p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
                p.setPen(QPen(QColor('#f97316')))
                p.drawText(int(target_pos.x()) + 10, int(target_pos.y()) + 4, lbl)

            # Etykieta globalna kalibracji nad radarem
            lbl = f"Kalibracja: {getattr(self, '_calib_label', '')}"
            p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            p.setPen(QPen(QColor('#f97316')))
            p.drawText(int(radar_pos.x()) - 50, int(radar_pos.y()) - self._radar_radius_px - 10, lbl)
            
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

    def _draw_radar_chart(self, p, center):
        R = self._radar_radius_px
        
        # Tło radaru (okrągłe ciemne menu z obwódką)
        p.setPen(QPen(QColor('#1e293b'), 2))
        p.setBrush(QBrush(QColor(15, 22, 35, 200)))
        p.drawEllipse(center, R, R)

        # Koncentryczne kręgi siatki (na poziomy -80 dBm i -60 dBm)
        grid_pens = QPen(QColor('#334155'), 1)
        grid_pens.setStyle(Qt.PenStyle.DotLine)
        p.setPen(grid_pens)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, R * 0.33, R * 0.33) # -80 dBm
        p.drawEllipse(center, R * 0.66, R * 0.66) # -60 dBm

        # Etykiety poziomów dBm na kręgach siatki
        p.setFont(QFont('Segoe UI', 6))
        p.setPen(QPen(QColor('#475569')))
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.33 - 2), "-80 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.66 - 2), "-60 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R - 2), "-40 dBm")
        
        # Linie radialne (co 30 stopni)
        for i in range(12):
            angle_rad = math.radians(i * 30 - 90)
            dx = R * math.cos(angle_rad)
            dy = R * math.sin(angle_rad)
            p.drawLine(center, center + QPointF(dx, dy))

        # Etykiety kątów
        p.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
        p.setPen(QPen(QColor('#94a3b8')))
        fm = p.fontMetrics()
        p.drawText(int(center.x() - fm.horizontalAdvance("0°")/2), int(center.y() - R + 10), "0°")
        p.drawText(int(center.x() + R - fm.horizontalAdvance("90°") - 5), int(center.y() + 4), "90°")
        p.drawText(int(center.x() - fm.horizontalAdvance("180°")/2), int(center.y() + R - 3), "180°")
        p.drawText(int(center.x() - R + 5), int(center.y() + 4), "270°")

        # Rysuj polygony RSSI dla wszystkich widocznych beaconów
        COLORS = [
            ('#f97316', QColor(249, 115, 22)),   # Pomarańczowy
            ('#3b82f6', QColor(59, 130, 246)),   # Niebieski
            ('#10b981', QColor(16, 185, 129)),   # Zielony
            ('#ec4899', QColor(236, 72, 153)),   # Różowy
            ('#8b5cf6', QColor(139, 92, 246))    # Fioletowy
        ]
        
        from rssi_analysis import CHAR_TO_DEG
        deg_to_char = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
        sorted_degs = sorted(deg_to_char.keys())
        
        radar_data_dict = getattr(self, '_radar_rssi_data', {})
        # Zapewnij kompatybilność, jeśli dane to dict z pojedynczego beacona vs pełny słownik beaconów
        if radar_data_dict and not any(isinstance(v, dict) for v in radar_data_dict.values()):
            radar_data_dict = {"28": radar_data_dict}
            
        bid_to_color_idx = {}
        for i, b in enumerate(getattr(self, '_calib_beacons', [])):
            bid_to_color_idx[b['id']] = i
            bid_to_color_idx[str(b['id'])] = i
            bid_to_color_idx[int(b['id'])] = i
            
        for bid_str, data_avg in radar_data_dict.items():
            try:
                bid = int(bid_str)
            except:
                continue
                
            if bid not in getattr(self, '_visible_radar_beacons', set()) and bid_str not in getattr(self, '_visible_radar_beacons', set()):
                continue
                
            idx = bid_to_color_idx.get(bid, bid % len(COLORS))
            c_hex, c_q = COLORS[idx % len(COLORS)]
            
            poly_points = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                rssi = data_avg.get(ch) if ch in data_avg else data_avg.get(str(ch), -100.0)
                # Clamp and normalize
                rssi_clamped = max(-100.0, min(-40.0, rssi))
                val_r = ((rssi_clamped - (-100.0)) / 60.0) * R
                
                angle_rad = math.radians(deg - 90)
                dx = val_r * math.cos(angle_rad)
                dy = val_r * math.sin(angle_rad)
                poly_points.append(center + QPointF(dx, dy))

            # Narysuj obszar i obwódkę
            if poly_points:
                poly = QPolygonF(poly_points)
                p.setPen(QPen(c_q, 2))
                c_fill = QColor(c_q)
                c_fill.setAlpha(70)
                p.setBrush(QBrush(c_fill))
                p.drawPolygon(poly)
                
                # Małe kropki na wierzchołkach i szacowanie kierunku
                p.setBrush(QBrush(c_q))
                p.setPen(Qt.PenStyle.NoPen)
                sum_x = 0.0
                sum_y = 0.0
                sum_r = 0.0
                for pt, deg in zip(poly_points, sorted_degs):
                    ch = deg_to_char[deg]
                    rssi = data_avg.get(ch) if ch in data_avg else data_avg.get(str(ch), -100.0)
                    r_val = ((rssi + 100.0) / 60.0) * R
                    p.drawEllipse(pt, 3, 3)
                    # Wektory do wyliczenia "środka ciężkości"
                    dx = pt.x() - center.x()
                    dy = pt.y() - center.y()
                    sum_x += dx * r_val
                    sum_y += dy * r_val
                    sum_r += r_val
                    
                # Rysuj estymowaną pozycję (kierunek środka ciężkości sygnału)
                if sum_r > 0:
                    est_angle = math.atan2(sum_y, sum_x)
                    p.setPen(QPen(c_q, 2, Qt.PenStyle.DashDotLine))
                    # Rysujemy dłuższą linię (1.5 promienia), aby odróżnić ją od wielokąta
                    p.drawLine(center, center + QPointF(math.cos(est_angle) * R * 1.5, math.sin(est_angle) * R * 1.5))


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
        try:
            if not hasattr(self, '_lbl_id') or self._lbl_id is None:
                return
            id_txt = f'#{beacon_id}' if beacon_id is not None else '—'
            self._lbl_id.setText(id_txt)
            self._lbl_x.setText(f'{x_m:.2f} m')
            self._lbl_y.setText(f'{y_m:.2f} m')
            pct = int(confidence * 100)
            self._lbl_conf.setText(f'{pct} %')
            bar_w = int((160) * confidence)
            self._conf_bar.setFixedWidth(bar_w)
            self._lbl_svg.setText(f'x={svg_x:.0f}\ny={svg_y:.0f}')
        except RuntimeError:
            pass

    def setup_calibration_mode(self, label, calib_beacons, target_packets=100):
        # Usuń stare widgety z układu bocznego panelu
        while self.layout().count():
            item = self.layout().takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                
        lay = self.layout()
        
        # Tytuł sekcji kalibracji
        title = QLabel('📡  ESPAR IPS')
        title.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        title.setStyleSheet(f'color: {C_ACCENT.name()};')
        lay.addWidget(title)
        lay.addSpacing(4)

        sub = QLabel('Tryb Kalibracji (Fingerprinting)')
        sub.setFont(QFont('Segoe UI', 8))
        sub.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(sub)

        lay.addSpacing(15)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        # Sekcja: Dane punktu pomiarowego
        lay.addWidget(self._section_label('AKTUALNY PUNKT'))
        self._lbl_calib_point = QLabel(f"{label}")
        self._lbl_calib_point.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._lbl_calib_point.setStyleSheet(f'color: {C_TEXT.name()};')
        self._lbl_calib_point.setWordWrap(True)
        lay.addWidget(self._lbl_calib_point)
        lay.addSpacing(8)

        self._lbl_calib_coords = QLabel(f"Liczba beaconów: {len(calib_beacons)}")
        self._lbl_calib_coords.setFont(QFont('JetBrains Mono', 11))
        self._lbl_calib_coords.setStyleSheet(f'color: {C_TEXT.name()};')
        lay.addWidget(self._lbl_calib_coords)
        lay.addSpacing(4)

        self._lbl_calib_beacon = QLabel(f"Widoczne radary:")
        self._lbl_calib_beacon.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        self._lbl_calib_beacon.setStyleSheet(f'color: {C_TEXT.name()};')
        lay.addWidget(self._lbl_calib_beacon)
        
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
        """
        self._radar_checkboxes = {}
        for b in calib_beacons:
            chk = QCheckBox(f"Beacon #{b['id']}")
            chk.setChecked(True)
            chk.setStyleSheet(chk_style)
            lay.addWidget(chk)
            self._radar_checkboxes[b['id']] = chk

        lay.addSpacing(15)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        # Sekcja: Postęp zbierania
        lay.addWidget(self._section_label('POSTĘP ZBIERANIA'))
        lay.addSpacing(6)
        self._lbl_progress = QLabel("Czekam na połączenie…")
        self._lbl_progress.setFont(QFont('Segoe UI', 9))
        self._lbl_progress.setStyleSheet(f'color: {C_TEXT.name()};')
        lay.addWidget(self._lbl_progress)
        lay.addSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C_PANEL2.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: {C_SUCCESS.name()};
                border-radius: 3px;
            }}
        """)
        lay.addWidget(self._progress_bar)

        lay.addSpacing(15)
        lay.addWidget(self._divider())
        lay.addSpacing(15)

        # Sekcja: Przyciski akcji
        lay.addWidget(self._section_label('AKCJE'))
        lay.addSpacing(8)

        self._btn_save_calib = QPushButton('Zapisz i zakończ')
        self._btn_save_calib.setEnabled(False)
        self._btn_save_calib.setStyleSheet(
            'QPushButton { background: #1e293b; color: #64748b; '
            'border: 1px solid #334155; border-radius: 5px; padding: 10px; font-size: 13px; font-weight: bold; }'
        )
        lay.addWidget(self._btn_save_calib)
        lay.addSpacing(8)

        self._btn_force_save = QPushButton('Zapisz teraz (wcześniej)')
        self._btn_force_save.setStyleSheet(f"""
            QPushButton {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 5px;
                padding: 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {C_BORDER.name()};
                border-color: {C_ACCENT.name()};
            }}
        """)
        lay.addWidget(self._btn_force_save)
        lay.addSpacing(8)

        self._btn_cancel_calib = QPushButton('Anuluj')
        self._btn_cancel_calib.setStyleSheet("""
            QPushButton {
                background: #991b1b;
                color: #fca5a5;
                border: 1px solid #7f1d1d;
                border-radius: 5px;
                padding: 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #b91c1c;
            }
        """)
        lay.addWidget(self._btn_cancel_calib)

        lay.addStretch()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class MapWindow(QMainWindow):
    """Główne okno wizualizacji systemu ESPAR IPS."""

    _sig_pos = pyqtSignal(float, float, object, float)

    def __init__(self, svg_path: str = SVG_PATH, pick_mode: bool = False,
                 show_points: bool = False, mark_origin_mode: bool = False,
                 select_mode: bool = False,
                 calibrate_mode: bool = False, calib_label: str = '',
                 calib_beacons: list = None,
                 calib_target_packets: int = 100,
                 grid_collect_mode: bool = False, grid_json_path: str = ''):
        super().__init__()
        
        self._grid_collect_mode = grid_collect_mode
        self._grid_json_path = grid_json_path
        self._grid_data = None
        self._grid_idx = 0
        self._collecting_active = True
        
        if self._grid_collect_mode:
            calibrate_mode = True
            if os.path.exists(self._grid_json_path):
                with open(self._grid_json_path, 'r', encoding='utf-8') as f:
                    self._grid_data = json.load(f)
                if self._grid_data and self._grid_data.get('points'):
                    pt = self._grid_data['points'][0]
                    calib_label = pt['label']
                    calib_beacons = pt['beacons']
                    calib_target_packets = self._grid_data.get('target_packets', 100)
                    self._collecting_active = False

        # Wczytaj istniejące punkty kalibracyjne do wyświetlenia
        existing_points = []
        if pick_mode or show_points or mark_origin_mode or select_mode:
            try:
                radio_path = os.path.join(_DATA_DIR, 'radio_map.json')
                if os.path.exists(radio_path):
                    with open(radio_path, encoding='utf-8') as f:
                        existing_points = json.load(f)
            except Exception as e:
                print(f"[!] Błąd wczytywania radio_map.json: {e}", file=sys.stderr)

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
        self._calibrate_mode   = calibrate_mode
        self._calib_label      = calib_label
        self._calib_beacons    = calib_beacons or [{"id": 28, "x": 0.0, "y": 0.0}]
        self._calib_target_packets = calib_target_packets
        self._calib_rssi_accum = {}

        if mark_origin_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz globalny narożnik budynku (0,0)')
        elif pick_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz lokalny origin sesji pomiarowej')
        elif show_points:
            self.setWindowTitle('ESPAR IPS — Baza Punktów Kalibracyjnych')
        elif select_mode:
            self.setWindowTitle('ESPAR IPS — Wybierz punkty kalibracyjne do analizy')
        elif calibrate_mode:
            self.setWindowTitle(f'ESPAR IPS — Wizualna Kalibracja: {calib_label}')
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
        msg = 'Oczekiwanie na dane pozycji…  |  Kółko myszy: zoom  |  Przeciągnij: przesuń  |  F: dopasuj'
        if pick_mode:
            msg = 'Kliknij na mapie miejsce gdzie stoi statyw  |  F: dopasuj  |  Scroll: zoom'
        elif calibrate_mode:
            msg = 'Zbieranie ramek…  |  Przeciągnij radar lewym klawiszem  |  F: dopasuj'
        self._sb.showMessage(msg)

        # Setup layout based on mode
        if self._calibrate_mode:
            self._panel.setup_calibration_mode(self._calib_label, self._calib_beacons, self._calib_target_packets)
            self._canvas._calibrate_mode = True
            self._canvas._calib_label = self._calib_label
            self._canvas._visible_radar_beacons = set()
            for b in self._calib_beacons:
                try:
                    self._canvas._visible_radar_beacons.add(int(b['id']))
                    self._canvas._visible_radar_beacons.add(str(b['id']))
                except ValueError:
                    self._canvas._visible_radar_beacons.add(b['id'])

            for bid, chk in self._panel._radar_checkboxes.items():
                # Używamy default argument 'b' aby poprawnie przekazać ID w pętli
                chk.toggled.connect(lambda checked, b=bid: self._on_toggle_radar_beacon(b, checked))

            if self._calib_beacons:
                first_b = self._calib_beacons[0]
                target_svg_x = SVG_ORIGIN_X + first_b["x"] * SCALE
                target_svg_y = SVG_ORIGIN_Y + first_b["y"] * SCALE
                self._canvas._radar_center_svg = QPointF(target_svg_x, target_svg_y)

            # Podłącz przyciski tylko w trybie NIE-grid (grid robi to w sekcji poniżej)
            if not self._grid_collect_mode:
                self._panel._btn_save_calib.clicked.connect(self._save_and_exit)
                self._panel._btn_force_save.clicked.connect(self._force_save)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
        elif pick_mode or mark_origin_mode:
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
        import time
        self._last_radar_update = 0.0
        self._last_ui_update = 0.0

        if self._calibrate_mode:
            # Ustaw tryb kalibracji na panelu i płótnie
            self._panel.setup_calibration_mode(self._calib_label, self._calib_beacons, self._calib_target_packets)
            self._canvas._calibrate_mode = True
            self._canvas._calib_beacons = self._calib_beacons
            self._canvas._calib_label = self._calib_label
            self._canvas._calib_target_packets = self._calib_target_packets
            
            # Use the first beacon to set the initial radar position
            if self._calib_beacons:
                sx, sy = physical_to_svg(self._calib_beacons[0]['x'], self._calib_beacons[0]['y'])
            else:
                sx, sy = physical_to_svg(0.0, 0.0)
            self._canvas._radar_center_svg = QPointF(sx, sy)

            # Inicjalizacja widoczności beaconów
            self._canvas._visible_radar_beacons = set()
            for b in self._calib_beacons:
                try:
                    self._canvas._visible_radar_beacons.add(int(b['id']))
                    self._canvas._visible_radar_beacons.add(str(b['id']))
                except ValueError:
                    self._canvas._visible_radar_beacons.add(b['id'])
            for bid, chk in self._panel._radar_checkboxes.items():
                chk.stateChanged.connect(lambda state, b=bid: self._on_radar_vis_toggled(b, state))

            # Podłącz przyciski kalibracji
            if getattr(self, '_grid_collect_mode', False):
                self._panel._btn_save_calib.clicked.connect(self._save_grid_point)
                self._panel._btn_force_save.clicked.connect(self._save_grid_point)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
                self._load_grid_point(0)
                self._start_live()
            else:
                self._panel._btn_save_calib.clicked.connect(self._save_and_exit)
                self._panel._btn_force_save.clicked.connect(self._force_save)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
                # Automatycznie uruchom zbieranie
                self._start_live()
        else:
            # Podłącz checkboxy
            self._panel._chk_beacons.toggled.connect(self._on_toggle_beacons)
            self._panel._chk_live.toggled.connect(self._on_toggle_live)

    def _on_toggle_radar_beacon(self, bid, checked):
        if checked:
            self._canvas._visible_radar_beacons.add(bid)
        else:
            self._canvas._visible_radar_beacons.discard(bid)
        self._canvas.update()

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

    def _on_frame_received(self, beacon_id: int, char_int: int, rssi: float):
        if not getattr(self, '_collecting_active', True):
            return
        if not self._calibrate_mode:
            return

        bid_str = str(beacon_id)
        b_data = self._calib_rssi_accum.setdefault(bid_str, {})
        b_data.setdefault(char_int, []).append(rssi)

        target_bids = [str(b['id']) for b in self._calib_beacons]
        if bid_str not in target_bids:
            return

        # Szybka ocena postępu bez ciężkich kalkulacji i aktualizacji GUI
        target_pkts = self._calib_target_packets
        num_beacons = len(self._calib_beacons)
        total_target = target_pkts * num_beacons
        
        total_collected = 0
        done_beacons = 0
        for b_str in target_bids:
            b_acc = self._calib_rssi_accum.get(b_str, {})
            c = sum(len(b_acc.get(ch, [])) for ch in VALID_CHARS)
            total_collected += min(target_pkts, c)
            if c >= target_pkts:
                done_beacons += 1

        is_done = (done_beacons >= num_beacons)

        import time
        now = time.time()
        # Aktualizujemy interfejs i wykres maksymalnie co 100 ms, chyba że zbieranie się zakończyło
        if not is_done and (now - getattr(self, '_last_ui_update', 0.0) < 0.1):
            return
        self._last_ui_update = now

        radar_data = {}
        for b_str in target_bids:
            radar_averages = {}
            b_accum = self._calib_rssi_accum.get(b_str, {})
            for ch in VALID_CHARS:
                vals = b_accum.get(ch, [])
                radar_averages[ch] = sum(vals) / len(vals) if vals else -100.0
            radar_data[b_str] = radar_averages
        
        self._canvas.set_radar_data(radar_data)
        
        progress_val = int((total_collected / total_target) * 100) if total_target > 0 else 0
        self._panel._progress_bar.setValue(progress_val)
        
        self._panel._lbl_progress.setText(
            f"Zebrano: {total_collected}/{total_target} pakietów\n"
            f"({done_beacons}/{num_beacons} beaconów gotowe)"
        )

        if is_done:
            self._panel._btn_save_calib.setEnabled(True)
            self._panel._btn_save_calib.setStyleSheet(
                'QPushButton { background: #166534; color: #86efac; '
                'border: 1px solid #22c55e; border-radius: 5px; padding: 10px; font-size: 13px; font-weight: bold; }'
                'QPushButton:hover { background: #15803d; }'
            )
            self._panel._lbl_progress.setText(
                self._panel._lbl_progress.text() + "\n✅ Gotowe! Wciśnij Zapisz."
            )

    def _save_and_exit(self):
        """Oblicza średnie i znormalizowane wartości RSSI dla wszystkich odebranych beaconów,
        wypisuje wynik jako JSON na standardowe wyjście (stdout) i zamyka okno.
        """
        result = {}
        target_pkts = self._calib_target_packets
        target_bids = [str(b['id']) for b in self._calib_beacons]
        for bid_str, chars_data in self._calib_rssi_accum.items():
            if bid_str not in target_bids:
                continue
            avg = {}
            for ch, values in chars_data.items():
                if not values:
                    continue
                trimmed = values[:target_pkts]
                avg[str(ch)] = round(sum(trimmed) / len(trimmed), 2)
            
            if not avg:
                continue
                
            mn, mx = min(avg.values()), max(avg.values())
            if mx > mn:
                norm = {ch: round((v - mn) / (mx - mn), 4) for ch, v in avg.items()}
            else:
                norm = {ch: 0.0 for ch in avg}
                
            result[bid_str] = {
                "avg": avg,
                "norm": norm
            }

        print(json.dumps(result), flush=True)
        self.close()

    def _force_save(self):
        """Wymusza zapisanie aktualnie zebranych danych, nawet jeśli nie ma kompletu."""
        if not self._calib_rssi_accum:
            self._sb.showMessage("Brak zebranych danych! Nie można zapisać.")
            return
        self._save_and_exit()

    def _start_collect_current_point(self):
        self._calib_rssi_accum = {}
        self._canvas._radar_rssi_data = {}
        self._canvas.set_radar_data({})
        self._collecting_active = True
        self._panel._btn_start_collect.setEnabled(False)
        self._panel._btn_start_collect.setText("Zbieranie w toku...")
        self._panel._lbl_progress.setText("Trwa zbieranie danych...")

        if self._live_thread is None or not self._live_thread.isRunning():
            self._sb.showMessage("Wznawianie połączenia z ESPAR...")
            self._start_live()

    def _skip_grid_point(self):
        next_idx = self._grid_idx + 1
        if next_idx < len(self._grid_data['points']):
            self._load_grid_point(next_idx)
        else:
            self.close()

    def _go_to_previous_point(self):
        if self._grid_idx <= 0:
            return
            
        prev_idx = self._grid_idx - 1
        prev_pt = self._grid_data['points'][prev_idx]
        prev_label = prev_pt['label']
        
        import os, sys
        sys.path.append(os.path.dirname(__file__))
        try:
            from wknn import load_radio_map, save_radio_map
            existing_db = load_radio_map()
        except ImportError:
            existing_db = []
            
        if existing_db:
            new_db = [pt for pt in existing_db if pt.get("label") != prev_label]
            removed_count = len(existing_db) - len(new_db)
            if removed_count > 0:
                print(f"  [Cofanie] Usunięto {removed_count} wpisów dla punktu '{prev_label}' z radio_map.json")
                try:
                    save_radio_map(new_db)
                except Exception as e:
                    print(f"  [!] Błąd zapisu po cofnięciu: {e}")
                    
        self._load_grid_point(prev_idx)
        self._sb.showMessage(f"Cofnięto do punktu {prev_label}. Stare dane usunięte.")

    def _save_grid_point(self):
        # calculate normalized RSSI
        result = {}
        target_pkts = self._calib_target_packets
        target_bids = [str(b['id']) for b in self._calib_beacons]
        for bid_str, chars_data in self._calib_rssi_accum.items():
            if bid_str not in target_bids:
                continue
            avg = {}
            for ch, values in chars_data.items():
                if not values:
                    continue
                trimmed = values[:target_pkts]
                avg[str(ch)] = round(sum(trimmed) / len(trimmed), 2)
            if not avg:
                continue
            mn, mx = min(avg.values()), max(avg.values())
            if mx > mn:
                norm = {ch: round((v - mn) / (mx - mn), 4) for ch, v in avg.items()}
            else:
                norm = {ch: 0.0 for ch in avg}
            result[bid_str] = {"avg": avg, "norm": norm}
            
        if not result:
            self._sb.showMessage("Brak danych do zapisu!")
            return

        import os, sys, datetime
        sys.path.append(os.path.dirname(__file__))
        try:
            from wknn import load_radio_map, save_radio_map
            existing_db = load_radio_map()
        except ImportError:
            existing_db = []

        pt_info = self._grid_data['points'][self._grid_idx]
        for bid_str, stats in result.items():
            bid = int(bid_str)
            b_global_x, b_global_y = 0.0, 0.0
            for b in self._calib_beacons:
                if b['id'] == bid:
                    b_global_x = b['x']
                    b_global_y = b['y']
                    break
            pt = {
                "label": self._calib_label,
                "x_local": pt_info['x_local'],
                "y_local": pt_info['y_local'],
                "origin_label": self._grid_data["origin_label"],
                "beacon_id": bid,
                "x_m": b_global_x,
                "y_m": b_global_y,
                "average_rssi": stats["avg"],
                "normalized_rssi": stats["norm"],
                "timestamp": datetime.datetime.now().isoformat()
            }
            # Upsert — nadpisz istniejący punkt o tych samych współrzędnych i beacon_id
            replaced = False
            for idx_e, existing_pt in enumerate(existing_db):
                if (existing_pt.get("beacon_id") == bid
                        and existing_pt.get("x_m") == b_global_x
                        and existing_pt.get("y_m") == b_global_y):
                    existing_db[idx_e] = pt
                    replaced = True
                    break
            if not replaced:
                existing_db.append(pt)
            
        try:
            from wknn import save_radio_map
            save_radio_map(existing_db)
        except ImportError:
            pass
            
        self._sb.showMessage(f"Zapisano punkt {self._calib_label}.")
        self._skip_grid_point()

    def _load_grid_point(self, idx):
        if not self._grid_data or idx >= len(self._grid_data['points']):
            return False
            
        self._grid_idx = idx
        pt = self._grid_data['points'][idx]
        self._calib_label = pt['label']
        self._calib_beacons = pt['beacons']
        self._calib_target_packets = self._grid_data.get('target_packets', 100)
        
        self._calib_rssi_accum = {}
        self._canvas._radar_rssi_data = {}
        self._canvas.set_radar_data({})
        
        from PyQt6.QtWidgets import QPushButton
        lay = self._panel.layout()
        
        if not hasattr(self._panel, '_btn_skip_calib'):
            self._panel._btn_skip_calib = QPushButton("Pomiń punkt")
            self._panel._btn_skip_calib.setStyleSheet("""
                QPushButton { background: #334155; color: #94a3b8; border: 1px solid #475569; border-radius: 5px; padding: 10px; font-weight: bold; }
                QPushButton:hover { background: #475569; color: #e2e8f0; }
            """)
            self._panel._btn_skip_calib.clicked.connect(self._skip_grid_point)
            idx_save = lay.indexOf(self._panel._btn_save_calib)
            lay.insertWidget(idx_save + 1, self._panel._btn_skip_calib)

        if not hasattr(self._panel, '_btn_prev_calib'):
            self._panel._btn_prev_calib = QPushButton("Poprzedni (Cofnij)")
            self._panel._btn_prev_calib.setStyleSheet("""
                QPushButton { background: #3f2c2c; color: #f87171; border: 1px solid #7f1d1d; border-radius: 5px; padding: 10px; font-weight: bold; }
                QPushButton:hover { background: #7f1d1d; color: #fecaca; }
                QPushButton:disabled { background: #1e293b; color: #4b5563; border: 1px solid #334155; }
            """)
            self._panel._btn_prev_calib.clicked.connect(self._go_to_previous_point)
            idx_save = lay.indexOf(self._panel._btn_save_calib)
            lay.insertWidget(idx_save + 1, self._panel._btn_prev_calib)

        self._panel._btn_prev_calib.setEnabled(idx > 0)

        if not hasattr(self._panel, '_btn_start_collect'):
            self._panel._btn_start_collect = QPushButton("Rozpocznij zbieranie dla tej pozycji")
            self._panel._btn_start_collect.setStyleSheet("""
                QPushButton { background: #2563eb; color: white; border: 1px solid #3b82f6; border-radius: 5px; padding: 10px; font-weight: bold; }
                QPushButton:hover { background: #1d4ed8; }
            """)
            self._panel._btn_start_collect.clicked.connect(self._start_collect_current_point)
            idx_save = lay.indexOf(self._panel._btn_save_calib)
            lay.insertWidget(idx_save, self._panel._btn_start_collect)

        self._collecting_active = False
        self._panel._btn_start_collect.setEnabled(True)
        self._panel._btn_start_collect.setText("Rozpocznij zbieranie dla tej pozycji")
        self._panel._lbl_progress.setText(f"Czekam na start...\nPunkt {idx+1}/{len(self._grid_data['points'])}: {self._calib_label}")
        self._panel._progress_bar.setValue(0)
        self._canvas._grid_idx = idx
        
        self._panel._btn_save_calib.setText("Zapisz i idź dalej")
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._btn_save_calib.setStyleSheet(
            'QPushButton { background: #1e293b; color: #64748b; '
            'border: 1px solid #334155; border-radius: 5px; padding: 10px; font-weight: bold; }'
        )

        self._canvas._calibrate_mode = True
        self._canvas._calib_beacons = self._calib_beacons
        self._canvas._calib_label = self._calib_label
        self._canvas._calib_target_packets = self._calib_target_packets
        self._canvas._grid_data = self._grid_data
        
        # Ustaw początkowe położenie radaru tylko wtedy, gdy nie zostało jeszcze ustawione (jest równe (0,0))
        if self._canvas._radar_center_svg.isNull() or (self._canvas._radar_center_svg.x() == 0.0 and self._canvas._radar_center_svg.y() == 0.0):
            if self._calib_beacons:
                sx, sy = physical_to_svg(self._calib_beacons[0]['x'], self._calib_beacons[0]['y'])
            else:
                sx, sy = physical_to_svg(0.0, 0.0)
            self._canvas._radar_center_svg = QPointF(sx, sy)
        self._canvas._visible_radar_beacons = set()
        for b in self._calib_beacons:
            try:
                self._canvas._visible_radar_beacons.add(int(b['id']))
                self._canvas._visible_radar_beacons.add(str(b['id']))
            except ValueError:
                self._canvas._visible_radar_beacons.add(b['id'])
        
        self._canvas.update()
        return True

    def _on_radar_vis_toggled(self, bid: int, state: int):
        try:
            bid_int = int(bid)
        except ValueError:
            bid_int = bid
        if state == Qt.CheckState.Checked.value:
            self._canvas._visible_radar_beacons.add(bid_int)
            self._canvas._visible_radar_beacons.add(str(bid_int))
        else:
            self._canvas._visible_radar_beacons.discard(bid_int)
            self._canvas._visible_radar_beacons.discard(str(bid_int))
        self._canvas.update()

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
        if self._calibrate_mode:
            self._live_thread.calibrate_mode = True
            self._live_thread.frame_received.connect(self._on_frame_received)
        else:
            self._live_thread.position.connect(self.update_position)
        self._live_thread.status_msg.connect(self._on_live_status)
        self._live_thread.finished.connect(self._on_live_finished)
        self._live_thread.start()
        if self._calibrate_mode:
            self._sb.showMessage('Uruchamianie strumienia kalibracji…')
        else:
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
        if hasattr(self._panel, '_chk_live') and self._panel._chk_live is not None:
            try:
                self._panel._chk_live.blockSignals(True)
                self._panel._chk_live.setChecked(False)
                self._panel._chk_live.blockSignals(False)
            except RuntimeError:
                pass

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
    frame_received = pyqtSignal(int, int, float)  # (beacon_id, char_int, rssi)

    WINDOW_SEC = 5.0     # czas okna zbierania danych
    BEACON_ID  = 28
    BLE_CHANNEL = 37

    def run(self):
        # Importy lokalne — moduły w tym samym katalogu
        from telnet_reader import get_espar_stream
        from wknn import load_radio_map, wknn_estimate
        from validate import load_optimal_k
        from espar_client import EsparClient

        is_calib = getattr(self, 'calibrate_mode', False)

        radio_map = None
        if not is_calib:
            radio_map = load_radio_map()
            if not radio_map:
                self.status_msg.emit('Brak radio_map.json — najpierw wykonaj kalibrację')
                return

        k = load_optimal_k(default=3)
        client = EsparClient(host=ESPAR_HOST, port=ESPAR_PORT, timeout=ESPAR_TIMEOUT)
        self.status_msg.emit(f'Łączenie z {client.host}:{client.port}…' + (f' (K={k})' if not is_calib else ''))

        sock = client.connect_and_start()
        if sock is None:
            self.status_msg.emit(f'Nie można połączyć z {client.host}:{client.port}')
            return

        # Usuń timeout połączeniowy — recv() ma czekać na dane bez limitu
        sock.settimeout(None)

        if is_calib:
            self.status_msg.emit('Połączono — zbieranie danych kalibracyjnych…')
        else:
            self.status_msg.emit(f'Połączono — zbieram dane (okno {self.WINDOW_SEC}s, K={k})…')

        try:
            window_data: dict = {}
            window_start = time.time()

            for frame in get_espar_stream(sock):
                if self.isInterruptionRequested():
                    break

                # Filtruj kanał 37 tylko w trybie pozycjonowania (nie-kalibracji).
                # W trybie kalibracji przyjmujemy wszystkie kanały advertising (37, 38, 39),
                # aby przyspieszyć zbieranie danych 3x.
                if not is_calib and frame['ble_channel'] != self.BLE_CHANNEL:
                    continue
                if frame['espar_char_int'] not in VALID_CHARS:
                    continue
                
                # W trybie kalibracji nie odrzucamy innych beaconów (wielobeaconowy statyw)
                if not is_calib:
                    if frame['beacon_num'] != self.BEACON_ID:
                        continue

                bid = frame['beacon_num']
                char_key = str(frame['espar_char_int'])
                rssi = frame['rssi_dbm']

                # Emituj odebrany pakiet na żywo
                self.frame_received.emit(bid, frame['espar_char_int'], float(rssi))

                if not is_calib:
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
            client.stop_and_close(sock)
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

        # --calibrate <label> <beacons_json> [target_packets]
        if '--calibrate' in sys.argv:
            idx = sys.argv.index('--calibrate')
            label = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else 'punkt'
            b_json = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else '[{"id": 28, "x": 0.0, "y": 0.0}]'
            target_pkts = int(sys.argv[idx + 3]) if idx + 3 < len(sys.argv) else 100
            try:
                beacons = json.loads(b_json)
            except Exception:
                beacons = [{"id": 28, "x": 0.0, "y": 0.0}]
            win = MapWindow(calibrate_mode=True, calib_label=label, calib_beacons=beacons, calib_target_packets=target_pkts)
            win.show()
            sys.exit(app.exec())

        # --grid_collect <json_path>
        if '--grid_collect' in sys.argv:
            idx = sys.argv.index('--grid_collect')
            json_path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ''
            win = MapWindow(grid_collect_mode=True, grid_json_path=json_path)
            win.show()
            sys.exit(app.exec())

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
