"""Zbieranie i analiza w czasie rzeczywistym strumienia pakietów ESPAR."""

import socket
import sys
import time

from config import CHAR_TO_DEG, VALID_CHARS
from espar_client import EsparClient
from telnet_reader import get_espar_stream


# Parsuje ciąg znaków z ID beaconów oddzielonych przecinkami na zbiór liczb całkowitych.
def parse_target_beacons(user_input: str) -> set[int] | None:
    cleaned = user_input.strip()
    return {int(p.strip()) for p in cleaned.split(",") if p.strip().isdigit()} if cleaned else None


# Wyświetla tabelę ze statystykami próbek RSSI (średnia, min, max) dla każdego kąta wiązki anteny.
def print_results_table(samples: dict[int, dict[int, list[float]]], show_raw: bool = False):
    if not samples:
        return print("\n[!] Brak aktywnych beaconów w sesji nasłuchu.")

    sorted_chars = sorted(CHAR_TO_DEG.keys(), key=lambda c: CHAR_TO_DEG[c])
    for bid in sorted(samples.keys()):
        print(f"\n{(' BEACON #'+str(bid)+' '):-^73}")
        print(f"{'Kąt [°]':>8} | {'Port':>5} | {'Próbki (N)':>11} | {'Średnia RSSI':>13} | {'Min [dBm]':>10} | {'Max [dBm]':>10}")
        print("-" * 73)

        for char in sorted_chars:
            deg = CHAR_TO_DEG[char]
            vals = samples[bid].get(char, [])
            if vals:
                print(f"{deg:>7}° | {char:>5} | {len(vals):>11} | {sum(vals)/len(vals):>11.2f} dBm | {min(vals):>10.1f} | {max(vals):>10.1f}")
            else:
                print(f"{deg:>7}° | {char:>5} | {0:>11} | {'brak':>13} | {'-':>10} | {'-':>10}")

        if show_raw:
            for char in sorted_chars:
                print(f"  {CHAR_TO_DEG[char]:>3}° (char {char:>4}): {samples[bid].get(char, []) or 'brak próbek'}")


# Nasłuchuje pakiety z anteny w czasie rzeczywistym i agreguje próbki do momentu przerwania przez Ctrl+C.
def run_sample_counter(client: EsparClient | None = None):
    print("\n" + "=" * 50 + "\n           ANALIZATOR PAKIETÓW ESPAR\n" + "=" * 50)
    tracked_beacons = parse_target_beacons(input("\nPodaj ID beaconów po przecinku (np. 28, 29) [Enter = wszystkie]: "))

    if tracked_beacons:
        print(f"-> Śledzone beacony: {sorted(list(tracked_beacons))}")
    else:
        print("-> Śledzenie WSZYSTKICH wykrytych beaconów")

    client = client or EsparClient()
    sock = client.connect_and_start()
    if not sock:
        return print("[!] Błąd połączenia z anteną.")

    samples: dict[int, dict[int, list[float]]] = {}
    print("\nOdbieranie danych... Wciśnij Ctrl+C, aby zakończyć.\n")

    try:
        for frame in get_espar_stream(sock):
            bid = frame.get("beacon_num")
            char_val = frame.get("espar_char_int")
            rssi = frame.get("rssi_dbm")

            if char_val not in VALID_CHARS or rssi is None:
                continue
            if tracked_beacons is not None and bid not in tracked_beacons:
                continue

            samples.setdefault(bid, {ch: [] for ch in CHAR_TO_DEG})[char_val].append(float(rssi))
            sys.stdout.write(f"\rZebrano łącznie: {sum(len(v) for b in samples.values() for v in b.values())} pakietów...")

    except KeyboardInterrupt:
        print("\n\n[OK] Zatrzymano nasłuch.")
    except (socket.timeout, TimeoutError):
        print("\n\n[!] Błąd połączenia timeout (brak pakietów z anteny ESPAR).")
    finally:
        client.stop_and_close(sock)
        print_results_table(samples, show_raw=False)
        if samples and input("\nPokazać surowe wartości RSSI? [t/N]: ").strip().lower() == 't':
            print_results_table(samples, show_raw=True)


if __name__ == "__main__":
    run_sample_counter()
