"""Bezkalibracyjna lokalizacja oparta na stałych beaconach referencyjnych (kotwicach)."""

import datetime
import json
import os
import socket
import subprocess
import sys
import time

from beacon_config import load_beacons, print_beacons_table
from config import (
    DEFAULT_TARGET_PACKETS,
    SCRIPT_DIR,
    VALID_CHARS,
    get_active_session_label,
    get_radio_map_path,
    slugify,
)
from espar_client import EsparClient
from fingerprint import process_multi_beacon
from telnet_reader import get_espar_stream
from wknn import load_radio_map, save_radio_map


# Zbiera pakiety ze statycznych beaconów-kotwic i tworzy z nich mapę radiową bez manualnego chodzenia.
def run_beacon_calibration(client: EsparClient, beacons: list[dict],
                           target_packets: int = DEFAULT_TARGET_PACKETS) -> bool:
    if not beacons:
        print("Brak zarejestrowanych beaconów orientacyjnych.")
        return False

    beacon_ids = {b["beacon_id"] for b in beacons}
    beacon_id_strs = [str(b["beacon_id"]) for b in beacons]

    print("\n=== AUTO-KALIBRACJA Z BEACONOW ===")
    print(f"Target: {target_packets} ramek dla {sorted(beacon_ids)}\n")

    sock = client.connect_and_start()
    if not sock:
        print("[!] Blad polaczenia z ESPAR.")
        return False

    rssi_accum = {}
    start_time = time.time()

    try:
        sock.settimeout(60.0)
        total_frames = 0

        for frame in get_espar_stream(sock):
            bid = frame.get("beacon_num")
            if bid is None or bid not in beacon_ids:
                continue

            char_int = frame.get("espar_char_int")
            rssi = frame.get("rssi_dbm")

            if char_int not in VALID_CHARS or rssi is None:
                continue

            bid_str = str(bid)
            rssi_accum.setdefault(bid_str, {}).setdefault(char_int, []).append(rssi)
            total_frames += 1

            all_done = True
            status_parts = []
            for b in beacons:
                b_acc = rssi_accum.get(str(b["beacon_id"]), {})
                count = sum(len(b_acc.get(ch, [])) for ch in VALID_CHARS)
                if count < target_packets:
                    all_done = False
                status_parts.append(f"B{b['beacon_id']}:{count}/{target_packets}")

            if total_frames % 50 == 0:
                print(f"\r[{(time.time() - start_time):.0f}s] Ramki: {total_frames}  |  {' | '.join(status_parts)}", end="", flush=True)

            if all_done:
                break

    except socket.timeout:
        print("\n[!] Timeout serwera.")
    except Exception as e:
        print(f"\n[!] Blad: {e}")
    finally:
        client.stop_and_close(sock)

    print(f"\nUkonczono w {(time.time() - start_time):.1f}s ({total_frames} ramek)")
    has_missing = False
    for b_str in beacon_id_strs:
        missing_cnt = sum(1 for ch in VALID_CHARS if not len(rssi_accum.get(b_str, {}).get(ch, [])))
        if missing_cnt > 0:
            has_missing = True
            print(f"Brakuje {missing_cnt}/12 kierunków dla beacona {b_str}")

    fill_missing = False
    if has_missing:
        fill_missing = input("Uzupełnić zera (-95dBm)? [T/n]: ").strip().lower() != 'n'

    result = process_multi_beacon(rssi_accum, beacon_id_strs, target_packets, fill_missing=fill_missing, fill_value=-95.0)
    if not result:
        print("Za malo danych na mapę.")
        return False

    radio_map = _build_beacon_radio_map(result, beacons)
    if not radio_map:
        return False

    cleaned_map = [pt for pt in load_radio_map() if not pt.get("_beacon_anchor")]
    cleaned_map.extend(radio_map)
    save_radio_map(cleaned_map)

    print(f"\n[OK] Zbudowano z {len(radio_map)} beaconów. Calość: {len(cleaned_map)}.")
    for pt in radio_map:
        bid = list(pt["beacons"].keys())[0]
        print(f"  ID {bid} ('{pt['label']}') -> {len(pt['beacons'][bid].get('avg', {}))} kierunków anteny")

    return True


# Konwertuje zagregowane fingerprinty ze stałych beaconów do formatu punktów mapy radiowej.
def _build_beacon_radio_map(fingerprints: dict, beacons: list[dict]) -> list[dict]:
    sess_label = get_active_session_label() or "unknown"
    radio_map = []

    for b in beacons:
        bid_str = str(b["beacon_id"])
        if bid_str not in fingerprints:
            continue

        radio_map.append({
            "label": b.get("label", f"beacon_{bid_str}"),
            "x_m": b["x_m"],
            "y_m": b["y_m"],
            "_local": {
                "x": 0.0,
                "y": 0.0,
                "session": sess_label,
            },
            "_beacon_anchor": True,
            "beacons": { bid_str: fingerprints[bid_str] },
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        })

    return radio_map


# Uruchamia graficzny interfejs mapy z ciągłym śledzeniem wybranego obiektu.
def run_live_tracking(client: EsparClient, target_beacon_id: int) -> None:
    radio_map = load_radio_map()
    if not radio_map:
        print("Brak radio mapy.")
        return

    print(f"\nŚledzenie #{target_beacon_id} - Otwieram GUI...")
    try:
        subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "map_viewer.py"), "--view", str(target_beacon_id)], check=False)
    except Exception:
        pass


# Wybiera beacon mobilny do śledzenia, filtrując stałe kotwice pomiarowe.
def choose_target_beacon(scan_fn, beacons: list[dict]) -> int | None:
    anchor_ids = {b["beacon_id"] for b in beacons}
    available = scan_fn()

    targets = [bid for bid in available if bid not in anchor_ids]
    anchors_detected = [bid for bid in available if bid in anchor_ids]

    all_available = targets + anchors_detected if targets else available
    if not all_available:
        try:
            return int(input("Podaj ID recznie: ").strip())
        except ValueError:
            return None

    print(f"\nBeacony w zasiegu:")
    for idx, bid in enumerate(all_available, 1):
        print(f"  {idx} - Beacon ID {bid} {'(kotwica)' if bid in anchor_ids else ''}")

    choice = input(f"Wybierz cel [1-{len(all_available)}] (Enter=anuluj): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(all_available):
        return all_available[int(choice) - 1]
    return None
