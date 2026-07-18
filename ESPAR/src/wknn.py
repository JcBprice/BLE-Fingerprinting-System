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

from config import get_radio_map_path


# ════════════════════════════════════════════════════════════════════════════
# Operacje I/O na mapie radiowej
# ════════════════════════════════════════════════════════════════════════════

def load_radio_map(path: str = None, filter_session: bool = False) -> list:
    """
    Wczytuje mapę radiową z pliku JSON.

    Args:
        path: Ścieżka do pliku (None = użyj dynamicznej z get_radio_map_path()).
        filter_session: Jeśli True, zwraca tylko punkty dopasowane do aktywnej sesji z session.json.

    Returns:
        Lista punktów kalibracyjnych (słowniki). Pusta lista jeśli plik
        nie istnieje lub jest w nieobsługiwanym formacie.
    """
    if path is None:
        path = get_radio_map_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        return []
        
    entries = [entry for entry in data if isinstance(entry, dict) and "beacons" in entry]
    
    # Filtrowanie po aktywnej sesji (tylko dla pliku radio_map.json — sesyjne pliki mają już odfiltrowane dane)
    if filter_session and os.path.basename(path) == "radio_map.json":
        from config import get_active_session_label
        sess = get_active_session_label()
        if sess and sess != 'unknown':
            entries = [e for e in entries if e.get("_local", {}).get("session") == sess]
                
    return entries


def save_radio_map(fingerprints: list, path: str = None) -> None:
    """
    Zapisuje listę punktów kalibracyjnych do pliku JSON.

    Args:
        fingerprints: Lista punktów kalibracyjnych (jak zwrócona przez load_radio_map).
        path:         Ścieżka docelowa pliku (None = użyj dynamicznej z get_radio_map_path()).
    """
    if path is None:
        path = get_radio_map_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fingerprints, f, indent=2, ensure_ascii=False)


def _get_directions(radio_map: list, beacon_id: int) -> list:
    """
    Zwraca posortowaną listę wszystkich kluczy konfiguracji ESPAR (char_int
    jako stringi), które występują w mapie radiowej.

    Zbiera konfiguracje kierunkowe anteny ze wszystkich wpisów, ponieważ
    zbiór możliwych stanów przełączanych jest stałą cechą sprzętową anteny ESPAR.
    """
    dirs = set()
    for fp in radio_map:
        beacons = fp.get("beacons", {})
        for bid_str, bid_data in beacons.items():
            avg_dict = bid_data.get("avg", {})
            dirs.update(k for k in avg_dict.keys() if k not in ("0", "4095"))
    return sorted(dirs, key=lambda x: int(x))


