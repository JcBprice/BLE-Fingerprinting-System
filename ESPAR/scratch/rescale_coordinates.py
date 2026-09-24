#!/usr/bin/env python3
"""Skrypt migracyjny przeliczający współrzędne w plikach JSON na rzeczywisty viewBox SVG."""

import datetime
import glob
import json
import os
import shutil

OLD_VB_W = 4600.0
OLD_VB_H = 2760.0
RAW_W = 4373.5528
RAW_H = 2617.9691

SCALE_X = RAW_W / OLD_VB_W
SCALE_Y = RAW_H / OLD_VB_H


# Tworzy kopię zapasową wszystkich plików JSON z katalogu data/ przed rozpoczęciem migracji.
def backup_data_dir(data_dir: str, backup_root: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(backup_root, f"backup_pre_rescale_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)
    count = 0
    for fname in os.listdir(data_dir):
        src = os.path.join(data_dir, fname)
        dst = os.path.join(backup_dir, fname)
        if os.path.isfile(src) and src.endswith(".json"):
            shutil.copy2(src, dst)
            count += 1
    print(f"[BACKUP] Skopiowano {count} plików JSON do: {backup_dir}")
    return backup_dir


# Przeskalowuje pozycje (x_m, y_m) zarejestrowanych beaconów.
def rescale_beacons(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return
    modified = False
    for b in data:
        if "x_m" in b and isinstance(b["x_m"], (int, float)):
            b["x_m"] = round(b["x_m"] * SCALE_X, 4)
            modified = True
        if "y_m" in b and isinstance(b["y_m"], (int, float)):
            b["y_m"] = round(b["y_m"] * SCALE_Y, 4)
            modified = True
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[RESCALE] Zaktualizowano beacons: {os.path.basename(file_path)} ({len(data)} wpisów)")


# Przeskalowuje współrzędne punktów w mapie radiowej (zarówno globalne jak i lokalne).
def rescale_radio_map(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return
    modified = False
    for p in data:
        if "x_m" in p and isinstance(p["x_m"], (int, float)):
            p["x_m"] = round(p["x_m"] * SCALE_X, 4)
            modified = True
        if "y_m" in p and isinstance(p["y_m"], (int, float)):
            p["y_m"] = round(p["y_m"] * SCALE_Y, 4)
            modified = True
        if "_local" in p and isinstance(p["_local"], dict):
            if "x" in p["_local"] and isinstance(p["_local"]["x"], (int, float)):
                p["_local"]["x"] = round(p["_local"]["x"] * SCALE_X, 4)
                modified = True
            if "y" in p["_local"] and isinstance(p["_local"]["y"], (int, float)):
                p["_local"]["y"] = round(p["_local"]["y"] * SCALE_Y, 4)
                modified = True
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[RESCALE] Zaktualizowano radio_map: {os.path.basename(file_path)} ({len(data)} wpisów)")


# Przeskalowuje współrzędne referencyjne ground truth (x_true, y_true) w zbiorze testowym.
def rescale_test_set(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return
    modified = False
    for p in data:
        if "x_true" in p and isinstance(p["x_true"], (int, float)):
            p["x_true"] = round(p["x_true"] * SCALE_X, 4)
            modified = True
        if "y_true" in p and isinstance(p["y_true"], (int, float)):
            p["y_true"] = round(p["y_true"] * SCALE_Y, 4)
            modified = True
        if "_local" in p and isinstance(p["_local"], dict):
            if "x" in p["_local"] and isinstance(p["_local"]["x"], (int, float)):
                p["_local"]["x"] = round(p["_local"]["x"] * SCALE_X, 4)
                modified = True
            if "y" in p["_local"] and isinstance(p["_local"]["y"], (int, float)):
                p["_local"]["y"] = round(p["_local"]["y"] * SCALE_Y, 4)
                modified = True
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[RESCALE] Zaktualizowano test_set: {os.path.basename(file_path)} ({len(data)} wpisów)")


# Przeskalowuje współrzędne origin aktywnej sesji oraz sesji archiwalnych w session.json.
def rescale_session(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        sess = json.load(f)
    if not isinstance(sess, dict):
        return
    modified = False
    if "active_session" in sess and isinstance(sess["active_session"], dict):
        act = sess["active_session"]
        if "origin_x_m" in act and isinstance(act["origin_x_m"], (int, float)):
            act["origin_x_m"] = round(act["origin_x_m"] * SCALE_X, 4)
            modified = True
        if "origin_y_m" in act and isinstance(act["origin_y_m"], (int, float)):
            act["origin_y_m"] = round(act["origin_y_m"] * SCALE_Y, 4)
            modified = True
    if "history" in sess and isinstance(sess["history"], dict):
        for h_key, h_val in sess["history"].items():
            if isinstance(h_val, dict):
                if "origin_x_m" in h_val and isinstance(h_val["origin_x_m"], (int, float)):
                    h_val["origin_x_m"] = round(h_val["origin_x_m"] * SCALE_X, 4)
                    modified = True
                if "origin_y_m" in h_val and isinstance(h_val["origin_y_m"], (int, float)):
                    h_val["origin_y_m"] = round(h_val["origin_y_m"] * SCALE_Y, 4)
                    modified = True
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(sess, f, indent=2, ensure_ascii=False)
        print(f"[RESCALE] Zaktualizowano session.json")


# Przeskalowuje punkty zaplanowanej siatki pomiarowej (planned_grid.json).
def rescale_planned_grid(file_path: str):
    if not os.path.isfile(file_path):
        return
    with open(file_path, "r", encoding="utf-8") as f:
        grid = json.load(f)
    if not isinstance(grid, dict):
        return
    if "ox" in grid and isinstance(grid["ox"], (int, float)):
        grid["ox"] = round(grid["ox"] * SCALE_X, 4)
    if "oy" in grid and isinstance(grid["oy"], (int, float)):
        grid["oy"] = round(grid["oy"] * SCALE_Y, 4)
    for pt in grid.get("points", []):
        if "x_local" in pt:
            pt["x_local"] = round(pt["x_local"] * SCALE_X, 4)
        if "y_local" in pt:
            pt["y_local"] = round(pt["y_local"] * SCALE_Y, 4)
        if "x_global" in pt:
            pt["x_global"] = round(pt["x_global"] * SCALE_X, 4)
        if "y_global" in pt:
            pt["y_global"] = round(pt["y_global"] * SCALE_Y, 4)
        for b in pt.get("beacons", []):
            if "x" in b:
                b["x"] = round(b["x"] * SCALE_X, 4)
            if "y" in b:
                b["y"] = round(b["y"] * SCALE_Y, 4)
            if "local_x" in b:
                b["local_x"] = round(b["local_x"] * SCALE_X, 4)
            if "local_y" in b:
                b["local_y"] = round(b["local_y"] * SCALE_Y, 4)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(grid, f, indent=2, ensure_ascii=False)
    print(f"[RESCALE] Zaktualizowano planned_grid.json")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.abspath(os.path.join(script_dir, "..", "data"))
    backup_root = os.path.abspath(os.path.join(script_dir, "..", "..", "old_fingerprints"))

    print(f"Start migracji współrzędnych...")
    print(f"  SCALE_X = {SCALE_X:.10f}")
    print(f"  SCALE_Y = {SCALE_Y:.10f}")

    backup_data_dir(data_dir, backup_root)

    for f in sorted(glob.glob(os.path.join(data_dir, "beacons*.json"))):
        rescale_beacons(f)

    for f in sorted(glob.glob(os.path.join(data_dir, "radio_map*.json"))):
        rescale_radio_map(f)

    for f in sorted(glob.glob(os.path.join(data_dir, "test_set*.json"))):
        rescale_test_set(f)

    sess_file = os.path.join(data_dir, "session.json")
    if os.path.isfile(sess_file):
        rescale_session(sess_file)

    grid_file = os.path.join(data_dir, "planned_grid.json")
    if os.path.isfile(grid_file):
        rescale_planned_grid(grid_file)

    print("\nMigracja zakończona sukcesem!")


if __name__ == "__main__":
    main()
