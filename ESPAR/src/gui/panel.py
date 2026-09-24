"""Panel boczny interfejsu GUI ESPAR (statystyki, kontrolki trybów i paski postępu)."""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from gui.styles import (
    C_ACCENT,
    C_BORDER,
    C_DOT,
    C_MUTED,
    C_PANEL,
    C_PANEL2,
    C_SUCCESS,
    C_TEXT,
)

# Style arkuszy CSS dla kontrolek panelu bocznego
_S_SPIN = f"""
    QSpinBox {{
        background: {C_PANEL2.name()}; color: {C_TEXT.name()};
        border: 1px solid {C_BORDER.name()}; border-radius: 4px;
        padding: 4px; font-family: 'Segoe UI'; font-size: 11px;
    }}
"""
_S_EDIT = f"""
    QLineEdit {{
        background: {C_PANEL2.name()}; color: {C_TEXT.name()};
        border: 1px solid {C_BORDER.name()}; border-radius: 4px;
        padding: 5px; font-family: 'Segoe UI'; font-size: 11px;
    }}
"""
_S_CHK = f"""
    QCheckBox {{
        color: {C_TEXT.name()}; font-size: 11px; spacing: 6px;
        background: transparent; border: none;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1px solid {C_BORDER.name()};
        border-radius: 3px; background: {C_PANEL2.name()};
    }}
    QCheckBox::indicator:checked {{
        background: {C_ACCENT.name()}; border-color: {C_ACCENT.name()};
    }}
"""
_S_PROGRESS = f"""
    QProgressBar {{
        background: {C_PANEL2.name()}; border: 1px solid {C_BORDER.name()};
        border-radius: 4px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {C_SUCCESS.name()}; border-radius: 3px; }}
"""


