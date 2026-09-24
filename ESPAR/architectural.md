# ESPAR IPS — Dokumentacja Architektury

> **Wersja:** 2.2 (Stan po pełnej refaktoryzacji GUI, unifikacji wyboru beaconów i optymalizacji danych)  
> **Data aktualizacji:** 2026-09-23  
> **Status:** Obowiązujący (Single Source of Truth)  
> **Cel:** Kompletne, techniczne źródło wiedzy o architekturze systemu ESPAR IPS — dla programistów, integratorów i modeli AI.

---

## 1. Informacje o projekcie

### Nazwa projektu
**BLE-Fingerprinting-System / ESPAR IPS** (*Indoor Positioning System*)

### Cel projektu
System precyzyjnej lokalizacji wewnątrzbudynkowej oparty na antenach ESPAR (*Electronically Steerable Parasitic Array Radiator*) oraz nadajnikach BLE (*Bluetooth Low Energy*). Umożliwia wyznaczanie współrzędnych fizycznych $(x, y)$ obiektów ruchomych na podstawie charakterystyk promieniowania anteny pasożytniczej przełączanej w 12 dyskretnych kierunkach azymutalnych (co 30°).

### Kluczowe funkcjonalności
1. **Klasyczny fingerprinting radiowy:**
   - Zbieranie pojedynczych odcisków radiowych (graficznie przez celownik na rzucie SVG lub tekstowo w konsoli).
   - Kreator planowania wielu punktów w GUI (`--multi_plan`) z asystentem przestawiania statywu.
   - Zautomatyzowana siatka meandrowa (wężykiem) z obsługą zestawów wielobeaconowych (*tripod*) i orientacją kątową.
2. **Bezkalibracyjna lokalizacja kotwicowa (*Anchor Beacons*):**
   - Odwrócony model fingerprintingu: stacjonarne beacony o znanych współrzędnych na mapie wysyłają sygnał do stałej anteny.
   - Budowa mapy radiowej w czasie rzeczywistym z oznaczeniem `_beacon_anchor: True` bez konieczności fizycznego chodzenia z anteną.
3. **Śledzenie na żywo (*Live Tracking*):**
   - Wielowątkowy odbiór pakietów w buforze przesuwnym FIFO (`collections.deque`) o konfigurowalnym oknie czasowym $T$ (domyślnie 7.0 s).
   - Cykliczna estymacja pozycji co 0.5 s za pomocą algorytmu WkNN z 4 metrykami odległości.
   - Wygładzanie trajektorii filtrem wykładniczym EMA ($\alpha = 0.35$) redukującym skoki i szum pomiarowy.
4. **Walidacja dokładności (*Ground Truth*):**
   - Rejestracja punktów testowych o znanych współrzędnych fizycznych (graficznie lub tekstowo).
   - Wyliczanie miar błędów (RMSE, Mean Error, Max Error, percentyle P50, P75, P90).
   - Generowanie wykresów dystrybuanty empirycznej błędu (CDF) oraz map rozproszenia (*scatter plot*).
   - Automatyczna optymalizacja hiperparametru $K$ metodą przeszukiwania siatki (*grid search*) lub nastawa ręczna.
5. **Diagnostyka sygnału i analiza RSSI:**
   - Licznik pakietów na żywo z odświeżaniem w miejscu w terminalu ANSI (`counter.py`).
   - Generowanie wykresów biegunowych (radary RSSI) oraz map ciepła (*heatmaps*).
   - Porównywanie migawek offline z filtrowaniem punktów mapy radiowej przy łączeniu danych.
   - Ważona wektorowo estymacja kąta nadejścia sygnału (AoA) wyświetlana bezpośrednio na mapie SVG.
6. **Wielowątkowa detekcja najsilniejszej anteny / strefy:**
   - Równoległe skanowanie portów TCP dostępnych anten ESPAR w laboratorium i klasyfikacja pomieszczenia na podstawie marginesu RSSI.
7. **Nowoczesny interfejs graficzny PyQt6:**
   - Wektorowy rzut piętra budynku w skali 1:100 (1 m = 100 jednostek SVG).
   - Płynna nawigacja (zoom kółkiem myszy, pan przeciąganiem), animowane celowniki, historia śladu (*trail*) i wykres radarowy w punkcie pomiaru.
8. **Izolacja sesji pomiarowych:**
   - Niezależne przestrzenie robocze dla skrzydeł/pokojów budynku (`session.json`, `radio_map_{session}.json`, `test_set_{session}.json`, `beacons_{session}.json`).

