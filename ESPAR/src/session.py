"""Zarządzanie sesją pomiarową (zmiana pokoju i punktu odniesienia origin)."""

import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data"))


class SessionManager:
    """Zarządza punktem odniesienia (origin) aktywnej sesji/pokoju oraz historią sesji."""

    def __init__(self, data_dir: str, script_dir: str):
        self.data_dir = data_dir
        self.script_dir = script_dir
        self.session_path = os.path.join(self.data_dir, "session.json")

    def load_session(self) -> dict | None:
        try:
            with open(self.session_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if "origin_label" in data else data.get("active_session")
        except Exception:
            return None

    def save_session(self, origin_label: str, origin_x: float, origin_y: float) -> None:
        os.makedirs(self.data_dir, exist_ok=True)

        history = {}
        try:
            with open(self.session_path, encoding="utf-8") as f:
                old_data = json.load(f)
            history = old_data.get("history", {old_data.get("origin_label"): old_data} if "origin_label" in old_data else {})
        except Exception:
            pass

        active = {
            "origin_label": origin_label,
            "origin_x_m":   round(origin_x, 4),
            "origin_y_m":   round(origin_y, 4),
            "created":      datetime.now().isoformat(timespec="seconds"),
        }
        history[origin_label] = active

        with open(self.session_path, "w", encoding="utf-8") as f:
            json.dump({"active_session": active, "history": history}, f, indent=2)

    def _session_has_files(self, session_label: str) -> bool:
        for p in ["radio_map", "beacons", "test_set"]:
            if os.path.exists(os.path.join(self.data_dir, f"{p}_{session_label}.json")):
                return True
        return False

    # Uruchamia graficzne okno mapy jako podproces i przechwytuje kliknięte współrzędne z wyjścia stdout.
    def _pick_on_map(self, flag: str) -> dict | None:
        try:
            res = subprocess.run([sys.executable, os.path.join(self.script_dir, "map_viewer.py"), flag],
                                 capture_output=True, text=True, encoding="utf-8")
            for line in reversed(res.stdout.strip().splitlines()):
                if line.strip().startswith("{"):
                    return json.loads(line.strip())
        except Exception:
            pass
        return None

    # Odtwarza położenie punktu (0,0) sesji obliczając przesunięcie między współrzędnymi globalnymi i lokalnymi.
    def _get_session_origin(self, session_label: str) -> tuple[float, float] | None:
        path = os.path.join(self.data_dir, f"radio_map_{session_label}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                for pt in json.load(f):
                    if "_local" in pt and "x" in pt["_local"] and "y" in pt["_local"]:
                        gx = pt.get("x_m", pt.get("x_true", 0.0))
                        gy = pt.get("y_m", pt.get("y_true", 0.0))
                        return round(gx - pt["_local"]["x"], 4), round(gy - pt["_local"]["y"], 4)
        except Exception:
            pass
        return None

    # Interaktywny kreator wyboru pokoju, zmiany aktywnej sesji lub wyznaczenia nowego punktu origin.
    def manage_session(self) -> None:
        sess = self.load_session()
        known_sessions = set()

        if os.path.exists(self.data_dir):
            for f in os.listdir(self.data_dir):
                if f.startswith("radio_map_") and f.endswith(".json"):
                    known_sessions.add(f[10:-5])

        history = {}
        try:
            with open(self.session_path, encoding="utf-8") as f:
                old_data = json.load(f)
                history = old_data.get("history", {old_data.get("origin_label"): old_data} if "origin_label" in old_data else {})
                for k in history.keys():
                    if self._session_has_files(k) or (sess and sess.get("origin_label") == k):
                        known_sessions.add(k)
        except Exception:
            pass

        known_sessions = sorted(list(known_sessions - {"", "unknown"}))

        print("\n=== WYBÓR SESJI (POKOJU) ===")
        if sess:
            print(f"  Aktywny pokój: '{sess['origin_label']}'")
            print(f"  Origin:        X={sess['origin_x_m']} m, Y={sess['origin_y_m']} m")
        else:
            print("  Brak aktywnej sesji.")

        print("\n  1 - Kontynuuj" if sess else "  1 - [Niedostępne]")
        print("  2 - Wybierz inną sesję")
        print("  3 - Utwórz nową sesję (zaznacz origin mapy)")

        choice = input("\nWybór -> ").strip()
        if choice == "1" and sess:
            return
        elif choice == "2":
            if not known_sessions:
                print("  [!] Brak zapisanych pokoi.")
                return
            print("\n  Dostępne pokoje:")
            for idx, sname in enumerate(known_sessions, 1):
                print(f"    {idx} - {sname} {'(Aktywna)' if sess and sess['origin_label'] == sname else ''}")
            while True:
                ans = input(f"  Wybierz [1-{len(known_sessions)}] (Enter=Powrót): ").strip()
                if not ans:
                    return
                try:
                    val = int(ans)
                    if 1 <= val <= len(known_sessions):
                        selected = known_sessions[val - 1]
                        restored = history.get(selected)
                        if not restored:
                            origin = self._get_session_origin(selected)
                            if not origin:
                                print(f"\n[!] Origin dla '{selected}' - zaznacz na mapie.")
                                pdata = self._pick_on_map("--pick-session")
                                if not pdata or not pdata.get("picked"):
                                    break
                                origin = (pdata["x_m"], pdata["y_m"])
                            restored = {
                                "origin_label": selected,
                                "origin_x_m":   origin[0],
                                "origin_y_m":   origin[1],
                                "created":      datetime.now().isoformat(timespec="seconds"),
                            }
                        self.save_session(restored["origin_label"], restored["origin_x_m"], restored["origin_y_m"])
                        print(f"  [✓] Przełączono na: '{selected}'")
                        break
                except ValueError:
                    pass
            return
        elif choice == "3":
            data = self._pick_on_map("--pick-session")
            if not data or not data.get("picked"):
                return

            label = input("Nazwa nowej sesji (np. pokoj707): ").strip() or f"origin_{datetime.now().strftime('%Y%m%d_%H%M')}"

            self.save_session(label, data["x_m"], data["y_m"])
            print(f"\n[✓] Zapisano: '{label}' @ ({data['x_m']}, {data['y_m']})")
