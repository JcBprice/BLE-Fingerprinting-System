"""Detekcja najbliższej anteny ESPAR (konkurencja mocy RSSI między portami)."""

import socket
import sys
import threading
import time
from typing import Dict, List, Tuple

from config import PORT_NAMES
from espar_client import EsparClient
from telnet_reader import get_espar_stream


# Łączy się równolegle w osobnych wątkach ze wszystkimi portami anten ESPAR i gromadzi odebrane pakiety RSSI.
def scan_antennas_rssi(host: str = "153.19.49.102",
                       ports: List[int] = None,
                       duration_sec: float = 4.0) -> Tuple[Dict[int, Dict[int, List[float]]], Dict[int, str]]:
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
                    continue
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


# Wyznacza antenę o najwyższym średnim RSSI dla każdego beacona oraz margines przewagi nad kolejną.
def analyze_and_predict(beacon_rssi: Dict[int, Dict[int, List[float]]],
                        connection_status: Dict[int, str]) -> List[dict]:
    predictions = []

    for bid in sorted(beacon_rssi.keys()):
        port_stats = []
        for port, rssi_list in beacon_rssi[bid].items():
            if not rssi_list:
                continue
            port_stats.append({
                "port": port, "antenna_name": f"{PORT_NAMES.get(port, f'espar_{port}')} (Port {port})",
                "avg_rssi": round(sum(rssi_list) / len(rssi_list), 2),
                "max_rssi": round(max(rssi_list), 2), "count": len(rssi_list)
            })

        if not port_stats:
            continue
        port_stats.sort(key=lambda x: x["avg_rssi"], reverse=True)

        best = port_stats[0]
        margin = round(best["avg_rssi"] - port_stats[1]["avg_rssi"], 2) if len(port_stats) > 1 else 0.0

        predictions.append({
            "beacon_id": bid, "best_antenna": best["antenna_name"], "best_port": best["port"],
            "best_avg_rssi": best["avg_rssi"], "margin_db": margin, "all_ports": port_stats
        })
    return predictions


def print_report(predictions: List[dict],
                 connection_status: Dict[int, str],
                 duration_sec: float):
    print("\n" + "=" * 80 + "\n 🔍 DETEKCJA NAJBLIŻSZEJ ANTENY ESPAR (RSSI)\n" + "=" * 80)
    print(f" Czas skanowania: {duration_sec} s\n\n Status połączeń:")
    for port in sorted(connection_status.keys()):
        st = connection_status[port]
        print(f"   {'✅' if 'OK' in st else '❌'} {PORT_NAMES.get(port, f'espar_{port}')} (Port {port}): {st}")

    if not predictions:
        print("\n [!] Brak widocznych beaconów.\n" + "=" * 80 + "\n")
        return

    print(f"\n Szczegóły RSSI per antena ESPAR:\n{'-'*80}")
    print(f" {'BEACON':<12} | {'ANTENA ESPAR':<26} | {'ŚREDNI RSSI':<12} | {'MAX RSSI':<10} | {'PAKIETY':<8}\n{'-'*80}")

    for p in predictions:
        bid = p["beacon_id"]
        for idx, ps in enumerate(p["all_ports"]):
            print(f" {f'Beacon #{bid}' if idx == 0 else '':<12} | {ps['antenna_name']:<26} | {ps['avg_rssi']:>8.2f} dBm | {ps['max_rssi']:>6.2f} dBm | {ps['count']:>7}")
        print("-" * 80)

    print("\n 📍 PREDIKCJA NAJBLIŻSZEJ ANTENY ESPAR (NAJMOCNIEJSZY SYGNAŁ):")
    for p in predictions:
        print(f"   ▶ Beacon #{p['beacon_id']:<3} ➔  {p['best_antenna']}  [Średni RSSI: {p['best_avg_rssi']:.2f} dBm]" +
              (f" (przewaga +{p['margin_db']:.2f} dBm)" if p["margin_db"] > 0 else ""))
    print("=" * 80 + "\n")


def run_room_detection(duration_sec: float = 4.0):
    client = EsparClient()
    host = client.host
    ports = sorted(list(PORT_NAMES.keys()))
    print(f"\n[Skanowanie] Łączenie z antenami ESPAR ({host}: {', '.join(str(p) for p in ports)})...")
    data, conn_status = scan_antennas_rssi(host, ports, duration_sec)
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
