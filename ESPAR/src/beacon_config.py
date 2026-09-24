"""Zarządzanie rejestrem beaconów referencyjnych (kotwic orientacyjnych)."""

import json
import os
import subprocess
import sys

from config import DATA_DIR, SCRIPT_DIR, get_beacons_config_path


# Wczytuje listę zarejestrowanych beaconów referencyjnych dla aktywnej sesji.
def load_beacons() -> list[dict]:
    path = get_beacons_config_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_beacons(beacons: list[dict]) -> None:
    path = get_beacons_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(beacons, f, indent=2, ensure_ascii=False)
    print(f"[OK] Zapisano {len(beacons)} beaconów.")


# Uruchamia graficzny interfejs mapy, pozwalając kliknąć fizyczną pozycję kotwicy na rzucie budynku.
def _pick_position_on_map() -> tuple[float, float] | None:
    try:
        res = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "map_viewer.py"), "--pick"],
                             capture_output=True, text=True, encoding="utf-8")
        for line in reversed(res.stdout.strip().splitlines()):
            if line.strip().startswith("{"):
                data = json.loads(line.strip())
                if data.get("picked"):
                    return data["x_m"], data["y_m"]
    except Exception:
        pass
    return None


def print_beacons_table(beacons: list[dict]) -> None:
    if not beacons:
        print("Brak zarejestrowanych beaconów orientacyjnych.")
        return
    print(f"\n{'#':>3}  {'ID':>5}  {'Etykieta':<20}  {'X [m]':>8}  {'Y [m]':>8}")
    print("-" * 52)
    for idx, b in enumerate(beacons, 1):
        print(f"{idx:>3}  {b['beacon_id']:>5}  {b.get('label', '?'):<20}  {b['x_m']:>8.3f}  {b['y_m']:>8.3f}")
    print()


# Kreator rejestracji beaconów: skanuje pasmo radiowe, pyta o etykietę i pobiera pozycję z mapy.
def register_beacons_interactive(scan_fn) -> list[dict]:
    existing = load_beacons()
    existing_ids = {b["beacon_id"] for b in existing}

    available = scan_fn()
    if not available:
        try:
            available = [int(input("Wpisz ID beacona recznie: ").strip())]
        except ValueError:
            return existing

    print(f"\nWykryte beacony:")
    for idx, bid in enumerate(available, 1):
        print(f"  {idx} - Beacon ID {bid} {'(zarejestrowany)' if bid in existing_ids else ''}")

    choice = input("Wybierz numery (np. 1,3) lub 'all' (Enter=anuluj): ").strip().lower()
    if not choice:
        return existing

    selected_ids = available if choice == "all" else []
    if choice != "all":
        for part in choice.split(","):
            try:
                idx = int(part.strip())
                if 1 <= idx <= len(available):
                    selected_ids.append(available[idx - 1])
            except ValueError:
                pass

    new_beacons = list(existing)
    for bid in selected_ids:
        if bid in existing_ids and input(f"Nadpisac pozycje beacona {bid}? [t/N]: ").strip().lower() != "t":
            continue
        label = input(f"Etykieta beacona {bid}: ").strip() or f"beacon_{bid}"

        print(f"Kliknij na mapie by wyznaczyc wspolrzedne dla {label}...")
        pos = _pick_position_on_map()
        if pos is None:
            continue
        new_beacons = [b for b in new_beacons if b["beacon_id"] != bid]
        new_beacons.append({"beacon_id": bid, "label": label, "x_m": round(pos[0], 4), "y_m": round(pos[1], 4)})
        existing_ids.add(bid)

    save_beacons(new_beacons)
    return new_beacons


# Usuwa zaznaczony beacon referencyjny z bazy i zapisuje zaktualizowany plik.
def remove_beacon_interactive() -> list[dict]:
    beacons = load_beacons()
    if not beacons:
        return beacons
    print_beacons_table(beacons)

    choice = input(f"Podaj numer beacona do usuniecia [1-{len(beacons)}] (Enter=anuluj): ").strip()
    if not choice:
        return beacons
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(beacons):
            removed = beacons.pop(idx)
            save_beacons(beacons)
            print(f"Usunieto {removed['beacon_id']}")
    except ValueError:
        pass
    return beacons
