"""Główne okno aplikacji graficznej ESPAR IPS (mapa, sterowanie trybami i integracja z wątkiem TCP)."""

import datetime
import json
import os
import re
import statistics
import sys
import time

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QWidget,
)

from config import (
    DEFAULT_BEACON_ID,
    DEFAULT_TARGET_PACKETS,
    SVG_CALIB_PATH,
    SVG_PATH,
    VALID_CHARS,
    get_active_session,
)
from espar_client import EsparClient
from fingerprint import process_multi_beacon
from gui.canvas import MapCanvas
from gui.panel import InfoPanel
from gui.styles import (
    C_BG,
    C_BORDER,
    C_MUTED,
    C_PANEL,
    SCALE,
    SVG_ORIGIN_X,
    SVG_ORIGIN_Y,
    physical_to_svg,
)
from gui.threads import LiveThread

# Style CSS dla przycisków akcji w oknie
_BTN_SUCCESS = """
    QPushButton { background: #166534; color: #86efac; border: 1px solid #22c55e;
                  border-radius: 5px; padding: 10px; font-size: 13px; font-weight: bold; }
    QPushButton:hover { background: #15803d; }
"""
_BTN_WARN = """
    QPushButton { background: #854d0e; color: #fef08a; border: 1px solid #ca8a04;
                  border-radius: 5px; padding: 10px; font-size: 13px; font-weight: bold; }
    QPushButton:hover { background: #a16207; }
"""
_BTN_DISABLED = """
    QPushButton { background: #1e293b; color: #64748b; border: 1px solid #334155;
                  border-radius: 5px; padding: 10px; font-weight: bold; }
"""
_BTN_DANGER = """
    QPushButton { background: #3f2c2c; color: #f87171; border: 1px solid #7f1d1d;
                  border-radius: 5px; padding: 10px; font-weight: bold; }
    QPushButton:hover { background: #7f1d1d; color: #fecaca; }
    QPushButton:disabled { background: #1e293b; color: #4b5563; border: 1px solid #334155; }
"""
_BTN_SECONDARY = """
    QPushButton { background: #334155; color: #94a3b8; border: 1px solid #475569;
                  border-radius: 5px; padding: 10px; font-weight: bold; }
    QPushButton:hover { background: #475569; color: #e2e8f0; }
"""
_BTN_PRIMARY = """
    QPushButton { background: #2563eb; color: white; border: 1px solid #3b82f6;
                  border-radius: 5px; padding: 10px; font-weight: bold; }
    QPushButton:hover { background: #1d4ed8; }
"""


# Wyznacza kolejną etykietę z automatyczną numeracją (np. 'test_pt01' -> 'test_pt02').
def _next_indexed_label(points: list, default_prefix: str, pad: int = 2) -> str:
    labels = [p.get("label", "") for p in points if p.get("label")]
    prefix, max_num = default_prefix, 0
    for l in labels:
        m = re.search(r'(.*?)(\d+)$', l)
        if m:
            prefix, max_num = m.group(1), max(max_num, int(m.group(2)))
    return f"{prefix}{max_num + 1:0{pad}d}" if max_num > 0 else f"{default_prefix}{1:0{pad}d}"


