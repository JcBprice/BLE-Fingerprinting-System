"""
window.py — Główne okno aplikacji wizualizacji i kalibracji ESPAR IPS.

Klasa MapWindow łączy widget mapy (MapCanvas) oraz panel boczny (InfoPanel)
i realizuje całą logikę biznesową w zależności od wybranego trybu:
    - Normalny podgląd (update_position na żywo przez LiveThread)
    - Wybór lokalnego originu sesji pomiarowej (--pick-session)
    - Wyznaczenie globalnego narożnika budynku (--mark-origin)
    - Zbieranie pojedynczych punktów kalibracji (--calibrate)
    - Zbieranie automatycznej siatki punktów kalibracji (--grid_collect)
    - Graficzne zbieranie punktów testowych walidacji (--test_collect)
    - Wybór punktów kalibracyjnych do analizy (--select-points)
"""

import os
import sys
import json
import datetime
import re

from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStatusBar, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal, QPointF

from gui.styles import (
    C_BG, C_PANEL, C_BORDER, C_ACCENT, C_DOT, C_TEXT, C_MUTED,
    SVG_ORIGIN_X, SVG_ORIGIN_Y, SCALE,
    physical_to_svg, svg_to_physical,
)
from gui.canvas import MapCanvas
from gui.panel import InfoPanel
from gui.threads import LiveThread

from config import (
    VALID_CHARS, SVG_PATH, SVG_CALIB_PATH, SESSION_PATH,
    DEFAULT_BEACON_ID, DEFAULT_TARGET_PACKETS,
)
from fingerprint import process_multi_beacon
from espar_client import EsparClient


