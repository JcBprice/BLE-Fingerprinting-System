"""Moduł algorytmu Weighted k-Nearest Neighbors (WkNN) układu ESPAR."""

import json
import math
import os
import statistics

from config import VALID_CHARS, get_radio_map_path


# Wczytuje bazę odcisków z pliku JSON i opcjonalnie filtruje punkty należące do aktywnej sesji.
def load_radio_map(filter_session: bool = False, path: str = None) -> list:
    path = path or get_radio_map_path()
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if isinstance(data, dict):
        return []

    entries = [entry for entry in data if isinstance(entry, dict) and "beacons" in entry]

    if filter_session and os.path.basename(path) == "radio_map.json":
        from config import get_active_session_label
        sess = get_active_session_label()
        if sess and sess != 'unknown':
            entries = [e for e in entries if e.get("_local", {}).get("session") == sess]

    return entries


def save_radio_map(fingerprints: list, path: str = None) -> None:
    path = path or get_radio_map_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fingerprints, f, indent=2, ensure_ascii=False)


# Zwraca posortowaną listę aktywnych sektorów anteny obecnych w badanej mapie radiowej.
def _get_directions(radio_map: list, beacon_id: int = None) -> list:
    dirs = set()
    for fp in radio_map:
        beacons = fp.get("beacons", {})
        for bid_str, bid_data in beacons.items():
            avg_dict = bid_data.get("avg", {})
            dirs.update(k for k in avg_dict.keys() if k not in ("0", "4095"))
    return sorted(dirs, key=lambda x: int(x))


HYBRID_LAMBDA: float = 0


# Odległość oparta na korelacji Pearsona (1 - r) badająca dopasowanie samego kształtu wiązki RSSI.
def _pearson_distance(v1: list, v2: list) -> float:
    n = len(v1)
    if n == 0:
        return 2.0

    mean1 = sum(v1) / n
    mean2 = sum(v2) / n

    num  = sum((a - mean1) * (b - mean2) for a, b in zip(v1, v2))
    den1 = sum((a - mean1) ** 2 for a in v1)
    den2 = sum((b - mean2) ** 2 for b in v2)

    if den1 == 0 or den2 == 0:
        return 2.0

    r = num / math.sqrt(den1 * den2)
    return 1.0 - r


# Klasyczna odległość euklidesowa wyliczana po odjęciu średnich poziomów RSSI.
def _euclidean_distance(v1: list, v2: list) -> float:
    n1, n2 = len(v1), len(v2)
    if n1 == 0 or n2 == 0:
        return 0.0

    m1 = sum(v1) / n1
    m2 = sum(v2) / n2

    return math.sqrt(sum(((a - m1) - (b - m2)) ** 2 for a, b in zip(v1, v2)))


# Metryka hybrydowa łącząca dopasowanie kształtu (Pearson) z karą za różnicę średniej mocy sygnału.
def _hybrid_distance(v1: list, v2: list, lambda_penalty: float = HYBRID_LAMBDA) -> float:
    d_p = _pearson_distance(v1, v2)

    v1_valid = [x for x in v1 if x > -94.0]
    v2_valid = [x for x in v2 if x > -94.0]

    m1 = sum(v1_valid) / len(v1_valid) if v1_valid else (sum(v1) / len(v1) if len(v1) > 0 else 0.0)
    m2 = sum(v2_valid) / len(v2_valid) if v2_valid else (sum(v2) / len(v2) if len(v2) > 0 else 0.0)

    penalty = lambda_penalty * abs(m1 - m2)
    return d_p + penalty