class MapWindow(QMainWindow):
    """Główne okno graficzne integrujące widżet mapy, panel boczny i wątek odbioru danych ESPAR."""

    _sig_pos = pyqtSignal(float, float, object, float)

    def __init__(self, svg_path: str = SVG_PATH, pick_mode: bool = False,
                 show_points: bool = False, mark_origin_mode: bool = False,
                 select_mode: bool = False,
                 calibrate_mode: bool = False, calib_label: str = '',
                 calib_beacons: list = None,
                 calib_target_packets: int = DEFAULT_TARGET_PACKETS,
                 grid_collect_mode: bool = False, grid_json_path: str = '',
                 live_beacon_id: int = DEFAULT_BEACON_ID,
                 test_collect_mode: bool = False,
                 fingerprint_collect_mode: bool = False,
                 plan_points_mode: bool = False):
        super().__init__()

        self._grid_collect_mode = grid_collect_mode
        self._grid_json_path = grid_json_path
        self._grid_data = None
        self._grid_idx = 0
        self._fingerprint_collect_mode = fingerprint_collect_mode
        self._plan_points_mode = plan_points_mode
        self._planned_points = []
        self._collecting_active = not (grid_collect_mode or test_collect_mode or fingerprint_collect_mode or plan_points_mode)

        if self._grid_collect_mode:
            calibrate_mode = True
            if os.path.exists(self._grid_json_path):
                try:
                    with open(self._grid_json_path, "r", encoding="utf-8") as f:
                        self._grid_data = json.load(f)
                except Exception as e:
                    print(f"[!] Błąd wczytywania grid JSON: {e}", file=sys.stderr)
                    self._grid_data = {}
                if self._grid_data and self._grid_data.get("points"):
                    pt0 = self._grid_data["points"][0]
                    calib_label = pt0["label"]
                    calib_beacons = pt0["beacons"]
                    calib_target_packets = self._grid_data.get("target_packets", DEFAULT_TARGET_PACKETS)
                    self._collecting_active = False

        existing_points, test_points = [], []
        if pick_mode or show_points or mark_origin_mode or select_mode or test_collect_mode or fingerprint_collect_mode or plan_points_mode:
            try:
                from wknn import load_radio_map
                existing_points = load_radio_map(filter_session=True)
            except Exception as e:
                print(f"[!] Błąd wczytywania radio_map: {e}", file=sys.stderr)

        if test_collect_mode or select_mode:
            try:
                from validate import load_test_set
                test_points = load_test_set(filter_session=True)
            except Exception as e:
                print(f"[!] Błąd wczytywania test_set: {e}", file=sys.stderr)

        sess = get_active_session()
        if sess:
            self._session_ox, self._session_oy = sess.get("origin_x_m", 0.0), sess.get("origin_y_m", 0.0)
            self._session_label = sess.get("origin_label", "")
            session_origin = (self._session_ox, self._session_oy)
        else:
            self._session_ox, self._session_oy, self._session_label, session_origin = 0.0, 0.0, "", None

        self._pick_mode = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._show_points = show_points
        self._select_mode = select_mode
        self._calibrate_mode = calibrate_mode
        self._test_collect_mode = test_collect_mode
        self._calib_label = calib_label
        self._calib_beacons = calib_beacons or [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]
        self._calib_target_packets = calib_target_packets
        self._calib_rssi_accum = {}
        self._live_beacon_id = live_beacon_id
        self._test_beacon_id = live_beacon_id
        self._calib_beacon_id = live_beacon_id

        titles = {
            mark_origin_mode: "ESPAR IPS — Zaznacz globalny narożnik budynku (0,0)",
            pick_mode: "ESPAR IPS — Zaznacz lokalny origin sesji pomiarowej",
            show_points: f"ESPAR IPS — Baza Punktów Kalibracyjnych (Live Beacon #{live_beacon_id})",
            select_mode: "ESPAR IPS — Wybierz punkty kalibracyjne do analizy",
            calibrate_mode: f"ESPAR IPS — Wizualna Kalibracja: {calib_label}",
            test_collect_mode: "ESPAR IPS — Graficzne Zbieranie Punktów Testowych",
            fingerprint_collect_mode: "ESPAR IPS — Graficzne Zbieranie Odcisku (Mapa Radiowa)",
            plan_points_mode: "ESPAR IPS — Planowanie Wielu Punktów Kalibracji",
        }
        self.setWindowTitle(titles.get(True, "ESPAR IPS — Mapa Pozycjonowania"))
        self.resize(1300, 740)
        self._setup_style()
        self._picked = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._panel = InfoPanel()
        root.addWidget(self._panel)

        self._canvas = MapCanvas(
            svg_path, pick_mode=pick_mode, mark_origin_mode=mark_origin_mode,
            select_mode=select_mode, test_collect_mode=test_collect_mode,
            fingerprint_collect_mode=fingerprint_collect_mode,
            plan_points_mode=plan_points_mode, existing_points=existing_points,
            session_origin=session_origin,
        )
        self._canvas._test_points = test_points
        root.addWidget(self._canvas)

        self._panel._btn_fit.clicked.connect(self._canvas.fit_view)
        self._panel._btn_clear.clicked.connect(self._canvas.clear_trail)

        self._sb = QStatusBar()
        self._sb.setStyleSheet(
            f"background: {C_PANEL.name()}; color: {C_MUTED.name()}; border-top: 1px solid {C_BORDER.name()};"
        )
        self.setStatusBar(self._sb)

        init_msgs = {
            pick_mode: "Kliknij na mapie miejsce gdzie stoi statyw  |  F: dopasuj  |  Scroll: zoom",
            mark_origin_mode: "Kliknij narożnik budynku (globalny 0,0)  |  F: dopasuj  |  Scroll: zoom",
            calibrate_mode: "Zbieranie ramek…  |  Przeciągnij radar lewym klawiszem  |  F: dopasuj",
            test_collect_mode: "Zaznacz myszką prawdziwą pozycję na mapie i kliknij Rozpocznij zbieranie",
            fingerprint_collect_mode: "Zaznacz myszką pozycję na mapie i kliknij Rozpocznij zbieranie",
            plan_points_mode: "Klikaj lewym przyciskiem myszy na mapie, aby rozplanować punkty kalibracji",
            select_mode: "Klikaj punkty na mapie, aby je zaznaczyć/odznaczyć do analizy",
        }
        self._sb.showMessage(init_msgs.get(True, "Oczekiwanie na dane pozycji…  |  Kółko myszy: zoom  |  Przeciągnij: przesuń  |  F: dopasuj"))

        self._fit_key = Qt.Key.Key_F
        self._sig_pos.connect(self._on_position)
        self._last_x, self._last_y = 0.0, 0.0
        self._live_thread = None
        self._live_window_sec = 7.0
        self._last_ui_update = 0.0

        self._setup_modes(existing_points, test_points)

    # Konfiguruje kontrolki panelu i połączenia sygnałów dla wybranego trybu pracy GUI.
    def _setup_modes(self, existing_points, test_points):
        if self._calibrate_mode:
            self._panel.setup_calibration_mode(self._calib_label, self._calib_beacons, self._calib_target_packets)
            self._canvas._calibrate_mode = True
            self._canvas._calib_beacons = self._calib_beacons
            self._canvas._calib_label = self._calib_label
            self._canvas._calib_target_packets = self._calib_target_packets

            first_b = self._calib_beacons[0] if self._calib_beacons else {"x": 0.0, "y": 0.0}
            sx, sy = physical_to_svg(first_b.get("x", 0.0), first_b.get("y", 0.0))
            self._canvas._radar_center_svg = QPointF(sx, sy)

            self._canvas._visible_radar_beacons = {b["id"] for b in self._calib_beacons} | {str(b["id"])}
            for bid, chk in self._panel._radar_checkboxes.items():
                chk.stateChanged.connect(lambda state, b=bid: self._on_radar_vis_toggled(b, state))

            if self._grid_collect_mode:
                self._panel._btn_save_calib.clicked.connect(self._save_grid_point)
                self._panel._btn_force_save.clicked.connect(self._save_grid_point)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
                self._load_grid_point(0)
            else:
                self._panel._btn_save_calib.clicked.connect(self._save_and_exit)
                self._panel._btn_force_save.clicked.connect(self._force_save)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
            self._start_live()

        elif self._test_collect_mode:
            lbl = _next_indexed_label(test_points, "test_pt")
            self._panel.setup_test_collect_mode(lbl, self._live_beacon_id, self._calib_target_packets)
            self._canvas._test_collect_mode = True
            self._panel._btn_start_collect.clicked.connect(self._start_test_collect)
            self._panel._btn_save_calib.clicked.connect(self._save_test_point)
            self._panel._btn_repeat.clicked.connect(self._repeat_test_collect)
            self._panel._btn_next.clicked.connect(self._next_test_point)
            self._panel._btn_cancel_calib.clicked.connect(self.close)
            self._canvas.position_picked.connect(self._on_picked)
            self._start_live()

        elif self._fingerprint_collect_mode:
            lbl = _next_indexed_label(existing_points, "p")
            self._panel.setup_single_fingerprint_mode(lbl, self._live_beacon_id, self._calib_target_packets)
            self._canvas._fingerprint_collect_mode = True
            self._panel._btn_start_collect.clicked.connect(self._start_fingerprint_collect)
            self._panel._btn_save_calib.clicked.connect(self._save_fingerprint_point)
            self._panel._btn_repeat.clicked.connect(self._repeat_fingerprint_collect)
            self._panel._btn_next.clicked.connect(self._next_fingerprint_point)
            self._panel._btn_cancel_calib.clicked.connect(self.close)
            self._panel._spin_packets.valueChanged.connect(self._on_fp_packets_changed)
            self._panel._spin_beacon.valueChanged.connect(self._on_fp_beacon_changed)
            self._canvas.position_picked.connect(self._on_picked)

        elif self._plan_points_mode:
            lbl = _next_indexed_label(existing_points, "pkt_", pad=1)
            self._panel.setup_multi_plan_mode(lbl, self._live_beacon_id, self._calib_target_packets)
            self._canvas._plan_points_mode = True
            self._canvas.position_picked.connect(self._on_plan_point_clicked)
            self._panel._btn_remove_plan_pt.clicked.connect(self._remove_selected_plan_point)
            self._panel._btn_clear_plan.clicked.connect(self._clear_planned_points)
            self._panel._btn_start_multi_collect.clicked.connect(self._start_multi_collect_workflow)
            self._panel._list_planned_points.itemDoubleClicked.connect(self._on_plan_point_double_clicked)

        elif self._pick_mode or self._mark_origin_mode:
            self._canvas.position_picked.connect(self._on_picked)
            btn_lbl = "Zatwierdź origin budynku" if self._mark_origin_mode else "Zatwierdź origin sesji"
            self._panel._btn_clear.setText(btn_lbl)
            self._panel._btn_clear.setStyleSheet(_BTN_SUCCESS)
            self._panel._btn_clear.clicked.disconnect()
            self._panel._btn_clear.clicked.connect(self._confirm_pick)

        elif self._select_mode:
            self._panel._btn_clear.setText("Zatwierdź wybór")
            self._panel._btn_clear.setStyleSheet(_BTN_SUCCESS)
            self._panel._btn_clear.clicked.disconnect()
            self._panel._btn_clear.clicked.connect(self._confirm_select)
            self._panel._btn_fit.setText("Wyczyść wybór")
            self._panel._btn_fit.clicked.disconnect()
            self._panel._btn_fit.clicked.connect(self._clear_selection)
            self._on_selection_changed()

        else:
            self._panel._chk_beacons.toggled.connect(self._on_toggle_beacons)
            self._panel._chk_live.toggled.connect(self._on_toggle_live)
            self._panel._spin_window.valueChanged.connect(self._on_window_sec_changed)
            if hasattr(self._panel, "_spin_beacon_id"):
                self._panel._spin_beacon_id.blockSignals(True)
                self._panel._spin_beacon_id.setValue(self._live_beacon_id)
                self._panel._spin_beacon_id.blockSignals(False)
                self._panel._spin_beacon_id.valueChanged.connect(self._on_beacon_id_changed)

    # Obsługuje kliknięcie punktu na mapie: przelicza współrzędne i aktualizuje celownik.
    def _on_picked(self, a: float, b: float):
        self._picked = (a, b)
        if self._test_collect_mode or self._fingerprint_collect_mode:
            lx, ly = a - self._session_ox, b - self._session_oy
            self._panel._lbl_coords.setText(f"X = {a:.3f} m, Y = {b:.3f} m\n(lok: {lx:.3f}, {ly:.3f})")
            if not self._collecting_active:
                self._panel._btn_start_collect.setEnabled(True)
            self._sb.showMessage(f"Wybrano pozycję: X={a:.3f} m, Y={b:.3f} m. Wciśnij 'Rozpocznij zbieranie'.")
            sx, sy = physical_to_svg(a, b)
            self._canvas._radar_center_svg = QPointF(sx, sy)
            self._canvas._picked_svg_x, self._canvas._picked_svg_y = sx, sy
            self._canvas.update()
            return

        if self._mark_origin_mode:
            self._sb.showMessage(f'Narożnik budynku: SVG=({a:.1f}, {b:.1f}) — Kliknij "Zatwierdź origin budynku"')
        else:
            self._sb.showMessage(f'Origin sesji: X={a:.3f} m, Y={b:.3f} m — Kliknij "Zatwierdź origin sesji"')
            self._panel.refresh(a, b, SVG_ORIGIN_X + a * SCALE, SVG_ORIGIN_Y + b * SCALE, "origin", 1.0)

    # Zapisuje wybrany punkt odniesienia do pliku konfiguracyjnego lub zwraca na stdout.
    def _confirm_pick(self):
        if self._picked is None:
            self._sb.showMessage("Najpierw kliknij na mapie!")
            return
        a, b = self._picked
        if self._mark_origin_mode:
            calib = {"origin_x_svg": a, "origin_y_svg": b, "scale": SCALE}
            os.makedirs(os.path.dirname(SVG_CALIB_PATH), exist_ok=True)
            with open(SVG_CALIB_PATH, "w", encoding="utf-8") as f:
                json.dump(calib, f, indent=2)
            print(json.dumps({"svg_x": a, "svg_y": b, "saved": True}), flush=True)
        else:
            print(json.dumps({"x_m": a, "y_m": b, "picked": True}), flush=True)
        self.close()

    def _clear_selection(self):
        self._canvas._selected_labels.clear()
        self._on_selection_changed()
        self._canvas.update()

    def _confirm_select(self):
        labels = list(self._canvas._selected_labels)
        print(json.dumps({"selected_labels": labels, "confirmed": True}), flush=True)
        self.close()

    def _on_selection_changed(self):
        count = len(self._canvas._selected_labels)
        self._sb.showMessage(f'Wybrano {count} punktów. Kliknij "Zatwierdź wybór", aby zakończyć.')
        self._panel._lbl_id.setText(str(count))
        self._panel._lbl_x.setText("wybranych")
        self._panel._lbl_y.setText("punktów")

    def _increment_label(self, label: str) -> str:
        m = re.search(r'(.*?)(\d+)$', label)
        if m:
            prefix, num_str = m.group(1), m.group(2)
            return f"{prefix}{int(num_str) + 1:0{len(num_str)}d}"
        return f"{label}_next"

    # Rozpoczyna procedurę odbioru próbek dla wskazanego punktu na mapie.
    def _start_point_collection(self, beacon_id: int, is_test: bool):
        if self._picked is None:
            return
        self._calib_target_packets = self._panel._spin_packets.value()
        lbl = self._panel._edit_label.text().strip() or ("test_pt" if is_test else "punkt")
        self._calib_beacons = [{"id": beacon_id, "x": self._picked[0], "y": self._picked[1]}]
        self._canvas._calib_beacons = self._calib_beacons
        self._canvas._calib_target_packets = self._calib_target_packets
        self._canvas._calib_label = lbl
        self._canvas._visible_radar_beacons = {beacon_id, str(beacon_id)}

        self._calib_rssi_accum = {}
        self._canvas.set_radar_data({})
        self._collecting_active = True

        self._panel._edit_label.setEnabled(False)
        self._panel._spin_beacon.setEnabled(False)
        self._panel._spin_packets.setEnabled(False)
        self._panel._btn_start_collect.setEnabled(False)
        self._panel._btn_start_collect.setText("Zbieranie...")
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._btn_repeat.setEnabled(False)
        self._panel._btn_next.setEnabled(False)
        self._panel._lbl_progress.setText("Rozpoczęto zbieranie...")

        if self._live_thread is None or not self._live_thread.isRunning():
            self._start_live()

    def _reset_collect_ui(self, msg: str):
        self._panel._edit_label.setEnabled(True)
        self._panel._spin_beacon.setEnabled(True)
        self._panel._spin_packets.setEnabled(True)
        self._panel._btn_start_collect.setEnabled(True)
        self._panel._btn_start_collect.setText("Rozpocznij zbieranie")
        self._panel._btn_repeat.setEnabled(False)
        self._panel._btn_next.setEnabled(False)
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._lbl_progress.setText(msg)
        self._panel._progress_bar.setValue(0)
        self._collecting_active = False
        self._calib_rssi_accum = {}
        self._canvas.set_radar_data({})
        self._canvas.update()

    def _prepare_next_point(self, hint: str):
        old_lbl = self._panel._edit_label.text().strip()
        new_lbl = self._increment_label(old_lbl)
        self._panel._edit_label.setText(new_lbl)
        self._reset_collect_ui(hint)
        self._panel._btn_start_collect.setEnabled(False)
        self._panel._lbl_coords.setText("Kliknij na mapie...")
        self._picked = None
        self._canvas._picked_svg_x, self._canvas._picked_svg_y = None, None
        self._sb.showMessage(f"Przygotowano kolejny punkt: {new_lbl}.")

    def _start_test_collect(self):
        self._test_beacon_id = self._panel._spin_beacon.value()
        self._start_point_collection(self._test_beacon_id, is_test=True)

    def _repeat_test_collect(self):
        self._reset_collect_ui("Wciśnij Start, aby powtórzyć")

    def _next_test_point(self):
        self._prepare_next_point("Wybierz pozycję i wciśnij Start")

    # Zapisuje zebrany punkt testowy do zbioru walidacyjnego ground truth.
    def _save_test_point(self):
        target_pkts = self._calib_target_packets
        bid_str = str(self._test_beacon_id)
        result = process_multi_beacon(self._calib_rssi_accum, [bid_str], target_pkts)
        if bid_str not in result:
            self._sb.showMessage("Brak danych do zapisu!")
            return

        gx, gy = round(self._picked[0], 4), round(self._picked[1], 4)
        lx, ly = round(gx - self._session_ox, 4), round(gy - self._session_oy, 4)
        label = self._panel._edit_label.text().strip() or "test_pt"

        new_pt = {
            "label": label, "x_true": gx, "y_true": gy,
            "_local": {"x": lx, "y": ly, "session": self._session_label},
            "beacons": result,
        }
        from validate import load_test_set, save_test_set
        existing = [tp for tp in load_test_set() if tp.get("label") != label]
        existing.append(new_pt)
        save_test_set(existing)

        self._sb.showMessage(f"Zapisano punkt testowy '{label}'! Razem: {len(existing)}")
        self._panel._lbl_progress.setText(f"Zapisano: {label} ({gx}, {gy}) m")
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._btn_repeat.setEnabled(True)
        self._panel._btn_next.setEnabled(True)
        self._canvas._test_points = existing
        self._canvas.update()

    def _start_fingerprint_collect(self):
        self._calib_beacon_id = self._panel._spin_beacon.value()
        self._start_point_collection(self._calib_beacon_id, is_test=False)

    def _repeat_fingerprint_collect(self):
        self._reset_collect_ui("Wciśnij Start, aby powtórzyć")

    def _next_fingerprint_point(self):
        self._prepare_next_point("Wybierz pozycję i wciśnij Start")

    def _on_fp_packets_changed(self, val: int):
        self._calib_target_packets = val

    def _on_fp_beacon_changed(self, val: int):
        self._calib_beacon_id = val

    # Zapisuje zebrany fingerprint do bazy mapy radiowej.
    def _save_fingerprint_point(self):
        target_pkts = self._calib_target_packets
        bid_str = str(getattr(self, "_calib_beacon_id", self._panel._spin_beacon.value()))
        fill = self._ask_missing_directions_action([bid_str])
        if fill is None:
            return

        result = process_multi_beacon(self._calib_rssi_accum, [bid_str], target_pkts, fill_missing=fill, fill_value=-95.0)
        if bid_str not in result:
            self._sb.showMessage("Brak danych do zapisu!")
            return

        gx, gy = round(self._picked[0], 4), round(self._picked[1], 4)
        lx, ly = round(gx - self._session_ox, 4), round(gy - self._session_oy, 4)
        label = self._panel._edit_label.text().strip() or "punkt"

        new_pt = {
            "label": label, "x_m": gx, "y_m": gy,
            "_local": {"x": lx, "y": ly, "session": self._session_label},
            "beacons": result,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        from wknn import load_radio_map, save_radio_map
        existing = load_radio_map()
        replaced = False
        for i, ep in enumerate(existing):
            if ep.get("label") == label or (
                ep.get("x_m") is not None and abs(ep["x_m"] - gx) < 0.001 and
                ep.get("y_m") is not None and abs(ep["y_m"] - gy) < 0.001 and
                "beacons" in ep and bid_str in ep["beacons"]
            ):
                existing[i] = new_pt
                replaced = True
                break
        if not replaced:
            existing.append(new_pt)
        save_radio_map(existing)

        desc = "Zaktualizowano" if replaced else "Zapisano"
        self._sb.showMessage(f"{desc} punkt '{label}' w mapie radiowej! Razem: {len(existing)}")
        self._panel._lbl_progress.setText(f"{desc}: {label} ({gx}, {gy}) m")
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._btn_repeat.setEnabled(True)
        self._panel._btn_next.setEnabled(True)
        self._canvas._existing_points = existing
        self._canvas.update()

    # Dodaje nowy punkt do listy zaplanowanych do kalibracji.
    def _on_plan_point_clicked(self, x: float, y: float):
        if not self._plan_points_mode:
            return
        suggested = self._panel._edit_plan_label.text().strip() or f"pkt_{len(self._planned_points) + 1}"
        name, ok = QInputDialog.getText(
            self, f"Nowy punkt #{len(self._planned_points) + 1}",
            f"Współrzędne: X = {x:.3f} m, Y = {y:.3f} m\n\nPodaj nazwę dla tego punktu:",
            text=suggested,
        )
        if not ok or not name.strip():
            return

        base_label = name.strip()
        existing_labels = {p["label"] for p in self._planned_points}
        label, counter = base_label, 2
        while label in existing_labels:
            label = f"{base_label}_{counter}"
            counter += 1

        self._planned_points.append({"label": label, "x": round(x, 3), "y": round(y, 3)})
        self._canvas._planned_points = self._planned_points
        self._canvas.update()

        idx = len(self._planned_points)
        self._panel._list_planned_points.addItem(f"#{idx}: {label} ({x:.2f}, {y:.2f}) m")
        self._panel._list_planned_points.setCurrentRow(idx - 1)
        self._panel._edit_plan_label.setText(self._increment_label(base_label))
        self._panel._btn_start_multi_collect.setText(f"Rozpocznij zbieranie ({idx} pkt)")
        self._panel._btn_start_multi_collect.setEnabled(True)
        self._sb.showMessage(f"Dodano punkt #{idx}: '{label}'.")

    def _on_plan_point_double_clicked(self, item):
        row = self._panel._list_planned_points.row(item)
        if 0 <= row < len(self._planned_points):
            pt = self._planned_points[row]
            name, ok = QInputDialog.getText(
                self, f"Zmień nazwę #{row + 1}",
                f"Współrzędne: X = {pt['x']:.3f} m, Y = {pt['y']:.3f} m\n\nNowa nazwa:",
                text=pt["label"],
            )
            if ok and name.strip():
                pt["label"] = name.strip()
                item.setText(f"#{row + 1}: {pt['label']} ({pt['x']:.2f}, {pt['y']:.2f}) m")
                self._canvas.update()

    def _remove_selected_plan_point(self):
        row = self._panel._list_planned_points.currentRow()
        if 0 <= row < len(self._planned_points):
            removed = self._planned_points.pop(row)
            self._panel._list_planned_points.clear()
            for idx, pt in enumerate(self._planned_points, 1):
                self._panel._list_planned_points.addItem(f"#{idx}: {pt['label']} ({pt['x']:.2f}, {pt['y']:.2f}) m")
            self._canvas._planned_points = self._planned_points
            self._canvas.update()
            n = len(self._planned_points)
            self._panel._btn_start_multi_collect.setText(f"Rozpocznij zbieranie ({n} pkt)")
            self._panel._btn_start_multi_collect.setEnabled(n > 0)
            self._sb.showMessage(f"Usunięto '{removed['label']}'. Pozostało: {n}.")

    def _clear_planned_points(self):
        self._planned_points.clear()
        self._panel._list_planned_points.clear()
        self._canvas._planned_points = []
        self._canvas.update()
        self._panel._btn_start_multi_collect.setText("Rozpocznij zbieranie (0 pkt)")
        self._panel._btn_start_multi_collect.setEnabled(False)
        self._sb.showMessage("Wyczyszczono rozplanowane punkty.")

    # Generuje sekwencję punktów i przełącza okno w tryb krokowej kalibracji.
    def _start_multi_collect_workflow(self):
        if not self._planned_points:
            return
        bid = self._panel._spin_plan_beacon.value()
        target_pkts = self._panel._spin_plan_packets.value()
        points_list = []
        for pt in self._planned_points:
            gx, gy = pt["x"], pt["y"]
            lx, ly = round(gx - self._session_ox, 4), round(gy - self._session_oy, 4)
            points_list.append({
                "label": pt["label"], "x_local": lx, "y_local": ly, "x_global": gx, "y_global": gy,
                "beacons": [{"id": bid, "x": gx, "y": gy, "local_x": lx, "local_y": ly}],
            })

        self._grid_data = {
            "origin_label": self._session_label or "sesja",
            "target_packets": target_pkts,
            "points": points_list,
        }
        from session import DATA_DIR
        try:
            with open(os.path.join(DATA_DIR, "planned_grid.json"), "w", encoding="utf-8") as f:
                json.dump(self._grid_data, f, indent=2)
        except Exception as e:
            print(f"[!] Błąd zapisu planned_grid.json: {e}")

        self._plan_points_mode = False
        self._canvas._plan_points_mode = False
        self._grid_collect_mode = True
        self._calibrate_mode = True
        self._canvas._calibrate_mode = True

        first_pt = points_list[0]
        self._panel.setup_calibration_mode(first_pt["label"], first_pt["beacons"], target_pkts)
        self._panel._btn_save_calib.clicked.connect(self._save_grid_point)
        self._panel._btn_force_save.clicked.connect(self._save_grid_point)
        self._panel._btn_cancel_calib.clicked.connect(self.close)

        self._just_started_multi = True
        self._load_grid_point(0)
        self._start_live()

    def _ensure_grid_buttons(self):
        lay = self._panel.layout()
        idx_save = lay.indexOf(self._panel._btn_save_calib)

        if not hasattr(self._panel, "_btn_start_collect"):
            b = QPushButton("Rozpocznij zbieranie dla tej pozycji")
            b.setStyleSheet(_BTN_PRIMARY)
            b.clicked.connect(self._start_collect_current_point)
            lay.insertWidget(idx_save, b)
            self._panel._btn_start_collect = b

        if not hasattr(self._panel, "_btn_prev_calib"):
            b = QPushButton("Poprzedni (Cofnij)")
            b.setStyleSheet(_BTN_DANGER)
            b.clicked.connect(self._go_to_previous_point)
            lay.insertWidget(idx_save + 2, b)
            self._panel._btn_prev_calib = b

        if not hasattr(self._panel, "_btn_skip_calib"):
            b = QPushButton("Pomiń punkt")
            b.setStyleSheet(_BTN_SECONDARY)
            b.clicked.connect(self._skip_grid_point)
            lay.insertWidget(idx_save + 3, b)
            self._panel._btn_skip_calib = b

    # Ładuje punkt z sekwencji siatki, przestawia pozycję radaru i wyświetla monit o statywie.
    def _load_grid_point(self, idx: int) -> bool:
        if not self._grid_data or idx >= len(self._grid_data["points"]):
            return False

        self._grid_idx = idx
        pt = self._grid_data["points"][idx]
        self._calib_label = pt["label"]
        self._calib_beacons = pt["beacons"]
        self._calib_target_packets = self._grid_data.get("target_packets", DEFAULT_TARGET_PACKETS)
        self._calib_rssi_accum = {}
        self._canvas.set_radar_data({})

        self._ensure_grid_buttons()
        self._panel._btn_prev_calib.setEnabled(idx > 0)
        self._collecting_active = False
        self._panel._btn_start_collect.setEnabled(True)
        self._panel._btn_start_collect.setText("Rozpocznij zbieranie dla tej pozycji")

        total = len(self._grid_data["points"])
        self._panel._lbl_progress.setText(f"KROK {idx+1}/{total}:\nUmieść statyw w: {self._calib_label}")
        self._sb.showMessage(f"KROK {idx+1}/{total}: Umieść statyw w '{self._calib_label}' (X={pt['x_global']:.2f}, Y={pt['y_global']:.2f}) m.")

        if idx > 0:
            QMessageBox.information(
                self, "Przestaw statyw",
                f"Punkt {idx} zapisany!\n\nKROK {idx+1} z {total}:\n"
                f"Przestaw statyw do: '{pt['label']}' (X = {pt['x_global']:.2f} m, Y = {pt['y_global']:.2f} m)\n\n"
                f"Po ustawieniu statywu wciśnij OK i kliknij 'Rozpocznij zbieranie'.",
            )
        elif getattr(self, "_just_started_multi", False):
            self._just_started_multi = False
            QMessageBox.information(
                self, "Umieść statyw w 1. punkcie",
                f"Rozpoczynamy zbieranie mapy!\n\nKROK 1 z {total}:\n"
                f"Umieść statyw w: '{pt['label']}' (X = {pt['x_global']:.2f} m, Y = {pt['y_global']:.2f} m)\n\n"
                f"Po ustawieniu statywu wciśnij OK i kliknij 'Rozpocznij zbieranie'.",
            )

        self._panel._progress_bar.setValue(0)
        self._panel._btn_save_calib.setText("Zapisz i idź dalej")
        self._panel._btn_save_calib.setEnabled(False)
        self._panel._btn_save_calib.setStyleSheet(_BTN_DISABLED)

        self._canvas._calibrate_mode = True
        self._canvas._calib_beacons = self._calib_beacons
        self._canvas._calib_label = self._calib_label
        self._canvas._calib_target_packets = self._calib_target_packets
        self._canvas._grid_data = self._grid_data
        self._canvas._grid_idx = idx

        sx, sy = physical_to_svg(self._calib_beacons[0]["x"], self._calib_beacons[0]["y"]) if self._calib_beacons else physical_to_svg(0, 0)
        self._canvas._radar_center_svg = QPointF(sx, sy)
        self._canvas._visible_radar_beacons = {b["id"] for b in self._calib_beacons} | {str(b["id"])}
        self._canvas.update()
        return True

    def _start_collect_current_point(self):
        self._calib_rssi_accum = {}
        self._canvas.set_radar_data({})
        self._collecting_active = True
        self._panel._btn_start_collect.setEnabled(False)
        self._panel._btn_start_collect.setText("Zbieranie w toku...")
        self._panel._lbl_progress.setText("Trwa zbieranie danych...")
        if self._live_thread is None or not self._live_thread.isRunning():
            self._start_live()

    def _skip_grid_point(self):
        next_idx = self._grid_idx + 1
        if next_idx < len(self._grid_data["points"]):
            self._load_grid_point(next_idx)
        else:
            QMessageBox.information(self, "Kalibracja zakończona", "Zebrano i zapisano wszystkie punkty z planu!")
            self.close()

    def _go_to_previous_point(self):
        if self._grid_idx <= 0:
            return
        prev_idx = self._grid_idx - 1
        prev_pt = self._grid_data["points"][prev_idx]
        prev_lbl = prev_pt["label"]

        try:
            from wknn import load_radio_map, save_radio_map
            existing = load_radio_map()
            beacons = prev_pt.get("beacons", [])
            to_remove = {prev_lbl} | {f"{prev_lbl}_{b['id']}" for b in beacons if isinstance(beacons, list) and len(beacons) > 1}
            new_db = [pt for pt in existing if pt.get("label") not in to_remove]
            save_radio_map(new_db)
        except Exception as e:
            print(f"[!] Błąd cofania: {e}")

        self._load_grid_point(prev_idx)
        self._sb.showMessage(f"Cofnięto do punktu {prev_lbl}.")

    def _save_grid_point(self):
        target_pkts = self._calib_target_packets
        target_bids = [str(b["id"]) for b in self._calib_beacons]
        fill = self._ask_missing_directions_action(target_bids)
        if fill is None:
            return

        result = process_multi_beacon(self._calib_rssi_accum, target_bids, target_pkts, fill_missing=fill, fill_value=-95.0)
        if not result:
            self._sb.showMessage("Brak danych do zapisu!")
            return

        from wknn import load_radio_map, save_radio_map
        existing = load_radio_map()
        pt_info = self._grid_data["points"][self._grid_idx]

        for bid_str, stats in result.items():
            bid = int(bid_str)
            bx, by = next((b["x"], b["y"]) for b in self._calib_beacons if b["id"] == bid)
            pt = {
                "label": f"{self._calib_label}_{bid}" if len(self._calib_beacons) > 1 else self._calib_label,
                "x_m": bx, "y_m": by,
                "_local": {"x": pt_info["x_local"], "y": pt_info["y_local"], "session": self._grid_data["origin_label"]},
                "beacons": {bid_str: stats},
                "timestamp": datetime.datetime.now().isoformat(),
            }
            if self._grid_data.get("tripod"):
                tripod = self._grid_data["tripod"]
                pt["_tripod"] = {"base_label": self._calib_label, "beacon_id": bid,
                                 "spacing_m": tripod["spacing_m"], "angle_deg": tripod["angle_deg"]}

            replaced = False
            for i, ep in enumerate(existing):
                if ep.get("x_m") == bx and ep.get("y_m") == by and "beacons" in ep and bid_str in ep["beacons"]:
                    existing[i] = pt
                    replaced = True
                    break
            if not replaced:
                existing.append(pt)

        save_radio_map(existing)
        self._sb.showMessage(f"Zapisano punkt {self._calib_label}.")
        self._skip_grid_point()

    # Odbiera pojedynczą ramkę BLE z wątku TCP, aktualizuje wykres radarowy i pasek postępu.
    def _on_frame_received(self, beacon_id: int, char_int: int, rssi: float):
        if not self._collecting_active:
            return

        bid_str = str(beacon_id)
        self._calib_rssi_accum.setdefault(bid_str, {}).setdefault(char_int, []).append(rssi)

        target_bids = [str(b["id"]) for b in self._calib_beacons]
        if bid_str not in target_bids:
            return

        target_pkts = self._calib_target_packets
        num_beacons = len(self._calib_beacons)
        total_target = target_pkts * num_beacons

        total_collected = 0
        done_beacons = 0
        total_dirs_collected = 0

        for b_str in target_bids:
            b_acc = self._calib_rssi_accum.get(b_str, {})
            c = sum(len(b_acc.get(ch, [])) for ch in VALID_CHARS)
            total_collected += min(target_pkts, c)
            dirs = sum(1 for ch in VALID_CHARS if len(b_acc.get(ch, [])) > 0)
            total_dirs_collected += dirs
            if c >= target_pkts and dirs == len(VALID_CHARS):
                done_beacons += 1

        is_done = (done_beacons >= num_beacons)
        now = time.time()
        if not is_done and (now - self._last_ui_update < 0.1):
            return
        self._last_ui_update = now

        radar_data = {}
        for b_str in target_bids:
            b_accum = self._calib_rssi_accum.get(b_str, {})
            radar_data[b_str] = {
                ch: float(statistics.median(b_accum[ch])) if ch in b_accum and b_accum[ch] else -95.0
                for ch in VALID_CHARS
            }
        self._canvas.set_radar_data(radar_data)

        val = int((total_collected / total_target) * 100) if total_target > 0 else 0
        self._panel._progress_bar.setValue(val)
        dirs_info = f"Kierunki: {total_dirs_collected}/{len(VALID_CHARS) * num_beacons}"
        self._panel._lbl_progress.setText(
            f"Zebrano: {total_collected}/{total_target} pakietów [{dirs_info}]\n({done_beacons}/{num_beacons} beaconów gotowe)"
        )

        if is_done:
            self._panel._btn_save_calib.setEnabled(True)
            self._panel._btn_save_calib.setStyleSheet(_BTN_SUCCESS)
            self._panel._lbl_progress.setText(self._panel._lbl_progress.text() + "\n✅ Gotowe! Wciśnij Zapisz.")
        elif done_beacons > 0 or total_collected >= target_pkts:
            self._panel._btn_save_calib.setEnabled(True)
            self._panel._btn_save_calib.setStyleSheet(_BTN_WARN)
            hint = f"\n⚠️ Gotowe {done_beacons}/{num_beacons} beaconów" if done_beacons < num_beacons else f"\n⚠️ Brakuje {(len(VALID_CHARS)*num_beacons) - total_dirs_collected} kierunków"
            self._panel._lbl_progress.setText(self._panel._lbl_progress.text() + hint)

    # Pyta użytkownika o sposób uzupełnienia brakujących kierunków anteny przy zapisie.
    def _ask_missing_directions_action(self, target_bids: list[str]) -> bool | None:
        missing_details = []
        for b_str in target_bids:
            b_acc = self._calib_rssi_accum.get(b_str, {})
            m = sum(1 for ch in VALID_CHARS if len(b_acc.get(ch, [])) == 0)
            if m == len(VALID_CHARS) and sum(len(v) for v in b_acc.values()) == 0:
                missing_details.append(f"• Beacon #{b_str}: brak sygnału (0 pakietów)")
            elif m > 0:
                missing_details.append(f"• Beacon #{b_str}: brakuje {m}/12 kierunków")

        if not missing_details:
            return False

        msg = QMessageBox(self)
        msg.setWindowTitle("Brakujące kierunki")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Wykryto brakujące kierunki dla niektórych beaconów:\n\n" + "\n".join(missing_details) + "\n\nCo chcesz zrobić?")
        btn_fill = msg.addButton("Uzupełnij na -95 dBm", QMessageBox.ButtonRole.AcceptRole)
        btn_skip = msg.addButton("Pominąć brakujące", QMessageBox.ButtonRole.RejectRole)
        msg.addButton("Anuluj zapis", QMessageBox.ButtonRole.DestructiveRole)

        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_fill:
            return True
        elif clicked == btn_skip:
            return False
        return None

    def _save_and_exit(self):
        target_pkts = self._calib_target_packets
        target_bids = [str(b["id"]) for b in self._calib_beacons]
        fill = self._ask_missing_directions_action(target_bids)
        if fill is None:
            return
        result = process_multi_beacon(self._calib_rssi_accum, target_bids, target_pkts, fill_missing=fill, fill_value=-95.0)
        print(json.dumps(result), flush=True)
        self.close()

    def _force_save(self):
        if not self._calib_rssi_accum:
            self._sb.showMessage("Brak danych do zapisu!")
            return
        self._save_and_exit()

    def _on_radar_vis_toggled(self, bid, state: int):
        target = {bid, str(bid), int(bid) if str(bid).isdigit() else bid}
        if state == Qt.CheckState.Checked.value:
            self._canvas._visible_radar_beacons |= target
        else:
            self._canvas._visible_radar_beacons -= target
        self._canvas.update()

    def _on_toggle_beacons(self, checked: bool):
        self._canvas._show_fingerprints = checked
        self._canvas.update()

    def _on_toggle_live(self, checked: bool):
        self._start_live() if checked else self._stop_live()

    # Tworzy i uruchamia wątek LiveThread odbierający ramki w tle.
    def _start_live(self):
        if self._live_thread is not None:
            return
        client = EsparClient()
        self._live_thread = LiveThread(self, host=client.host, port=client.port, timeout=client.timeout)
        self._live_thread.BEACON_ID = getattr(self, "_live_beacon_id", DEFAULT_BEACON_ID)
        self._live_thread.WINDOW_SEC = getattr(self, "_live_window_sec", 7.0)

        is_calib_like = self._calibrate_mode or self._test_collect_mode or self._fingerprint_collect_mode
        if is_calib_like:
            self._live_thread.calibrate_mode = True
            self._live_thread.frame_received.connect(self._on_frame_received)
        else:
            self._live_thread.position.connect(self.update_position)

        self._live_thread.status_msg.connect(self._sb.showMessage)
        self._live_thread.finished.connect(self._on_live_finished)
        self._live_thread.start()
        self._sb.showMessage("Uruchamianie strumienia ESPAR...")

    def _on_window_sec_changed(self, val: int):
        self._live_window_sec = float(val)
        if self._live_thread is not None:
            self._live_thread.WINDOW_SEC = float(val)

    def _on_beacon_id_changed(self, val: int):
        self._live_beacon_id = int(val)
        if self._live_thread is not None:
            self._live_thread.BEACON_ID = int(val)
        self._sb.showMessage(f"Zmieniono śledzony Beacon na #{val}")

    def _stop_live(self):
        if self._live_thread is None:
            return
        self._live_thread.requestInterruption()
        self._live_thread.wait(3000)
        self._live_thread = None
        self._canvas._bx, self._canvas._by = None, None
        self._canvas._trail.clear()
        self._canvas.update()
        self._panel.refresh(0, 0, 0, 0, None, 0)
        self._sb.showMessage("Pozycjonowanie na żywo zatrzymane")

    def _on_live_finished(self):
        self._live_thread = None
        if hasattr(self._panel, "_chk_live") and self._panel._chk_live is not None:
            try:
                self._panel._chk_live.blockSignals(True)
                self._panel._chk_live.setChecked(False)
                self._panel._chk_live.blockSignals(False)
            except RuntimeError:
                pass

    def update_position(self, x_m: float, y_m: float, beacon_id=None, confidence: float = 1.0):
        self._sig_pos.emit(float(x_m), float(y_m), beacon_id, float(confidence))

    def _on_position(self, x_m: float, y_m: float, beacon_id, confidence: float):
        self._last_x, self._last_y = x_m, y_m
        self._canvas.update_position(x_m, y_m, beacon_id, confidence)
        sx, sy = physical_to_svg(x_m, y_m)
        self._panel.refresh(x_m, y_m, sx, sy, beacon_id, confidence)
        self._sb.showMessage(f"Beacon #{beacon_id}  |  X={x_m:.2f} m   Y={y_m:.2f} m  |  Pewność: {int(confidence*100)} %")

    def keyPressEvent(self, e):
        if e.key() == self._fit_key:
            self._canvas.fit_view()

    def closeEvent(self, event):
        self._stop_live()
        super().closeEvent(event)

    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {C_BG.name()}; }}
            QStatusBar  {{ color: {C_MUTED.name()}; font-size: 11px; }}
        """)
