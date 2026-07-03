"""
canvas.py — Widget mapy SVG z nawigacją i rysowaniem pozycji beaconów.

Klasa MapCanvas renderuje plik SVG budynku, obsługuje:
    - Zoom kółkiem myszy i przesuwanie przeciąganiem
    - Rysowanie pozycji beacona z animowaną pulsacją
    - Wyświetlanie śladu ruchu (trail)
    - Rysowanie punktów kalibracyjnych i testowych
    - Tryb pick (wybór pozycji myszką)
    - Tryb kalibracji z radarem wizualnym (radar chart)
    - Rysowanie siatki punktów dla zbierania gridowego
"""

import math

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient,
    QPixmap, QPolygonF,
)

from gui.styles import (
    C_BG, C_PANEL, C_ACCENT, C_DOT, C_TRAIL, C_TEXT,
    SVG_ORIGIN_X, SVG_ORIGIN_Y, SCALE,
    physical_to_svg, svg_to_physical,
)
from config import VALID_CHARS, CHAR_TO_DEG


class MapCanvas(QWidget):
    """Widżet z mapą SVG i animowaną kropką beacona."""

    position_picked = pyqtSignal(float, float)

    def __init__(self, svg_path: str, pick_mode: bool = False,
                 mark_origin_mode: bool = False, select_mode: bool = False,
                 test_collect_mode: bool = False,
                 existing_points=None, session_origin=None, parent=None):
        super().__init__(parent)
        self._existing_points = existing_points or []
        self._test_points = []
        self._session_origin  = session_origin   # (x_m, y_m) lub None
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._pick_mode        = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._select_mode      = select_mode
        self._test_collect_mode = test_collect_mode
        self._selected_labels  = set()
        if pick_mode or mark_origin_mode or test_collect_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
            if mark_origin_mode:
                tip = 'Kliknij narożnik budynku (globalny 0,0)'
            elif pick_mode:
                tip = 'Kliknij miejsce gdzie stoi statyw / lokalny origin'
            else:
                tip = 'Kliknij miejsce, aby zaznaczyć prawdziwe położenie punktu testowego'
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

        # Pozycja beacona (w jednostkach SVG)
        self._bx: float | None = None
        self._by: float | None = None
        self._bid: int | None  = None
        self._conf: float      = 1.0
        self._trail: list[tuple[float, float]] = []
        self._MAX_TRAIL = 50

        # Animacja pulsacji
        self._pulse  = 0.0
        self._p_dir  = 1.0
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

        # Cache tła SVG
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

    # ── Geometria renderowania ────────────────────────────────────────────────

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

    # ── Obsługa myszy i kółka ─────────────────────────────────────────────────

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

            # Tryb pick / mark_origin / test_collect
            if (self._pick_mode or self._mark_origin_mode or self._test_collect_mode) and r.width() > 0:
                svg_x = (wx - r.x()) / r.width()  * self._vb_w
                svg_y = (wy - r.y()) / r.height() * self._vb_h
                self._picked_svg_x = svg_x
                self._picked_svg_y = svg_y
                if self._mark_origin_mode:
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

            # Ctrl+klik → wypisz współrzędne SVG i fizyczne (debug)
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
            if self._pick_mode or self._mark_origin_mode or self._test_collect_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self._select_mode:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._calibrate_mode:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

    def resizeEvent(self, _):
        self._bg_pix = None   # invalidate on resize

    # ── Animacja pulsacji ─────────────────────────────────────────────────────

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

    # ── Rysowanie (paintEvent) ────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Tło
        p.fillRect(self.rect(), C_BG)

        # Mapa SVG (cache jako pixmap)
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

        # Punkty kalibracyjne (niebieskie / zielone jeśli wybrane)
        self._draw_calibration_points(p)

        # Punkty testowe (fioletowe)
        self._draw_test_points(p)

        # Siatka zbierania gridowego
        self._draw_grid_points(p)

        # Origin sesji (żółty krzyżyk)
        self._draw_session_origin(p)

        # Tryb PICK / TEST_COLLECT: zielony celownik
        if self._pick_mode or self._test_collect_mode:
            if self._picked_svg_x is not None:
                self._draw_crosshair(p)
            p.end()
            return

        # Tryb CALIBRATE: radar chart + cele
        if self._calibrate_mode:
            self._draw_calibration_overlay(p)
            p.end()
            return

        # Brak pozycji beacona
        if self._bx is None:
            p.end()
            return

        # Pozycja beacona z animacją
        self._draw_beacon_position(p)

        p.end()

    # ── Metody rysowania (wydzielone z paintEvent) ────────────────────────────

    def _draw_calibration_points(self, p: QPainter):
        """Rysuje istniejące punkty kalibracyjne na mapie."""
        if not self._show_fingerprints or not self._existing_points:
            return
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for pt in self._existing_points:
            x_m, y_m = pt.get('x_m'), pt.get('y_m')
            lbl = pt.get('label', '')
            if x_m is None or y_m is None:
                continue
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

    def _draw_test_points(self, p: QPainter):
        """Rysuje istniejące punkty testowe (fioletowe)."""
        if not self._show_fingerprints or not self._test_points:
            return
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for pt in self._test_points:
            x_m, y_m = pt.get('x_true'), pt.get('y_true')
            lbl = pt.get('label', '')
            if x_m is None or y_m is None:
                continue
            sx, sy = physical_to_svg(x_m, y_m)
            wp = self._svg_to_widget(sx, sy)
            p.setBrush(QBrush(QColor('#c084fc')))
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.drawEllipse(wp, 5, 5)
            p.setPen(QPen(QColor('#e9d5ff')))
            p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
            p.drawText(int(wp.x()) + 8, int(wp.y()) + 4, lbl)

    def _draw_grid_points(self, p: QPainter):
        """Rysuje siatkę punktów zbierania gridowego."""
        grid_data = getattr(self, '_grid_data', None)
        if not grid_data or not grid_data.get('points'):
            return
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Pozycje beaconów (szare kropki)
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

        # Aktualny cel (pulsujący żółty)
        curr_idx = getattr(self, '_grid_idx', -1)
        if 0 <= curr_idx < len(grid_data['points']):
            pt = grid_data['points'][curr_idx]
            if pt.get('beacons'):
                bx_avg = sum(b['x'] for b in pt['beacons']) / len(pt['beacons'])
                by_avg = sum(b['y'] for b in pt['beacons']) / len(pt['beacons'])
                sx, sy = physical_to_svg(bx_avg, by_avg)
                wp = self._svg_to_widget(sx, sy)

                p.setBrush(QBrush(QColor(234, 179, 8, int(60 + self._pulse * 0.5))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(wp, 18, 18)

                p.setBrush(QBrush(QColor('#eab308')))
                p.setPen(QPen(Qt.GlobalColor.white, 2))
                p.drawEllipse(wp, 7, 7)

                p.setPen(QPen(QColor('#fef08a')))
                p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
                p.drawText(int(wp.x()) + 12, int(wp.y()) + 4, pt['label'])

    def _draw_session_origin(self, p: QPainter):
        """Rysuje origin aktualnej sesji (żółty krzyżyk)."""
        if self._session_origin is None:
            return
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

    def _draw_crosshair(self, p: QPainter):
        """Rysuje zielony celownik w wybranym miejscu (pick/test_collect)."""
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

    def _draw_calibration_overlay(self, p: QPainter):
        """Rysuje overlay kalibracji: radar chart + cele beaconów."""
        radar_pos = self._svg_to_widget(
            self._radar_center_svg.x(), self._radar_center_svg.y()
        )

        # Radar chart
        self._draw_radar_chart(p, radar_pos)

        # Cele beaconów (pomarańczowe)
        for b in getattr(self, '_calib_beacons', []):
            target_svg_x = SVG_ORIGIN_X + b['x'] * SCALE
            target_svg_y = SVG_ORIGIN_Y + b['y'] * SCALE
            target_pos = self._svg_to_widget(target_svg_x, target_svg_y)

            p.setPen(QPen(QColor('#f97316'), 2))
            p.setBrush(QBrush(QColor('#f97316')))
            p.drawEllipse(target_pos, 6, 6)

            # Linia łącząca cel z radarem
            pen = QPen(QColor('#f97316'), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(target_pos, radar_pos)

            # Etykieta celu
            lbl = f"#{b['id']}"
            p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
            p.setPen(QPen(QColor('#f97316')))
            p.drawText(int(target_pos.x()) + 10, int(target_pos.y()) + 4, lbl)

        # Etykieta kalibracji nad radarem
        lbl = f"Kalibracja: {getattr(self, '_calib_label', '')}"
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        p.setPen(QPen(QColor('#f97316')))
        p.drawText(int(radar_pos.x()) - 50, int(radar_pos.y()) - self._radar_radius_px - 10, lbl)

    def _draw_beacon_position(self, p: QPainter):
        """Rysuje pozycję beacona z animowaną pulsacją i śladem."""
        dot_r  = self._dot_r()
        centre = self._svg_to_widget(self._bx, self._by)

        # Ślad (trail)
        n = len(self._trail)
        for i, (tx, ty) in enumerate(self._trail):
            tp    = self._svg_to_widget(tx, ty)
            alpha = int(30 + 150 * (i + 1) / max(n, 1))
            tr    = max(2.0, dot_r * 0.45 * (i + 1) / max(n, 1))
            tc    = QColor(C_TRAIL); tc.setAlpha(alpha)
            p.setBrush(QBrush(tc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(tp, tr, tr)

        # Poświata
        glow = QRadialGradient(centre, dot_r * 3)
        gc   = QColor(C_DOT); gc.setAlpha(70)
        glow.setColorAt(0, gc); glow.setColorAt(1, Qt.GlobalColor.transparent)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centre, dot_r * 3, dot_r * 3)

        # Pulsujący pierścień
        ring_r = dot_r + self._pulse
        alpha  = max(0, int(220 * (1 - self._pulse / 28)))
        rc     = QColor(C_DOT); rc.setAlpha(alpha)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rc, 2.0))
        p.drawEllipse(centre, ring_r, ring_r)

        # Główna kropka
        p.setBrush(QBrush(C_DOT))
        p.setPen(QPen(Qt.GlobalColor.white, max(1.5, dot_r * 0.18)))
        p.drawEllipse(centre, dot_r, dot_r)

        # Etykieta beacona (bąbelek)
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

    def _draw_radar_chart(self, p: QPainter, center: QPointF):
        """Rysuje radar chart z danymi RSSI per kierunek anteny."""
        R = self._radar_radius_px

        # Tło radaru
        p.setPen(QPen(QColor('#1e293b'), 2))
        p.setBrush(QBrush(QColor(15, 22, 35, 200)))
        p.drawEllipse(center, R, R)

        # Koncentryczne kręgi siatki
        grid_pen = QPen(QColor('#334155'), 1)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(grid_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, R * 0.33, R * 0.33)  # -80 dBm
        p.drawEllipse(center, R * 0.66, R * 0.66)  # -60 dBm

        # Etykiety poziomów dBm
        p.setFont(QFont('Segoe UI', 6))
        p.setPen(QPen(QColor('#475569')))
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.33 - 2), "-80 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.66 - 2), "-60 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R - 2), "-40 dBm")

        # Linie radialne (co 30°)
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

        # Polygony RSSI per beacon
        COLORS = [
            ('#f97316', QColor(249, 115, 22)),   # Pomarańczowy
            ('#3b82f6', QColor(59, 130, 246)),    # Niebieski
            ('#10b981', QColor(16, 185, 129)),    # Zielony
            ('#ec4899', QColor(236, 72, 153)),    # Różowy
            ('#8b5cf6', QColor(139, 92, 246)),    # Fioletowy
        ]

        deg_to_char = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
        sorted_degs = sorted(deg_to_char.keys())

        radar_data_dict = getattr(self, '_radar_rssi_data', {})
        # Kompatybilność: dict z pojedynczego beacona vs pełny słownik beaconów
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
            except (ValueError, TypeError):
                continue

            visible_beacons = getattr(self, '_visible_radar_beacons', set())
            if bid not in visible_beacons and bid_str not in visible_beacons:
                continue

            idx = bid_to_color_idx.get(bid, bid % len(COLORS))
            _c_hex, c_q = COLORS[idx % len(COLORS)]

            poly_points = []
            for deg in sorted_degs:
                ch = deg_to_char[deg]
                rssi = data_avg.get(ch) if ch in data_avg else data_avg.get(str(ch), -100.0)
                rssi_clamped = max(-100.0, min(-40.0, rssi))
                val_r = ((rssi_clamped - (-100.0)) / 60.0) * R

                angle_rad = math.radians(deg - 90)
                dx = val_r * math.cos(angle_rad)
                dy = val_r * math.sin(angle_rad)
                poly_points.append(center + QPointF(dx, dy))

            if not poly_points:
                continue

            # Rysuj polygon i obwódkę
            poly = QPolygonF(poly_points)
            p.setPen(QPen(c_q, 2))
            c_fill = QColor(c_q)
            c_fill.setAlpha(70)
            p.setBrush(QBrush(c_fill))
            p.drawPolygon(poly)

            # Kropki na wierzchołkach i estymacja kierunku
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
                dx = pt.x() - center.x()
                dy = pt.y() - center.y()
                sum_x += dx * r_val
                sum_y += dy * r_val
                sum_r += r_val

            # Estymowany kierunek (środek ciężkości sygnału)
            if sum_r > 0:
                est_angle = math.atan2(sum_y, sum_x)
                p.setPen(QPen(c_q, 2, Qt.PenStyle.DashDotLine))
                p.drawLine(center, center + QPointF(
                    math.cos(est_angle) * R * 1.5,
                    math.sin(est_angle) * R * 1.5
                ))
