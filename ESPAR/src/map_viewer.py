"""
map_viewer.py — Wrapper kompatybilności wstecznej dla interfejsu GUI ESPAR IPS.

Plik ten stanowi punkt wejścia do wizualizacji graficznej systemu.
Cała logika interfejsu została przeniesiona do pakietu `gui/` w ramach refaktoryzacji,
a ten plik zachowuje pełne wsparcie dla parametrów linii komend wywoływanych
przez main.py, calibration.py oraz validate.py.
"""

import sys
import json
from PyQt6.QtWidgets import QApplication

from config import SVG_PATH, DEFAULT_BEACON_ID, DEFAULT_TARGET_PACKETS
from gui.window import MapWindow


def launch_viewer(svg_path: str = SVG_PATH) -> MapWindow:
    """Kompatybilne API uruchamiania okna mapy (używane przez zewnętrzne moduły)."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MapWindow(svg_path)
    win.show()
    return win


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')

        # --calibrate <label> <beacons_json> [target_packets]
        if '--calibrate' in sys.argv:
            idx = sys.argv.index('--calibrate')
            label = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else 'punkt'
            b_json = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else '[{"id": 28, "x": 0.0, "y": 0.0}]'
            target_pkts = int(sys.argv[idx + 3]) if idx + 3 < len(sys.argv) else DEFAULT_TARGET_PACKETS
            try:
                beacons = json.loads(b_json)
            except Exception:
                beacons = [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]
            win = MapWindow(calibrate_mode=True, calib_label=label, calib_beacons=beacons, calib_target_packets=target_pkts)
            win.show()
            sys.exit(app.exec())

        # --test_collect <beacon_id> [target_packets]
        if '--test_collect' in sys.argv:
            idx = sys.argv.index('--test_collect')
            beacon_id = DEFAULT_BEACON_ID
            target_pkts = DEFAULT_TARGET_PACKETS
            if idx + 1 < len(sys.argv):
                try:
                    beacon_id = int(sys.argv[idx + 1])
                except ValueError:
                    pass
            if idx + 2 < len(sys.argv):
                try:
                    target_pkts = int(sys.argv[idx + 2])
                except ValueError:
                    pass
            win = MapWindow(test_collect_mode=True, live_beacon_id=beacon_id, calib_target_packets=target_pkts)
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

        # --view [beacon_id] : podgląd bazy punktów kalibracyjnych
        if '--view' in sys.argv:
            idx = sys.argv.index('--view')
            beacon_id = DEFAULT_BEACON_ID
            if idx + 1 < len(sys.argv):
                try:
                    beacon_id = int(sys.argv[idx + 1])
                except ValueError:
                    pass
            win = MapWindow(show_points=True, live_beacon_id=beacon_id)
            win.show()
            sys.exit(app.exec())

        # --select-points : graficzny wybór wielu punktów
        if '--select-points' in sys.argv:
            win = MapWindow(select_mode=True)
            win.show()
            sys.exit(app.exec())

        # --pick (legacy)
        if '--pick' in sys.argv:
            win = MapWindow(pick_mode=True)
            win.show()
            sys.exit(app.exec())

        # Domyślny start (bez parametrów) -> mapa z możliwością włączenia pozycjonowania live
        win = MapWindow()
        win.show()
        sys.exit(app.exec())

    except SystemExit:
        pass
    except Exception as e:
        print(f'[!] Błąd map_viewer wrapper: {e}', file=sys.stderr)
        sys.exit(0)