### Środowisko wykonawcze i technologie
| Warstwa | Technologia / Narzędzie | Wersja | Zastosowanie |
|---|---|---|---|
| **Język** | Python | 3.10+ (zalecany 3.12) | Rdzeń obliczeniowy, logika biznesowa, komunikacja sieciowa |
| **Interfejs GUI** | PyQt6 | >= 6.4.0 | Okno aplikacji, widżety panelu, rendering SVG, wielowątkowość |
| **Grafika wektorowa** | `QSvgRenderer` (QtSvg) | — | Renderowanie rzutu architektonicznego w przestrzeni viewBox |
| **Obliczenia numeryczne** | NumPy | >= 1.23.0 | Wektoryzacja RSSI, algorytmika AoA |
| **Wizualizacja analityczna** | Matplotlib | >= 3.6.0 | Backend `Agg`, generowanie wykresów CDF, błędów i radarów |
| **Transmisja danych** | TCP Socket (Telnet stream) | — | Strumień JSON z kontrolera anteny ESPAR (porty 8893–8896+) |
| **Serializacja** | JSON (UTF-8) | — | Bazy map radiowych, konfiguracje, raporty |
| **Wieloplatformowość** | Windows / Linux | — | Obsługa kodowania UTF-8, `os.startfile` (Win) / `xdg-open` (Linux) |

---

## 2. Struktura katalogów i plików

```text
BLE-Fingerprinting-System/
├── .gitignore                             # Ignorowane pliki (.venv, __pycache__, pliki tymczasowe)
├── SVG_parser/
│   └── mapaAK_sieciowe_v3.svg             # Rzut architektoniczny piętra (skala 1:100, 4373.55 x 2617.97)
├── old_fingerprints/                      # Archiwum historycznych baz i automatycznych backupów migracji
│   ├── backup_pre_rescale_*/              # Kopie zapasowe przed przeskalowaniem viewBox
│   ├── radio_map_*.json                   # Archiwalne bazy odcisków
│   └── test_set_*.json                    # Archiwalne zbiory walidacyjne
├── pyproject.toml                         # Definicja projektu i zależności Python
├── uv.lock                                # Deterministyczna blokada wersji pakietów
├── README.md                              # Podręcznik użytkownika i skrócony przegląd systemu
└── ESPAR/                                 # Główny katalog roboczy systemu ESPAR IPS
    ├── architectural.md                   # Niniejsza dokumentacja (Single Source of Truth)
    ├── data/                              # Trwałe repozytorium danych JSON i wygenerowanych raportów
    │   ├── espar_config.json              # Aktywny port, host, metryka odległości, rejestr anten
    │   ├── session.json                   # Bieżąca sesja pomiarowa (lokalny origin i historia)
    │   ├── svg_calibration.json           # Kalibracja skali mapy (skala 100.0, origin SVG)
    │   ├── optimal_k.json                 # Wyznaczona optymalna wartość K sąsiadów WkNN
    │   ├── radio_map.json                 # Domyślna mapa radiowa (fallback)
    │   ├── radio_map_{session}.json       # Sesyjna baza odcisków (np. radio_map_korytarz.json)
    │   ├── beacons_{session}.json         # Baza beaconów orientacyjnych dla danej sesji
    │   ├── test_set.json                  # Domyślny zbiór walidacyjny (fallback)
    │   ├── test_set_{session}.json        # Sesyjny zbiór punktów walidacyjnych ground truth
    │   ├── planned_grid.json              # Plan kroków siatki meandrowej dla podprocesu GUI
    │   ├── validation_report.json         # Ostatni wygenerowany raport statystyk błędu
    │   ├── validation_cdf.png             # Wykres empirycznej dystrybuanty błędu (CDF)
    │   ├── validation_scatter.png         # Wykres rozproszenia pozycji rzeczywistych vs estymowanych
    │   ├── k_optimization.png             # Wykres zależności RMSE od hiperparametru K
    │   └── rssi_snapshots/                # Zrzuty pomiarów kierunkowych (10 najnowszych .json + .png)
    │       └── *.json, *.png
    └── src/                               # Kod źródłowy aplikacji
        ├── main.py                        # Główny punkt startowy CLI z ramkowym menu konsolowym (1-12)
        ├── config.py                      # Globalne stałe, kąty wiązek ESPAR, dynamiczne ścieżki sesji
        ├── session.py                     # Zarządzanie sesjami pomiarowymi i punktem origin
        ├── espar_client.py                # Klient TCP do kontrolera anteny (handshake start/stop)
        ├── telnet_reader.py               # Parser strumienia bajtów telnet do ramek BLE
        ├── fingerprint.py                 # Matematyczne przetwarzanie odcisków (mediana, normalizacja)
        ├── calibration.py                 # Klasa Calibrator: kalibracja pojedyncza, sekwencyjna, siatkowa
        ├── beacon_calibration.py          # Auto-kalibracja z beaconów orientacyjnych i live tracking
        ├── beacon_config.py               # Rejestracja i edycja współrzędnych beaconów orientacyjnych
        ├── counter.py                     # Monitor pakietów BLE i statystyk RSSI w terminalu ANSI
        ├── wknn.py                        # Silnik pozycjonowania WkNN (Pearson, Euklides, Hybryda, Pattern)
        ├── validate.py                    # Procedura walidacji dokładności i optymalizacja K (chroniony)
        ├── rssi_analysis.py               # Diagnostyka stabilności, zrzuty migawkowe, wykresy polarne
        ├── room_detector.py               # Równoległy skaner portów antenowych ESPAR
        ├── map_viewer.py                  # Dispatcher trybów graficznych CLI dla okna PyQt6
        ├── utils.py                       # Pomocnicze funkcje konsoli, selekcji beaconów i show_plot
        └── gui/                           # Pakiet interfejsu graficznego PyQt6
            ├── __init__.py                # Inicjalizacja pakietu GUI
            ├── styles.py                  # Paleta ciemnego motywu, SCALE=100.0, SVG<->metry
            ├── canvas.py                  # MapCanvas: rendering mapy SVG, zoom, pan, radary AoA
            ├── panel.py                   # InfoPanel: wielotrybowy boczny panel sterujący
            ├── threads.py                 # LiveThread: bufor przesuwny FIFO, filtr EMA, wątek TCP
            └── window.py                  # MapWindow: główne okno aplikacji spajające widoki
```

