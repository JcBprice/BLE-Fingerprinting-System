# 📡 ESPAR IPS — Indoor Positioning System

System precyzyjnej lokalizacji wewnątrzbudynkowej (IPS — *Indoor Positioning System*) czasu rzeczywistego, oparty na pojedynczych elektronicznie sterowanych antenach pasożytniczych **ESPAR** (*Electronically Steerable Parasitic Array Radiator*) oraz miniaturowych nadajnikach radiowych **BLE** (*Bluetooth Low Energy*).

System umożliwia estymację pozycji obiektu na podstawie kierunkowych sygnatur radiowych (*fingerprinting*) z 12 sektorów wiązki antenowej ESPAR, osiągając średnią dokładność lokalizacji poniżej **1 metra** (RMSE ~1.08 m w warunkach korytarza akademickiego).

---

## ✨ Kluczowe funkcjonalności

| Moduł | Opis |
|---|---|
| **Klasyczny Fingerprinting (Offline)** | Precyzyjne zbieranie odcisków radiowych RSSI w siatce regularnej, z obsługą statywów wielonadajnikowych (*tripod array*) i automatycznej ścieżki meandrowej. |
| **Lokalizacja kotwicowa (Anchor Beacons)** | Tryb szybkiej auto-kalibracji bez konieczności manualnego pomiaru siatki — wykorzystuje stałe nadajniki referencyjne zamontowane w znanych punktach budynku (np. na drzwiach sal). |
| **Pozycjonowanie Live (Online)** | Śledzenie pozycji w czasie rzeczywistym z użyciem algorytmu **WkNN** (*Weighted k-Nearest Neighbors*), bufora kołowego FIFO i adaptacyjnego filtru wygładzającego **EMA** ($\alpha=0.35$). |
| **Metryki odległości sygnatur** | Wybór metryki podobieństwa wektorów RSSI: korelacja Pearsona, Zero-Mean Euclidean, metryka hybrydowa oraz wzorzec ważony (*Weighted Pattern*). |
| **Wizualizacja GUI (PyQt6)** | Dynamiczny interfejs graficzny z wektorowym rzutem piętra w formacie SVG, śladem trajektorii (*history trail*), radarem kąta nadejścia sygnału (AoA) oraz interaktywnym panelem bocznym. |
| **Walidacja i optymalizacja K** | Moduł analityczny wyznaczający błędy empiryczne (średni, mediana, RMSE, P90, błędy stref krańcowych), automatyczny dobór optymalnego $K$ oraz wykresy dystrybuanty błędu (CDF). |
| **Analiza stabilności RSSI** | Wykresy biegunowe (radary kierunkowe) dla 12 wiązek, analizy wielosesyjne, mapy ciepła (heatmaps) i detekcja anomalii tłumienia. |
| **Multi-antena (Auto-Switching)** | Skanowanie dostępnych portów TCP i automatyczne przełączanie na antenę ESPAR odbierającą najsilniejszy pakiet od szukanego beacona. |

---

## 🏗️ Architektura przepływu danych

```
 [Antena ESPAR 2.4 GHz]
          │ (Strumień TCP / Telnet)
          ▼
   telnet_reader.py ────► espar_client.py
          │
          ├──── [FAZA OFFLINE / KALIBRACJA]
          │         ▼
          │   fingerprint.py ────► calibration.py / beacon_calibration.py
          │         ▼
          │   radio_map_{sesja}.json (baza odcisków 12 wiązek)
          │
          └──── [FAZA ONLINE / POZYCJONOWANIE LIVE]
                    ▼
              threads.py (QThread, bufor FIFO w oknie czasowym)
                    ▼
              wknn.py (Pearson / Zero-Mean / Hybrydowa / Weighted Pattern)
                    ▼
              Filtracja EMA (x_ema, y_ema)
                    ▼
              gui/window.py + gui/canvas.py (SVG Floorplan + Radar AoA)
```

---

## 🛠️ Technologie i wymagania

- **Python**: 3.10+ (rekomendowany Python 3.12)
- **PyQt6**: Wielowątkowy interfejs graficzny i akcelerowane renderowanie SVG
- **NumPy & Matplotlib**: Obliczenia macierzowe wektorów RSSI, generowanie wykresów CDF, scatter oraz radarów biegunowych
- **Menadżer pakietów**: `uv` lub `pip`

---

## 🚀 Uruchomienie projektu

### 1. Instalacja zależności

Przy użyciu standardowego menadżera `pip`:
```bash
pip install PyQt6 matplotlib numpy
```

Lub przy użyciu menadżera `uv` (rekomendowane):
```bash
uv sync
```

### 2. Uruchomienie konsolowego menu głównego

Główny punkt wejściowy systemu:
```bash
python ESPAR/src/main.py
```

### 3. Bezpośrednie uruchomienie GUI podglądu mapy

