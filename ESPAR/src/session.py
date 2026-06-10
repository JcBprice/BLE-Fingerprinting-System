import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data"))

class SessionManager:
    """Zarządza sesją pomiarową (punktem odniesienia/origin)."""
    
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
                return json.load(f)
        except Exception:
            return None

    def save_session(self, origin_label: str, origin_x: float, origin_y: float) -> None:
        """Zapisuje sesję pomiarową do session.json."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.session_path, "w", encoding="utf-8") as f:
            json.dump({
                "origin_label": origin_label,
                "origin_x_m":   round(origin_x, 4),
                "origin_y_m":   round(origin_y, 4),
                "created":      datetime.now().isoformat(timespec="seconds"),
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
        Tryb 5: Sesja pomiarowa — ustaw lokalny origin siatki.
        Użytkownik klika na mapie SVG miejsce, od którego będzie mierzyć
        lokalne współrzędne (taśmą). System zapisuje to jako origin sesji.
        Każdy kolejny punkt kalibracyjny jest podawany w metrach od tego origin.
        """
        sess = self.load_session()
        if sess:
            print(f"\n[Sesja aktywna]")
            print(f"  Origin: '{sess['origin_label']}'")
            print(f"  Pozycja globalna: X={sess['origin_x_m']} m, Y={sess['origin_y_m']} m")
            print(f"  Utworzona: {sess.get('created', '?')}")
            ans = input("\nKontynuować tę sesję? (t=tak / n=nowa sesja): ").strip().lower()
            if ans != "n":
                return

        print("\n[Nowa sesja] Otwieram mapę — kliknij miejsce gdzie zaczyna się Twoja siatka pomiarowa.")
        print("  To będzie lokalny punkt (0,0). Mierz od niego taśmą do kolejnych punktów.\n")

        data = self._pick_on_map("--pick-session")
        if not data or not data.get("picked"):
            print("[!] Nie zaznaczono originu. Sesja niezmieniona.")
            return

        x_m = data["x_m"]
        y_m = data["y_m"]
        label = input(f"  Opis tego punktu (np. 'narożnik pok.707 przy drzwiach'): ").strip()
        if not label:
            label = f"origin_{datetime.now().strftime('%Y%m%d_%H%M')}"

        self.save_session(label, x_m, y_m)
        print(f"\n[OK] Sesja zapisana: '{label}' @ ({x_m} m, {y_m} m)")
        print("     Podczas kalibracji wpisuj lokalne X, Y od tego punktu.")