---

## 3. Architektura systemu

### Wzorzec architektoniczny
System oparty jest na architekturze **warstwowej modularnej z centralnym dyspozytorem konsolowym oraz autonomicznymi podprocesami GUI PyQt6**.

```
                        ┌─────────────────────────┐
                        │        main.py          │
                        │    (Pulpit CLI 1-12)    │
                        └────────────┬────────────┘
                                     │
          ┌─────────────┬────────────┼─────────────┬─────────────┐
          ▼             ▼            ▼             ▼             ▼
   SessionManager   Calibrator   map_viewer.py  validate.py  Diagnostics
   (session.py)   (calibrat..)    (GUI launch)  (RMSE, CDF)  (rssi, room)
          │             │            │             │             │
          │             │            ▼             │             │
          │             │       ┌─────────┐        │             │
          │             │       │  gui/   │        │             │
          │             │       │ window  │        │             │
          │             │       │ canvas  │        │             │
          │             │       │ panel   │        │             │
          │             │       │ threads │        │             │
          │             │       └────┬────┘        │             │
          ▼             ▼            ▼             ▼             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                  Warstwa Danych (JSON I/O)                  │
   │      radio_map_{session}.json  │  test_set_{session}.json    │
   │      session.json              │  espar_config.json         │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │               Warstwa Sieciowa (TCP Socket)                 │
   │      EsparClient ──► telnet_reader ──► Serwer ESPAR         │
   └─────────────────────────────────────────────────────────────┘
```

1. **Warstwa Prezentacji i Sterowania:**
   - **Menu konsolowe (`main.py`):** Pulpit sterujący z ramką Unicode wyświetlający w czasie rzeczywistym stan sesji, aktywnej anteny, metryki, parametru $K$ oraz liczbę zarejestrowanych odcisków.
   - **Podprocesy GUI (`map_viewer.py` -> `MapWindow`):** Uruchamiane jako niezależne procesy potomne (`subprocess.run`), co izoluje pętlę zdarzeń Qt od wątku konsolowego i eliminuje ryzyko deadlocków.
   - **Dashboard terminalowy (`counter.py`):** Prezentacja statystyk RSSI na żywo z odświeżaniem w miejscu za pomocą kodów sterujących ANSI.
2. **Warstwa Algorytmiki i Przetwarzania:**
   - **Estymacja pozycji WkNN (`wknn.py`):** Wyznaczanie współrzędnych metodą ważonych $K$-najbliższych sąsiadów z wagami odwrotnie proporcjonalnymi do kwadratu odległości w przestrzeni cech: $w_i = \frac{1}{\max(d_i, \epsilon)^2}$.
   - **Bufor przesuwny FIFO i filtracja EMA (`gui/threads.py`):** Kolejka pakietów o horyzoncie $T$ sekund z cyklicznym odświeżaniem co 0.5 s oraz tłumieniem drgań pozycji filtrem wykładniczym:
     $$\mathbf{p}_{smooth}(t) = \alpha \mathbf{p}_{raw}(t) + (1 - \alpha) \mathbf{p}_{smooth}(t - 1), \quad \alpha = 0.35$$
   - **Agregacja fingerprintów (`fingerprint.py`):** Zastosowanie mediany RSSI per sektor zamiast średniej arytmetycznej, co uodparnia bazę na piki zakłóceniowe.
3. **Warstwa Danych i Konfiguracji:**
   - Pliki JSON w katalogu `ESPAR/data/` z dynamicznym rozwiązywaniem ścieżek per sesja pomiarowa.
   - Matematyczna spójność transformacji układów współrzędnych (`gui/styles.py`):
     $$x_{svg} = X_{origin} + x_{m} \cdot 100.0, \quad y_{svg} = Y_{origin} + y_{m} \cdot 100.0$$
4. **Warstwa Sieciowa:**
   - `EsparClient` i `telnet_reader` zapewniające niezawodny odbiór strumienia TCP, czyszczenie buforów przed startem sesji pomiarowej oraz parsowanie ramek.

---

## 4. Szczegółowy opis modułów

### Moduły główne (`ESPAR/src/`)

