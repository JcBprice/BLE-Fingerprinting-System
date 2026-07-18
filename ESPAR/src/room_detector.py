"""
room_detector.py — Uniwersalny moduł detekcji najbliższej anteny ESPAR na podstawie mocy RSSI.

Program łączy się jednocześnie do dostępnych portów anten ESPAR (zdefiniowanych w PORT_NAMES),
odporny na awarie/brak połączenia z poszczególnymi serwerami, odbiera pakiety BLE i porównuje
poziomy sygnału RSSI dla każdego wykrytego beacona, wskazując antenę o najwyższej mocy sygnału.
"""

import sys
import time
import socket
import threading
from typing import Dict, List, Tuple

from espar_client import EsparClient
from telnet_reader import get_espar_stream
from config import PORT_NAMES


def scan_antennas_rssi(host: str = "153.19.49.102",
                       ports: List[int] = None,
                       duration_sec: float = 4.0) -> Tuple[Dict[int, Dict[int, List[float]]], Dict[int, str]]:
    """Skanuje podane porty ESPAR przez duration_sec i zbiera wartości RSSI dla beaconów.

    Obsługuje awarie połączeń z poszczególnymi portami.

    Args:
        host: IP serwera ESPAR
        ports: Lista portów TCP do odpytania (domyślnie klucze z PORT_NAMES)
        duration_sec: Czas skanowania w sekundach

    Returns:
        Krotka:
            - beacon_rssi: {beacon_id: {port: [rssi_dbm1, rssi_dbm2, ...]}}
            - connection_status: {port: "OK" | "BŁĄD"}
    """
    if ports is None:
        ports = sorted(list(PORT_NAMES.keys()))

    beacon_rssi: Dict[int, Dict[int, List[float]]] = {}
    connection_status: Dict[int, str] = {}
    lock = threading.Lock()

    def worker(port: int):
        client = EsparClient(host=host, port=port, timeout=3)
        sock = client.connect_and_start()
        if not sock:
            with lock:
                connection_status[port] = "Błąd połączenia / Serwer nieaktywny"
            return

        with lock:
            connection_status[port] = "Połączono (OK)"

        sock.settimeout(0.5)
        start_time = time.time()
        try:
            while time.time() - start_time < duration_sec:
                try:
                    for frame in get_espar_stream(sock):
                        if time.time() - start_time >= duration_sec:
                            break
                        bid = frame.get('beacon_num')
                        rssi = frame.get('rssi_dbm')
                        if bid is not None and rssi is not None:
                            with lock:
                                beacon_rssi.setdefault(bid, {}).setdefault(port, []).append(float(rssi))
                except socket.timeout:
                    continue  # Timeout okna 0.5s — kontynuuj próbkowanie do końca duration_sec
                except Exception:
                    break
        finally:
            client.stop_and_close(sock)

    threads = []
    for p in ports:
        t = threading.Thread(target=worker, args=(p,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return beacon_rssi, connection_status


def analyze_and_predict(beacon_rssi: Dict[int, Dict[int, List[float]]],
                        connection_status: Dict[int, str]) -> List[dict]:
    """Przetwarza zebrane dane RSSI i wyznacza najbardziej prawdopodobną antenę ESPAR dla każdego beacona."""
    predictions = []

    for bid in sorted(beacon_rssi.keys()):
        port_stats = []
        for port, rssi_list in beacon_rssi[bid].items():
            if not rssi_list:
                continue
            avg_rssi = sum(rssi_list) / len(rssi_list)
            max_rssi = max(rssi_list)
            count = len(rssi_list)
            ant_label = f"{PORT_NAMES.get(port, f'espar_{port}')} (Port {port})"
            port_stats.append({
                "port": port,
                "antenna_name": ant_label,
                "avg_rssi": round(avg_rssi, 2),
                "max_rssi": round(max_rssi, 2),
                "count": count,
                "status": "OK"
            })

        if not port_stats:
            continue

        # Sortuj porty od najwyższego średniego RSSI
        port_stats.sort(key=lambda x: x["avg_rssi"], reverse=True)

        best = port_stats[0]
        margin = 0.0
        if len(port_stats) > 1:
            margin = round(best["avg_rssi"] - port_stats[1]["avg_rssi"], 2)

        predictions.append({
            "beacon_id": bid,
            "best_antenna": best["antenna_name"],
            "best_port": best["port"],
            "best_avg_rssi": best["avg_rssi"],
            "margin_db": margin,
            "all_ports": port_stats
        })

    return predictions


def print_report(predictions: List[dict],
                 connection_status: Dict[int, str],
                 duration_sec: float):
    """Wyświetla sformatowany raport połączeń, odczytów RSSI i predikcji anten w konsoli."""
    print("\n" + "=" * 80)
    print(" 🔍 DETEKCJA NAJBLIŻSZEJ ANTYNY ESPAR (PORÓWNANIE MOCY RSSI)")
    print("=" * 80)
    print(f" Czas skanowania: {duration_sec} s")

    print("\n Status połączeń z antenami ESPAR:")
    for port in sorted(connection_status.keys()):
        st = connection_status[port]
        ant_label = f"{PORT_NAMES.get(port, f'espar_{port}')} (Port {port})"
        icon = "✅" if "OK" in st else "❌"
        print(f"   {icon} {ant_label:<28}: {st}")

    if not predictions:
        print("\n [!] Nie wykryto żadnych nadających beaconów na aktywnych portach ESPAR.")
        print("=" * 80 + "\n")
        return

    print("\n Szczegółowe pomiary RSSI per antena ESPAR:")
    print("-" * 80)
    print(f" {'BEACON':<12} | {'ANTENA ESPAR':<26} | {'ŚREDNI RSSI':<12} | {'MAX RSSI':<10} | {'PAKIETY':<8}")
    print("-" * 80)

    for p in predictions:
        bid = p["beacon_id"]
        for idx, ps in enumerate(p["all_ports"]):
            b_label = f"Beacon #{bid}" if idx == 0 else ""
            print(f" {b_label:<12} | {ps['antenna_name']:<26} | {ps['avg_rssi']:>8.2f} dBm | {ps['max_rssi']:>6.2f} dBm | {ps['count']:>7}")
        print("-" * 80)

    print("\n 📍 PREDIKCJA NAJBLIŻSZEJ ANTYNY ESPAR (NAJMOCNIEJSZY SYGNAŁ):")
    for p in predictions:
        bid = p["beacon_id"]
        ant = p["best_antenna"]
        rssi = p["best_avg_rssi"]
        margin_str = f" (przewaga +{p['margin_db']:.2f} dBm nad kolejną anteną)" if p["margin_db"] > 0 else ""
        print(f"   ▶ Beacon #{bid:<3} ➔  {ant}  [Średni RSSI: {rssi:.2f} dBm]{margin_str}")

    print("=" * 80 + "\n")


def run_room_detection(duration_sec: float = 4.0):
    """Główna funkcja wykonawcza modułu detekcji anten ESPAR."""
    client = EsparClient()
    host = client.host
    ports = sorted(list(PORT_NAMES.keys()))
    ports_str = ", ".join(str(p) for p in ports)
    print(f"\n[Skanowanie] Łączenie z antenami ESPAR ({host}: {ports_str})...")
    data, conn_status = scan_antennas_rssi(host=host, ports=ports, duration_sec=duration_sec)
    predictions = analyze_and_predict(data, conn_status)
    print_report(predictions, conn_status, duration_sec)


if __name__ == '__main__':
    duration = 4.0
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
        except ValueError:
            pass
    run_room_detection(duration_sec=duration)