def load_distance_metric() -> str:
    from config import ESPAR_CONFIG_PATH
    if os.path.exists(ESPAR_CONFIG_PATH):
        try:
            with open(ESPAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("metric", "pearson")
        except Exception:
            pass
    return "pearson"


def save_distance_metric(metric: str) -> None:
    global DISTANCE_METRIC
    DISTANCE_METRIC = metric
    from config import ESPAR_CONFIG_PATH
    try:
        cfg = {}
        if os.path.exists(ESPAR_CONFIG_PATH):
            try:
                with open(ESPAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        cfg["metric"] = metric
        with open(ESPAR_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Błąd zapisu konfiguracji metryki: {e}")


DISTANCE_METRIC: str = load_distance_metric()


# Estymuje pozycję (X, Y) oraz pewność pomiaru na podstawie K najbliższych sąsiadów ważonych wagami 1/d^2.
def wknn_estimate(window_data: dict, radio_map: list,
                  k: int = 3, beacon_id: int = None):
    if not radio_map or not window_data:
        return None

    b_data = None
    if beacon_id is not None:
        b_data = window_data.get(beacon_id) or window_data.get(str(beacon_id))

    if b_data is None and window_data:
        b_data = next(iter(window_data.values()))

    if not b_data:
        return None

    directions = _get_directions(radio_map, beacon_id)
    if not directions:
        directions = [str(ch) for ch in sorted(VALID_CHARS)]

    raw_avg = {}
    measured_count = 0

    # Wyliczamy medianę RSSI dla każdego zmierzonego kierunku wiązki
    for d in directions:
        vals = b_data.get(d) or b_data.get(str(d)) or b_data.get(int(d))
        if vals:
            raw_avg[str(d)] = float(statistics.median(vals))
            measured_count += 1
        else:
            raw_avg[str(d)] = -95.0

    if measured_count == 0:
        return None

    dists = []
    for fp in radio_map:
        beacons = fp.get("beacons", {})
        if not beacons:
            continue

        fp_avg = None
        if beacon_id is not None:
            entry = beacons.get(str(beacon_id))
            if isinstance(entry, dict):
                fp_avg = entry.get("avg")

        if fp_avg is None:
            first_entry = next(iter(beacons.values()), None)
            if isinstance(first_entry, dict):
                fp_avg = first_entry.get("avg", {})

        if not fp_avg:
            continue

        live_vec = []
        fp_vec = []

        for d in directions:
            live_vec.append(raw_avg[str(d)])
            val_ref = fp_avg.get(d) or fp_avg.get(str(d)) or fp_avg.get(int(d))

            if val_ref is not None:
                fp_vec.append(float(val_ref))
            else:
                fp_vec.append(-95.0)

        if DISTANCE_METRIC == 'euclidean':
            d = _euclidean_distance(live_vec, fp_vec)
        elif DISTANCE_METRIC == 'hybrid':
            d = _hybrid_distance(live_vec, fp_vec)
        else:
            d = _pearson_distance(live_vec, fp_vec)

        dists.append((d, fp["x_m"], fp["y_m"], fp.get("label", ""), len(directions)))

    if not dists:
        return None

    dists.sort(key=lambda t: t[0])
    k = min(k, len(dists))
    top_k = dists[:k]

    EPS = 1e-9
    if top_k[0][0] < EPS:
        return top_k[0][1], top_k[0][2], 1.0

    # Wagi proporcjonalne do odwrotności kwadratu odległości w przestrzeni cech
    weights = [1.0 / (max(d, EPS) ** 2) for d, *_ in top_k]
    total_w = sum(weights)

    x_est = sum(w * x for w, (_, x, y, *_) in zip(weights, top_k)) / total_w
    y_est = sum(w * y for w, (_, x, y, *_) in zip(weights, top_k)) / total_w

    d_min = top_k[0][0]
    if DISTANCE_METRIC == 'euclidean':
        n_dirs = top_k[0][4]
        e_avg = d_min / math.sqrt(n_dirs) if n_dirs > 0 else 0.0
        confidence = math.exp(-e_avg / 10.0)
    else:
        confidence = max(0.0, min(1.0, 1.0 - d_min))

    return round(x_est, 3), round(y_est, 3), round(confidence, 3)