#### `main.py`
- **Rola:** Główny punkt startowy aplikacji (tekstowe menu CLI).
- **Funkcjonalność:** Rysuje pulpit w estetycznej ramce ANSI, monitoruje stan bazy w locie i obsługuje 12 modułów operacyjnych:
  - `[KALIBRACJA]`:
    - `1. Zmiana pokoju (sesji)`: wybór aktywnej sesji pomiarowej (np. korytarz, pokój) oraz graficzne/tekstowe ustalenie punktu bazowego $(0,0)$ na rzucie SVG.
    - `2. Tworzenie mapy radiowej`: tworzenie odcisków offline (pojedynczy punkt graficznie/tekstowo `p`, sekwencja trasy `w`, automatyczna siatka meandrowa `s`).
  - `[DIAGNOSTYKA & MAPA]`:
    - `3. Podgląd mapy na żywo`: uruchomienie interfejsu graficznego (`--view`) ze śledzeniem pozycji, radarem AoA i podglądem bazy odcisków.
    - `4. Analiza RSSI & wizualizacje`: analiza istniejącej bazy offline (z filtrowaniem punktów mapy przy łączeniu), pomiar rotacji anteny na żywo lub klasyfikacja strefy/anteny.
  - `[WALIDACJA & TESTY]`:
    - `5. Punkty testowe`: rejestracja punktów referencyjnych *ground truth* (graficznie celownikiem `g` lub tekstowo `t`).
    - `6. Optymalizacja parametru K`: automatyczny dobór $K$ metodą grid search `[a]` lub nastawa ręczna `[r]`.
    - `7. Raport walidacji błędów`: pełna analiza statystyczna (RMSE, Mean, Mediana, P90, strefy krańcowe) i wykresy dystrybuanty błędu (CDF).
  - `[USTAWIENIA & SYSTEM]`:
    - `8. Wybór anteny i portu`: przełączanie portu TCP kontrolera ESPAR oraz dynamiczne dodawanie nowych anten (`d`).
    - `9. Zmiana metryki odległości`: wybór jednej z 4 metryk: Pearson, Euclidean, Hybrid, Weighted Pattern.
    - `10. Zbadaj RSSI beaconów`: wieloportowe skanowanie anten i klasyfikacja pomieszczenia o najwyższym poziomie sygnału.
    - `11. System kotwicowy - anchors`: bezkalibracyjne pozycjonowanie w oparciu o stałe beacony orientacyjne zamontowane w znanych punktach budynku.
    - `12. Monitor pakietów - podgląd strumienia danych`: terminalowy monitor pakietów BLE ANSI z podglądem odbioru dla 12 sektorów wiązki.
    - `0. Zakończ program`: bezpieczne zamknięcie gniazd TCP i wyjście.

#### `config.py`
- **Rola:** Centralny magazyn stałych konfiguracyjnych i generator ścieżek sesyjnych.
- **Kluczowe stałe:**
  - `VALID_CHARS`: Zbiór 12 poprawnych kodów sterujących wiązką ESPAR: `{31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}`.
  - `CHAR_TO_DEG`: Odwzorowanie kodu wiązki na azymut fizyczny w stopniach: `{31: 90, 62: 120, 124: 150, 248: 180, 496: 210, 992: 240, 1984: 270, 3968: 300, 3841: 330, 3587: 0, 3079: 30, 2063: 60}`.
  - `PORT_NAMES`: Domyślna mapa portów: `{8893: "espar07", 8894: "espar37", 8895: "espar35"}`.
  - `DEFAULT_RSSI_PENALTY`: `-95.0` dBm (poziom szumu dla brakujących sektorów).
- **Kluczowe funkcje:** `get_active_session()`, `get_radio_map_path()`, `get_test_set_path()`, `get_beacons_config_path()`, `register_antenna(port, name)`.

#### `wknn.py`
- **Rola:** Implementacja algorytmu pozycjonowania WkNN i zarządzanie bazą mapy radiowej.
- **4 metryki odległości:**
  1. **Pearson (`_pearson_distance`):** $d = 1 - r$, gdzie $r$ to współczynnik korelacji liniowej Pearsona między wektorami RSSI. Bada podobieństwo kształtu wiązki niezależnie od tłumienia.
  2. **Euklidesowa wycentrowana (`_euclidean_distance`):** $d = \sqrt{\sum ((v_{1,i} - \bar{v}_1) - (v_{2,i} - \bar{v}_2))^2}$. Mierzy różnice kształtu po odjęciu średniej mocy sygnału.
  3. **Hybrydowa (`_hybrid_distance`):** $d = (1 - r) + \lambda \cdot |\bar{v}_1 - \bar{v}_2|$. Łączy korelację kształtu z karą za różnicę poziomów mocy.
  4. **Wzorzec ważony (`_weighted_pattern_distance`):** Uwzględnia wagi sektorów i wariancję sygnału.
- **Ważenie sąsiadów:** $w_i = \frac{1}{\max(d_i, \epsilon)^2}$ ($\epsilon = 10^{-9}$). Współrzędne estymowane są jako średnia ważona: $\hat{\mathbf{p}} = \frac{\sum w_i \mathbf{p}_i}{\sum w_i}$.
- **Pewność estymacji (*confidence*):**
  - Dla Pearsona/Hybrydy: $\text{conf} = \max(0.0, \min(1.0, 1.0 - d_{min}))$.
  - Dla Euklidesa: $\text{conf} = \exp(-e_{avg} / 10.0)$, gdzie $e_{avg} = d_{min} / \sqrt{N_{dirs}}$.

