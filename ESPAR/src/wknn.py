"""
wknn.py — Algorytm Weighted k-Nearest Neighbors (WkNN) dla systemu ESPAR IPS.

Rola modułu
-----------
Moduł odpowiada za dwie operacje:
    1. Wczytywanie / zapisywanie mapy radiowej (radio_map.json).
    2. Estymację pozycji metodą WkNN na podstawie pomiarów RSS z anteny ESPAR.

Mapa radiowa (radio_map.json)
-----------------------------
Jest to lista punktów kalibracyjnych zebranych ręcznie podczas fazy offline.
Każdy punkt reprezentuje jedno miejsce w przestrzeni, w którym zebrano
pomiary RSSI dla wszystkich 12 konfiguracji anteny ESPAR.

Struktura pojedynczego wpisu:
    {
        "label":  "pokoj_707_p1",   # czytelna nazwa punktu
        "x_m":    27.26,            # współrzędna X w metrach (układ budynku)
        "y_m":    -4.46,            # współrzędna Y w metrach (układ budynku)
        "beacons": {
            "28": {                 # numer beacona BLE
                "avg":  {           # średnie RSSI per konfiguracja anteny
                    "31":  -65.2,   # klucz = char_int konfiguracji, wartość = dBm
                    "62":  -67.8,
                    ...
                },
                "norm": {           # znormalizowane wartości min-max [0.0 .. 1.0]
                    "31":  1.0,
                    "62":  0.76,
                    ...
                }
            }
        }
    }

Algorytm WkNN
-------------
Faza online (pozycjonowanie):
    1. Zbierz pakiety BLE z okna czasowego (np. 5 s).
    2. Oblicz średnie RSSI per konfiguracja anteny → wektor V_live.
    3. Oblicz odległość między V_live a każdym fingerprinting-iem z mapy.
    4. Wybierz K najbliższych sąsiadów.
    5. Wylicz ważoną sumę ich współrzędnych (waga = 1 / d²).

Metryka odległości
------------------
Aktywna: korelacja Pearsona (1 − r).
    Zakres [0, 2], mniejsze = lepiej.
    Odporna na bezwzględne przesunięcia RSS między sesjami (liczy się
    kształt wektora, a nie jego poziom bezwzględny).

Alternatywna (zakomentowana): odległość euklidesowa.
    Zgodna ze wzorem (6) z artykułu "Calibration-Free Single-Anchor
    Indoor Localization Using an ESPAR Antenna", Sensors 2021, 21, 3431.
    Wrażliwa na zmiany bezwzględnego poziomu RSS — wymaga wcześniejszej
    normalizacji wektorów.
"""

import json
import math
import os

# ── Ścieżka do pliku mapy radiowej ──────────────────────────────────────────
RADIO_MAP_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "radio_map.json")
)


# ════════════════════════════════════════════════════════════════════════════
# Operacje I/O na mapie radiowej
# ════════════════════════════════════════════════════════════════════════════

def load_radio_map(path: str = RADIO_MAP_PATH) -> list:
    """
    Wczytuje mapę radiową z pliku JSON.

    Returns:
        Lista punktów kalibracyjnych (słowniki). Pusta lista jeśli plik
        nie istnieje lub jest w nieobsługiwanym formacie.
    """
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Stary format — słownik zamiast listy (brak współrzędnych pozycji)
    if isinstance(data, dict):
        return []
    return data


