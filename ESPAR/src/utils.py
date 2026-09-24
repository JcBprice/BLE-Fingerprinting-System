"""Funkcje pomocnicze systemu ESPAR (walidacja wejścia, wybór beaconów, wykresy)."""

import os
import subprocess
import sys


# Pobiera liczbę całkowitą z walidacją dolnej granicy i wartością domyślną po wciśnięciu Enter.
def get_int_input(prompt: str, default: int | None = None,
                  min_val: int | None = None) -> int:
    while True:
        try:
            val = input(prompt).strip()
            if not val:
                if default is not None:
                    return default
                print("  [!] Wartość nie może być pusta. Spróbuj ponownie.")
                continue
            res = int(val)
            if min_val is not None and res < min_val:
                print(f"  [!] Wartość musi być >= {min_val}. Spróbuj ponownie.")
                continue
            return res
        except ValueError:
            print("  [!] Nieprawidłowa liczba całkowita. Spróbuj ponownie.")
        except KeyboardInterrupt:
            print("\n  [!] Anulowano.")
            raise


# Pobiera float od użytkownika, akceptując zarówno kropkę jak i przecinek dziesiętny.
def get_float_input(prompt: str, default: float | None = None,
                    min_val: float | None = None) -> float:
    while True:
        try:
            val = input(prompt).strip()
            if not val:
                if default is not None:
                    return default
                print("  [!] Wartość nie może być pusta. Spróbuj ponownie.")
                continue
            val = val.replace(",", ".")
            res = float(val)
            if min_val is not None and res <= min_val:
                print(f"  [!] Wartość musi być > {min_val}. Spróbuj ponownie.")
                continue
            return res
        except ValueError:
            print("  [!] Nieprawidłowa liczba. Spróbuj ponownie.")
        except KeyboardInterrupt:
            print("\n  [!] Anulowano.")
            raise


# Wymusza podanie jednej z predefiniowanych opcji tekstowych (np. t/n).
def get_choice_input(prompt: str, valid_choices: list[str] | tuple[str, ...],
                     default: str | None = None) -> str:
    valid_choices = [c.strip().lower() for c in valid_choices]
    while True:
        val = input(prompt).strip().lower()
        if not val:
            if default is not None:
                return default
            print("  [!] Wybór nie może być pusty. Spróbuj ponownie.")
            continue
        if val in valid_choices:
            return val
        print(f"  [!] Nieprawidłowy wybór. Dozwolone: {', '.join(valid_choices)}")


# Łączy beacony wykryte w paśmie radiowym z tymi zapisanymi w bazie bez powtórzeń.
def build_beacon_candidates(available: list[int],
                            db_beacons: list[int]) -> list[int]:
    candidates = []
    for b in available:
        if b not in candidates:
            candidates.append(b)
    for b in db_beacons:
        if b not in candidates:
            candidates.append(b)

    if not candidates:
        candidates = [28]
    return candidates


def print_available_beacons(candidates: list[int],
                            db_beacons: list[int],
                            available: list[int]) -> None:
    print(f"\n  Dostępne beacony (wykryte w zasięgu i/lub obecne w bazie):")
    for idx, bid in enumerate(candidates, 1):
        in_db = " [w bazie]" if bid in db_beacons else " [brak w bazie]"
        detected = " [W ZASIĘGU]" if bid in available else ""
        print(f"    {idx} - Beacon #{bid}{in_db}{detected}")


# Pozwala wybrać docelowy beacon podając jego numer z listy lub wpisując ID bezpośrednio.
def select_beacon_interactive(candidates: list[int],
                              db_beacons: list[int],
                              available: list[int],
                              prompt_label: str = "podglądu",
                              rescan_callback = None) -> int:
    while True:
        print_available_beacons(candidates, db_beacons, available)

        rescan_hint = ", 'r' = ponów skan" if rescan_callback else ""
        print(f"\n  Wybierz beacon do {prompt_label} "
              f"(numer 1-{len(candidates)} lub ID, domyślnie {candidates[0]}{rescan_hint}):")
        ans = input("  Wybór -> ").strip()

        if not ans:
            return candidates[0]
        if ans.lower() == 'r' and rescan_callback:
            print("\n  Ponawiam skanowanie pasma radiowego...")
            available = rescan_callback()
            candidates = build_beacon_candidates(available, db_beacons)
            continue
        try:
            val = int(ans)
            if 1 <= val <= len(candidates):
                return candidates[val - 1]
            return val
        except ValueError:
            print("  [!] Nieprawidłowy wybór. Spróbuj ponownie.")


# Pobiera listę unikalnych ID beaconów występujących w aktywnej mapie radiowej.
def get_beacons_from_radio_map() -> list[int]:
    try:
        from wknn import load_radio_map
        radio_map = load_radio_map(filter_session=True)
        beacons = set()
        for fp in radio_map:
            beacons.update(int(b) for b in fp.get("beacons", {}).keys())
        return sorted(beacons)
    except Exception:
        return []


# Zapisuje wykres matplotliba do pliku graficznego i automatycznie otwiera go w systemie operacyjnym.
def show_plot(fig, out_path: str) -> None:
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    import matplotlib.pyplot as plt
    plt.close(fig)
    abs_path = os.path.abspath(out_path)
    print(f"  [+] Wykres zapisany: {abs_path}")
    try:
        if os.name == 'nt':
            os.startfile(abs_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', abs_path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            env = dict(os.environ)
            env["QT_LOGGING_RULES"] = "qt.*=false"
            subprocess.Popen(['xdg-open', abs_path],
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True,
                             env=env)
    except Exception as e:
        print(f"  [!] Nie udało się automatycznie otworzyć wykresu: {e}")