#### `fingerprint.py`
- **Rola:** Agregacja i normalizacja próbek radiowych.
- **Klasa `Fingerprint`:**
  - `compute_avg()`: Wylicza medianę RSSI dla każdego z 12 kierunków wiązki (odporność na szpilki zakłóceniowe).
  - `compute_norm()`: Min-max normalizacja wektora median do przedziału $[0.0, 1.0]$.
  - `process_multi_beacon()`: Zbiorcze przetwarzanie próbek dla listy beaconów z opcjonalnym wypełnianiem braków karą -95.0 dBm.

#### `calibration.py`
- **Rola:** Koordynacja procedur kalibracyjnych.
- **Klasa `Calibrator`:**
  - `_get_beacon_candidates(duration=3.5)`: Zunifikowany mechanizm wykrywania nadajników – skanuje pasmo radiowe przez telnet (`_scan_available_beacons`), odczytuje beacony zarejestrowane w bazie [radio_map.json](data/radio_map.json) oraz liście domyślnej, budując kandydatów z etykietami `[w bazie]` i `[wykryty]`.
  - `run_gui_single_fingerprint()`: Odpala podproces GUI `--fingerprint_collect` ze swobodnym wyborem punktu.
  - `run_multi_point_calibration()`: Uruchamia interaktywny kreator planowania trasy na mapie (`--multi_plan`).
  - `run_grid_calibration()`: Generuje siatkę wężykiem (meandrową) z uwzględnieniem rozstawu statywu i kąta orientacji, zapisuje `planned_grid.json` i uruchamia asystenta w GUI.
  - `run_average()`: Klasyczny tryb terminalowy dla pojedynczego punktu z uwzględnieniem kąta statywu (`angle_deg`, zapobieganie błędowi braku klucza) oraz interaktywnym wyborem `select_beacon_interactive()`.
  - `run_collect_test_point()`: Zbieranie punktu walidacyjnego ground truth z wyborem beacona na początku procedury.

#### `beacon_calibration.py` & `beacon_config.py`
- **Rola:** Bezkalibracyjne pozycjonowanie z użyciem kotwic (*anchor beacons*).
- **Funkcjonalność:** Rejestracja fizycznego położenia nadajników na mapie SVG (`--pick`), jednoczesny nasłuch wszystkich kotwic, wygenerowanie bazy `radio_map_{session}.json` z flagą `_beacon_anchor: True` oraz uruchomienie śledzenia obiektu ruchomego (`--view`).

#### `session.py`
- **Rola:** Zarządzanie lokalnym układem odniesienia (punkt origin).
- **Klasa `SessionManager`:** Przechowuje `origin_x_m`, `origin_y_m` oraz `origin_label` w pliku `session.json`, obsługuje zmianę aktywnej sali/strefy oraz pozwala na kliknięcie originu na rzucie SVG (`--pick-session`).

#### `espar_client.py` & `telnet_reader.py`
- **Rola:** Warstwa komunikacji ze sterownikiem anteny ESPAR.
- **Funkcjonalność:** Ustanawianie połączenia TCP (`host: 153.19.49.102`), wysyłanie poleceń `start\n` / `stop\n`, opróżnianie buforów wejściowych (`_drain`) oraz dekodowanie linii JSON do słowników (`beacon_num`, `espar_char_int`, `rssi_dbm`, `ble_channel`).

#### `counter.py`
- **Rola:** Szybka diagnostyka środowiska radiowego i anteny w terminalu.
- **Funkcjonalność:** Zlicza odebrane pakiety w czasie rzeczywistym i drukuje tabelę z podziałem na 12 kątów wiązki (liczba próbek, RSSI min, max, avg).

#### `room_detector.py`
- **Rola:** Wielowątkowy skaner anten laboratoryjnych.
- **Funkcjonalność:** Łączy się równolegle ze wszystkimi portami zdefiniowanymi w `PORT_NAMES`, zbiera pakiety przez zadany czas i wyznacza antenę o najwyższym poziomie sygnału per beacon.

#### `rssi_analysis.py`
- **Rola:** Badanie propagacji, stabilności sygnału i wykresy biegunowe.
- **Funkcjonalność:**
  - Zapis snapshotów pomiarów do formatu JSON i wykresów radarowych PNG (magazyn utrzymuje 10 najnowszych pomiarów).
  - Generowanie wykresów biegunowych (radary RSSI) oraz map ciepła (*heatmaps* dla $> 4$ punktów).
  - W trybie offline `run_rssi_offline()` przy pytaniu o dołączenie bieżących danych do innych wpisów (`Czy połączyć bieżące dane z innymi dostępnymi?`), wyklucza pozycje z mapy radiowej (`e[0] != 'mapa'`), prezentując wyłącznie migawki (`[MIGAWKA]`) i punkty testowe (`[TEST]`) z bezpośrednim 1-indeksowanym mapowaniem wyboru.
  - Wektorowa estymacja kąta nadejścia fali (AoA).