# _fp_vector został usunięty zgodnie z życzeniem usuwania stałej -95 dBm.
# Odległość jest teraz wyliczana tylko na przecięciu rzeczywiście odebranych kierunków.


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
    Odległość euklidesowa między wektorami RSS z wycentrowaniem do zera (mean-centering).

    Wzór z wycentrowaniem poziomu sygnału (zero-mean Euclidean distance):
        D_j = sqrt( Σ ((RSS_live_i - mean(RSS_live)) − (RSS_fp_i - mean(RSS_fp)))² )

    Zakres: [0, +∞), mniejsze = lepiej.

    Wycentrowanie eliminuje niekorzystny wpływ bezwzględnego poziomu sygnału (path-loss / moc beacona),
    skupiając się na profilu kierunkowym anteny ESPAR i dynamice zmian między kierunkami.
    """
    n1, n2 = len(v1), len(v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    m1 = sum(v1) / n1
    m2 = sum(v2) / n2
    return math.sqrt(sum(((a - m1) - (b - m2)) ** 2 for a, b in zip(v1, v2)))


# ════════════════════════════════════════════════════════════════════════════
# Wybór metryki odległości
# ════════════════════════════════════════════════════════════════════════════

def load_distance_metric() -> str:
    """Wczytuje wybraną metrykę odległości z pliku konfiguracyjnego."""
    from config import ESPAR_CONFIG_PATH
    if os.path.exists(ESPAR_CONFIG_PATH):
        try:
            with open(ESPAR_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("metric", "pearson")
        except Exception:
            pass
    return "pearson"

def save_distance_metric(metric: str) -> None:
    """Zapisuje wybraną metrykę do pliku konfiguracyjnego i aktualizuje zmienną globalną."""
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

# Zmień tę wartość aby przełączyć metrykę używaną w wknn_estimate().
# Obsługiwane wartości: 'pearson', 'euclidean'
DISTANCE_METRIC: str = load_distance_metric()


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
        3. Dla każdego fingerprinta z mapy oblicz odległość do V_live
           korzystając tylko ze wspólnych, zmierzonych kierunków (bez kar -95 dBm).
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
    #    Pomijamy wartości równe -95.0, aby nie brać ich pod uwagę.
    raw_avg = {}
    valid_dirs = []
    for d in directions:
        vals = b_data.get(d) or b_data.get(str(d)) or b_data.get(int(d))
        if vals:
            avg_val = sum(vals) / len(vals)
            if avg_val != -95.0:
                raw_avg[str(d)] = avg_val
                valid_dirs.append(str(d))

    # Odrzuć okno, jeśli danych jest zbyt mało (mniej niż 4 konfiguracje)
    if len(valid_dirs) < 4:
        return None

    # 4. Oblicz odległości do wszystkich punktów kalibracyjnych
    dists = []
    for fp in radio_map:
        if "beacons" not in fp or not fp["beacons"]:
            continue
        
        beacons = fp["beacons"]
        bid_str = str(beacon_id)
        if bid_str in beacons:
            fp_avg = beacons[bid_str].get("avg", {})
        else:
            first_bid = next(iter(beacons))
            fp_avg = beacons[first_bid].get("avg", {})
            
        # Filtrujemy kierunki — bierzemy tylko te, które są obecne w OBU wektorach
        # i nie są równe -95.0 (kara z ewentualnych starszych baz danych)
        common_dirs = []
        for d in valid_dirs:
            val_ref = fp_avg.get(d) or fp_avg.get(str(d)) or fp_avg.get(int(d))
            if val_ref is not None and float(val_ref) != -95.0:
                common_dirs.append(d)
                
        # Wymagamy co najmniej 4 wspólnych kierunków
        if len(common_dirs) < 4:
            continue
            
        live_subvec = [raw_avg[d] for d in common_dirs]
        fp_subvec = [float(fp_avg.get(d) or fp_avg.get(str(d)) or fp_avg.get(int(d))) for d in common_dirs]
        
        if DISTANCE_METRIC == 'euclidean':
            d = _euclidean_distance(live_subvec, fp_subvec)
        else:  # 'pearson' (domyślne)
            d = _pearson_distance(live_subvec, fp_subvec)
            
        dists.append((d, fp["x_m"], fp["y_m"], fp.get("label", ""), len(common_dirs)))

    if not dists:
        return None

    # Sortowanie rosnąco — mniejsza odległość = lepsze dopasowanie
    dists.sort(key=lambda t: t[0])
    k = min(k, len(dists))
    top_k = dists[:k]

    # 5. Przypadek specjalny: idealny match (odległość praktycznie zerowa)
    EPS = 1e-9
    if top_k[0][0] < EPS:
        return top_k[0][1], top_k[0][2], 1.0

    # 6. Ważona suma współrzędnych K sąsiadów.
    # Dodajemy małe wygładzenie (alpha = 0.05), aby zapobiec "przyklejaniu" się (snapping)
    # pozycji do punktów referencyjnych w przypadku bardzo małych odległości d.
    # Umożliwia to płynną estymację pozycji beacona pomiędzy punktami.
    alpha = 0.05
    weights = [1.0 / ((d + alpha) ** 2) for d, *_ in top_k]
    total_w = sum(weights)
    x_est = sum(w * x for w, (_, x, y, *_) in zip(weights, top_k)) / total_w
    y_est = sum(w * y for w, (_, x, y, *_) in zip(weights, top_k)) / total_w

    # 7. Pewność (confidence)
    d_min = top_k[0][0]
    if DISTANCE_METRIC == 'euclidean':
        # Euklides: d_min to pierwiastek z sumy kwadratów różnic RSSI.
        # Przeliczamy na średni błąd na kierunek i mapujemy wykładniczo:
        # e_avg = d_min / sqrt(n_dirs). Przy e_avg = 0 dB -> 100%, 10 dB -> ~37%
        n_dirs = top_k[0][4]
        e_avg = d_min / math.sqrt(n_dirs) if n_dirs > 0 else 0.0
        confidence = math.exp(-e_avg / 10.0)
    else:
        confidence = max(0.0, min(1.0, 1.0 - d_min))

    return round(x_est, 3), round(y_est, 3), round(confidence, 3)