class InfoPanel(QFrame):
    """Boczny panel sterujący i informacyjny GUI ze statystykami i przełączaniem widoków."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet(f"""
            QFrame {{ background: {C_PANEL.name()}; border-right: 1px solid {C_BORDER.name()}; }}
            QLabel {{ color: {C_TEXT.name()}; background: transparent; border: none; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(0)
        self._init_live_ui()

    # Usuwa wszystkie kontrolki z panelu przed przełączeniem do innego trybu.
    def _clear_layout(self):
        lay = self.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _divider(self):
        d = QFrame()
        d.setFixedHeight(1)
        d.setStyleSheet(f"background: {C_BORDER.name()};")
        return d

    def _sec_label(self, txt):
        lbl = QLabel(txt)
        lbl.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {C_MUTED.name()}; letter-spacing: 1px;")
        return lbl

    _section_label = _sec_label

    def _sub_label(self, txt):
        lbl = QLabel(txt)
        lbl.setFont(QFont("Segoe UI", 8))
        lbl.setStyleSheet(f"color: {C_MUTED.name()};")
        return lbl

    def _make_btn(self, txt, bg=C_PANEL2.name(), fg=C_TEXT.name(), border=C_BORDER.name(), bold=False, pad=6):
        b = QPushButton(txt)
        weight = "bold" if bold else "normal"
        b.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg}; border: 1px solid {border};
                border-radius: 5px; padding: {pad}px; font-size: 11px; font-weight: {weight};
            }}
            QPushButton:hover {{ background: {C_BORDER.name()}; border-color: {C_ACCENT.name()}; }}
            QPushButton:disabled {{ background: #1e293b; color: #64748b; border: 1px solid #334155; }}
        """)
        return b

    def _make_spin(self, min_v, max_v, cur_v, suffix=""):
        s = QSpinBox()
        s.setRange(min_v, max_v)
        s.setValue(cur_v)
        if suffix:
            s.setSuffix(suffix)
        s.setStyleSheet(_S_SPIN)
        return s

    def _make_edit(self, txt):
        e = QLineEdit(txt)
        e.setStyleSheet(_S_EDIT)
        return e

    def _header(self, subtitle):
        lay = self.layout()
        title = QLabel("📡  ESPAR IPS")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C_ACCENT.name()};")
        lay.addWidget(title)
        lay.addSpacing(4)
        sub = QLabel(subtitle)
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet(f"color: {C_MUTED.name()};")
        lay.addWidget(sub)
        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

    # Inicjalizuje widok panelu w domyślnym trybie śledzenia na żywo (Live Tracking).
    def _init_live_ui(self):
        lay = self.layout()
        self._header("Indoor Positioning System")

        lay.addWidget(self._sec_label("ŚLEDZONY OBIEKT"))
        lay.addSpacing(6)
        self._lbl_id = QLabel("—")
        self._lbl_id.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self._lbl_id.setStyleSheet(f"color: {C_DOT.name()};")
        lay.addWidget(self._lbl_id)

        lay.addSpacing(4)
        lay.addWidget(self._sub_label("Beacon ID:"))
        lay.addSpacing(2)
        self._spin_beacon_id = self._make_spin(1, 1000, 28)
        lay.addWidget(self._spin_beacon_id)

        lay.addSpacing(16)
        lay.addWidget(self._divider())
        lay.addSpacing(12)

        lay.addWidget(self._sec_label("POZYCJA (METRY)"))
        lay.addSpacing(6)
        lay.addWidget(self._sub_label("X (wzdłuż)"))
        self._lbl_x = QLabel("—")
        self._lbl_x.setFont(QFont("JetBrains Mono", 14, QFont.Weight.Medium))
        lay.addWidget(self._lbl_x)
        lay.addSpacing(6)
        lay.addWidget(self._sub_label("Y (w poprzek)"))
        self._lbl_y = QLabel("—")
        self._lbl_y.setFont(QFont("JetBrains Mono", 14, QFont.Weight.Medium))
        lay.addWidget(self._lbl_y)

        lay.addSpacing(16)
        lay.addWidget(self._divider())
        lay.addSpacing(12)

        lay.addWidget(self._sec_label("PEWNOŚĆ"))
        lay.addSpacing(6)
        self._lbl_conf = QLabel("—")
        self._lbl_conf.setFont(QFont("JetBrains Mono", 14, QFont.Weight.Medium))
        lay.addWidget(self._lbl_conf)

        self._conf_bar = QFrame()
        self._conf_bar.setFixedHeight(4)
        self._conf_bar.setFixedWidth(0)
        self._conf_bar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #10b981, stop:1 #3b82f6);"
            "border-radius: 2px;"
        )
        bar_wrap = QFrame()
        bar_wrap.setFixedHeight(4)
        bar_wrap.setStyleSheet(f"background: {C_PANEL2.name()}; border-radius: 2px;")
        bar_lay = QHBoxLayout(bar_wrap)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.addWidget(self._conf_bar)
        bar_lay.addStretch()
        lay.addSpacing(6)
        lay.addWidget(bar_wrap)

        lay.addSpacing(16)
        lay.addWidget(self._divider())
        lay.addSpacing(12)

        lay.addWidget(self._sec_label("SVG UNITS"))
        lay.addSpacing(4)
        self._lbl_svg = QLabel("—")
        self._lbl_svg.setFont(QFont("Cascadia Code", 9))
        self._lbl_svg.setStyleSheet(f"color: {C_MUTED.name()};")
        lay.addWidget(self._lbl_svg)

        lay.addStretch()

        lay.addWidget(self._divider())
        lay.addSpacing(10)
        lay.addWidget(self._sec_label("WIDOK"))
        lay.addSpacing(6)
        self._btn_fit = self._make_btn("Dopasuj (F)")
        lay.addWidget(self._btn_fit)
        lay.addSpacing(4)
        self._btn_clear = self._make_btn("Wyczyść ślad")
        lay.addWidget(self._btn_clear)

        lay.addSpacing(12)
        lay.addWidget(self._divider())
        lay.addSpacing(10)
        lay.addWidget(self._sec_label("OPCJE"))
        lay.addSpacing(6)

        self._chk_beacons = QCheckBox("Pokaż odciski radiowe")
        self._chk_beacons.setChecked(True)
        self._chk_beacons.setStyleSheet(_S_CHK)
        lay.addWidget(self._chk_beacons)
        lay.addSpacing(4)

        self._chk_live = QCheckBox("Pozycja na żywo")
        self._chk_live.setStyleSheet(_S_CHK)
        lay.addWidget(self._chk_live)

        lay.addSpacing(12)
        lay.addWidget(self._divider())
        lay.addSpacing(10)
        lay.addWidget(self._sec_label("PARAMETRY"))
        lay.addSpacing(6)
        lay.addWidget(self._sub_label("Długość bufora [s]:"))
        lay.addSpacing(4)
        self._spin_window = self._make_spin(1, 60, 7, " s")
        self._spin_window.setToolTip("Czas trwania okna bufora przesuwnego FIFO (T w sekundach)")
        lay.addWidget(self._spin_window)

    # Aktualizuje wyświetlane współrzędne fizyczne, SVG i pasek pewności w trybie na żywo.
    def refresh(self, x_m, y_m, svg_x, svg_y, beacon_id, confidence):
        try:
            if not hasattr(self, "_lbl_id") or self._lbl_id is None:
                return
            self._lbl_id.setText(f"#{beacon_id}" if beacon_id is not None else "—")
            self._lbl_x.setText(f"{x_m:.2f} m")
            self._lbl_y.setText(f"{y_m:.2f} m")
            self._lbl_conf.setText(f"{int(confidence * 100)} %")
            self._conf_bar.setFixedWidth(int(160 * confidence))
            self._lbl_svg.setText(f"x={svg_x:.0f}\ny={svg_y:.0f}")
        except RuntimeError:
            pass

    # Przebudowuje układ panelu na potrzeby ręcznego wskazywania i zbierania punktów testowych.
    def setup_test_collect_mode(self, label="test_pt01", beacon_id=28, target_packets=100):
        self._clear_layout()
        lay = self.layout()
        self._header("Punkty Testowe (Ground Truth)")

        lay.addWidget(self._sec_label("ETYKIETA PUNKTU"))
        lay.addSpacing(4)
        self._edit_label = self._make_edit(label)
        lay.addWidget(self._edit_label)
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("BEACON ID"))
        lay.addSpacing(4)
        self._spin_beacon = self._make_spin(1, 1000, beacon_id)
        lay.addWidget(self._spin_beacon)
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("PAKIETY NA BEACON"))
        lay.addSpacing(4)
        self._spin_packets = self._make_spin(1, 10000, target_packets)
        lay.addWidget(self._spin_packets)
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("PRAWDZIWA POZYCJA"))
        lay.addSpacing(4)
        self._lbl_coords = QLabel("Kliknij na mapie...")
        self._lbl_coords.setFont(QFont("JetBrains Mono", 10))
        lay.addWidget(self._lbl_coords)
        lay.addSpacing(10)

        lay.addWidget(self._divider())
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("POSTĘP ZBIERANIA"))
        lay.addSpacing(4)
        self._lbl_progress = QLabel("Wybierz pozycję i wciśnij Start")
        self._lbl_progress.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._lbl_progress)
        lay.addSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(_S_PROGRESS)
        lay.addWidget(self._progress_bar)

        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("AKCJE"))
        lay.addSpacing(6)
        self._btn_start_collect = self._make_btn("Rozpocznij zbieranie", bg=C_ACCENT.name(), fg="white", bold=True, pad=9)
        self._btn_start_collect.setEnabled(False)
        lay.addWidget(self._btn_start_collect)
        lay.addSpacing(6)

        self._btn_save_calib = self._make_btn("Zapisz odcisk", bold=True, pad=9)
        self._btn_save_calib.setEnabled(False)
        lay.addWidget(self._btn_save_calib)
        lay.addSpacing(6)

        self._btn_repeat = self._make_btn("Powtórz pomiar")
        self._btn_repeat.setEnabled(False)
        lay.addWidget(self._btn_repeat)
        lay.addSpacing(6)

        self._btn_next = self._make_btn("Kolejny punkt")
        self._btn_next.setEnabled(False)
        lay.addWidget(self._btn_next)
        lay.addSpacing(6)

        self._btn_cancel_calib = self._make_btn("Zakończ", bg="#991b1b", fg="#fca5a5", border="#7f1d1d")
        lay.addWidget(self._btn_cancel_calib)
        lay.addStretch()

    def setup_single_fingerprint_mode(self, initial_label="p01", beacon_id=28, target_packets=100):
        self.setup_test_collect_mode(label=initial_label, beacon_id=beacon_id, target_packets=target_packets)

    # Przebudowuje panel pod procedurę zbierania danych kalibracyjnych dla zadanego punktu.
    def setup_calibration_mode(self, label, calib_beacons, target_packets=100):
        self._clear_layout()
        lay = self.layout()
        self._header("Tryb Kalibracji (Fingerprinting)")

        lay.addWidget(self._sec_label("AKTUALNY PUNKT"))
        self._lbl_calib_point = QLabel(f"{label}")
        self._lbl_calib_point.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._lbl_calib_point.setWordWrap(True)
        lay.addWidget(self._lbl_calib_point)
        lay.addSpacing(8)

        self._lbl_calib_coords = QLabel(f"Liczba beaconów: {len(calib_beacons)}")
        self._lbl_calib_coords.setFont(QFont("JetBrains Mono", 11))
        lay.addWidget(self._lbl_calib_coords)
        lay.addSpacing(6)

        self._lbl_calib_beacon = QLabel("Widoczne radary:")
        self._lbl_calib_beacon.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lay.addWidget(self._lbl_calib_beacon)
        lay.addSpacing(4)

        self._radar_checkboxes = {}
        for b in calib_beacons:
            chk = QCheckBox(f"Beacon #{b['id']}")
            chk.setChecked(True)
            chk.setStyleSheet(_S_CHK)
            lay.addWidget(chk)
            self._radar_checkboxes[b["id"]] = chk

        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("POSTĘP ZBIERANIA"))
        lay.addSpacing(4)
        self._lbl_progress = QLabel("Czekam na połączenie…")
        self._lbl_progress.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._lbl_progress)
        lay.addSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(_S_PROGRESS)
        lay.addWidget(self._progress_bar)

        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(12)

        lay.addWidget(self._sec_label("AKCJE"))
        lay.addSpacing(6)
        self._btn_save_calib = self._make_btn("Zapisz i zakończ", bold=True, pad=9)
        self._btn_save_calib.setEnabled(False)
        lay.addWidget(self._btn_save_calib)
        lay.addSpacing(6)

        self._btn_force_save = self._make_btn("Zapisz teraz (wcześniej)")
        lay.addWidget(self._btn_force_save)
        lay.addSpacing(6)

        self._btn_cancel_calib = self._make_btn("Anuluj", bg="#991b1b", fg="#fca5a5", border="#7f1d1d")
        lay.addWidget(self._btn_cancel_calib)
        lay.addStretch()

    # Przebudowuje panel pod tryb interaktywnego rozplanowywania punktów pomiarowych na rzucie.
    def setup_multi_plan_mode(self, default_label="pkt_1", beacon_id=28, target_packets=100):
        self._clear_layout()
        lay = self.layout()
        self._header("Planowanie Wielu Punktów")

        lay.addWidget(self._sec_label("NASTĘPNY PUNKT"))
        lay.addSpacing(4)
        self._edit_plan_label = self._make_edit(default_label)
        lay.addWidget(self._edit_plan_label)
        lay.addSpacing(8)

        lay.addWidget(self._sec_label("BEACON ID"))
        lay.addSpacing(4)
        self._spin_plan_beacon = self._make_spin(1, 1000, beacon_id)
        lay.addWidget(self._spin_plan_beacon)
        lay.addSpacing(8)

        lay.addWidget(self._sec_label("PAKIETY NA PUNKT"))
        lay.addSpacing(4)
        self._spin_plan_packets = self._make_spin(1, 10000, target_packets)
        lay.addWidget(self._spin_plan_packets)
        lay.addSpacing(10)

        lay.addWidget(self._divider())
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("ROZPLANOWANE PUNKTY"))
        lay.addSpacing(4)
        hint = QLabel("Klikaj lewym przyciskiem na mapie, aby dodawać kolejne punkty.")
        hint.setFont(QFont("Segoe UI", 8))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C_MUTED.name()};")
        lay.addWidget(hint)
        lay.addSpacing(6)

        self._list_planned_points = QListWidget()
        self._list_planned_points.setStyleSheet(f"""
            QListWidget {{
                background: {C_PANEL2.name()}; color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()}; border-radius: 4px;
                font-family: 'JetBrains Mono', 'Segoe UI'; font-size: 11px;
            }}
            QListWidget::item:selected {{ background: {C_ACCENT.name()}; color: white; }}
        """)
        self._list_planned_points.setFixedHeight(140)
        lay.addWidget(self._list_planned_points)
        lay.addSpacing(6)

        row_btns = QHBoxLayout()
        row_btns.setSpacing(6)
        self._btn_remove_plan_pt = self._make_btn("Usuń pkt", fg="#f87171", border="#7f1d1d")
        row_btns.addWidget(self._btn_remove_plan_pt)

        self._btn_clear_plan_pts = self._make_btn("Wyczyść", fg=C_MUTED.name())
        self._btn_clear_plan = self._btn_clear_plan_pts
        row_btns.addWidget(self._btn_clear_plan_pts)
        lay.addLayout(row_btns)

        lay.addSpacing(12)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        lay.addWidget(self._sec_label("AKCJA"))
        lay.addSpacing(6)
        self._btn_start_multi_collect = self._make_btn("Rozpocznij zbieranie (0 pkt)", bg=C_SUCCESS.name(), fg="#064e3b", border="#10b981", bold=True, pad=9)
        self._btn_start_multi_collect.setEnabled(False)
        lay.addWidget(self._btn_start_multi_collect)
        lay.addSpacing(6)

        self._btn_cancel_plan = self._make_btn("Anuluj", bg="#334155", fg="#94a3b8", border="#475569")
        lay.addWidget(self._btn_cancel_plan)
        lay.addStretch()