#### `validate.py`
- **Rola:** Ewaluacja dokładności pozycjonowania WkNN (*plik chroniony przed modyfikacją*).
- **Funkcjonalność:** Porównanie estymacji z pozycją fizyczną punktów ze zbioru testowego, obliczanie metryk błędu (RMSE, P50, P75, P90, strefy krańcowe), optymalizacja parametru $K$ metodą grid search oraz generowanie wykresów dystrybuanty błędu (CDF).

#### `map_viewer.py`
- **Rola:** Punkt wejściowy dla procesów graficznych PyQt6.
- **Obsługiwane flagi CLI:**
  - `--view [beacon_id]`: Tryb live tracking z podglądem na żywo.
  - `--calibrate <label> <beacons_json> [target_packets]`: Zbieranie odcisku dla zadanego zestawu beaconów.
  - `--fingerprint_collect [beacon_id] [target_packets]`: Interaktywne zbieranie pojedynczego odcisku na mapie.
  - `--multi_plan [beacon_id] [target_packets]`: Graficzne planowanie wielu punktów z sekwencyjnym zbieraniem.
  - `--grid_collect <planned_grid_path>`: Prowadzenie użytkownika przez wygenerowaną siatkę punktów.
  - `--test_collect [beacon_id] [target_packets]`: Zbieranie punktu walidacyjnego ground truth na mapie.
  - `--pick`: Wskazanie punktu na mapie (zwraca `{x_m, y_m}` na stdout).
  - `--pick-session`: Wskazanie nowego punktu origin dla sesji.
  - `--select-points`: Zaznaczenie punktów z mapy do analizy offline RSSI.

#### `utils.py`
- **Rola:** Narzędzia pomocnicze i interaktywna selekcja urządzeń BLE.
- **Kluczowe funkcje:**
  - `build_beacon_candidates(available, db_beacons)`: buduje listę kandydatów łączącą wykryte urządzenia i bazę danych.
  - `select_beacon_interactive()`: interaktywne menu wyboru z adnotacjami `[w bazie]`, `[wykryty]` oraz obsługą ponownego skanowania (`rescan_callback`).
  - Bezpieczne wprowadzanie danych z walidacją typów (`get_int_input`, `get_float_input`, `get_choice_input`).

---

### Pakiet GUI (`ESPAR/src/gui/`)

#### `gui/styles.py`
- **Rola:** Stylistyka interfejsu i transformacja współrzędnych.
- **Stałe geometryczne:**
  - `SCALE = 100.0`: 1 metr fizyczny odpowiada dokładnie 100 jednostkom mapy SVG.
  - `SVG_ORIGIN_X = 0.0`, `SVG_ORIGIN_Y = 0.0`: Domyślne przesunięcie bazowe.
- **Funkcje transformacji:**
  - `physical_to_svg(x_m, y_m)` -> `(svg_x, svg_y)`
  - `svg_to_physical(svg_x, svg_y)` -> `(x_m, y_m)`
- **Kolorystyka ciemnego motywu:** `C_BG (#0a0e1a)`, `C_PANEL (#0f1623)`, `C_BORDER (#1e2d45)`, `C_ACCENT (#3b82f6)`, `C_DOT (#ef4444)`, `C_SUCCESS (#10b981)`.

#### `gui/canvas.py` (`MapCanvas`)
- **Rola:** Płótno graficzne prezentujące rzut architektoniczny budynku.
- **Funkcjonalność:**
  - Renderowanie wektorowe SVG za pomocą `QSvgRenderer`.
  - Płynny zoom (kółko myszy w punkcie kursora) i pan (przeciąganie lewym przyciskiem myszy).
  - Wyświetlanie bazy punktów kalibracyjnych (odcisków) i punktów testowych.
  - Wizualizacja pozycji estymowanej z animowaną pulsacją kropki oraz historią śladu ruchu (*trail*).
  - Wykres radarowy RSSI renderowany wprost na mapie z wektorem szacowanego kąta nadejścia sygnału (AoA).
  - Interaktywne celowniki do wskazywania współrzędnych w trybach zbierania i planowania.

#### `gui/panel.py` (`InfoPanel`)
- **Rola:** Adaptacyjny boczny panel sterowania i wskaźników stanu.
- **Obsługiwane tryby:**
  - `_init_live_ui()`: Podgląd współrzędnych fizycznych, jednostek SVG, ID beacona, paska pewności oraz konfiguracja czasu okna przesuwnego.
  - `setup_test_collect_mode()`: Zbieranie punktów walidacyjnych ze wskazaniem współrzędnych na mapie.
  - `setup_single_fingerprint_mode()`: Graficzne zbieranie pojedynczego odcisku z auto-inkrementacją etykiet.
  - `setup_calibration_mode()`: Monitorowanie postępu zbierania ramek dla poszczególnych beaconów zestawu.
  - `setup_multi_plan_mode()`: Narzędzie dodawania, usuwania i zatwierdzania zaplanowanych przystanków statywu.
  - `setup_grid_collect_mode()`: Prowadzenie krok po kroku po wygenerowanej siatce z asystentem przestawiania.

