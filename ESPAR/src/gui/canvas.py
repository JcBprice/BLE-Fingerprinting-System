"""Widżet mapy SVG z obsługą zoomu, przesuwania, rysowania pozycji i radaru kierunkowego."""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSizePolicy, QWidget

from config import CHAR_TO_DEG
from gui.styles import (
    C_ACCENT,
    C_BG,
    C_DOT,
    C_PANEL,
    C_TEXT,
    C_TRAIL,
    SCALE,
    SVG_ORIGIN_X,
    SVG_ORIGIN_Y,
    physical_to_svg,
    svg_to_physical,
)

_RADAR_COLORS = [
    QColor(249, 115, 22),   # Pomarańczowy
    QColor(59, 130, 246),   # Niebieski
    QColor(16, 185, 129),   # Zielony
    QColor(236, 72, 153),   # Różowy
    QColor(139, 92, 246),   # Fioletowy
]


class MapCanvas(QWidget):
    """Widżet graficzny renderujący mapę piętra, śledzone obiekty i wykres kołowy wiązek anteny."""

    position_picked = pyqtSignal(float, float)

    def __init__(self, svg_path: str, pick_mode: bool = False,
                 mark_origin_mode: bool = False, select_mode: bool = False,
                 test_collect_mode: bool = False,
                 fingerprint_collect_mode: bool = False,
                 plan_points_mode: bool = False,
                 existing_points=None, session_origin=None, parent=None):
        super().__init__(parent)
        self._existing_points = existing_points or []
        self._test_points = []
        self._session_origin = session_origin
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        self._pick_mode = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._select_mode = select_mode
        self._test_collect_mode = test_collect_mode
        self._fingerprint_collect_mode = fingerprint_collect_mode
        self._plan_points_mode = plan_points_mode
        self._planned_points = []
        self._selected_labels = set()

        self._picked_svg_x: float | None = None
        self._picked_svg_y: float | None = None

        self._renderer = QSvgRenderer(svg_path, self)
        vb = self._renderer.viewBoxF()
        self._vb_w = vb.width() if vb.width() > 10 else 4373.5528
        self._vb_h = vb.height() if vb.height() > 10 else 2617.9691

        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_start = None
        self._pan_at_drag = QPointF(0.0, 0.0)

        # Bieżąca estymowana pozycja i bufor trajektorii ruchu
        self._bx, self._by = None, None
        self._bid: int | None = None
        self._conf: float = 1.0
        self._trail: list[tuple[float, float]] = []
        self._MAX_TRAIL = 50

        # Timer do płynnej pulsacji kropki na mapie
        self._pulse = 0.0
        self._p_dir = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

        self._bg_pix: QPixmap | None = None
        self._bg_rect: QRectF | None = None
        self._show_fingerprints = True

        # Stan wykresu radarowego
        self._calibrate_mode = False
        self._calib_label = ""
        self._radar_center_svg = QPointF(0.0, 0.0)
        self._radar_drag_active = False
        self._radar_radius_px = 75
        self._radar_rssi_data = {}

        self._update_cursor_and_tooltip()

    # Dopasowuje kursor myszy i etykietę podpowiedzi do aktywnego trybu pracy interfejsu.
    def _update_cursor_and_tooltip(self):
        if self._pick_mode or self._mark_origin_mode or self._test_collect_mode or self._fingerprint_collect_mode or self._plan_points_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
            tips = {
                self._mark_origin_mode: "Kliknij narożnik budynku (globalny 0,0)",
                self._pick_mode: "Kliknij miejsce gdzie stoi statyw / lokalny origin",
                self._test_collect_mode: "Kliknij miejsce, aby zaznaczyć położenie punktu testowego",
                self._plan_points_mode: "Klikaj lewym przyciskiem myszy, aby rozplanować punkty",
            }
            self.setToolTip(tips.get(True, "Kliknij miejsce na mapie, aby zaznaczyć pozycję nowego odcisku"))
        elif self._select_mode:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Klikaj punkty na mapie, aby je zaznaczyć/odznaczyć")
        elif self._calibrate_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.setToolTip("Przeciągnij: przesuń  |  Kółko: zoom  |  Ctrl+klik: współrzędne")

    def update_position(self, x_m: float, y_m: float, beacon_id=None, confidence: float = 1.0):
        sx, sy = physical_to_svg(x_m, y_m)
        if self._bx is not None:
            self._trail.append((self._bx, self._by))
            if len(self._trail) > self._MAX_TRAIL:
                self._trail.pop(0)
        self._bx, self._by = sx, sy
        self._bid, self._conf = beacon_id, confidence

    def set_radar_data(self, data):
        self._radar_rssi_data = data
        self.update()

    def fit_view(self):
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._bg_pix = None
        self.update()

    def clear_trail(self):
        self._trail.clear()
        self.update()

    # Wyznacza obszar rysowania mapy zachowując proporcje viewBox i uwzględniając aktualny zoom i pan.
    def _render_rect(self) -> QRectF:
        w, h = self.width(), self.height()
        aspect = self._vb_w / self._vb_h
        rw = (h * self._zoom) * aspect if w / h > aspect else w * self._zoom
        rh = rw / aspect
        return QRectF(self._pan.x() + (w - rw) / 2.0, self._pan.y() + (h - rh) / 2.0, rw, rh)

    def _svg_to_widget(self, sx: float, sy: float) -> QPointF:
        r = self._render_rect()
        return QPointF(r.x() + (sx / self._vb_w) * r.width(), r.y() + (sy / self._vb_h) * r.height())

    def _widget_to_svg(self, wx: float, wy: float) -> tuple[float, float]:
        r = self._render_rect()
        if r.width() <= 0 or r.height() <= 0:
            return 0.0, 0.0
        return (wx - r.x()) / r.width() * self._vb_w, (wy - r.y()) / r.height() * self._vb_h

    def _widget_to_physical(self, wx: float, wy: float) -> tuple[float, float]:
        sx, sy = self._widget_to_svg(wx, wy)
        return svg_to_physical(sx, sy)

    def _dot_r(self) -> float:
        r = self._render_rect()
        return max(7.0, min(18.0, ((r.width() / self._vb_w) * SCALE) * 0.20))

    # Płynny zoom kółkiem myszy z zachowaniem punktu skupienia pod kursorem.
    def wheelEvent(self, e):
        factor = 1.15 if e.angleDelta().y() > 0 else 1.0 / 1.15
        old_z = self._zoom
        self._zoom = max(0.25, min(12.0, self._zoom * factor))
        mx, my = float(e.position().x()), float(e.position().y())
        r = self._render_rect()
        ratio = self._zoom / old_z
        self._pan = QPointF(
            mx - (mx - r.x()) * ratio - (self.width() - r.width() * ratio) / 2,
            my - (my - r.y()) * ratio - (self.height() - r.height() * ratio) / 2,
        )
        self._bg_pix = None
        self.update()

    # Obsługuje kliknięcia: prawy przycisk przesuwa mapę, lewy wskazuje pozycje w trybach interaktywnych.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._drag_start = e.position()
            self._pan_at_drag = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if e.button() == Qt.MouseButton.LeftButton:
            wx, wy = float(e.position().x()), float(e.position().y())

            if self._calibrate_mode:
                radar_pos = self._svg_to_widget(self._radar_center_svg.x(), self._radar_center_svg.y())
                if math.hypot(wx - radar_pos.x(), wy - radar_pos.y()) <= self._radar_radius_px:
                    self._radar_drag_active = True
                    self._radar_drag_offset = e.position() - radar_pos
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return

            if self._plan_points_mode:
                px, py = self._widget_to_physical(wx, wy)
                self.position_picked.emit(round(px, 3), round(py, 3))
                return

            if self._pick_mode or self._mark_origin_mode or self._test_collect_mode or self._fingerprint_collect_mode:
                sx, sy = self._widget_to_svg(wx, wy)
                self._picked_svg_x, self._picked_svg_y = sx, sy
                if self._mark_origin_mode:
                    self.position_picked.emit(round(sx, 2), round(sy, 2))
                else:
                    px, py = svg_to_physical(sx, sy)
                    self.position_picked.emit(round(px, 3), round(py, 3))
                self.update()
                return

            if self._select_mode:
                px, py = self._widget_to_physical(wx, wy)
                all_pts = list(self._existing_points) + [
                    {"label": pt.get("label"), "x_m": pt.get("x_true"), "y_m": pt.get("y_true")}
                    for pt in getattr(self, "_test_points", [])
                ]
                closest = min(
                    (pt for pt in all_pts if pt.get("x_m") is not None and pt.get("y_m") is not None),
                    key=lambda pt: math.hypot(px - pt["x_m"], py - pt["y_m"]),
                    default=None,
                )
                if closest and math.hypot(px - closest["x_m"], py - closest["y_m"]) < 1.5:
                    lbl = closest.get("label")
                    if lbl:
                        self._selected_labels.symmetric_difference_update({lbl})
                        parent_win = self.window()
                        if hasattr(parent_win, "_on_selection_changed"):
                            parent_win._on_selection_changed()
                        self.update()
                return

            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                sx, sy = self._widget_to_svg(wx, wy)
                px, py = svg_to_physical(sx, sy)
                print(f"[PROBE] widget=({wx:.0f},{wy:.0f}) SVG=({sx:.1f},{sy:.1f}) Fizyczne=({px:.2f}m, {py:.2f}m)")
                return

            self._drag_start = e.position()
            self._pan_at_drag = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._calibrate_mode and self._radar_drag_active:
            new_pos = e.position() - self._radar_drag_offset
            sx, sy = self._widget_to_svg(new_pos.x(), new_pos.y())
            self._radar_center_svg = QPointF(sx, sy)
            self.update()
            return

        if self._drag_start is not None:
            self._pan = self._pan_at_drag + (e.position() - self._drag_start)
            self._bg_pix = None
            self.update()

    def mouseReleaseEvent(self, e):
        if self._calibrate_mode and self._radar_drag_active:
            self._radar_drag_active = False
        self._drag_start = None
        self._update_cursor_and_tooltip()

    def resizeEvent(self, _):
        self._bg_pix = None

    def _tick(self):
        if self._bx is None:
            return
        self._pulse += self._p_dir * 0.9
        if self._pulse >= 28.0:
            self._p_dir = -1.0
        elif self._pulse <= 0.0:
            self._p_dir, self._pulse = 1.0, 0.0
        self.update()

    # Rysuje podkład SVG, naniesione punkty, trajektorię ruchu oraz aktywny radar.
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), C_BG)

        # Buforowane tło mapy SVG
        r = self._render_rect()
        iw, ih = int(r.width()), int(r.height())
        if iw > 0 and ih > 0:
            if self._bg_pix is None or self._bg_rect != r:
                self._bg_rect = QRectF(r)
                self._bg_pix = QPixmap(iw, ih)
                self._bg_pix.fill(Qt.GlobalColor.transparent)
                bp = QPainter(self._bg_pix)
                bp.setRenderHint(QPainter.RenderHint.Antialiasing)
                self._renderer.render(bp, QRectF(0, 0, iw, ih))
                bp.end()
            p.drawPixmap(int(r.x()), int(r.y()), self._bg_pix)

        self._draw_calibration_points(p)
        self._draw_test_points(p)
        self._draw_planned_points(p)
        self._draw_grid_points(p)
        self._draw_session_origin(p)

        if self._pick_mode or self._test_collect_mode or self._fingerprint_collect_mode:
            if self._picked_svg_x is not None:
                self._draw_crosshair(p)
            if (self._test_collect_mode or self._fingerprint_collect_mode) and self._radar_rssi_data:
                radar_pos = self._svg_to_widget(self._radar_center_svg.x(), self._radar_center_svg.y())
                self._draw_radar_chart(p, radar_pos)
            p.end()
            return

        if self._calibrate_mode:
            self._draw_calibration_overlay(p)
            p.end()
            return

        if self._bx is not None:
            self._draw_beacon_position(p)

        p.end()

    # Rysuje pojedynczy punkt na mapie z wyróżnieniem stanu zaznaczenia.
    def _draw_marker_point(self, p: QPainter, x_m: float, y_m: float, lbl: str,
                           default_col: str, text_col: str, tag: str = ""):
        sx, sy = physical_to_svg(x_m, y_m)
        wp = self._svg_to_widget(sx, sy)
        is_sel = lbl in self._selected_labels

        col = QColor("#10b981" if is_sel else default_col)
        p.setBrush(QBrush(col))
        p.setPen(QPen(Qt.GlobalColor.white, 2 if is_sel else 1))
        r = 8 if is_sel else 5
        p.drawEllipse(wp, r, r)

        p.setPen(QPen(QColor("#34d399" if is_sel else text_col)))
        p.setFont(QFont("Segoe UI", 9 if is_sel else 8, QFont.Weight.Bold))
        text = f"{lbl} {tag}".strip()
        p.drawText(int(wp.x()) + (11 if is_sel else 8), int(wp.y()) + 4, text)

    def _draw_calibration_points(self, p: QPainter):
        if not self._show_fingerprints or not self._existing_points:
            return
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for pt in self._existing_points:
            if pt.get("x_m") is not None and pt.get("y_m") is not None:
                self._draw_marker_point(p, pt["x_m"], pt["y_m"], pt.get("label", ""), "#3b82f6", "#bfdbfe")

    def _draw_test_points(self, p: QPainter):
        if not self._show_fingerprints or not self._test_points:
            return
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for pt in self._test_points:
            if pt.get("x_true") is not None and pt.get("y_true") is not None:
                self._draw_marker_point(p, pt["x_true"], pt["y_true"], pt.get("label", ""), "#c084fc", "#e9d5ff", "[test]")

    def _draw_planned_points(self, p: QPainter):
        if not self._planned_points:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        pts = [(self._svg_to_widget(*physical_to_svg(pt["x"], pt["y"])), pt["label"]) for pt in self._planned_points]

        if len(pts) > 1:
            p.setPen(QPen(QColor("#0284c7"), 2, Qt.PenStyle.DashLine))
            for i in range(len(pts) - 1):
                p.drawLine(pts[i][0], pts[i + 1][0])

        for idx, (wp, label) in enumerate(pts, 1):
            p.setBrush(QBrush(QColor("#0284c7")))
            p.setPen(QPen(Qt.GlobalColor.white, 2))
            p.drawEllipse(wp, 13, 13)

            p.setPen(QPen(Qt.GlobalColor.white))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(wp.x() - 13, wp.y() - 13, 26, 26), Qt.AlignmentFlag.AlignCenter, str(idx))

            p.setPen(QPen(QColor("#38bdf8")))
            p.drawText(int(wp.x()) + 16, int(wp.y()) + 4, label)

    def _draw_grid_points(self, p: QPainter):
        grid_data = getattr(self, "_grid_data", None)
        if not grid_data or not grid_data.get("points"):
            return

        all_beacons = {(b["x"], b["y"]) for pt in grid_data["points"] for b in pt.get("beacons", [])}
        for bx, by in all_beacons:
            wp = self._svg_to_widget(*physical_to_svg(bx, by))
            p.setBrush(QBrush(QColor("#64748b")))
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.drawEllipse(wp, 4, 4)

        curr_idx = getattr(self, "_grid_idx", -1)
        if 0 <= curr_idx < len(grid_data["points"]):
            pt = grid_data["points"][curr_idx]
            if pt.get("beacons"):
                bx_avg = sum(b["x"] for b in pt["beacons"]) / len(pt["beacons"])
                by_avg = sum(b["y"] for b in pt["beacons"]) / len(pt["beacons"])
                wp = self._svg_to_widget(*physical_to_svg(bx_avg, by_avg))

                p.setBrush(QBrush(QColor(234, 179, 8, int(60 + self._pulse * 0.5))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(wp, 18, 18)

                p.setBrush(QBrush(QColor("#eab308")))
                p.setPen(QPen(Qt.GlobalColor.white, 2))
                p.drawEllipse(wp, 7, 7)

                p.setPen(QPen(QColor("#fef08a")))
                p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                p.drawText(int(wp.x()) + 12, int(wp.y()) + 4, pt["label"])

    def _draw_session_origin(self, p: QPainter):
        if self._session_origin is None:
            return
        sp = self._svg_to_widget(*physical_to_svg(*self._session_origin))
        R = 10
        p.setPen(QPen(QColor("#facc15"), 2))
        p.drawLine(int(sp.x()) - R, int(sp.y()), int(sp.x()) + R, int(sp.y()))
        p.drawLine(int(sp.x()), int(sp.y()) - R, int(sp.x()), int(sp.y()) + R)
        p.setBrush(QBrush(QColor("#facc15")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(sp, 4, 4)
        p.setPen(QPen(QColor("#fef08a")))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(int(sp.x()) + 8, int(sp.y()) - 4, "origin sesji")

    def _draw_crosshair(self, p: QPainter):
        centre = self._svg_to_widget(self._picked_svg_x, self._picked_svg_y)
        CR = 14
        pen = QPen(QColor("#22c55e"), 2)
        p.setPen(pen)
        p.drawLine(int(centre.x()) - CR - 4, int(centre.y()), int(centre.x()) + CR + 4, int(centre.y()))
        p.drawLine(int(centre.x()), int(centre.y()) - CR - 4, int(centre.x()), int(centre.y()) + CR + 4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, CR, CR)
        p.setBrush(QBrush(QColor("#22c55e")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centre, 4, 4)

    def _draw_calibration_overlay(self, p: QPainter):
        radar_pos = self._svg_to_widget(self._radar_center_svg.x(), self._radar_center_svg.y())
        self._draw_radar_chart(p, radar_pos)

        for b in getattr(self, "_calib_beacons", []):
            target_pos = self._svg_to_widget(SVG_ORIGIN_X + b["x"] * SCALE, SVG_ORIGIN_Y + b["y"] * SCALE)
            p.setPen(QPen(QColor("#f97316"), 2))
            p.setBrush(QBrush(QColor("#f97316")))
            p.drawEllipse(target_pos, 6, 6)

            dash_pen = QPen(QColor("#f97316"), 1.5, Qt.PenStyle.DashLine)
            p.setPen(dash_pen)
            p.drawLine(target_pos, radar_pos)

            p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            p.drawText(int(target_pos.x()) + 10, int(target_pos.y()) + 4, f"#{b['id']}")

        lbl = f"Kalibracja: {self._calib_label}"
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.setPen(QPen(QColor("#f97316")))
        p.drawText(int(radar_pos.x()) - 50, int(radar_pos.y()) - self._radar_radius_px - 10, lbl)

    # Rysuje pulsującą kropkę obiektu, jej etykietę oraz zanikający ślad ostatnich pozycji.
    def _draw_beacon_position(self, p: QPainter):
        dot_r = self._dot_r()
        centre = self._svg_to_widget(self._bx, self._by)
        n = len(self._trail)

        # Ślad przebytej trajektorii z zanikającym kanałem alpha
        for i, (tx, ty) in enumerate(self._trail):
            tp = self._svg_to_widget(tx, ty)
            alpha = int(30 + 150 * (i + 1) / max(n, 1))
            tr = max(2.0, dot_r * 0.45 * (i + 1) / max(n, 1))
            tc = QColor(C_TRAIL)
            tc.setAlpha(alpha)
            p.setBrush(QBrush(tc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(tp, tr, tr)

        # Efekt poświaty i pierścień pulsacji
        glow = QRadialGradient(centre, dot_r * 3)
        gc = QColor(C_DOT)
        gc.setAlpha(70)
        glow.setColorAt(0, gc)
        glow.setColorAt(1, Qt.GlobalColor.transparent)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centre, dot_r * 3, dot_r * 3)

        ring_r = dot_r + self._pulse
        alpha = max(0, int(220 * (1 - self._pulse / 28)))
        rc = QColor(C_DOT)
        rc.setAlpha(alpha)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rc, 2.0))
        p.drawEllipse(centre, ring_r, ring_r)

        # Główny punkt obiektu
        p.setBrush(QBrush(C_DOT))
        p.setPen(QPen(Qt.GlobalColor.white, max(1.5, dot_r * 0.18)))
        p.drawEllipse(centre, dot_r, dot_r)

        # Etykieta ID beacona
        if self._bid is not None:
            lbl = f"  Beacon #{self._bid}  "
            p.setFont(QFont("Segoe UI", max(8, int(dot_r * 0.85)), QFont.Weight.Bold))
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(lbl), fm.height()
            lx, ly = int(centre.x() - tw / 2), int(centre.y() - dot_r - 8)
            bg = QColor(C_PANEL)
            bg.setAlpha(230)
            p.setBrush(QBrush(bg))
            p.setPen(QPen(C_ACCENT, 1))
            p.drawRoundedRect(lx - 4, ly - th - 4, tw + 8, th + 8, 5, 5)
            p.setPen(QPen(C_TEXT))
            p.drawText(lx, ly - fm.descent(), lbl)

    # Rysuje wykres kołowy RSSI dla 12 sektorów anteny oraz wektor szacowanego kąta nadejścia fali.
    def _draw_radar_chart(self, p: QPainter, center: QPointF):
        R = self._radar_radius_px

        p.setPen(QPen(QColor("#1e293b"), 2))
        p.setBrush(QBrush(QColor(15, 22, 35, 200)))
        p.drawEllipse(center, R, R)

        p.setPen(QPen(QColor("#334155"), 1, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, R * 0.33, R * 0.33)
        p.drawEllipse(center, R * 0.66, R * 0.66)

        p.setFont(QFont("Segoe UI", 6))
        p.setPen(QPen(QColor("#475569")))
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.33 - 2), "-80 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R * 0.66 - 2), "-60 dBm")
        p.drawText(int(center.x() + 3), int(center.y() - R - 2), "-40 dBm")

        # Linie radialne dla każdego kąta co 30°
        for i in range(12):
            deg = i * 30
            disp_rad = math.radians(225.0 - deg)
            p.drawLine(center, center + QPointF(R * math.cos(disp_rad), -R * math.sin(disp_rad)))

        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QPen(QColor("#94a3b8")))
        fm = p.fontMetrics()
        for deg in (0, 90, 180, 270):
            disp_rad = math.radians(225.0 - deg)
            lx = center.x() + (R - 10) * math.cos(disp_rad)
            ly = center.y() - (R - 10) * math.sin(disp_rad)
            txt = f"{deg}°"
            p.drawText(int(lx - fm.horizontalAdvance(txt) / 2), int(ly + fm.height() / 4), txt)

        radar_data = self._radar_rssi_data or {}
        if radar_data and not any(isinstance(v, dict) for v in radar_data.values()):
            radar_data = {"28": radar_data}

        sorted_degs = sorted(deg for deg in CHAR_TO_DEG.values())
        deg_to_ch = {deg: ch for ch, deg in CHAR_TO_DEG.items()}
        visible = getattr(self, "_visible_radar_beacons", set())

        for idx, (bid_str, data_avg) in enumerate(radar_data.items()):
            try:
                bid = int(bid_str)
            except (ValueError, TypeError):
                continue

            if visible and bid not in visible and bid_str not in visible:
                continue

            c_q = _RADAR_COLORS[idx % len(_RADAR_COLORS)]
            poly_points, rssi_vals = [], []

            for deg in sorted_degs:
                ch = deg_to_ch[deg]
                rssi = data_avg.get(ch) if ch in data_avg else data_avg.get(str(ch), -95.0)
                rssi_vals.append(rssi)
                val_r = ((max(-95.0, min(-40.0, rssi)) + 95.0) / 55.0) * R
                disp_rad = math.radians(225.0 - deg)
                poly_points.append(center + QPointF(val_r * math.cos(disp_rad), -val_r * math.sin(disp_rad)))

            if not poly_points:
                continue

            p.setPen(QPen(c_q, 2))
            c_fill = QColor(c_q)
            c_fill.setAlpha(70)
            p.setBrush(QBrush(c_fill))
            p.drawPolygon(QPolygonF(poly_points))

            p.setBrush(QBrush(c_q))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in poly_points:
                p.drawEllipse(pt, 3, 3)

            # Wyznacza dominujący wektor nadejścia sygnału (AoA) ważony mocą RSSI
            min_rssi = min(rssi_vals)
            sin_s = sum(10.0 ** ((r - min_rssi) / 10.0) * math.sin(math.radians(d)) for d, r in zip(sorted_degs, rssi_vals))
            cos_s = sum(10.0 ** ((r - min_rssi) / 10.0) * math.cos(math.radians(d)) for d, r in zip(sorted_degs, rssi_vals))
            if sin_s != 0.0 or cos_s != 0.0:
                best_deg = math.degrees(math.atan2(sin_s, cos_s)) % 360.0
                disp_rad = math.radians(225.0 - best_deg)
                p.setPen(QPen(c_q, 2, Qt.PenStyle.DashDotLine))
                p.drawLine(center, center + QPointF(math.cos(disp_rad) * R * 1.5, -math.sin(disp_rad) * R * 1.5))
