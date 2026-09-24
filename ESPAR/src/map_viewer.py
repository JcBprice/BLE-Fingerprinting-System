"""Punkt wejścia CLI dla wizualizacji graficznej GUI ESPAR (PyQt6)."""

import json
import sys

from PyQt6.QtWidgets import QApplication

from config import DEFAULT_BEACON_ID, DEFAULT_TARGET_PACKETS, SVG_PATH
from gui.window import MapWindow


# Pomocnicza funkcja otwierająca okno podglądu mapy w istniejącej lub nowej instancji QApplication.
def launch_viewer(svg_path: str = SVG_PATH) -> MapWindow:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MapWindow(svg_path)
    win.show()
    return win


if __name__ == '__main__':
    def g(idx, default, cast=str):
        try:
            return cast(sys.argv[idx]) if idx < len(sys.argv) else default
        except Exception:
            return default

    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')

        # Parsujemy flagi wiersza poleceń uruchamiające GUI w odpowiednim trybie pracy
        win = None
        for i, a in enumerate(sys.argv):
            bid = g(i+1, DEFAULT_BEACON_ID, int)
            pkts = g(i+2, DEFAULT_TARGET_PACKETS, int)

            if a == '--calibrate':
                try:
                    bcs = json.loads(g(i+2, '[{"id": 28, "x": 0.0, "y": 0.0}]'))
                except Exception:
                    bcs = [{"id": DEFAULT_BEACON_ID, "x": 0.0, "y": 0.0}]
                win = MapWindow(calibrate_mode=True, calib_label=g(i+1, 'punkt'), calib_beacons=bcs, calib_target_packets=g(i+3, DEFAULT_TARGET_PACKETS, int))
                break
            elif a in ('--multi_plan', '--plan_points'):
                win = MapWindow(plan_points_mode=True, live_beacon_id=bid, calib_target_packets=pkts)
                break
            elif a in ('--fingerprint_collect', '--single_calibrate'):
                win = MapWindow(fingerprint_collect_mode=True, live_beacon_id=bid, calib_target_packets=pkts)
                break
            elif a == '--test_collect':
                win = MapWindow(test_collect_mode=True, live_beacon_id=bid, calib_target_packets=pkts)
                break
            elif a == '--grid_collect':
                win = MapWindow(grid_collect_mode=True, grid_json_path=g(i+1, ''))
                break
            elif a in ('--pick-session', '--pick'):
                win = MapWindow(pick_mode=True)
                break
            elif a == '--mark-origin':
                win = MapWindow(mark_origin_mode=True)
                break
            elif a == '--view':
                win = MapWindow(show_points=True, live_beacon_id=bid)
                break
            elif a == '--select-points':
                win = MapWindow(select_mode=True, live_beacon_id=bid)
                break

        if not win:
            win = MapWindow()
        win.show()
        sys.exit(app.exec())

    except SystemExit:
        pass
    except Exception as e:
        print(f'[!] Błąd map_viewer wrapper: {e}', file=sys.stderr)
        sys.exit(0)