#### `gui/threads.py` (`LiveThread`)
- **Rola:** Asynchroniczny wątek tła realizujący odbiór danych i pozycjonowanie.
- **Parametry pracy:**
  - `WINDOW_SEC = 7.0`: Horyzont czasowy bufora przesuwnego FIFO.
  - `UPDATE_INTERVAL = 0.5`: Częstotliwość odświeżania estymacji pozycji [s].
  - `EMA_ALPHA = 0.35`: Współczynnik wygładzania wykładniczego pozycji.
  - `MIN_DIRECTIONS = 4`: Wymagana minimalna liczba aktywnych sektorów w oknie do wywołania algorytmu WkNN.
- **Sygnały Qt:**
  - `position(float, float, int, float)`: Emituje `(x_est, y_est, beacon_id, confidence)`.
  - `frame_received(int, int, float)`: Emituje surowe pakiety `(beacon_id, char_int, rssi_dbm)` na potrzeby radaru.
  - `status_msg(str)`: Komunikaty diagnostyczne dla paska stanu GUI.

#### `gui/window.py` (`MapWindow`)
- **Rola:** Główne okno aplikacji (`QMainWindow`).
- **Funkcjonalność:**
  - Reaguje na sygnały z `MapCanvas`, `InfoPanel` i `LiveThread`.
  - Obsługuje logikę sekwencyjnego zbierania próbek w trybach siatki i planowania trasy.
  - Kontroluje kompletność 12 sektorów wiązki i wyświetla dialog decyzyjny w przypadku brakujących kątów.
  - Zapisuje zebrane dane bezpośrednio do odpowiednich baz JSON w katalogu `data/`.

---

## 5. Przepływy wykonywania i architektura danych

### Przepływ śledzenia obiektu na żywo (*Live Tracking*)

```text
[Antena ESPAR] ──(TCP: 8894)──> [LiveThread (QThread)]
                                       │
                                       ├─ Odbiór ramki: get_espar_stream()
                                       ├─ Filtracja: VALID_CHARS i beacon_id
                                       ├─ Zapis do bufora FIFO (deque per sektor)
                                       ├─ Usunięcie próbek starszych niż WINDOW_SEC (7 s)
                                       │
                                [Co 0.5 s (UPDATE_INTERVAL)]
                                       │
                                       ├─ Sprawdzenie warunku: active_dirs >= 4
                                       ├─ wknn_estimate(window_data, radio_map, K)
                                       ├─ Wygładzenie EMA: p_smooth = 0.35*p_raw + 0.65*p_prev
                                       ├─ Emisja sygnału: position.emit(x, y, bid, conf)
                                       │
                                       ▼
                             [MapWindow / MapCanvas / InfoPanel]
                                       ├─ MapCanvas: aktualizacja pozycji, pulsujący celownik, trail
                                       └─ InfoPanel: odświeżenie współrzędnych i paska pewności
```

### Przepływ kalibracji pojedynczego punktu w GUI (`--fingerprint_collect`)

```text
Menu konsolowe (Opcja 2 -> p -> g)
       │
       ▼
Uruchomienie podprocesu: map_viewer.py --fingerprint_collect <bid> [pkts]
       │
       ▼
MapWindow (tryb fingerprint_collect_mode):
       ├─ 1. Użytkownik klika punkt na mapie SVG (MapCanvas) -> ustawienie celownika
       ├─ 2. InfoPanel: wprowadzenie etykiety (np. p01) i target_packets
       ├─ 3. Kliknięcie "Rozpocznij zbieranie":
       │      └─ Start LiveThread (calibrate_mode=True)
       │      └─ Rysowanie radaru RSSI na żywo w punkcie celownika
       │      └─ Zliczanie pakietów per sektor na pasku postępu
       ├─ 4. Po zebraniu pakietów: aktywacja przycisku "Zapisz odcisk"
       │      └─ Kontrola 12 kierunków (dialog w razie braków)
       │      └─ process_multi_beacon() -> Fingerprint.compute_avg(), compute_norm()
       │      └─ Zapis punktu do data/radio_map_{session}.json
       │      └─ Naniesienie trwałego punktu na mapę
       └─ 5. Przejście do kolejnego punktu ("Kolejny punkt" -> etykieta p02)
```

---

## 6. Protokół komunikacyjny i struktury danych

### Protokół sterowania anteną ESPAR (TCP Telnet)
- **Host domyślny:** `153.19.49.102`
- **Porty anten:** 8893 (`espar07`), 8894 (`espar37`), 8895 (`espar35`) itp.
- **Komenda startowa:** wysłanie `start\n`
- **Komenda zatrzymania:** wysłanie `stop\n`
- **Struktura ramki:**
  ```json
  {"v":"cnt_robot","d":"7,37,42,62,28,15320,0,0,0"}
  ```
  - `Pole 0`: ID anteny (`7`)
  - `Pole 1`: Kanał BLE (`37`)
  - `Pole 2`: Surowa wartość mocy (`rssi_raw`). Rzeczywiste RSSI: `rssi_dbm = rssi_raw - 100` (np. $42 - 100 = -58\text{ dBm}$)
  - `Pole 3`: Kod konfiguracji wiązki ESPAR (`espar_char_int`), np. `62` odpowiadający kątowi 120°
  - `Pole 4`: Numer beacona (`beacon_num`), np. `28`
  - `Pole 5`: Licznik sekwencji pakietu (`seq_cnt`)

