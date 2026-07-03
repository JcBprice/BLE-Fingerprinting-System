"""
utils.py — Funkcje pomocnicze systemu lokalizacji ESPAR.

Zawiera:
    - Funkcje bezpiecznego wczytywania danych od użytkownika (int, float, wybór)
    - Wspólna logika skanowania beaconów i budowania listy kandydatów
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Funkcje bezpiecznego wczytywania danych od użytkownika
# ═══════════════════════════════════════════════════════════════════════════════

def get_int_input(prompt: str, default: int | None = None,
                  min_val: int | None = None) -> int:
    """Bezpiecznie wczytuje liczbę całkowitą od użytkownika.

    Args:
        prompt:   Tekst zachęty wyświetlany użytkownikowi.
        default:  Wartość domyślna (używana gdy użytkownik wciśnie Enter).
        min_val:  Minimalna akceptowalna wartość.

    Returns:
        Wczytana liczba całkowita.

    Raises:
        KeyboardInterrupt: Gdy użytkownik wciśnie Ctrl+C.
    """
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


def get_float_input(prompt: str, default: float | None = None,
                    min_val: float | None = None) -> float:
    """Bezpiecznie wczytuje liczbę zmiennoprzecinkową od użytkownika.

    Akceptuje przecinek jako separator dziesiętny (zamienia na kropkę).

    Args:
        prompt:   Tekst zachęty.
        default:  Wartość domyślna.
        min_val:  Minimalna akceptowalna wartość (strict: >).

    Returns:
        Wczytana liczba zmiennoprzecinkowa.
    """
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


def get_choice_input(prompt: str, valid_choices: list[str] | tuple[str, ...],
                     default: str | None = None) -> str:
    """Wczytuje wybór użytkownika z ograniczonego zestawu opcji.

    Args:
        prompt:        Tekst zachęty.
        valid_choices: Lista/krotka dozwolonych wartości (porównywane lowercase).
        default:       Wartość domyślna.

    Returns:
        Wybrany string (lowercase).
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# Skanowanie beaconów i budowanie listy kandydatów
# ═══════════════════════════════════════════════════════════════════════════════

def build_beacon_candidates(available: list[int],
                            db_beacons: list[int]) -> list[int]:
    """Buduje unikatową listę kandydatów (z otoczenia i bazy danych).

    Beacony wykryte w otoczeniu są umieszczane na początku listy,
    następnie beacony obecne w bazie, które nie zostały wykryte.

    Args:
        available:  Lista ID beaconów wykrytych w zasięgu.
        db_beacons: Lista ID beaconów obecnych w bazie danych.

    Returns:
        Posortowana lista unikalnych ID beaconów (wykryte mają priorytet).
    """
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


def select_beacon_interactive(candidates: list[int],
                              db_beacons: list[int],
                              available: list[int],
                              prompt_label: str = "podglądu") -> int:
    """Wyświetla interaktywne menu wyboru beacona.

    Args:
        candidates:   Lista kandydatów (z build_beacon_candidates).
        db_beacons:   Lista beaconów w bazie (do adnotacji).
        available:    Lista beaconów wykrytych (do adnotacji).
        prompt_label: Opis celu wyboru (np. "podglądu", "zbierania").

    Returns:
        Wybrany ID beacona.
    """
    print(f"\n  Dostępne beacony (wykryte w zasięgu i/lub obecne w bazie):")
    for idx, bid in enumerate(candidates, 1):
        in_db = " [w bazie]" if bid in db_beacons else " [brak w bazie]"
        detected = " [wykryty]" if bid in available else ""
        print(f"    {idx} - Beacon #{bid}{in_db}{detected}")

    print(f"\n  Wybierz beacon do {prompt_label} "
          f"(numer 1-{len(candidates)} lub ID, domyślnie {candidates[0]}):")
    ans = input("  Wybór -> ").strip()

    if not ans:
        return candidates[0]
    try:
        val = int(ans)
        if 1 <= val <= len(candidates):
            return candidates[val - 1]
        return val
    except ValueError:
        print("  [!] Nieprawidłowy wybór. Używam domyślnego beacona.")
        return candidates[0]


def get_beacons_from_radio_map() -> list[int]:
    """Wyciąga posortowaną listę ID beaconów z radio_map.json.

    Returns:
        Lista ID beaconów (int, posortowana rosnąco).
        Pusta lista jeśli nie udało się wczytać mapy.
    """
    try:
        from wknn import load_radio_map
        radio_map = load_radio_map(filter_session=True)
        beacons = set()
        for fp in radio_map:
            beacons.update(int(b) for b in fp.get("beacons", {}).keys())
        return sorted(beacons)
    except Exception:
        return []