```bash
python ESPAR/src/map_viewer.py
```

---

## 📋 Menu główne systemu (CLI)

Główny pulpit konsolowy [ESPAR/src/main.py](ESPAR/src/main.py) wyświetla na żywo podsumowanie stanu aktywnej sesji, podłączonej anteny, bazy odcisków oraz udostępnia 12 dedykowanych opcji operacyjnych:

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    SYSTEM LOKALIZACJI ESPAR IPS                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  Sesja:    'korytarz' @ (21.74, 8.30) m                              ║
║  Konf:     Antena 8894 (espar37) │ Metryka: pearson │ K: 3           ║
║  Baza:     Odciski: 63 pkt │ Testowe: 10 pkt │ Beacony: 10           ║
╠══════════════════════════════════════════════════════════════════════╣
║  [KALIBRACJA]                                                        ║
║    1. Zmiana pokoju (sesji)       2. Tworzenie mapy radiowej         ║
║                                                                      ║
║  [DIAGNOSTYKA & MAPA]                                                ║
║    3. Podgląd mapy na żywo        4. Analiza RSSI & wizualizacje     ║
║                                                                      ║
║  [WALIDACJA & TESTY]                                                 ║
║    5. Punkty testowe              6. Optymalizacja parametru K       ║
║    7. Raport walidacji błędów                                        ║
║                                                                      ║
║  [USTAWIENIA & SYSTEM]                                               ║
║    8. Wybór anteny i portu        9. Zmiana metryki odległości       ║
║   10. Zbadaj RSSI beaconów       11. System kotwicowy - anchors      ║
║   12. Monitor pakietów - podgląd strumienia danych                   ║
║                                                                      ║
║    0. Zakończ program                                                ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Szczegółowy opis opcji:

* **`1. Zmiana pokoju (sesji)`** — Zarządzanie sesją pomiarową (np. korytarz, pokój), wybór lub utworzenie nowej sesji oraz graficzne/tekstowe ustalenie punktu bazowego (origin $(0,0)$) na rzucie SVG.
* **`2. Tworzenie mapy radiowej`** — Kalibracja offline:
  * `p` — Pojedynczy punkt (graficznie celownikiem na mapie SVG `[g]` lub tekstowo z konsoli `[t]`).
  * `w` — Wiele punktów (sekwencja ze statywem / lista punktów trasy).
  * `s` — Siatka automatyczna (grid pomiarowy meandrowy z obsługą statywu tripod i orientacji kątowej).
* **`3. Podgląd mapy na żywo`** — Uruchomienie okna wizualizacji GUI (`map_viewer.py --view <beacon_id>`) ze śledzeniem pozycji wybranego nadajnika na żywo, radarem AoA i podglądem siatki punktów.
* **`4. Analiza RSSI & wizualizacje`** — Moduł diagnostyczny:
  * `1` — Analiza istniejących danych (charakterystyka bazy offline z filtrowaniem punktów mapy przy łączeniu).
  * `2` — Nowy pomiar na żywo z rotacją anteny i zapisem snapshotu.
  * `3` — Detekcja najsilniejszej anteny / klasyfikacja pomieszczenia.
* **`5. Punkty testowe`** — Rejestracja punktów referencyjnych *ground truth* (graficznie celownikiem na mapie SVG `[g]` lub ze współrzędnych tekstowych `[t]`) do niezależnej walidacji.
* **`6. Optymalizacja parametru K`** — Wyznaczenie optymalnej liczby najbliższych sąsiadów $K$ dla algorytmu WkNN: automatycznie metodą grid search `[a]` lub ręcznie `[r]`.
* **`7. Raport walidacji błędów`** — Pełna ewaluacja dokładności: wyliczenie błędu średniego, mediany, RMSE, P90, błędów w strefach krańcowych korytarza oraz wykresów dystrybuanty błędu (CDF).
* **`8. Wybór anteny i portu`** — Przełączenie aktywnego portu TCP kontrolera ESPAR (np. `8894` dla espar37, `8895` dla espar35) oraz dynamiczne dodawanie nowych anten (`d`).
* **`9. Zmiana metryki odległości`** — Wybór funkcji odległości wektorów sygnatur:
  * `1` — Pearson (korelacja kształtu sygnatury),
  * `2` — Euclidean (odległość euklidesowa wycentrowana),
  * `3` — Hybrid (kombinacja korelacji kształtu i różnicy amplitud mocy),
  * `4` — Weighted Pattern (wzorzec ważony sektorów).