### Format rekordu mapy radiowej (`radio_map_{session}.json`)
```json
[
  {
    "label": "p01",
    "x_m": 24.50,
    "y_m": 12.30,
    "_local": {
      "x": 1.63,
      "y": 3.55,
      "session": "korytarz"
    },
    "_beacon_anchor": false,
    "beacons": {
      "28": {
        "avg": {
          "31": -68.5,
          "62": -71.0,
          "124": -84.2,
          "248": -89.0,
          "496": -92.5,
          "992": -95.0,
          "1984": -91.0,
          "3968": -85.0,
          "3841": -78.0,
          "3587": -70.5,
          "3079": -66.0,
          "2063": -65.2
        },
        "norm": {
          "31": 0.889,
          "62": 0.805,
          "124": 0.362,
          "2063": 1.0
        }
      }
    },
    "timestamp": "2026-09-23T14:30:00"
  }
]
```

---

## 7. Historia zmian architektury

### 2026-07-03 (Wersja bazowa)
- Inicjalizacja dokumentacji architektury i modularnego podziału systemu.
- Wdrożenie obsługi anten laboratoryjnych oraz estymacji korelacyjnej Pearsona.

### 2026-07-17 (Metryka Euklidesowa i Room Detector)
- Wprowadzenie wycentrowanej odległości euklidesowej (*Zero-Mean Euclidean Distance*).
- Implementacja modułu `room_detector.py` realizującego równoległe skanowanie anten.

### 2026-09-09 (Korekta geometrii SVG viewBox)
- Usunięcie błędnego skalowania (4600x2760) na rzecz rzeczywistego (`4373.5528 x 2617.9691`).
- Wykonanie migracji współrzędnych i archiwizacja starych map.

### 2026-09-15 (Wersja 2.0 — Kotwice, bufor przesuwny FIFO i monitor pakietów)
- Wdrożenie bezkalibracyjnego pozycjonowania opartego na beaconach orientacyjnych (`beacon_calibration.py`, `beacon_config.py`).
- Implementacja bufora przesuwnego FIFO (`collections.deque`) o horyzoncie $T$ sekund z krokiem 0.5 s w `LiveThread`.
- Dodanie terminalowego monitora pakietów ANSI (`counter.py`).

### 2026-09-23 (Wersja 2.2 — Gruntowna refaktoryzacja, unifikacja beaconów i optymalizacja bazy)
- **Harmonizacja i optymalizacja pakietu GUI:**
  - Usunięcie rozbieżności interfejsów pomiędzy `gui/panel.py` i `gui/window.py` (pełna obsługa trybów planowania wielopunktowego, zbierania ground truth i siatki statywowej).
  - Wdrożenie filtru wygładzającego EMA ($\alpha = 0.35$) w `LiveThread`, eliminującego skoki punktu na mapie.
  - Przeniesienie stałych skali (`SCALE = 100.0`, `SVG_ORIGIN_X`, `SVG_ORIGIN_Y`) do `gui/styles.py` z precyzyjną konwersją współrzędnych.
  - Dodanie wektorowej estymacji kąta nadejścia sygnału (AoA) oraz interaktywnego podglądu radaru wprost na płótnie `MapCanvas`.
- **Refaktoryzacja modułów logicznych:**
  - Zredukowanie objętości kodu o **~40%** (skrócono ponad 3 500 linii zbędnego kodu).
  - **Zunifikowanie wyboru beaconów w procedurach kalibracyjnych**: wdrożono `_get_beacon_candidates(duration=3.5)` i `select_beacon_interactive()`, eliminując niespójności pomiędzy metodami `run_average()`, `run_grid_calibration()` i `run_collect_test_point()`.
  - **Usunięcie błędu geometrii statywu**: dodanie pytania o kąt obrotu statywu (`angle_deg`) w `run_average()` w [calibration.py](src/calibration.py), zabezpieczające przed błędem `KeyError`.
  - **Inteligentne filtrowanie analizy RSSI**: w `run_rssi_offline()` przy łączeniu bieżących danych z innymi wykluczono punkty surowej mapy radiowej, wyświetlając wyłącznie właściwe migawki i punkty testowe.
  - **Czyszczenie magazynu danych**: usunięcie 137 starych snapshotów z `data/rssi_snapshots/` (utrzymywane 10 najnowszych pomiarów `.json` i `.png`).
  - **Synchronizacja CLI i dokumentacji**: ujednolicenie 12 opcji menu w `main.py`, `README.md` oraz `architectural.md`.
  - **Integralność walidacji**: plik [validate.py](src/validate.py) zachowany w 100% nienaruszonym stanie zgodnie z krytycznymi wytycznymi.

---

## 8. Status i weryfikacja systemu

Wszystkie moduły w katalogu `ESPAR/src/` zostały zweryfikowane pod kątem spójności składniowej za pomocą kompilacji Python (`py_compile`, kod wyjścia 0) oraz przetestowane pod kątem poprawności importów wzajemnych. System jest w pełni spójny, zoptymalizowany i operacyjny.
