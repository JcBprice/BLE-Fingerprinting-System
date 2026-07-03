import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data"))

class SessionManager:
    """Zarządza sesją pomiarową (punktem odniesienia/origin) oraz historią sesji (pokoi)."""
    
    def __init__(self, data_dir: str, script_dir: str):
        self.data_dir = data_dir
        self.script_dir = script_dir
        self.session_path = os.path.join(self.data_dir, "session.json")

    def load_session(self) -> dict | None:
        """Wczytuje aktywną sesję z session.json lub zwraca None."""
        if not os.path.exists(self.session_path):
            return None
        try:
            with open(self.session_path, encoding="utf-8") as f:
                data = json.load(f)
            # Obsługa starego płaskiego formatu
            if "origin_label" in data:
                return data
            # Nowy format z kluczem active_session
            return data.get("active_session")
        except Exception:
            return None

    def save_session(self, origin_label: str, origin_x: float, origin_y: float) -> None:
        """Zapisuje sesję pomiarową do session.json wraz z historią sesji."""
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Wczytanie historii w celu zachowania znanych pokoi
        history = {}
        if os.path.exists(self.session_path):
            try:
                with open(self.session_path, encoding="utf-8") as f:
                    old_data = json.load(f)
                if "history" in old_data:
                    history = old_data["history"]
                elif "origin_label" in old_data:
                    # Migracja starego formatu do historii
                    old_lbl = old_data["origin_label"]
                    history[old_lbl] = old_data
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
            json.dump({
                "active_session": active,
                "history": history
            }, f, indent=2, ensure_ascii=False)

    def _pick_on_map(self, flag: str) -> dict | None:
        """
        Uruchamia map_viewer.py z podanym trybem i czeka na JSON z stdout.
        flag: '--pick-session' lub '--mark-origin' lub '--pick'
        """
        viewer = os.path.join(self.script_dir, "map_viewer.py")
        try:
            result = subprocess.run(
                [sys.executable, viewer, flag],
                capture_output=True, text=True, encoding="utf-8",
            )
        except Exception as e:
            print(f"[!] Błąd podczas otwierania mapy: {e}")
            return None
            
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        return None

    def manage_session(self) -> None:
        """
        Zarządzanie sesją pomiarową (pokojem). Pozwala kontynuować,
        przełączać się na istniejące pokoje lub utworzyć nową sesję.
        """
        sess = self.load_session()
        
        # Automatyczne wyszukiwanie wszystkich dostępnych map w folderach data i old_fingerprints
        known_sessions = set()
        
        # Skanujemy data/
        if os.path.exists(self.data_dir):
            for f in os.listdir(self.data_dir):
                if f.startswith("radio_map_") and f.endswith(".json"):
                    sname = f[10:-5]
                    known_sessions.add(sname)
                    
        # Skanujemy old_fingerprints/
        old_dir = os.path.normpath(os.path.join(self.data_dir, "..", "..", "old_fingerprints"))
        if os.path.exists(old_dir):
            for f in os.listdir(old_dir):
                if f.startswith("radio_map_") and f.endswith(".json"):
                    sname = f[10:-5]
                    known_sessions.add(sname)

        # Skanujemy historię sesji w session.json
        history = {}
        if os.path.exists(self.session_path):
            try:
                with open(self.session_path, encoding="utf-8") as f:
                    old_data = json.load(f)
                if "history" in old_data:
                    history = old_data["history"]
                    for k in history.keys():
                        known_sessions.add(k)
                elif "origin_label" in old_data:
                    known_sessions.add(old_data["origin_label"])
            except Exception:
                pass

        # Usunięcie pustych wpisów i unknown
        known_sessions = sorted(list(known_sessions - {"", "unknown"}))

        print("\n=== SYSTEM LOKALIZACJI ESPAR — WYBÓR SESJI (POKOJU) ===")
        if sess:
            print(f"  Aktywny pokój (sesja): '{sess['origin_label']}'")
            print(f"  Współrzędne origin:    X={sess['origin_x_m']} m, Y={sess['origin_y_m']} m")
            print(f"  Data utworzenia:       {sess.get('created', '?')}")
        else:
            print("  Brak aktywnej sesji.")

        print("\n  Co chcesz zrobić?")
        print("    1 - Kontynuuj obecną sesję" if sess else "    1 - [Niedostępne]")
        print("    2 - Wybierz inną zapisaną sesję (pokój)")
        print("    3 - Utwórz nową sesję (zaznacz nowy origin na mapie)")
        print("    Enter - Anuluj")

        choice = input("\nWybór -> ").strip()
        if choice == "1" and sess:
            return
        elif choice == "2":
            if not known_sessions:
                print("  [!] Brak zapisanych pokoi/sesji w systemie.")
                return
            print("\n  Dostępne pokoje (sesje):")
            for idx, sname in enumerate(known_sessions, 1):
                active_mark = "  <-- AKTYWNY" if sess and sess["origin_label"] == sname else ""
                print(f"    {idx} - {sname}{active_mark}")
            while True:
                ans = input(f"  Wybierz sesję [1-{len(known_sessions)}] (lub Enter aby powrócić): ").strip()
                if not ans:
                    return
                try:
                    val = int(ans)
                    if 1 <= val <= len(known_sessions):
                        selected = known_sessions[val - 1]
                        restored = history.get(selected)
                        if not restored:
                            restored = {
                                "origin_label": selected,
                                "origin_x_m":   22.87,  # Domyślny fallback współrzędnych z espar37
                                "origin_y_m":   8.748,
                                "created":      datetime.now().isoformat(timespec="seconds"),
                            }
                        self.save_session(restored["origin_label"], restored["origin_x_m"], restored["origin_y_m"])
                        print(f"  [OK] Przełączono na sesję pokoju: '{selected}'")
                        break
                    else:
                        print("  [!] Nieprawidłowy numer wyboru.")
                except ValueError:
                    print("  [!] Podaj poprawną liczbę.")
            return
        elif choice == "3":
            print("\n[Nowa sesja] Otwieram mapę — kliknij miejsce gdzie zaczyna się Twoja siatka pomiarowa.")
            print("  To będzie lokalny punkt (0,0). Mierz od niego taśmą do kolejnych punktów.\n")

            data = self._pick_on_map("--pick-session")
            if not data or not data.get("picked"):
                print("[!] Nie zaznaczono originu. Sesja niezmieniona.")
                return

            x_m = data["x_m"]
            y_m = data["y_m"]
            label = input(f"  Podaj nazwę nowej sesji (pokoju, np. '707dziala'): ").strip()
            if not label:
                label = f"origin_{datetime.now().strftime('%Y%m%d_%H%M')}"

            self.save_session(label, x_m, y_m)
            print(f"\n[OK] Sesja zapisana: '{label}' @ ({x_m} m, {y_m} m)")
            print("     Podczas kalibracji wpisuj lokalne X, Y od tego punktu.")
