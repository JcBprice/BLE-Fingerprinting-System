"""
panel.py — Panel boczny interfejsu wizualizacji ESPAR.

Klasa InfoPanel wyświetla status pozycjonowania (śledzony obiekt,
współrzędne w metrach, pewność estymacji) oraz udostępnia kontrolki
w zależności od trybu pracy:
    - Tryb live (śledzenie na żywo, opcje widoku, zoom)
    - Tryb kalibracji (postęp zbierania, lista beaconów, przyciski akcji)
    - Tryb punktów testowych (postęp, wprowadzanie etykiety, przyciski akcji)
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QProgressBar, QLineEdit, QSpinBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from gui.styles import (
    C_PANEL, C_PANEL2, C_BORDER, C_ACCENT, C_DOT, C_TEXT,
    C_MUTED, C_SUCCESS,
)
from config import VALID_CHARS


class InfoPanel(QFrame):
    """Panel boczny z informacjami o pozycji i przyciskami kontrolnymi."""

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

        # Tytuł aplikacji
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

        # Sekcja: Śledzony obiekt
        lay.addSpacing(14)
        lay.addWidget(self._section_label('ŚLEDZONY OBIEKT'))
        lay.addSpacing(8)
        self._lbl_id = self._value_label('—')
        self._lbl_id.setFont(QFont('Segoe UI', 20, QFont.Weight.Bold))
        self._lbl_id.setStyleSheet(f'color: {C_DOT.name()};')
        lay.addWidget(self._lbl_id)

        lay.addSpacing(18)
        lay.addWidget(self._divider())

        # Sekcja: Współrzędne
        lay.addSpacing(14)
        lay.addWidget(self._section_label('POZYCJA (METRY)'))
        lay.addSpacing(8)
        self._lbl_x = self._coord_row(lay, 'X (wzdłuż)')
        self._lbl_y = self._coord_row(lay, 'Y (w poprzek)')

        lay.addSpacing(18)
        lay.addWidget(self._divider())

        # Sekcja: Pewność
        lay.addSpacing(14)
        lay.addWidget(self._section_label('PEWNOŚĆ'))
        lay.addSpacing(6)
        self._lbl_conf = self._value_label('—')
        self._lbl_conf.setFont(QFont('JetBrains Mono', 14, QFont.Weight.Medium))
        lay.addWidget(self._lbl_conf)

        # Pasek postępu pewności (Confidence bar)
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

        # Sekcja: Współrzędne SVG (do debugowania)
        lay.addSpacing(14)
        lay.addWidget(self._section_label('SVG UNITS'))
        lay.addSpacing(6)
        self._lbl_svg = QLabel('—')
        self._lbl_svg.setFont(QFont('Cascadia Code', 9))
        self._lbl_svg.setWordWrap(True)
        self._lbl_svg.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(self._lbl_svg)

        lay.addStretch()

        # Przyciski widoku na dole
        lay.addWidget(self._divider())
        lay.addSpacing(12)
        lay.addWidget(self._section_label('WIDOK'))
        lay.addSpacing(6)
        self._btn_fit = self._btn('Dopasuj (F)')
        lay.addWidget(self._btn_fit)
        lay.addSpacing(6)
        self._btn_clear = self._btn('Wyczyść ślad')
        lay.addWidget(self._btn_clear)

        # Sekcja: Opcje (checkboxy)
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

        # Sekcja: Parametry (Czas okna)
        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(12)
        lay.addWidget(self._section_label('PARAMETRY'))
        lay.addSpacing(6)

        lay.addWidget(self._sub_label('Rozmiar okna [s]:'))
        lay.addSpacing(4)
        self._spin_window = QSpinBox()
        self._spin_window.setRange(1, 60)
        self._spin_window.setValue(7)
        self._spin_window.setStyleSheet(f"""
            QSpinBox {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 4px;
                padding: 4px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }}
        """)
        lay.addWidget(self._spin_window)

    # ── Elementy pomocnicze UI ────────────────────────────────────────────────

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

    def _sub_label(self, txt):
        l = QLabel(txt)
        l.setFont(QFont('Segoe UI', 8))
        l.setStyleSheet(f'color: {C_MUTED.name()};')
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

    # ── Metody aktualizacji ───────────────────────────────────────────────────

    def refresh(self, x_m, y_m, svg_x, svg_y, beacon_id, confidence):
        """Aktualizuje wartości w panelu bocznym."""
        try:
            if not hasattr(self, '_lbl_id') or self._lbl_id is None:
                return
            id_txt = f'#{beacon_id}' if beacon_id is not None else '—'
            self._lbl_id.setText(id_txt)
            self._lbl_x.setText(f'{x_m:.2f} m')
            self._lbl_y.setText(f'{y_m:.2f} m')
            pct = int(confidence * 100)
            self._lbl_conf.setText(f'{pct} %')
            bar_w = int(160 * confidence)
            self._conf_bar.setFixedWidth(bar_w)
            self._lbl_svg.setText(f'x={svg_x:.0f}\ny={svg_y:.0f}')
        except RuntimeError:
            pass

    def setup_test_collect_mode(self, label="test_pt01", beacon_id=28, target_packets=100):
        """Przebudowuje panel pod tryb graficznego zbierania punktów testowych."""
        # Wyczyść panel
        while self.layout().count():
            item = self.layout().takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        lay = self.layout()

        title = QLabel('📡  ESPAR IPS')
        title.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        title.setStyleSheet(f'color: {C_ACCENT.name()};')
        lay.addWidget(title)
        lay.addSpacing(4)

        sub = QLabel('Punkty Testowe (Ground Truth)')
        sub.setFont(QFont('Segoe UI', 8))
        sub.setStyleSheet(f'color: {C_MUTED.name()};')
        lay.addWidget(sub)

        lay.addSpacing(15)
        lay.addWidget(self._divider())
        lay.addSpacing(10)

        # Sekcja: Etykieta punktu
        lay.addWidget(self._section_label('ETYKIETA PUNKTU'))
        lay.addSpacing(4)
        self._edit_label = QLineEdit(label)
        self._edit_label.setStyleSheet(f"""
            QLineEdit {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 4px;
                padding: 6px;
                font-family: 'Segoe UI';
                font-size: 12px;
            }}
        """)
        lay.addWidget(self._edit_label)
        lay.addSpacing(10)

        # Sekcja: Beacon ID
        lay.addWidget(self._section_label('BEACON ID'))
        lay.addSpacing(4)
        self._spin_beacon = QSpinBox()
        self._spin_beacon.setRange(1, 1000)
        self._spin_beacon.setValue(beacon_id)
        self._spin_beacon.setStyleSheet(f"""
            QSpinBox {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 4px;
                padding: 6px;
                font-family: 'Segoe UI';
                font-size: 12px;
            }}
        """)
        lay.addWidget(self._spin_beacon)
        lay.addSpacing(10)

        # Sekcja: Pakiety na beacon
        lay.addWidget(self._section_label('PAKIETY NA BEACON'))
        lay.addSpacing(4)
        self._spin_packets = QSpinBox()
        self._spin_packets.setRange(1, 10000)
        self._spin_packets.setValue(target_packets)
        self._spin_packets.setStyleSheet(f"""
            QSpinBox {{
                background: {C_PANEL2.name()};
                color: {C_TEXT.name()};
                border: 1px solid {C_BORDER.name()};
                border-radius: 4px;
                padding: 6px;
                font-family: 'Segoe UI';
                font-size: 12px;
            }}
        """)
        lay.addWidget(self._spin_packets)
        lay.addSpacing(10)

        # Sekcja: Prawdziwa pozycja
        lay.addWidget(self._section_label('PRAWDZIWA POZYCJA'))
        lay.addSpacing(4)
        self._lbl_coords = QLabel("Kliknij na mapie...")
        self._lbl_coords.setFont(QFont('JetBrains Mono', 10))
        self._lbl_coords.setStyleSheet(f'color: {C_TEXT.name()};')
        lay.addWidget(self._lbl_coords)
        lay.addSpacing(10)

        lay.addWidget(self._divider())
        lay.addSpacing(10)

        # Sekcja: Postęp zbierania
        lay.addWidget(self._section_label('POSTĘP ZBIERANIA'))
        lay.addSpacing(6)
        self._lbl_progress = QLabel("Wybierz pozycję i wciśnij Start")
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
        lay.addSpacing(10)

        # Sekcja: Akcje
        lay.addWidget(self._section_label('AKCJE'))
        lay.addSpacing(8)

        # Przycisk start
        self._btn_start_collect = QPushButton("Rozpocznij zbieranie")
        self._btn_start_collect.setStyleSheet(f"""
            QPushButton {{
                background: {C_ACCENT.name()};
                color: white;
                border: 1px solid {C_BORDER.name()};
                border-radius: 5px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #2563eb;
            }}
            QPushButton:disabled {{
                background: #1e293b;
                color: #64748b;
                border: 1px solid #334155;
            }}
        """)
        self._btn_start_collect.setEnabled(False)
        lay.addWidget(self._btn_start_collect)
        lay.addSpacing(8)

        # Przycisk Zapisz
        self._btn_save_calib = QPushButton('Zapisz odcisk')
        self._btn_save_calib.setEnabled(False)
        self._btn_save_calib.setStyleSheet(
            'QPushButton { background: #1e293b; color: #64748b; '
            'border: 1px solid #334155; border-radius: 5px; padding: 10px; font-size: 12px; font-weight: bold; }'
        )
        lay.addWidget(self._btn_save_calib)
        lay.addSpacing(8)

        # Przycisk Powtórz
        self._btn_repeat = QPushButton('Powtórz pomiar')
        self._btn_repeat.setEnabled(False)
        self._btn_repeat.setStyleSheet(f"""
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
            QPushButton:disabled {{
                background: #1e293b;
                color: #64748b;
                border: 1px solid #334155;
            }}
        """)
        lay.addWidget(self._btn_repeat)
        lay.addSpacing(8)

        # Przycisk Kolejny
        self._btn_next = QPushButton('Kolejny punkt')
        self._btn_next.setEnabled(False)
        self._btn_next.setStyleSheet(f"""
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
            QPushButton:disabled {{
                background: #1e293b;
                color: #64748b;
                border: 1px solid #334155;
            }}
        """)
        lay.addWidget(self._btn_next)
        lay.addSpacing(8)

        # Przycisk Zakończ
        self._btn_cancel_calib = QPushButton('Zakończ')
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

    def setup_calibration_mode(self, label, calib_beacons, target_packets=100):
        """Przebudowuje panel pod tryb kalibracji (fingerprintingu)."""
        # Wyczyść panel
        while self.layout().count():
            item = self.layout().takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        lay = self.layout()

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