class MapWindow(QMainWindow):
    """Główne okno wizualizacji systemu ESPAR IPS."""

    _sig_pos = pyqtSignal(float, float, object, float)

    def __init__(self, svg_path: str = SVG_PATH, pick_mode: bool = False,
                 show_points: bool = False, mark_origin_mode: bool = False,
                 select_mode: bool = False,
                 calibrate_mode: bool = False, calib_label: str = '',
                 calib_beacons: list = None,
                 calib_target_packets: int = DEFAULT_TARGET_PACKETS,
                 grid_collect_mode: bool = False, grid_json_path: str = '',
                 live_beacon_id: int = DEFAULT_BEACON_ID,
                 test_collect_mode: bool = False):
        super().__init__()

        self._grid_collect_mode = grid_collect_mode
        self._grid_json_path = grid_json_path
        self._grid_data = None
        self._grid_idx = 0
        self._collecting_active = not (grid_collect_mode or test_collect_mode)

        if self._grid_collect_mode:
            calibrate_mode = True
            if os.path.exists(self._grid_json_path):
                try:
                    with open(self._grid_json_path, 'r', encoding='utf-8') as f:
                        self._grid_data = json.load(f)
                except Exception as e:
                    print(f"[!] Błąd wczytywania grid JSON: {e}", file=sys.stderr)
                    self._grid_data = {}
                if self._grid_data and self._grid_data.get('points'):
                    pt = self._grid_data['points'][0]
                    calib_label = pt['label']
                    calib_beacons = pt['beacons']
                    calib_target_packets = self._grid_data.get('target_packets', DEFAULT_TARGET_PACKETS)
                    self._collecting_active = False

        # Wczytaj istniejące punkty kalibracyjne do wyświetlenia
        existing_points = []
        if pick_mode or show_points or mark_origin_mode or select_mode or test_collect_mode:
            try:
                from wknn import load_radio_map
                existing_points = load_radio_map(filter_session=True)
            except Exception as e:
                print(f"[!] Błąd wczytywania radio_map.json: {e}", file=sys.stderr)

        # Wczytaj istniejące punkty testowe
        test_points = []
        if test_collect_mode:
            try:
                from validate import load_test_set
                test_points = load_test_set(filter_session=True)
            except Exception as e:
                print(f"[!] Błąd wczytywania test_set.json: {e}", file=sys.stderr)

        # Wczytaj origin aktywnej sesji (żółty marker)
        session_origin = None
        self._session_ox = 0.0
        self._session_oy = 0.0
        self._session_label = 'unknown'
        if os.path.exists(SESSION_PATH):
            try:
                with open(SESSION_PATH, encoding='utf-8') as f:
                    s = json.load(f)
                session_origin = (s['origin_x_m'], s['origin_y_m'])
                self._session_ox = s['origin_x_m']
                self._session_oy = s['origin_y_m']
                self._session_label = s['origin_label']
            except Exception:
                pass

        self._pick_mode        = pick_mode
        self._mark_origin_mode = mark_origin_mode
        self._show_points      = show_points
        self._select_mode      = select_mode
        self._calibrate_mode   = calibrate_mode
        self._test_collect_mode = test_collect_mode
        self._calib_label      = calib_label
        self._calib_beacons    = calib_beacons or [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]
        self._calib_target_packets = calib_target_packets
        self._calib_rssi_accum = {}
        self._live_beacon_id   = live_beacon_id

        # Dostosowanie tytułu okna do wybranego trybu
        if mark_origin_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz globalny narożnik budynku (0,0)')
        elif pick_mode:
            self.setWindowTitle('ESPAR IPS — Zaznacz lokalny origin sesji pomiarowej')
        elif show_points:
            self.setWindowTitle(f'ESPAR IPS — Baza Punktów Kalibracyjnych (Live Beacon #{live_beacon_id})')
        elif select_mode:
            self.setWindowTitle('ESPAR IPS — Wybierz punkty kalibracyjne do analizy')
        elif calibrate_mode:
            self.setWindowTitle(f'ESPAR IPS — Wizualna Kalibracja: {calib_label}')
        elif test_collect_mode:
            self.setWindowTitle('ESPAR IPS — Graficzne Zbieranie Punktów Testowych')
        else:
            self.setWindowTitle('ESPAR IPS — Mapa Pozycjonowania')
        self.resize(1300, 740)
        self._setup_style()
        self._picked = None

        # Układ okna: Panel boczny + Mapa
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Panel boczny
        self._panel = InfoPanel()
        root.addWidget(self._panel)

        # Mapa SVG
        self._canvas = MapCanvas(svg_path, pick_mode=pick_mode,
                                 mark_origin_mode=mark_origin_mode,
                                 select_mode=select_mode,
                                 test_collect_mode=test_collect_mode,
                                 existing_points=existing_points,
                                 session_origin=session_origin)
        self._canvas._test_points = test_points
        root.addWidget(self._canvas)

        # Powiązania przycisków pomocniczych
        self._panel._btn_fit.clicked.connect(self._canvas.fit_view)
        self._panel._btn_clear.clicked.connect(self._canvas.clear_trail)

        # Pasek statusu
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
        elif test_collect_mode:
            msg = 'Zaznacz myszką prawdziwą pozycję na mapie i kliknij Rozpocznij zbieranie'
        self._sb.showMessage(msg)

        # Inicjalizacja interfejsu trybów
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
                chk.toggled.connect(lambda checked, b=bid: self._on_toggle_radar_beacon(b, checked))

            if self._calib_beacons:
                first_b = self._calib_beacons[0]
                target_svg_x = SVG_ORIGIN_X + first_b["x"] * SCALE
                target_svg_y = SVG_ORIGIN_Y + first_b["y"] * SCALE
                self._canvas._radar_center_svg = QPointF(target_svg_x, target_svg_y)

            if not self._grid_collect_mode:
                self._panel._btn_save_calib.clicked.connect(self._save_and_exit)
                self._panel._btn_force_save.clicked.connect(self._force_save)
                self._panel._btn_cancel_calib.clicked.connect(self.close)

        elif self._test_collect_mode:
            # Automatyczna inkrementacja etykiety punktu testowego
            initial_label = "test_pt01"
            if test_points:
                labels = [pt.get("label", "") for pt in test_points if pt.get("label")]
                if labels:
                    max_num = 0
                    prefix = "test_pt"
                    for l in labels:
                        m = re.search(r'(.*?)(\d+)$', l)
                        if m:
                            prefix = m.group(1)
                            max_num = max(max_num, int(m.group(2)))
                    if max_num > 0:
                        initial_label = f"{prefix}{max_num + 1:02d}"

            self._panel.setup_test_collect_mode(initial_label, self._live_beacon_id, self._calib_target_packets)
            self._canvas._test_collect_mode = True

            self._panel._btn_start_collect.clicked.connect(self._start_test_collect)
            self._panel._btn_save_calib.clicked.connect(self._save_test_point)
            self._panel._btn_repeat.clicked.connect(self._repeat_test_collect)
            self._panel._btn_next.clicked.connect(self._next_test_point)
            self._panel._btn_cancel_calib.clicked.connect(self.close)

            self._canvas.position_picked.connect(self._on_picked)

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

        self._live_thread = None
        self._live_window_sec = 7.0
        self._last_radar_update = 0.0
        self._last_ui_update = 0.0

        if self._calibrate_mode:
            self._panel.setup_calibration_mode(self._calib_label, self._calib_beacons, self._calib_target_packets)
            self._canvas._calibrate_mode = True
            self._canvas._calib_beacons = self._calib_beacons
            self._canvas._calib_label = self._calib_label
            self._canvas._calib_target_packets = self._calib_target_packets

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
            for bid, chk in self._panel._radar_checkboxes.items():
                chk.stateChanged.connect(lambda state, b=bid: self._on_radar_vis_toggled(b, state))

            if self._grid_collect_mode:
                self._panel._btn_save_calib.clicked.connect(self._save_grid_point)
                self._panel._btn_force_save.clicked.connect(self._save_grid_point)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
                self._load_grid_point(0)
                self._start_live()
            else:
                self._panel._btn_save_calib.clicked.connect(self._save_and_exit)
                self._panel._btn_force_save.clicked.connect(self._force_save)
                self._panel._btn_cancel_calib.clicked.connect(self.close)
                self._start_live()
        elif self._test_collect_mode:
            self._start_live()
        else:
            self._panel._chk_beacons.toggled.connect(self._on_toggle_beacons)
            self._panel._chk_live.toggled.connect(self._on_toggle_live)
            self._panel._spin_window.valueChanged.connect(self._on_window_sec_changed)

    # ── Handlery i metody zdarzeń ─────────────────────────────────────────────

    def _on_toggle_radar_beacon(self, bid, checked):
        if checked:
            self._canvas._visible_radar_beacons.add(bid)
        else:
            self._canvas._visible_radar_beacons.discard(bid)
        self._canvas.update()

    def _on_picked(self, a: float, b: float):
        """Obsługuje kliknięcie na mapie (mark_origin lub pick)."""
        self._picked = (a, b)
        if self._test_collect_mode:
            self._panel._lbl_coords.setText(f"X = {a:.3f} m\nY = {b:.3f} m")
            self._panel._btn_start_collect.setEnabled(True)
            self._sb.showMessage(f"Wybrano pozycję: X={a:.3f} m, Y={b:.3f} m. Wciśnij 'Rozpocznij zbieranie'.")

            sx, sy = physical_to_svg(a, b)
            self._canvas._radar_center_svg = QPointF(sx, sy)
            self._canvas.update()
            return

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
        """Zatwierdza współrzędne i zamyka program."""
        if self._picked is None:
            self._sb.showMessage('Najpierw kliknij na mapie!')
            return
        a, b = self._picked
        if self._mark_origin_mode:
            calib = {"origin_x_svg": a, "origin_y_svg": b, "scale": SCALE,
                     "_note": "SVG 1 unit = 1 mm, SCALE = 1000 units/metr"}
            os.makedirs(os.path.dirname(SVG_CALIB_PATH), exist_ok=True)
            with open(SVG_CALIB_PATH, 'w', encoding='utf-8') as f:
                json.dump(calib, f, indent=2)
            print(json.dumps({'svg_x': a, 'svg_y': b, 'saved': True}), flush=True)
        else:
            print(json.dumps({'x_m': a, 'y_m': b, 'picked': True}), flush=True)
        self.close()

    def _start_test_collect(self):
        """Uruchamia zbieranie ramek dla punktu testowego."""
        try:
            if self._picked is None:
                return

            self._calib_target_packets = self._panel._spin_packets.value()
            self._test_beacon_id = self._panel._spin_beacon.value()
            self._calib_beacons = [{"id": self._test_beacon_id, "x": self._picked[0], "y": self._picked[1]}]
            self._canvas._calib_beacons = self._calib_beacons
            self._canvas._calib_target_packets = self._calib_target_packets
            self._canvas._calib_label = self._panel._edit_label.text().strip() or "test_pt"
            self._canvas._visible_radar_beacons = {self._test_beacon_id, str(self._test_beacon_id)}

            self._calib_rssi_accum = {}
            self._canvas._radar_rssi_data = {}
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
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._sb.showMessage(f"Błąd startu: {e}")

    def _save_test_point(self):
        """Uśrednia, normalizuje i zapisuje punkt testowy do test_set.json."""
        try:
            target_pkts = self._calib_target_packets
            bid_str = str(self._test_beacon_id)

            result = process_multi_beacon(self._calib_rssi_accum, [bid_str], target_pkts)
            if bid_str not in result:
                self._sb.showMessage("Brak danych do zapisu!")
                return

            x_global = round(self._picked[0], 4)
            y_global = round(self._picked[1], 4)

            ox = getattr(self, '_session_ox', 0.0)
            oy = getattr(self, '_session_oy', 0.0)
            sess_label = getattr(self, '_session_label', 'unknown')

            x_local = round(x_global - ox, 4)
            y_local = round(y_global - oy, 4)

            label = self._panel._edit_label.text().strip() or "test_pt"

            new_point = {
                "label":   label,
                "x_true":  x_global,
                "y_true":  y_global,
                "_local":  {"x": x_local, "y": y_local, "session": sess_label},
                "beacons": result,
            }

            from validate import load_test_set, save_test_set
            existing = [tp for tp in load_test_set() if tp.get("label") != label]
            existing.append(new_point)
            save_test_set(existing)

            self._sb.showMessage(f"Zapisano punkt testowy '{label}'! Razem: {len(existing)}")
            self._panel._lbl_progress.setText(f"Zapisano: {label} ({x_global}, {y_global}) m")

            self._panel._btn_save_calib.setEnabled(False)
            self._panel._btn_repeat.setEnabled(True)
            self._panel._btn_next.setEnabled(True)

            self._canvas._test_points = existing
            self._canvas.update()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._sb.showMessage(f"Błąd zapisu: {e}")

    def _repeat_test_collect(self):
        """Resetuje stan zbierania w celu powtórzenia pomiaru."""
        try:
            self._panel._edit_label.setEnabled(True)
            self._panel._spin_beacon.setEnabled(True)
            self._panel._spin_packets.setEnabled(True)
            self._panel._btn_start_collect.setEnabled(True)
            self._panel._btn_start_collect.setText("Rozpocznij zbieranie")
            self._panel._btn_repeat.setEnabled(False)
            self._panel._btn_next.setEnabled(False)
            self._panel._btn_save_calib.setEnabled(False)
            self._panel._lbl_progress.setText("Wciśnij Start, aby powtórzyć")
            self._panel._progress_bar.setValue(0)
            self._collecting_active = False
            self._calib_rssi_accum = {}
            self._canvas._radar_rssi_data = {}
            self._canvas.set_radar_data({})
            self._canvas.update()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._sb.showMessage(f"Błąd powtórzenia: {e}")

    def _next_test_point(self):
        """Przechodzi do kolejnego punktu testowego (inkrementacja etykiety)."""
        try:
            old_label = self._panel._edit_label.text().strip()
            new_label = self._increment_label(old_label)

            self._panel._edit_label.setText(new_label)
            self._panel._edit_label.setEnabled(True)
            self._panel._spin_beacon.setEnabled(True)
            self._panel._spin_packets.setEnabled(True)

            self._picked = None
            self._canvas._picked_svg_x = None
            self._canvas._picked_svg_y = None
            self._panel._lbl_coords.setText("Kliknij na mapie...")

            self._panel._btn_start_collect.setEnabled(False)
            self._panel._btn_start_collect.setText("Rozpocznij zbieranie")
            self._panel._btn_repeat.setEnabled(False)
            self._panel._btn_next.setEnabled(False)
            self._panel._btn_save_calib.setEnabled(False)
            self._panel._lbl_progress.setText("Wybierz pozycję i wciśnij Start")
            self._panel._progress_bar.setValue(0)

            self._collecting_active = False
            self._calib_rssi_accum = {}
            self._canvas._radar_rssi_data = {}
            self._canvas.set_radar_data({})
            self._canvas.update()

            self._sb.showMessage(f"Przygotowano kolejny punkt: {new_label}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._sb.showMessage(f"Błąd kolejnego punktu: {e}")

    def _increment_label(self, label: str) -> str:
        match = re.search(r'(.*?)(\d+)$', label)
        if match:
            prefix = match.group(1)
            num_str = match.group(2)
            length = len(num_str)
            num = int(num_str) + 1
            return f"{prefix}{num:0{length}d}"
        return f"{label}_next"

    def _on_frame_received(self, beacon_id: int, char_int: int, rssi: float):
        """Odbiera pakiety z LiveThread w trybie kalibracji/zbierania testowego."""
        if not getattr(self, '_collecting_active', True):
            return

        bid_str = str(beacon_id)
        b_data = self._calib_rssi_accum.setdefault(bid_str, {})
        b_data.setdefault(char_int, []).append(rssi)

        target_bids = [str(b['id']) for b in self._calib_beacons]
        if bid_str not in target_bids:
            return

        target_pkts = self._calib_target_packets
        num_beacons = len(self._calib_beacons)
        total_target = target_pkts * num_beacons

        total_collected = 0
        done_beacons = 0
        for b_str in target_bids:
            b_acc = self._calib_rssi_accum.get(b_str, {})
            c = sum(len(b_acc.get(ch, [])) for ch in VALID_CHARS)
            total_collected += min(target_pkts, c)

            has_all_dirs = all(len(b_acc.get(ch, [])) > 0 for ch in VALID_CHARS)
            if c >= target_pkts and (has_all_dirs or c >= target_pkts * 1.5):
                done_beacons += 1

        is_done = (done_beacons >= num_beacons)

        import time
        now = time.time()
        # Ograniczenie odświeżania GUI do 10 Hz
        if not is_done and (now - getattr(self, '_last_ui_update', 0.0) < 0.1):
            return
        self._last_ui_update = now

        # Wygeneruj uśrednione dane do radaru chart
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
        """Zamyka tryb kalibracji pojedynczej z wypisaniem pomiaru na stdout."""
        target_pkts = self._calib_target_packets
        target_bids = [str(b['id']) for b in self._calib_beacons]
        result = process_multi_beacon(self._calib_rssi_accum, target_bids, target_pkts)
        print(json.dumps(result), flush=True)
        self.close()

    def _force_save(self):
        """Zapisuje dane zebrane do tej pory."""
        if not self._calib_rssi_accum:
            self._sb.showMessage("Brak zebranych danych! Nie można zapisać.")
            return
        self._save_and_exit()

    def _start_collect_current_point(self):
        """Rozpoczyna zbieranie dla bieżącego punktu siatki."""
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
        """Przechodzi do kolejnego punktu siatki (pomiń)."""
        next_idx = self._grid_idx + 1
        if next_idx < len(self._grid_data['points']):
            self._load_grid_point(next_idx)
        else:
            self.close()

    def _go_to_previous_point(self):
        """Cofa do poprzedniego punktu siatki, usuwając go z bazy danych."""
        if self._grid_idx <= 0:
            return

        prev_idx = self._grid_idx - 1
        prev_pt = self._grid_data['points'][prev_idx]
        prev_label = prev_pt['label']

        try:
            from wknn import load_radio_map, save_radio_map
            existing_db = load_radio_map()
        except ImportError:
            existing_db = []

        if existing_db:
            prev_beacons = prev_pt.get('beacons', [])
            labels_to_remove = {prev_label}
            if isinstance(prev_beacons, list) and len(prev_beacons) > 1:
                for b in prev_beacons:
                    labels_to_remove.add(f"{prev_label}_{b['id']}")
            new_db = [pt for pt in existing_db if pt.get("label") not in labels_to_remove]
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
        """Uśrednia, normalizuje i zapisuje punkt siatki do radio_map.json."""
        target_pkts = self._calib_target_packets
        target_bids = [str(b['id']) for b in self._calib_beacons]
        result = process_multi_beacon(self._calib_rssi_accum, target_bids, target_pkts)

        if not result:
            self._sb.showMessage("Brak danych do zapisu!")
            return

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
                "label": f"{self._calib_label}_{bid}" if len(self._calib_beacons) > 1 else self._calib_label,
                "x_m": b_global_x,
                "y_m": b_global_y,
                "_local": {
                    "x": pt_info['x_local'],
                    "y": pt_info['y_local'],
                    "session": self._grid_data["origin_label"]
                },
                "beacons": {
                    bid_str: stats
                },
                "timestamp": datetime.datetime.now().isoformat()
            }
            if self._grid_data.get("tripod"):
                tripod = self._grid_data["tripod"]
                pt["_tripod"] = {
                    "base_label": self._calib_label,
                    "beacon_id": bid,
                    "spacing_m": tripod["spacing_m"],
                    "angle_deg": tripod["angle_deg"]
                }

            replaced = False
            for idx_e, existing_pt in enumerate(existing_db):
                if (existing_pt.get("x_m") == b_global_x
                        and existing_pt.get("y_m") == b_global_y
                        and "beacons" in existing_pt
                        and bid_str in existing_pt["beacons"]):
                    existing_db[idx_e] = pt
                    replaced = True
                    break
            if not replaced:
                existing_db.append(pt)

        try:
            save_radio_map(existing_db)
        except Exception:
            pass

        self._sb.showMessage(f"Zapisano punkt {self._calib_label}.")
        self._skip_grid_point()

    def _load_grid_point(self, idx):
        """Ładuje dane podanego indeksu z planu siatki i aktualizuje panel/płótno."""
        if not self._grid_data or idx >= len(self._grid_data['points']):
            return False

        self._grid_idx = idx
        pt = self._grid_data['points'][idx]
        self._calib_label = pt['label']
        self._calib_beacons = pt['beacons']
        self._calib_target_packets = self._grid_data.get('target_packets', DEFAULT_TARGET_PACKETS)

        self._calib_rssi_accum = {}
        self._canvas._radar_rssi_data = {}
        self._canvas.set_radar_data({})

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
        self._canvas._selected_labels.clear()
        self._on_selection_changed()
        self._canvas.update()

    def _confirm_select(self):
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

    # ── Zarządzanie wątkiem live ──────────────────────────────────────────────

    def _on_toggle_beacons(self, checked: bool):
        self._canvas._show_fingerprints = checked
        self._canvas.update()

    def _on_toggle_live(self, checked: bool):
        if checked:
            self._start_live()
        else:
            self._stop_live()

    def _start_live(self):
        if self._live_thread is not None:
            return

        # Pobierz parametry połączenia z konfiguracji EsparClient
        client = EsparClient()
        self._live_thread = LiveThread(
            self, host=client.host, port=client.port, timeout=client.timeout
        )
        self._live_thread.BEACON_ID = getattr(self, '_live_beacon_id', DEFAULT_BEACON_ID)
        self._live_thread.WINDOW_SEC = getattr(self, '_live_window_sec', 7.0)

        if self._calibrate_mode or self._test_collect_mode:
            self._live_thread.calibrate_mode = True
            self._live_thread.frame_received.connect(self._on_frame_received)
        else:
            self._live_thread.position.connect(self.update_position)

        self._live_thread.status_msg.connect(self._on_live_status)
        self._live_thread.finished.connect(self._on_live_finished)
        self._live_thread.start()

        if self._calibrate_mode or self._test_collect_mode:
            self._sb.showMessage('Uruchamianie strumienia kalibracji…')
        else:
            self._sb.showMessage('Uruchamianie pozycjonowania na żywo…')

    def _on_window_sec_changed(self, val: int):
        self._live_window_sec = float(val)
        if self._live_thread is not None:
            self._live_thread.WINDOW_SEC = float(val)

    def _stop_live(self):
        if self._live_thread is None:
            return
        self._live_thread.requestInterruption()
        self._live_thread.wait(3000)
        self._live_thread = None

        self._canvas._bx = None
        self._canvas._by = None
        self._canvas._trail.clear()
        self._canvas.update()
        self._panel.refresh(0, 0, 0, 0, None, 0)
        self._sb.showMessage('Pozycjonowanie na żywo zatrzymane')

    def _on_live_status(self, msg: str):
        self._sb.showMessage(msg)

    def _on_live_finished(self):
        self._live_thread = None
        if hasattr(self._panel, '_chk_live') and self._panel._chk_live is not None:
            try:
                self._panel._chk_live.blockSignals(True)
                self._panel._chk_live.setChecked(False)
                self._panel._chk_live.blockSignals(False)
            except RuntimeError:
                pass

    def closeEvent(self, event):
        self._stop_live()
        super().closeEvent(event)

    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {C_BG.name()}; }}
            QStatusBar  {{ color: {C_MUTED.name()}; font-size: 11px; }}
        """)

    # ── Wątkowo-bezpieczne API pozycji ────────────────────────────────────────

    def update_position(self, x_m: float, y_m: float,
                        beacon_id=None, confidence: float = 1.0):
        """Bezpieczne wywołanie aktualizacji pozycji z zewnętrznego wątku."""
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