* **`10. Zbadaj RSSI beaconów`** — Wieloportowe skanowanie anten laboratoryjnych i stref — automatyczna detekcja anteny ESPAR odbierającej najsilniejszy pakiet od poszukiwanego nadajnika.
* **`11. System kotwicowy - anchors`** — Podmenu bezkalibracyjnej lokalizacji opartej na stałych nadajnikach referencyjnych (*Anchor Beacons*):
  * `1` — Zarejestruj beacony orientacyjne na mapie SVG,
  * `2` — Pokaż listę zarejestrowanych beaconów,
  * `3` — Zbierz radio mapę z beaconów (auto-kalibracja wirtualnej bazy),
  * `4` — Śledź beacon na żywo w odniesieniu do kotwic,
  * `5` — Usuń beacon orientacyjny.
* **`12. Monitor pakietów - podgląd strumienia danych`** — Licznik odbieranych ramek radiowych w czasie rzeczywistym z odświeżaniem w miejscu w terminalu ANSI, statystykami RSSI i rotacji konfiguracji anteny.
* **`0. Zakończ program`** — Bezpieczne zamknięcie połączeń sieciowych gniazd TCP i wyjście z aplikacji.

---

## 📂 Struktura katalogów

```text
BLE-Fingerprinting-System/
├── ESPAR/
│   ├── architectural.md        # Szczegółowa dokumentacja techniczna i architektoniczna (v2.2)
│   ├── data/                   # Aktywne bazy radiowe, raporty walidacji i konfiguracja sesji
│   │   ├── session.json        # Bieżąca sesja, współrzędne originu i historia sesji
│   │   ├── espar_config.json   # Parametry sieciowe anten (IP, port TCP, aktywna metryka)
│   │   ├── optimal_k.json      # Optymalne parametry WkNN wyznaczone podczas walidacji
│   │   ├── validation_report.json # Ostatni wygenerowany raport dokładności systemu
│   │   ├── rssi_snapshots/     # Zrzuty pomiarowe i wygenerowane wykresy radarowe (10 najnowszych)
│   │   ├── radio_map_*.json    # Bazy odcisków radiowych poszczególnych sesji
│   │   └── test_set_*.json     # Zbiory punktów weryfikacyjnych
│   └── src/
│       ├── main.py             # Główny interfejs konsolowy CLI z ramkowym menu 1-12
│       ├── config.py           # Stałe globalne, porty, geometria anteny i mapowania wiązek
│       ├── session.py          # Zarządzanie sesjami pomiarowymi i punktem bazowym (origin)
│       ├── espar_client.py     # Klient gniazd TCP do komunikacji z kontrolerem ESPAR
│       ├── telnet_reader.py    # Asynchroniczny parser ramek binarno-tekstowych BLE
│       ├── fingerprint.py      # Agregacja pomiarów (mediana/średnia) do 12-kierunkowego wektora
│       ├── calibration.py      # Procedury kalibracji siatkowej i obsługa statywów tripod
│       ├── beacon_config.py    # Konfiguracja i rejestracja stałych beaconów kotwicowych
│       ├── beacon_calibration.py # Budowa wirtualnej bazy z beaconów kotwicowych
│       ├── wknn.py             # Implementacja algorytmu WkNN i 4 metryk odległości
│       ├── validate.py         # Moduł ewaluacji błędów, generowania krzywych CDF i siatek
│       ├── rssi_analysis.py    # Moduł wykresów biegunowych, stabilności i analizy AoA
│       ├── room_detector.py    # Wieloportowy detektor najsilniejszej anteny ESPAR
│       ├── counter.py          # Licznik odebranych pakietów w konsoli ANSI na żywo
│       ├── map_viewer.py       # Samodzielny launcher okna GUI
│       ├── utils.py            # Zunifikowana selekcja beaconów ([w bazie], [wykryty]), dialogi
│       └── gui/                # Zmodularyzowany interfejs graficzny PyQt6
│           ├── __init__.py     # Eksporty modułu GUI
│           ├── styles.py       # Palety kolorów, style CSS i transformacje współrzędnych SVG
│           ├── canvas.py       # Płótno mapy: renderowanie SVG, estymaty, radar AoA i trail
│           ├── panel.py        # Adaptacyjny panel boczny (parametry live, kalibracja, kotwice)
│           ├── threads.py      # Wątki QThread obsługujące odbiór danych TCP i filtrację EMA
│           └── window.py       # Główne okno aplikacji okienkowej (QMainWindow)
├── SVG_parser/
│   └── mapaAK_sieciowe_v3.svg  # Wektorowy rzut architektoniczny piętra budynku
├── old_fingerprints/           # Archiwum historycznych baz i backupów
├── pyproject.toml              # Definicja projektu i zależności Python
└── README.md                   # Niniejsza dokumentacja
```

---

## 📖 Pełna dokumentacja projektu

Kompletny, wyczerpujący opis matematyczny zastosowanych algorytmów (WkNN, metryka hybrydowa, filtracja EMA, estymacja AoA), protokołu komunikacyjnego anteny ESPAR oraz opis poszczególnych modułów znajduje się w dokumencie:
👉 [**ESPAR/architectural.md**](ESPAR/architectural.md)