def save_radio_map(fingerprints: list, path: str = RADIO_MAP_PATH) -> None:
    """
    Zapisuje listę punktów kalibracyjnych do pliku JSON.

    Args:
        fingerprints: Lista punktów kalibracyjnych (jak zwrócona przez load_radio_map).
        path:         Ścieżka docelowa pliku. Domyślnie RADIO_MAP_PATH.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fingerprints, f, indent=2, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════════════
# Funkcje pomocnicze
# ════════════════════════════════════════════════════════════════════════════

def normalize_rssi(avg_rssi: dict) -> dict:
    """
    Normalizacja min-max wektora RSSI do zakresu [0.0 .. 1.0].

    Wzór: norm_i = (rssi_i − min) / (max − min)

    Normalizacja eliminuje wpływ bezwzględnego poziomu sygnału (np. różnice
    odległości beacon–antena), pozostawiając jedynie informację o kierunkowości.

    Args:
        avg_rssi: Słownik {char_int_str: avg_rssi_dBm}.

    Returns:
        Słownik {char_int_str: wartość_znormalizowana}.
    """
    if not avg_rssi:
        return {}
    vals = list(avg_rssi.values())
    mn, mx = min(vals), max(vals)
    if mx == mn:
        return {k: 0.0 for k in avg_rssi}  # wszystkie wartości identyczne
    return {k: round((v - mn) / (mx - mn), 4) for k, v in avg_rssi.items()}


def _get_directions(radio_map: list, beacon_id: int) -> list:
    """
    Zwraca posortowaną listę wszystkich kluczy konfiguracji ESPAR (char_int
    jako stringi), które występują w mapie radiowej dla danego beacona.

    Używane do budowania spójnych wektorów cech o jednakowej kolejności.
    """
    dirs = set()
    bid = str(beacon_id)
    for fp in radio_map:
        avg_dict = fp.get("beacons", {}).get(bid, {}).get("avg", {})
        dirs.update(k for k in avg_dict.keys() if k not in ("0", "4095"))
    return sorted(dirs, key=lambda x: int(x))


def _fp_vector(fp: dict, beacon_id: int, directions: list) -> list:
    """
    Buduje wektor RSSI dla jednego punktu kalibracyjnego.

    Dla brakujących konfiguracji przyjmuje wartość -95.0 dBm (typowy dolny
    próg czułości odbiornika BLE — kara za brak danych).

    Args:
        fp:         Punkt kalibracyjny z mapy radiowej.
        beacon_id:  Numer beacona.
        directions: Posortowana lista kluczy konfiguracji (z _get_directions).

    Returns:
        Lista float w kolejności zgodnej z 'directions'.
    """
    avg = fp.get("beacons", {}).get(str(beacon_id), {}).get("avg", {})
    return [float(avg.get(d, -95.0)) for d in directions]


# ════════════════════════════════════════════════════════════════════════════
# Metryki odległości między wektorami RSS
# ════════════════════════════════════════════════════════════════════════════

def _pearson_distance(v1: list, v2: list) -> float:
    """
    Odległość oparta na współczynniku korelacji Pearsona: d = 1 − r.

    Zakres: [0, 2], gdzie 0 = wektory idealnie skorelowane (ten sam kształt),
    2 = wektory antyskorelowane.

    Zaleta: odporna na bezwzględne przesunięcia poziomu RSS między sesjami
    (liczy się kształt profilu kierunkowego, nie poziom bezwzględny).
    Dzięki temu nie wymaga normalizacji wektorów przed porównaniem.

    Args:
        v1, v2: Wektory RSSI tej samej długości.

    Returns:
        Odległość Pearsona. Wartość 2.0 przy błędzie (np. wektory zerowej wariancji).
    """
    n = len(v1)
    if n == 0:
        return 2.0

    mean1 = sum(v1) / n
    mean2 = sum(v2) / n

    num  = sum((a - mean1) * (b - mean2) for a, b in zip(v1, v2))
    den1 = sum((a - mean1) ** 2 for a in v1)
    den2 = sum((b - mean2) ** 2 for b in v2)

    if den1 == 0 or den2 == 0:
        return 2.0  # jeden z wektorów jest stały (zerowa wariancja)

    r = num / math.sqrt(den1 * den2)
    return 1.0 - r


def _euclidean_distance(v1: list, v2: list) -> float:
    """
    Odległość euklidesowa między wektorami RSS.

    Wzór (6) z artykułu "Calibration-Free Single-Anchor Indoor Localization
    Using an ESPAR Antenna", Sensors 2021, 21, 3431:
        D_j = sqrt( Σ (RSS_live_i − RSS_fp_i)² )

    Zakres: [0, +∞), mniejsze = lepiej.

    Uwaga: metryka jest wrażliwa na bezwzględny poziom RSS. Jeśli beacon
    jest bliżej lub dalej niż podczas kalibracji, cały wektor jest
    przesunięty i odległość rośnie nawet przy poprawnym kierunku.
    Zalecana normalizacja min-max wektorów przed porównaniem.
    """
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


# ════════════════════════════════════════════════════════════════════════════
# Wybór metryki odległości
# ════════════════════════════════════════════════════════════════════════════

# Zmień tę wartość aby przełączyć metrykę używaną w wknn_estimate().
#
# Metryka          │ Zakres      │ Sortowanie top-K │ Uwagi
# ─────────────────┼─────────────┼──────────────────┼──────────────────────────────
# 'pearson'        │ [0, 2]      │ rosnąco (min)    │ d = 1−r, kształt wektora
# 'euclidean'      │ [0, +∞)     │ rosnąco (min)    │ wymaga normalizacji RSS
DISTANCE_METRIC: str = 'pearson'  # <- zmień na 'euclidean' aby porównać


# ════════════════════════════════════════════════════════════════════════════
# Główna funkcja estymacji pozycji
# ════════════════════════════════════════════════════════════════════════════

def wknn_estimate(window_data: dict, radio_map: list,
                  k: int = 3, beacon_id: int = 28):
    """
    Estymuje pozycję metodą Weighted k-Nearest Neighbors (WkNN).

    Algorytm:
        1. Wyciągnij dane RSSI dla danego beacona z okna czasowego.
        2. Oblicz średnie RSSI per konfiguracja anteny → wektor V_live.
        3. Dla każdego fingerprinta z mapy oblicz odległość do V_live.
        4. Wybierz K najbliższych sąsiadów.
        5. Wylicz pozycję jako ważoną sumę (waga = 1 / d²) ich współrzędnych.

    Args:
        window_data: Słownik z pakietami zebranymi w oknie czasowym.
                     Format: {beacon_id: {char_int_str: [rssi_val, ...]}}
        radio_map:   Lista punktów kalibracyjnych (z load_radio_map()).
        k:           Liczba najbliższych sąsiadów.
        beacon_id:   Numer beacona BLE do lokalizowania.

    Returns:
        Krotka (x_m, y_m, confidence) jeśli estymacja się powiodła, lub None.
        confidence ∈ [0.0, 1.0]:  1.0 = idealnie pasuje do fingerprinta,
                                   0.0 = brak korelacji z żadnym punktem.
    """
    if not radio_map:
        return None

    # 1. Wyodrębnij dane dla lokalizowanego beacona z okna czasowego
    b_data = window_data.get(beacon_id) or window_data.get(str(beacon_id))
    if not b_data:
        return None

    # 2. Pobierz wspólną listę konfiguracji anteny z mapy radiowej
    directions = _get_directions(radio_map, beacon_id)
    if not directions:
        return None

    # 3. Uśrednij RSSI z okna dla każdej konfiguracji anteny.
    #    Porównujemy tylko konfiguracje z rzeczywistymi pomiarami.
    raw_avg = {}
    valid_dirs = []
    for d in directions:
        # Klucz może być stringiem lub intem — sprawdzamy oba warianty
        vals = b_data.get(d) or b_data.get(str(d)) or b_data.get(int(d))
        if vals:
            raw_avg[str(d)] = sum(vals) / len(vals)
            valid_dirs.append(str(d))

    # Odrzuć okno, jeśli danych jest zbyt mało (mniej niż połowa konfiguracji)
    if len(valid_dirs) < 6:
        return None

    live_vec = [raw_avg[d] for d in valid_dirs]

    # 4. Oblicz odległości do wszystkich punktów kalibracyjnych
    #
    # Obie dostępne metryki zwracają wartość, gdzie MNIEJSZA = lepsze dopasowanie:
    #   Pearson:   d = 1−r ∈ [0, 2]   (r=1 → d=0 = idealny, r=−1 → d=2 = antykorelacja)
    #   Euklides:  d ∈ [0, +∞)        (d=0 = identyczne wektory)
    # W obu przypadkach sortujemy rosnąco i wybieramy K pierwszych.
    dists = []
    for fp in radio_map:
        # Budujemy wektor odcisków radiowych tylko dla konfiguracji obecnych w oknie czasowym
        fp_vec = _fp_vector(fp, beacon_id, valid_dirs)
        if DISTANCE_METRIC == 'euclidean':
            d = _euclidean_distance(live_vec, fp_vec)
        else:  # 'pearson' (domyślne)
            d = _pearson_distance(live_vec, fp_vec)
        dists.append((d, fp["x_m"], fp["y_m"], fp.get("label", "")))

    # Sortowanie rosnąco — mniejsza odległość = lepsze dopasowanie (obie metryki)
    dists.sort(key=lambda t: t[0])
    k = min(k, len(dists))
    top_k = dists[:k]

    # 5. Przypadek specjalny: idealny match (odległość praktycznie zerowa)
    EPS = 1e-9
    if top_k[0][0] < EPS:
        return top_k[0][1], top_k[0][2], 1.0

    # 6. Ważona suma współrzędnych K sąsiadów (waga = 1 / d²)
    weights = [1.0 / (d ** 2 + EPS) for d, *_ in top_k]
    total_w = sum(weights)
    x_est = sum(w * x for w, (_, x, y, __) in zip(weights, top_k)) / total_w
    y_est = sum(w * y for w, (_, x, y, __) in zip(weights, top_k)) / total_w

    # 7. Pewność (confidence) — zależna od metryki:
    d_min = top_k[0][0]
    if DISTANCE_METRIC == 'euclidean':
        # Euklides: d ∈ [0, +∞) — normalizujemy przez d_max spośród top_k.
        # conf = 1 − d_min/d_max ∈ [0, 1]; pełna pewność gdy d_min=0,
        # zero gdy d_min = d_max (wszystkie K punktów jednakowo odległe).
        d_max = top_k[-1][0]
        confidence = 1.0 - (d_min / d_max) if d_max > EPS else 1.0
    else:
        # Pearson: d = 1−r ∈ [0, 2] — mapujemy liniowo na [0, 1].
        # conf = 1 − d_min  (d=0 → conf=1, d=1 → conf=0, d>1 → obcięte do 0)
        confidence = max(0.0, min(1.0, 1.0 - d_min))

    return round(x_est, 3), round(y_est, 3), round(confidence, 3)
