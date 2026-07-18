# ESPAR IPS — Dokumentacja Architektury

> **Wersja:** 1.1  
> **Data:** 2026-07-18  
> **Autorzy:** Wygenerowane automatycznie na podstawie analizy kodu  
> **Cel:** Jedyne źródło wiedzy o architekturze projektu — dla programistów i modeli AI.

---

## 1. Informacje o projekcie

### Nazwa projektu
**BLE-Fingerprinting-System / ESPAR IPS** (Indoor Positioning System)

### Cel projektu
System lokalizacji wewnątrzbudynkowej oparty na antenach ESPAR (Electronically Steerable Parasitic Array Radiator) i nadajnikach BLE (Bluetooth Low Energy). Umożliwia estymację pozycji obiektu wewnątrz budynku na podstawie kierunkowych odcisków radiowych (fingerprinting) z dokładnością rzędu metrów.

### Główne funkcjonalności
1. **Kalibracja (fingerprinting)** — zbieranie odcisków radiowych RSSI w punktach referencyjnych (pojedynczo lub automatyczną siatką)
2. **Pozycjonowanie na żywo** — estymacja pozycji obiektu w czasie rzeczywistym (algorytm WkNN z metryką Pearsona lub Euklidesa)
3. **Walidacja** — zbieranie punktów testowych i analiza błędu lokalizacji (RMSE, P90, CDF)
4. **Analiza RSSI & Detekcja anteny** — diagnostyka stabilności sygnału, wykresy radarowe oraz automatyczne wykrywanie najsilniejszej anteny ESPAR
5. **Wizualizacja GUI** — graficzny interfejs z mapą budynku SVG, radarem, podglądem live oraz możliwością dynamicznej zmiany śledzonego beacona i okna uśredniania
6. **Optymalizacja K** — automatyczny dobór liczby sąsiadów algorytmu WkNN metodą grid search lub ręczne ustawianie K

### Technologie
| Warstwa | Technologia |
|---|---|
| **Język** | Python 3.10+ |
| **GUI** | PyQt6 (QWidget, QPainter, QSvgRenderer) |
| **Wykresy** | matplotlib + numpy (backend Agg — renderowanie do pliku) |
| **Mapa budynku** | SVG (Inkscape, skala 1:100) |
| **Komunikacja** | TCP socket (telnet) z serwerem anteny ESPAR |
| **Dane** | JSON (radio_map, test_set, session, config) |
| **System** | Linux (xdg-open do otwierania plików) |

### Wymagania / zależności
- `PyQt6` — framework GUI
- `matplotlib` — wykresy (CDF, scatter, radar, heatmapa)
- `numpy` — obliczenia numeryczne (wykresy radarowe)
- Dostęp sieciowy do serwera ESPAR (`153.19.49.102:8893-8895`)
- Plik SVG mapy budynku (`SVG_parser/mapaAK_sieciowe_v3.svg`)

---

## 2. Struktura katalogów

```
BLE-Fingerprinting-System/
├── .gitignore                     # Reguły ignorowania (.venv, __pycache__, *.pyc)
├── ESPAR/                         # ← Główny katalog projektu
│   ├── architectural.md           # Ten dokument
│   ├── task.md                    # Opis zadania generacji dokumentacji
│   ├── data/                      # Dane pomiarowe i konfiguracyjne
│   │   ├── espar_config.json      # Port/host anteny ESPAR oraz aktywna metryka
│   │   ├── radio_map.json         # Mapa radiowa (fingerprints kalibracyjne)
│   │   ├── test_set.json          # Zbiór testowy (ground truth)
│   │   ├── optimal_k.json         # Optymalne K z grid search
│   │   ├── session.json           # Aktywna sesja pomiarowa (origin)
│   │   ├── svg_calibration.json   # Kalibracja SVG ↔ metry fizyczne
│   │   ├── planned_grid.json      # Plan siatki kalibracyjnej (tymczasowy)
│   │   ├── validation_cdf.png     # Wykres CDF walidacji
│   │   ├── validation_scatter.png # Scatter plot walidacji
│   │   ├── k_optimization.png     # Wykres optymalizacji K
│   │   ├── validation_report.json # Raport JSON walidacji
│   │   └── rssi_snapshots/        # Migawki surowego RSSI
│   │       └── *.json, *.png      # Migawki + wykresy radarowe
│   └── src/                       # Kod źródłowy
│       ├── main.py                # Punkt wejścia (menu konsolowe - 10 opcji)
│       ├── config.py              # Stałe konfiguracyjne (ścieżki, antena, domyślne)
│       ├── session.py             # Zarządzanie sesją pomiarową (origin)
│       ├── espar_client.py        # Klient TCP do anteny ESPAR
│       ├── telnet_reader.py       # Parser ramek BLE z telnet
│       ├── fingerprint.py         # Przetwarzanie odcisków radiowych
│       ├── calibration.py         # Logika kalibracji (pojedyncza + siatka)
│       ├── wknn.py                # Algorytm WkNN + I/O radio_map
│       ├── validate.py            # Walidacja dokładności lokalizacji
│       ├── rssi_analysis.py       # Analiza stabilności RSSI
│       ├── room_detector.py       # Detekcja najsilniejszej anteny ESPAR (RSSI)
│       ├── map_viewer.py          # Wrapper CLI → GUI (point d'entrée)
│       ├── utils.py               # Funkcje pomocnicze (input, beacon selection, show_plot)
│       └── gui/                   # Pakiet graficznego interfejsu (PyQt6)
│           ├── __init__.py        # Docstring pakietu
│           ├── styles.py          # Paleta kolorów, kalibracja SVG↔m
│           ├── canvas.py          # Widget mapy SVG (MapCanvas)
│           ├── panel.py           # Panel boczny (InfoPanel)
│           ├── threads.py         # Wątek odbioru i obliczeń (LiveThread)
│           └── window.py          # Główne okno aplikacji (MapWindow)
├── SVG_parser/                    # Plik mapy budynku
│   └── mapaAK_sieciowe_v3.svg    # Rysunek architektoniczny (Inkscape, skala 1:100)
└── old_fingerprints/              # Archiwum starych map radiowych
    ├── radio_map_1.json
    ├── radio_map_2.json
    ├── radio_map_707dziala.json
    ├── radio_map_espar37_2beacony.json
    ├── radio_map_korytarz.json
    ├── radio_map_korytarz_podwojne_etykiety.json
    ├── radio_map_korytarz_working.json
    └── test_set_10_kierunków.json
```

### Opis katalogów

| Katalog | Do czego służy | Zawiera | Zależy od |
|---|---|---|---|
| `ESPAR/src/` | Główny kod aplikacji | 13 modułów Python | — |
| `ESPAR/src/gui/` | Interfejs graficzny (PyQt6) | 5 modułów + `__init__` | PyQt6, `src/*.py` |
| `ESPAR/data/` | Dane pomiarowe i konfiguracyjne | JSON, PNG | generowane przez `src/` |
| `ESPAR/data/rssi_snapshots/` | Migawki surowego RSSI | JSON + PNG | generowane przez `rssi_analysis.py` |
| `SVG_parser/` | Mapa budynku | 1 plik SVG (~1 MB) | Inkscape |
| `old_fingerprints/` | Historyczne mapy radiowe | JSON | archiwalne dane |

---

## 3. Architektura

### Wzorzec architektoniczny
**Warstwowa architektura z centralnym menu konsolowym + opcjonalnym GUI.**

Aplikacja nie jest webowa ani klient-serwerowa. To desktopowy program Python z:
- **Warstwa prezentacji:** konsola (menu `main.py`) + GUI PyQt6 (`gui/`)
- **Warstwa logiki:** kalibracja, WkNN, walidacja, analiza, detekcja pokoi/anten
- **Warstwa danych:** pliki JSON w `data/`
- **Warstwa komunikacji:** TCP socket do serwera anteny ESPAR

### Diagram architektury

```
                        ┌─────────────────────────┐
                        │      main.py            │
                        │  (menu konsolowe)       │
                        └───────┬─────────────────┘
                                │
          ┌─────────────┬───────┼────────────┬──────────────┬──────────────────┐
          │             │       │            │              │                  │
          ▼             ▼       ▼            ▼              ▼                  ▼
   SessionManager   Calibrator map_viewer  validate.py   rssi_analysis.py  room_detector.py
   (session.py)    (calibration) (CLI)     (walidacja)   (diagnostyka)    (detekcja ESPAR)
          │             │       │            │              │                  │
          │             │       ▼            │              │                  │
          │             │  ┌───────────┐     │              │                  │
          │             │  │  gui/     │     │              │                  │
          │             │  │ ┌───────┐ │     │              │                  │
          │             │  │ │MapWin.│ │     │              │                  │
          │             │  │ │MapCanv│ │     │              │                  │
          │             │  │ │InfoPan│ │     │              │                  │
          │             │  │ │LiveThr│ │     │              │                  │
          │             │  │ └───────┘ │     │              │                  │
          │             │  └─────┬─────┘     │              │                  │
          │             │        │           │              │                  │
          ▼             ▼        ▼           ▼              ▼                  ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │                          Warstwa danych (JSON I/O)                              │
   │   wknn.py  ←→  radio_map.json                                                   │
   │   validate.py ←→ test_set.json, optimal_k.json                                 │
   │   session.py ←→ session.json                                                   │
   │   espar_client.py ←→ espar_config.json                                         │
   │   styles.py ←→ svg_calibration.json                                            │
   └─────────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
   ┌──────────────────────────────────┐
   │  EsparClient  →  TCP socket     │
   │  telnet_reader → parser ramek   │
   │  Serwer ESPAR (153.19.49.102)   │
   └──────────────────────────────────┘
```

### Zależności pomiędzy modułami

```
config.py              ← importowany przez WSZYSTKIE moduły (stałe, ścieżki)
  ↑
session.py             ← SessionManager (load/save sesji)
espar_client.py        ← EsparClient (TCP socket do ESPAR)
telnet_reader.py       ← parse_beacon_data(), get_espar_stream()
fingerprint.py         ← Fingerprint, process_multi_beacon()
wknn.py                ← load_radio_map(), save_radio_map(), wknn_estimate()
validate.py            ← load_test_set(), save_test_set(), run_validation(), optimize_k()
utils.py               ← get_int_input(), select_beacon_interactive(), show_plot()
rssi_analysis.py       ← run_rssi_analysis(), run_rssi_offline()
room_detector.py       ← scan_antennas_rssi(), analyze_and_predict(), run_room_detection()
calibration.py         ← Calibrator (zależy od: session, espar_client, telnet_reader, wknn, utils, config)
map_viewer.py          ← wrapper CLI → gui/window.py
gui/styles.py          ← kolory, kalibracja SVG↔m (zależy od: config)
gui/canvas.py          ← MapCanvas (zależy od: gui/styles, config)
gui/panel.py           ← InfoPanel (zależy od: gui/styles, config)
gui/threads.py         ← LiveThread (zależy od: espar_client, telnet_reader, wknn, validate, config)
gui/window.py          ← MapWindow (zależy od: gui/canvas, gui/panel, gui/threads, gui/styles,
                          config, fingerprint, espar_client, wknn, validate)
main.py                ← punkt wejścia (zależy od: session, espar_client, calibration,
                          wknn, validate, telnet_reader, room_detector, config, utils)
```

### Odpowiedzialność modułów

| Moduł | Odpowiedzialność |
|---|---|
| `config.py` | Centralizacja stałych: ścieżki, konfiguracje anteny, wartości domyślne |
| `session.py` | Zarządzanie sesją pomiarową (origin siatki) |
| `espar_client.py` | Połączenie TCP z serwerem ESPAR, start/stop transmisji |
| `telnet_reader.py` | Parsowanie ramek BLE z protokołu telnet |
| `fingerprint.py` | Przetwarzanie surowych pomiarów → uśrednione + znormalizowane odciski |
| `calibration.py` | Logika kalibracji: zbieranie danych, plan siatki, zapis do mapy |
| `wknn.py` | Algorytm lokalizacji WkNN + I/O mapy radiowej + przełączanie metryki |
| `validate.py` | Walidacja dokładności, optymalizacja K, wykresy |
| `rssi_analysis.py` | Diagnostyka stabilności RSSI, wykresy radarowe |
| `room_detector.py` | Automatyczne skanowanie portów i detekcja najsilniejszej anteny ESPAR |
| `utils.py` | Bezpieczne wczytywanie danych od użytkownika, wybór beaconów, wywoływanie `show_plot` |
| `map_viewer.py` | Punkt wejścia do GUI (parsowanie argumentów CLI) |
| `gui/` | Pełny graficzny interfejs użytkownika |

### Komunikacja między modułami
- **main.py → calibration.py**: Bezpośrednie wywołania metod `Calibrator`
- **main.py → room_detector.py**: Wywołanie `run_room_detection()` (opcja 10 oraz 4.3)
- **calibration.py → map_viewer.py**: Uruchamianie GUI jako podproces (`subprocess.run`), komunikacja przez **stdout (JSON)**
- **gui/window.py ↔ gui/threads.py**: Sygnały Qt (`pyqtSignal`) — wątkowo bezpieczne
- **gui/window.py → wknn.py, validate.py**: Bezpośrednie wywołania funkcji
- **gui/threads.py → espar_client.py → TCP**: Połączenie sieciowe w wątku tła

### Miejsca inicjalizacji

1. **`main.py:main()`** — punkt startowy całej aplikacji konsolowej
2. **`map_viewer.py:__main__`** — punkt startowy GUI (gdy uruchamiany jako podproces)
3. **`gui/window.py:MapWindow.__init__()`** — inicjalizacja okna GUI z odpowiednim trybem

---

## 4. Opis wszystkich plików

### src/main.py
- **Cel:** Punkt wejścia aplikacji — interaktywne menu konsolowe z 10 opcjami (+ 0 wyjście).
- **Importy:** `session`, `espar_client`, `calibration`, `wknn`, `validate`, `telnet_reader`, `config`, `utils`, `room_detector`
- **Eksportowane:** `main()` (funkcja główna)
- **Zależności:** Wszystkie moduły `src/`
- **Kto korzysta:** Użytkownik uruchamia bezpośrednio (`python main.py`)
- **Rozwiązuje:** Centralne sterowanie całym systemem z jednego menu

### src/config.py
- **Cel:** Centralizacja stałych konfiguracyjnych — eliminacja duplikacji.
- **Importy:** `os`
- **Eksportowane:** `SCRIPT_DIR`, `DATA_DIR`, `SVG_PATH`, `RADIO_MAP_PATH`, `TEST_SET_PATH`, `OPTIMAL_K_PATH`, `SESSION_PATH`, `SVG_CALIB_PATH`, `ESPAR_CONFIG_PATH`, `VALID_CHARS`, `CHAR_TO_DEG`, `DEG_TO_CHAR`, `DEFAULT_RSSI_PENALTY`, `DEFAULT_BEACON_ID`, `DEFAULT_TARGET_PACKETS`, `DEFAULT_K`, `PORT_NAMES`, `get_active_session_label()`, `get_radio_map_path()`, `get_test_set_path()`
- **Kto korzysta:** Wszystkie moduły
- **Rozwiązuje:** Unikanie hardkodowanych wartości w wielu plikach

### src/session.py
- **Cel:** Zarządzanie sesją pomiarową — punkt odniesienia (origin) dla lokalnych współrzędnych.
- **Importy:** `json`, `os`, `subprocess`, `sys`, `datetime`
- **Eksportowane:** `SessionManager`, `DATA_DIR`, `SCRIPT_DIR`
- **Kto korzysta:** `main.py`, `calibration.py`
- **Rozwiązuje:** Każda sesja ma własny origin, co pozwala na pomiary w różnych częściach budynku

### src/espar_client.py
- **Cel:** Zarządzanie połączeniem TCP z serwerem anteny ESPAR.
- **Importy:** `socket`, `time`, `os`, `json`
- **Eksportowane:** `EsparClient`
- **Kto korzysta:** `main.py`, `calibration.py`, `gui/threads.py`, `gui/window.py`, `room_detector.py`
- **Rozwiązuje:** Enkapsulacja logiki połączenia sieciowego (connect, start, stop, close)

### src/telnet_reader.py
- **Cel:** Odbieranie i parsowanie ramek BLE z serwera ESPAR.
- **Importy:** `json`, `config.VALID_CHARS`
- **Eksportowane:** `parse_beacon_data()`, `get_espar_stream()`
- **Kto korzysta:** `calibration.py`, `rssi_analysis.py`, `gui/threads.py`, `room_detector.py`
- **Rozwiązuje:** Parsowanie surowego strumienia telnet na strukturalne słowniki Python

### src/fingerprint.py
- **Cel:** Logika przetwarzania odcisków radiowych (średnia, normalizacja, eksport).
- **Importy:** `config.VALID_CHARS`, `config.DEFAULT_RSSI_PENALTY`
- **Eksportowane:** `Fingerprint`, `process_multi_beacon()`
- **Kto korzysta:** `gui/window.py`
- **Rozwiązuje:** Eliminacja zduplikowanego kodu uśredniania/normalizacji w GUI

### src/calibration.py
- **Cel:** Pełna logika kalibracji — zbieranie danych, plan siatki, zapis.
- **Importy:** `session`, `espar_client`, `telnet_reader`, `wknn`, `utils`, `config`
- **Eksportowane:** `Calibrator`
- **Kto korzysta:** `main.py`
- **Rozwiązuje:** Centralizacja logiki kalibracji z obsługą zestawów wielu beaconów (tripod)

### src/wknn.py
- **Cel:** Algorytm Weighted k-Nearest Neighbors + I/O mapy radiowej + przełączanie metryki.
- **Importy:** `json`, `math`, `os`, `config`
- **Eksportowane:** `load_radio_map()`, `save_radio_map()`, `wknn_estimate()`, `DISTANCE_METRIC`, `save_distance_metric()`, `load_distance_metric()`
- **Kto korzysta:** `main.py`, `calibration.py`, `validate.py`, `gui/threads.py`, `gui/window.py`, `utils.py`
- **Rozwiązuje:** Estymacja pozycji obiektu na podstawie porównania pomiarów live z bazą odcisków

### src/validate.py
- **Cel:** Walidacja dokładności lokalizacji (RMSE, P90, CDF, optymalizacja K).
- **Importy:** `json`, `math`, `os`, `matplotlib`, `config`, `wknn`, `utils.show_plot`
- **Eksportowane:** `load_test_set()`, `save_test_set()`, `run_validation()`, `optimize_k()`, `load_optimal_k()`, `load_optimal_beacon_id()`
- **Kto korzysta:** `main.py`, `gui/threads.py`, `gui/window.py`
- **Rozwiązuje:** Obiektywna ocena jakości systemu lokalizacji

### src/rssi_analysis.py
- **Cel:** Diagnostyka stabilności RSSI — migawki, wykresy radarowe, porównania.
- **Importy:** `json`, `math`, `os`, `matplotlib`, `numpy`, `config`, `utils.show_plot`
- **Eksportowane:** `run_rssi_analysis()`, `run_rssi_offline()`, `save_snapshot()`, `load_snapshot()`, `list_snapshots()`, `plot_radar_charts()`, `print_stability_table()`
- **Kto korzysta:** `main.py` (opcje 4.1, 4.2)
- **Rozwiązuje:** Ocena czy sygnał RSSI jest stabilny w czasie (czy trzeba rekalibrować)

### src/room_detector.py
- **Cel:** Uniwersalny moduł detekcji najbliższej anteny ESPAR na podstawie porównania mocy RSSI.
- **Importy:** `sys`, `time`, `socket`, `threading`, `espar_client`, `telnet_reader`, `config.PORT_NAMES`
- **Eksportowane:** `scan_antennas_rssi()`, `analyze_and_predict()`, `print_report()`, `run_room_detection()`
- **Kto korzysta:** `main.py` (opcje 10 oraz 4.3)
- **Rozwiązuje:** Automatyczna identyfikacja serwera ESPAR odbierającego najsilniejszy sygnał z beacona bez przypisywania do statycznych numerów pokoi. Odporny na awarie połączeń.

### src/utils.py
- **Cel:** Wspólne funkcje pomocnicze (bezpieczne wczytywanie, wybór beaconów, wywoływanie `show_plot`).
- **Importy:** `os`, `subprocess`
- **Eksportowane:** `get_int_input()`, `get_float_input()`, `get_choice_input()`, `build_beacon_candidates()`, `select_beacon_interactive()`, `get_beacons_from_radio_map()`, `show_plot()`
- **Kto korzysta:** `main.py`, `calibration.py`, `validate.py`, `rssi_analysis.py`
- **Rozwiązuje:** Eliminacja powtórzonych pętli walidacji inputu oraz bezcrashowe otwieranie plików PNG przez `xdg-open`

### src/map_viewer.py
- **Cel:** Wrapper CLI → GUI. Parsuje argumenty i uruchamia odpowiedni tryb `MapWindow`.
- **Importy:** `sys`, `json`, `PyQt6.QApplication`, `config`, `gui.window.MapWindow`
- **Eksportowane:** `launch_viewer()`
- **Kto korzysta:** `calibration.py`, `session.py`, `main.py`, `rssi_analysis.py` (jako podproces)
- **Tryby CLI:** `--calibrate`, `--test_collect`, `--grid_collect`, `--pick-session`, `--mark-origin`, `--view`, `--select-points`, `--pick`

### src/gui/__init__.py
- **Cel:** Inicjalizacja pakietu GUI (tylko docstring).

### src/gui/styles.py
- **Cel:** Paleta kolorów (dark theme) + konwersja SVG ↔ metry fizyczne.
- **Eksportowane:** stałe kolorów (`C_BG`, `C_ACCENT`, `C_DOT`, …), `physical_to_svg()`, `svg_to_physical()`, `SVG_ORIGIN_X`, `SVG_ORIGIN_Y`, `SCALE`

### src/gui/canvas.py
- **Cel:** Widget mapy SVG z nawigacją (zoom, pan), rysowaniem pozycji, radarem.
- **Eksportowane:** `MapCanvas`
- **Zawiera:** Rendering SVG, animację pulsacji, wykresy radarowe, rysowanie punktów

### src/gui/panel.py
- **Cel:** Panel boczny z informacjami o pozycji, przyciskami kontrolnymi oraz kontrolkami wyboru beacona i okna czasowego.
- **Eksportowane:** `InfoPanel`
- **Tryby:** normalny (live), kalibracja (fingerprinting), zbieranie testowe (ground truth)

### src/gui/threads.py
- **Cel:** Wątek tła — odbiór danych z ESPAR, obliczenia WkNN, emisja pozycji.
- **Eksportowane:** `LiveThread`
- **Sygnały:** `position(x, y, bid, conf)`, `status_msg(str)`, `frame_received(bid, char, rssi)`

### src/gui/window.py
- **Cel:** Główne okno aplikacji — łączy MapCanvas + InfoPanel + logikę biznesową.
- **Eksportowane:** `MapWindow`
- **Tryby:** 7 trybów pracy (live, pick-session, mark-origin, calibrate, grid_collect, test_collect, select-points)

---

## 5. Dokumentacja klas

### `SessionManager` (session.py)
- **Przeznaczenie:** Zarządza sesją pomiarową — punkt odniesienia (origin) siatki.
- **Odpowiedzialność:** Wczytywanie, zapisywanie, zarządzanie sesją; uruchamianie GUI do wyboru originu.
- **Pola:** `data_dir`, `script_dir`, `session_path`
- **Metody:** `load_session()`, `save_session(label, x, y)`, `manage_session()`, `_pick_on_map(flag)`
- **Zależności:** `map_viewer.py` (subprocess)
- **Tworzona w:** `main.py:main()` (raz, na starcie)
- **Używana w:** `main.py`, `calibration.py`

### `EsparClient` (espar_client.py)
- **Przeznaczenie:** Klient TCP do serwera anteny ESPAR.
- **Odpowiedzialność:** Nawiązywanie połączenia, wysyłanie komend `start`/`stop`, zarządzanie portem.
- **Pola:** `host`, `port`, `timeout`, `script_dir`, `config_path`
- **Metody:** `connect_and_start()`, `stop_and_close(sock)`, `load_port_from_config(default)`, `save_port_to_config(port)`
- **Zależności:** `socket`, konfiguracja z `espar_config.json`
- **Tworzona w:** `main.py:main()`, `gui/threads.py:LiveThread.run()`, `gui/window.py:_start_live()`, `room_detector.py`
- **Używana w:** `main.py`, `calibration.py`, `gui/threads.py`, `gui/window.py`, `room_detector.py`

### `Fingerprint` (fingerprint.py)
- **Przeznaczenie:** Reprezentuje jeden odcisk radiowy — uśrednianie + normalizacja.
- **Odpowiedzialność:** Przetwarzanie surowych RSSI per kierunek anteny.
- **Pola:** `raw` (surowe dane RSSI), `target_packets` (limit próbek)
- **Metody:** `compute_avg()`, `compute_norm(avg)` (static), `to_dict()`
- **Zależności:** `config.VALID_CHARS`, `config.DEFAULT_RSSI_PENALTY`
- **Tworzona w:** `process_multi_beacon()` w `fingerprint.py`
- **Używana w:** `gui/window.py` (przez `process_multi_beacon`)

### `Calibrator` (calibration.py)
- **Przeznaczenie:** Zbieranie danych kalibracyjnych (fingerprinting).
- **Odpowiedzialność:** Całość procesu kalibracji — od parametrów zestawu po zapis do mapy.
- **Pola:** `session_manager`, `client`, `VALID_CHARS`, `TARGET_PACKETS`
- **Metody:**
  - `run_average()` — kalibracja pojedynczego punktu
  - `run_grid_calibration()` — automatyczna kalibracja siatkowa
  - `run_collect_test_point()` — zbieranie punktu testowego (tekstowe)
  - `_collect_fingerprint(sock, label, packets, beacons)` — uruchamia GUI do zbierania
  - `_scan_available_beacons()` — skanuje aktywne beacony w zasięgu; w przypadku braku wyników zwraca pustą listę `[]`
  - `_ask_tripod_params()` — konfiguracja zestawu (wielobeaconowego)
  - `_beacon_positions(x, y, tripod)` — oblicza pozycje beaconów w zestawie
  - `_upsert_point(existing, label, point)` — dodaje/aktualizuje punkt w mapie
  - `_save_fingerprint_points(...)` — zapisuje fingerprinty (1 lub N punktów)
  - `_print_ascii_map(grid, tripod)` — wizualizacja ASCII siatki w terminalu
- **Zależności:** `SessionManager`, `EsparClient`, `telnet_reader`, `wknn`, `utils`, `config`
- **Tworzona w:** `main.py:main()` (raz)
- **Używana w:** `main.py` (opcje 2, 3, 4, 5, 7)

### `MapCanvas` (gui/canvas.py)
- **Przeznaczenie:** Widget renderujący mapę SVG z pozycją beacona i elementami interaktywnymi.
- **Odpowiedzialność:** Rendering SVG, zoom/pan, animacja pulsacji, radar chart, rysowanie punktów kalibracyjnych/testowych/gridowych.
- **Pola:** `_renderer` (QSvgRenderer), `_zoom`, `_pan`, `_bx/_by` (pozycja beacon SVG), `_trail` (ślad ruchu), `_pulse`, `_picked_svg_x/_y`, `_radar_rssi_data`, `_calibrate_mode`, `_existing_points`, `_test_points`, `_grid_data`, `_selected_labels` itd.
- **Sygnały:** `position_picked(float, float)` — pozycja wybrana przez użytkownika
- **Metody:** `update_position()`, `set_radar_data()`, `fit_view()`, `clear_trail()` + prywatne metody rysowania
- **Zależności:** `gui/styles`, `config`
- **Tworzona w:** `MapWindow.__init__()` (zawsze)

### `InfoPanel` (gui/panel.py)
- **Przeznaczenie:** Panel boczny z informacjami o pozycji i przyciskami.
- **Odpowiedzialność:** Wyświetlanie statusu, przycisków akcji, postępu zbierania, dynamiczna zmiana śledzonego beacona i rozszerzalnego okna uśredniania `WINDOW_SEC`.
- **Pola:** `_lbl_id`, `_lbl_x`, `_lbl_y`, `_lbl_conf`, `_conf_bar`, `_btn_fit`, `_btn_clear`, `_spn_beacon`, `_spn_window` + dynamiczne kontrolki kalibracji
- **Metody:** `refresh(x, y, svg_x, svg_y, bid, conf)`, `setup_calibration_mode(...)`, `setup_test_collect_mode(...)`
- **Zależności:** `gui/styles`, `config.VALID_CHARS`
- **Tworzona w:** `MapWindow.__init__()` (zawsze)

### `LiveThread` (gui/threads.py)
- **Przeznaczenie:** Wątek tła do odbierania ramek BLE i estymacji pozycji.
- **Odpowiedzialność:** Połączenie z ESPAR, odbiór strumienia, obliczenia WkNN w oknie czasowym.
- **Pola:** `host`, `port`, `timeout`, `calibrate_mode`, `WINDOW_SEC` (domyślnie 7s, modyfikowalne z GUI), `BEACON_ID`, `BLE_CHANNEL`
- **Sygnały:** `position(x, y, bid, conf)`, `status_msg(str)`, `frame_received(bid, char, rssi)`
- **Metody:** `run()` — główna pętla wątku
- **Zależności:** `EsparClient`, `telnet_reader`, `wknn`, `validate`, `config`
- **Tworzona w:** `MapWindow._start_live()`
- **Używana w:** `gui/window.py`

### `MapWindow` (gui/window.py)
- **Przeznaczenie:** Główne okno aplikacji — łączy MapCanvas + InfoPanel + logikę biznesową.
- **Odpowiedzialność:** Inicjalizacja trybów, obsługa zdarzeń, zapis danych, zarządzanie wątkiem.
- **Pola:** Liczne — tryby (`_pick_mode`, `_calibrate_mode`, …), dane kalibracji (`_calib_rssi_accum`, `_calib_beacons`, …), grid (`_grid_data`, `_grid_idx`), widgety (`_panel`, `_canvas`, `_sb`), wątek (`_live_thread`)
- **Sygnały:** `_sig_pos(x, y, bid, conf)` — wątkowo bezpieczna pozycja
- **Metody:** `update_position()`, `_on_picked()`, `_confirm_pick()`, `_start_test_collect()`, `_save_test_point()`, `_save_and_exit()`, `_save_grid_point()`, `_load_grid_point()`, `_start_live()`, `_stop_live()`, `_on_frame_received()`, …
- **Zależności:** Wszystkie moduły `gui/`, `config`, `fingerprint`, `espar_client`, `wknn`, `validate`
- **Tworzona w:** `map_viewer.py` (na starcie GUI)

---

## 6. Dokumentacja funkcji

### `main()` — main.py
- **Lokalizacja:** `src/main.py`, linia 60
- **Cel:** Główna pętla programu — wyświetla menu z 10 opcjami i deleguje do odpowiednich modułów.
- **Argumenty:** Brak
- **Zwracana wartość:** Brak (pętla `while True`, wyjście przez `choice == "0"`)
- **Opis działania:**
  1. Inicjalizuje `SessionManager`, `EsparClient`, `Calibrator`
  2. W pętli wyświetla podsumowanie stanu sesji, aktywnego portu, metryki, liczby punktów oraz menu z 10 opcjami
  3. Pobiera wybór użytkownika i deleguje do odpowiedniej metody/modułu
  4. Resetuje handler `SIGINT` na początku każdej iteracji (matplotlib go nadpisuje)
- **Złożoność:** O(1) per iterację (pętla zdarzeń)
- **Efekty uboczne:** Modyfikuje pliki JSON w `data/`, uruchamia podprocesy GUI

### `scan_antennas_rssi(host, ports, duration_sec)` — room_detector.py
- **Lokalizacja:** `src/room_detector.py`, linia 20
- **Cel:** Równoległe skanowanie podanych portów TCP serwerów ESPAR i zbieranie próbek RSSI per beacon.
- **Argumenty:** `host: str` (domyślnie IP z config), `ports: list[int]` (domyślnie porty z `PORT_NAMES`), `duration_sec: float` (domyślnie 4.0s)
- **Zwracana wartość:** `tuple(beacon_rssi: dict, connection_status: dict)`
- **Opis działania:** Uruchamia po jednym wątku tła dla każdego portu ESPAR. Każdy wątek łączy się, odbiera strumień przez `duration_sec` i zapisuje RSSI w bezpiecznej dla wątków strukturze z blokadą `threading.Lock`.
- **Wsparcie dla błędów:** Wyłapuje błędy sieciowe/timeouty bez zrywania całej operacji.

### `analyze_and_predict(beacon_rssi, connection_status)` — room_detector.py
- **Lokalizacja:** `src/room_detector.py`, linia 87
- **Cel:** Przetwarza zebrane dane RSSI i wyznacza najbardziej prawdopodobną antenę ESPAR dla każdego beacona.
- **Zwracana wartość:** `list[dict]` — wyznaczona najlepsza antena, średnie RSSI, marża przewagi w dBm.

### `run_room_detection(duration_sec)` — room_detector.py
- **Lokalizacja:** `src/room_detector.py`, linia 177
- **Cel:** Punkt wejścia wykonania detekcji pokoi/anten — wywołuje skanowanie, analizę oraz wyświetla czytelny raport w konsoli.

### `parse_beacon_data(json_line)` — telnet_reader.py
- **Lokalizacja:** `src/telnet_reader.py`, linia 29
- **Cel:** Parsuje jedną linię JSON z telnet → słownik ramki BLE.
- **Argumenty:** `json_line: str` — surowa linia z telnet (format: `{"v":"cnt_robot","d":"7,33,50,62,37,12604,0,0,0"}`)
- **Zwracana wartość:** `dict | None` — słownik z polami ramki lub `None` jeśli linia nieprawidłowa

### `get_espar_stream(sock)` — telnet_reader.py
- **Lokalizacja:** `src/telnet_reader.py`, linia 109
- **Cel:** Generator — odbiera dane z gniazda TCP i zwraca sparsowane ramki BLE.
- **Argumenty:** `sock: socket.socket` — aktywne gniazdo TCP

### `wknn_estimate(window_data, radio_map, k, beacon_id)` — wknn.py
- **Lokalizacja:** `src/wknn.py`, linia 247
- **Cel:** Estymacja pozycji metodą Weighted k-Nearest Neighbors (z dynamicznym wsparciem dla metryki Pearsona lub wycentrowanego Euklidesa na części wspólnej kierunków).
- **Zwracana wartość:** `tuple(x_m, y_m, confidence) | None`

### `_pearson_distance(v1, v2)` — wknn.py
- **Lokalizacja:** `src/wknn.py`, linia 177
- **Cel:** Oblicza odległość Pearsona: d = 1 − r na części wspólnej kierunków.

### `_euclidean_distance(v1, v2)` — wknn.py
- **Lokalizacja:** `src/wknn.py`, linia 182
- **Cel:** Odległość euklidesowa z wycentrowaniem do zera (zero-mean Euclidean distance). Odejmowanie średniej uśrednia wpływ poziomu bezwzględnego RSSI.

### `load_radio_map(path, filter_session)` — wknn.py
- **Lokalizacja:** `src/wknn.py`, linia 71
- **Cel:** Wczytuje mapę radiową z JSON (dynamicznie rozwiązywaną dla aktywnej sesji przez `get_radio_map_path()`).

### `save_radio_map(fingerprints, path)` — wknn.py
- **Lokalizacja:** `src/wknn.py`, linia 110
- **Cel:** Zapisuje mapę radiową do JSON.

### `optimize_k(beacon_id, k_max)` — validate.py
- **Lokalizacja:** `src/validate.py`, linia 319
- **Cel:** Grid search — wyznacza optymalne K minimalizujące RMSE na zbiorze testowym.

### `run_validation(k, beacon_id)` — validate.py
- **Lokalizacja:** `src/validate.py`, linia 429
- **Cel:** Pełna walidacja WkNN na zbiorze testowym. Generuje raport JSON oraz otwiera wykresy CDF i Scatter przez `show_plot()`.

### `run_rssi_analysis(connect_fn, stream_fn, close_fn, valid_chars, beacon_id, n_per_config)` — rssi_analysis.py
- **Lokalizacja:** `src/rssi_analysis.py`, linia 373
- **Cel:** Zbiera N próbek RSSI per konfigurację anteny i generuje wykresy radarowe.

### `process_multi_beacon(rssi_accum, target_bids, target_packets)` — fingerprint.py
- **Lokalizacja:** `src/fingerprint.py`, linia 83
- **Cel:** Przetwarza zebrane dane RSSI dla wielu beaconów → uśrednione + znormalizowane (bez sztucznych kar -95 dBm).

### `show_plot(fig, out_path)` — utils.py
- **Lokalizacja:** `src/utils.py`, linia 209
- **Cel:** Zapisuje wykres matplotlib do pliku PNG, zamyka figurę i otwiera plik z poziomu `xdg-open` (bez ryzyka crashu na Qt/Wayland).

---

## 7. Przepływ wykonywania programu

### Uruchomienie

```
python main.py
    │
    ├── os.environ["QT_LOGGING_RULES"] = "qt.*=false"  (wyciszenie logów Qt)
    │
    └── main()
         ├── SessionManager(DATA_DIR, SCRIPT_DIR)
         ├── EsparClient()                              (wczytuje port z espar_config.json)
         ├── Calibrator(session_manager, client)
         │
         └── PĘTLA GŁÓWNA (while True):
              ├── signal.signal(SIGINT, default)         (reset handlera)
              ├── session_manager.load_session()          (wczytaj session.json)
              ├── load_test_set(filter_session=True)      (policz punkty testowe)
              ├── load_radio_map(filter_session=True)     (policz punkty kalibracyjne)
              ├── load_optimal_k(default=3)               (wczytaj optymalne K)
              │
              ├── WYŚWIETL MENU (1-10, 0=wyjście)
              │
              └── OBSŁUŻ WYBÓR:
                   ├── 1  → session_manager.manage_session()
                   ├── 2  → calibrator.run_grid_calibration() lub run_average()
                   ├── 3  → subprocess.run(map_viewer.py --view <bid>)
                   ├── 4  → rssi_analysis (offline / live / 4.3 detekcja anteny)
                   ├── 5  → GUI zbierania punktów testowych lub calibrator.run_collect_test_point()
                   ├── 6  → optimize_k() lub ręczny zapis K
                   ├── 7  → run_validation(k=None, beacon_id=bid)
                   ├── 8  → zmiana portu anteny (8893, 8894, 8895)
                   ├── 9  → zmiana metryki odległości (Pearson vs Euclidean)
                   ├── 10 → room_detector.run_room_detection()
                   └── 0  → break
```

### Przepływ kalibracji (opcja 2, tryb siatka)

```
calibrator.run_grid_calibration()
    ├── load_session() → (ox, oy)
    ├── _ask_tripod_params() → tripod config (lub None)
    ├── _scan_available_beacons() → [beacon IDs]
    ├── Oblicz grid_points (meander/zygzak)
    ├── _print_ascii_map(grid_points, tripod) → wizualizacja
    ├── Zapisz planned_grid.json
    │
    └── subprocess.run(map_viewer.py --grid_collect <json_path>)
         │
         └── MapWindow(grid_collect_mode=True)
              ├── _load_grid_point(0) → załaduj pierwszy punkt
              ├── _start_live() → LiveThread → TCP socket → ESPAR
              │
              └── DLA KAŻDEGO PUNKTU:
                   ├── LiveThread.frame_received → _on_frame_received()
                   │    ├── Akumuluj RSSI w _calib_rssi_accum
                   │    ├── Aktualizuj radar chart na mapie
                   │    └── Aktualizuj pasek postępu
                   │
                   ├── [Użytkownik] → "Zapisz i idź dalej"
                   │    ├── _save_grid_point()
                   │    │    ├── process_multi_beacon() → avg + norm
                   │    │    ├── load_radio_map() → existing
                   │    │    ├── Dodaj/aktualizuj punkt
                   │    │    └── save_radio_map(existing)
                   │    │
                   │    └── _skip_grid_point() → _load_grid_point(idx+1)
                   │
                   └── [Ostatni punkt] → close()
```

### Przepływ pozycjonowania na żywo (GUI)

```
MapWindow (tryb normalny)
    │
    └── [Checkbox "Pozycja na żywo"] → _on_toggle_live(True)
         │
         └── _start_live()
              │
              └── LiveThread.run()
                   ├── EsparClient.connect_and_start() → socket TCP
                   │
                   └── PĘTLA (get_espar_stream):
                        ├── Filtruj ramki (beacon_id, valid_chars)
                        ├── Akumuluj RSSI w window_data
                        │
                        └── Co WINDOW_SEC (domyślnie 7s):
                             ├── wknn_estimate(window_data, radio_map, k, beacon_id)
                             │    ├── Buduj V_live (średnie RSSI)
                             │    ├── Oblicz odległość (Pearson / Euklides) do każdego FP
                             │    ├── Sortuj, wybierz K najbliższych
                             │    └── Ważona suma z wygładzeniem → (x_est, y_est, confidence)
                             │
                             ├── position.emit(x_est, y_est, bid, conf)
                             │    │
                             │    └── MapWindow._on_position()
                             │         ├── MapCanvas.update_position() → animacja
                             │         ├── InfoPanel.refresh() → aktualizacja panelu
                             │         └── StatusBar → nowy status
                             │
                             └── window_data.clear()  (reset okna)
```

---

## 8. Przepływ danych

### 1. Kalibracja (fingerprinting)

```
Źródło danych:    Serwer ESPAR (TCP socket) → ramki BLE
                  ↓
Parsowanie:       telnet_reader.parse_beacon_data() → dict{rssi_dbm, espar_char_int, ...}
                  ↓
Akumulacja:       gui/window.py:_on_frame_received() → _calib_rssi_accum[bid][char] = [rssi, ...]
                  ↓
Przetwarzanie:    fingerprint.process_multi_beacon() → {bid: {avg: {...}, norm: {...}}}
                  ↓
Walidacja:        Filtrowanie beaconów bez danych (brak pomiarów)
                  ↓
Zapis:            wknn.save_radio_map() → data/radio_map.json
                  ↓
Konsumenci:       wknn_estimate(), validate.py, rssi_analysis.py (offline)
```

### 2. Pozycjonowanie (online)

```
Źródło danych:    Serwer ESPAR → ramki BLE (ciągły strumień)
                  ↓
Buforowanie:      LiveThread — okno czasowe WINDOW_SEC (domyślnie 7 sekund)
                  ↓
Estymacja:        wknn_estimate(window_data, radio_map, k, beacon_id)
                  ↓
Wizualizacja:     MapCanvas.update_position() → animowana kropka na mapie SVG
                  ↓
Informacja:       InfoPanel.refresh() → współrzędne, pewność
```

### 3. Walidacja

```
Źródło danych:    data/test_set.json (zebrane punkty ground truth)
                  + data/radio_map.json (mapa kalibracyjna)
                  ↓
Konwersja:        avg_to_window_data() — symuluje okno z jednej próbki
                  ↓
Estymacja:        wknn_estimate() — pozycja estymowana
                  ↓
Błąd:             √((x_true - x_est)² + (y_true - y_est)²)
                  ↓
Statystyki:       compute_stats() → Mean, RMSE, Max, P50, P75, P90
                  ↓
Zapis:            data/validation_report.json
                  ↓
Wizualizacja:     utils.show_plot() → data/validation_cdf.png, data/validation_scatter.png
```

---

## 9. Diagram zależności

```
config.py
 └── (importowany przez wszystkie moduły)

main.py
 ├── korzysta z session.py (SessionManager)
 ├── korzysta z espar_client.py (EsparClient)
 ├── korzysta z calibration.py (Calibrator)
 ├── korzysta z wknn.py (load_radio_map, save_distance_metric)
 ├── korzysta z validate.py (load_test_set, load_optimal_k, optimize_k, run_validation)
 ├── korzysta z telnet_reader.py (get_espar_stream)
 ├── korzysta z room_detector.py (run_room_detection)
 ├── korzysta z utils.py (get_beacons_from_radio_map, build_beacon_candidates, select_beacon_interactive)
 └── korzysta z rssi_analysis.py (run_rssi_analysis, run_rssi_offline)

calibration.py
 ├── korzysta z session.py (SessionManager)
 ├── korzysta z espar_client.py (EsparClient)
 ├── korzysta z telnet_reader.py (get_espar_stream)
 ├── korzysta z wknn.py (load_radio_map, save_radio_map)
 ├── korzysta z utils.py (get_int_input, get_float_input, get_choice_input)
 └── korzysta z map_viewer.py (subprocess)

gui/window.py
 ├── korzysta z gui/canvas.py (MapCanvas)
 ├── korzysta z gui/panel.py (InfoPanel)
 ├── korzysta z gui/threads.py (LiveThread)
 ├── korzysta z gui/styles.py (kolory, konwersje)
 ├── korzysta z fingerprint.py (process_multi_beacon)
 ├── korzysta z espar_client.py (EsparClient)
 ├── korzysta z wknn.py (load_radio_map, save_radio_map)
 └── korzysta z validate.py (load_test_set, save_test_set)

gui/threads.py
 ├── korzysta z espar_client.py (EsparClient)
 ├── korzysta z telnet_reader.py (get_espar_stream)
 ├── korzysta z wknn.py (load_radio_map, wknn_estimate)
 └── korzysta z validate.py (load_optimal_k)

validate.py
 ├── korzysta z wknn.py (load_radio_map, wknn_estimate, DISTANCE_METRIC)
 └── korzysta z utils.py (show_plot)

rssi_analysis.py
 ├── korzysta z config.py (CHAR_TO_DEG)
 └── korzysta z utils.py (show_plot)

room_detector.py
 ├── korzysta z espar_client.py (EsparClient)
 ├── korzysta z telnet_reader.py (get_espar_stream)
 └── korzysta z config.py (PORT_NAMES)

wknn.py
 └── korzysta z config.py (RADIO_MAP_PATH, get_radio_map_path)

fingerprint.py
 └── korzysta z config.py (VALID_CHARS, DEFAULT_RSSI_PENALTY)
```

---

## 10. Diagram wywołań funkcji

### Uruchomienie → Detekcja najsilniejszej anteny ESPAR (Opcja 10)

```
main()
  ↓
run_room_detection()
  ↓
scan_antennas_rssi(host, ports, duration_sec)
  ↓
  EsparClient(host, port)
    ↓
  EsparClient.connect_and_start()
    ↓
  get_espar_stream(sock)
    ↓
  parse_beacon_data(json_line)
  ↓
analyze_and_predict(beacon_rssi, connection_status)
  ↓
print_report(predictions, connection_status, duration_sec)
```

### Uruchomienie → Walidacja

```
main()
  ↓
run_validation(k=None, beacon_id=bid)
  ↓
load_optimal_k(default=3)
  ↓
load_test_set(filter_session=True)
  ↓
load_radio_map(filter_session=True)
  ↓
avg_to_window_data(beacons_avg, beacon_id)
  ↓
wknn_estimate(window_data, radio_map, k, beacon_id)
  ↓
  _get_directions(radio_map, beacon_id)
  ↓
  _fp_vector(fp, beacon_id, directions)
  ↓
  _pearson_distance(live_vec, fp_vec) lub _euclidean_distance()
  ↓
compute_stats(errors)
  ↓
utils.show_plot(fig_cdf, cdf_path)
  ↓
utils.show_plot(fig_scatter, scatter_path)
```

---

## 11. Globalne zmienne i stałe

### Stałe z config.py

| Stała | Typ | Wartość | Znaczenie |
|---|---|---|---|
| `SCRIPT_DIR` | str | `dirname(__file__)` | Katalog skryptu |
| `DATA_DIR` | str | `../data` | Katalog danych |
| `SVG_PATH` | str | `../../SVG_parser/mapaAK_sieciowe_v3.svg` | Ścieżka do mapy SVG |
| `RADIO_MAP_PATH` | str | `data/radio_map.json` | Domyślna mapa radiowa |
| `TEST_SET_PATH` | str | `data/test_set.json` | Domyślny zbiór testowy |
| `OPTIMAL_K_PATH` | str | `data/optimal_k.json` | Optymalne K |
| `SESSION_PATH` | str | `data/session.json` | Sesja pomiarowa |
| `SVG_CALIB_PATH` | str | `data/svg_calibration.json` | Kalibracja SVG |
| `ESPAR_CONFIG_PATH` | str | `data/espar_config.json` | Port/host anteny + metryka |
| `VALID_CHARS` | set[int] | `{31, 62, 124, 248, 496, 992, 1984, 3968, 3841, 3587, 3079, 2063}` | 12 poprawnych konfiguracji anteny (12-bit) |
| `CHAR_TO_DEG` | dict | `{31: 90, 62: 120, ...}` | Konfiguracja → kąt wiązki |
| `DEG_TO_CHAR` | dict | `{90: 31, 120: 62, ...}` | Kąt → konfiguracja (odwrotne) |
| `DEFAULT_RSSI_PENALTY` | float | `-95.0` | Spuścizna (legacy) |
| `DEFAULT_BEACON_ID` | int | `28` | Domyślny ID beacona |
| `DEFAULT_TARGET_PACKETS` | int | `100` | Domyślna liczba pakietów per kierunek |
| `DEFAULT_K` | int | `3` | Domyślna liczba sąsiadów WkNN |
| `PORT_NAMES` | dict | `{8893: "espar07", 8894: "espar37", 8895: "espar35"}` | Porty TCP → nazwy anten |

### Stałe z gui/styles.py

| Stała | Wartość | Znaczenie |
|---|---|---|
| `C_BG` | `#0a0e1a` | Tło główne (dark theme) |
| `C_PANEL` | `#0f1623` | Tło panelu bocznego |
| `C_ACCENT` | `#3b82f6` | Kolor akcentu (niebieski) |
| `C_DOT` | `#ef4444` | Kolor kropki beacona (czerwony) |
| `C_SUCCESS` | `#10b981` | Kolor sukcesu (zielony) |
| `SVG_ORIGIN_X` | `0.0` | Origin SVG w osi X |
| `SVG_ORIGIN_Y` | `0.0` | Origin SVG w osi Y |
| `SCALE` | `100.0` | 100 SVG units = 1 metr |

### Zmienne modułowe

| Moduł | Zmienna | Wartość | Znaczenie |
|---|---|---|---|
| `wknn.py` | `DISTANCE_METRIC` | `'pearson'` / `'euclidean'` | Aktywna metryka odległości (wczytywana z JSON) |
| `gui/threads.py` | `LiveThread.WINDOW_SEC` | `7.0` | Długość okna czasowego [s] (modyfikowalna z GUI) |
| `rssi_analysis.py` | `SNAPSHOTS_DIR` | `data/rssi_snapshots` | Katalog migawek RSSI |

---

## 12. Konfiguracja

### Pliki konfiguracyjne

#### `data/espar_config.json`
```json
{"port": 8894, "host": "153.19.49.102", "metric": "pearson"}
```
- **Znaczenie:** Port TCP, adres IP serwera anteny ESPAR oraz aktywna metryka odległości
- **Modyfikowany przez:** opcja 8 i 9 w menu głównym

#### `data/session.json`
```json
{"origin_label": "espar37", "origin_x_m": 22.87, "origin_y_m": 8.748, "created": "2026-07-02T11:17:24"}
```
- **Znaczenie:** Aktywna sesja pomiarowa — punkt odniesienia (origin) dla lokalnych współrzędnych
- **Modyfikowany przez:** opcja 1 w menu głównym

---

## 15. Historia zmian architektury

### 2026-07-03

- Utworzono plik `architectural.md` — pełna dokumentacja architektury.
- Stan projektu: 12 modułów Python + 5 modułów GUI + 1 wrapper CLI.
- Aktywna metryka: Pearson (1-r).
- 3 anteny ESPAR (porty 8893, 8894, 8895).

### 2026-07-03 (Zmiany w kalibracji i estymacji)

- **Interaktywny wybór beaconów**: Usunięto automatyczne podstawianie beacon ID `28` w `_scan_available_beacons()` w przypadku braku wykrytych urządzeń. Funkcja zwraca `[]` i pyta użytkownika o ręczne wpisanie ID.
- **Usunięcie systemu kar -95 dBm**:
  - Usunięto dopisywanie sztucznych kar `DEFAULT_RSSI_PENALTY` (`-95.0` dBm) dla brakujących kierunków w `Fingerprint.compute_avg()` (`fingerprint.py`). Odciski w bazie zapisywane bez sztucznie wymuszonych kierunków.
  - Zmodyfikowano `wknn_estimate()` (`wknn.py`), aby wykonywała obliczenia metryki **wyłącznie na części wspólnej (przecięciu) kierunków**, dla których odebrano sygnał.
  - **Eliminacja przyciągania do siatki (snapping)**: Dodano wygładzenie `alpha = 0.05` do wag WkNN (`1 / (d + alpha)²`), co przywróciło płynną interpolację pozycji pomiędzy punktami referencyjnymi.
- **Poprawa pewności (confidence) dla metryki euklidesowej**: Wprowadzono wykładnicze mapowanie oparte na średnim błędzie RSSI na kierunek: $conf = \exp(-e_{avg} / 10)$.
- **Dynamiczna zmiana okna czasowego pozycjonowania (WINDOW_SEC)**: Do panelu bocznego (`InfoPanel` w `gui/panel.py`) dodano kontrolkę typu `QSpinBox` („Rozmiar okna [s]”), która pozwala na zmianę czasu okna uśredniania sygnału w locie.
- **Konfigurowalna metryka odległości z CLI (opcja 9)**: Do menu głównego dodano opcję `9` pozwalającą na zmianę aktywnej metryki odległości (Pearson vs Euklides) w locie. Wybór użytkownika jest zapisywany w pliku `espar_config.json`.
- **Dynamiczne bazy danych pokoi (sesji) i przełączanie (opcja 1)**: Zastąpiono statyczne ścieżki generatorami ścieżek `get_radio_map_path()` i `get_test_set_path()` w `config.py`.

### 2026-07-09 (Refaktoryzacja i optymalizacja kodu logiki)

- **Centralizacja sesji i ścieżek (`config.py`)**: Dodano helper `get_active_session_label()` i `_find_data_file()`.
- **Wspólne rysowanie wykresów (`utils.py`)**: Przeniesiono funkcję `show_plot()` z `validate.py` i `rssi_analysis.py` w jedno wspólne miejsce w `utils.py`.
- **Usunięcie duplikacji z wyborem beaconów (`main.py`, `calibration.py`)**: 
  - Dodano helper `_choose_single_beacon()` w `Calibrator`.
  - Dodano helper `_select_beacon()` w `main.py`.
- **Uporządkowanie importów**: Przeniesiono import `VALID_CHARS` w `telnet_reader.py` na poziom modułu. Usunięto zduplikowany alias importu w `main.py`.

### 2026-07-17 (Uniwersalny moduł detekcji najbliższej anteny ESPAR, usunięcie filtrowania punktów mapy po ID beacona oraz optymalizacja metryki euklidesowej)

- **Uniwersalny moduł detekcji najbliższej anteny ESPAR (`room_detector.py`)**: Utworzono uniwersalny moduł próbkowania portów anten ESPAR (8893 - `espar07`, 8894 - `espar37`, 8895 - `espar35`). Moduł uśrednia sygnały RSSI i automatycznie wskazuje najsilniejszą antenę ESPAR dla każdego wykrytego beacona bez odwołań do specyficznych numerów pokojów. Odporny na awarie połączeń. Zintegrowano z menu głównym jako opcja `10` (oraz `4.3`).
- **Wyświetlanie punktów w MapWindow**: Usunięto odfiltrowywanie punktów kalibracyjnych po `live_beacon_id` w `MapWindow.__init__()` (`gui/window.py`). Vizualizacja prezentuje pełen zestaw odcisków z aktywnej sesji.
- **Wycentrowanie odległości euklidesowej (Zero-Mean Euclidean Distance)**: Zmodyfikowano `_euclidean_distance()` w `wknn.py`, aby przed obliczeniem sumy kwadratów różnic odejmowała średni poziom RSSI wektora ($v - \mu$). Zmniejszyło błąd RMSE z 2.094 m do 1.591 m.
- **Dynamiczny wybór śledzonego Beacona w GUI (`gui/panel.py` i `gui/window.py`)**: Do panelu bocznego (`InfoPanel`) dodano pole `QSpinBox` („Beacon ID:”), które pozwala na płynną zmianę śledzonego urządzenia w locie.

---

## 16. Lista TODO

### Refaktoryzacja
- [ ] `calibration.py` (941 linii) — zbyt długi plik; rozdzielić na `calibration_single.py` i `calibration_grid.py`
- [ ] `gui/window.py` (960 linii) — zbyt długi; wydzielić logikę trybów do osobnych klas/mixinów
- [ ] `gui/canvas.py` (725 linii) — zbyt długie `paintEvent`; wydzielić metody rysowania radaru
- [ ] `rssi_analysis.py` (749 linii) — zbyt długi; rozdzielić na `rssi_collect.py` i `rssi_plot.py`

### Potencjalne błędy i usprawnienia GUI
- [ ] `gui/window.py`: wielokrotne `setup_calibration_mode()` i `_canvas._calibrate_mode = True` w `__init__()` (linie 186-210 i 275-308 — zduplikowana inicjalizacja)
- [ ] `wknn.py:_fp_vector()`: fallback na pierwszy dostępny beacon gdy nie ma docelowego — może dawać nieoczekiwane wyniki
- [ ] Brak obsługi błędu gdy `SVG_parser/mapaAK_sieciowe_v3.svg` nie istnieje

### Nieużywane elementy
- [ ] `utils.py:get_choice_input()` — używana tylko w `calibration.py`; mogłaby być prywatna
- [ ] `gui/canvas.py:_mark_origin_mode` — tryb `--mark-origin` istnieje ale rzadko używany

---

## 17. Najważniejsze zależności

| Biblioteka | Po co jest | Gdzie jest używana | Od czego zależy |
|---|---|---|---|
| **PyQt6** | Framework GUI (okna, widgety, rendering SVG, wątki) | `gui/*.py`, `map_viewer.py` | C++ Qt6, Python ≥ 3.8 |
| **PyQt6.QtSvg** | Renderowanie pliku SVG budynku | `gui/canvas.py` (QSvgRenderer) | PyQt6 |
| **matplotlib** | Wykresy (CDF, scatter, radar, heatmapa, K-opt) | `validate.py`, `rssi_analysis.py` | numpy |
| **numpy** | Obliczenia numeryczne (wykresy radarowe, estymacja kierunku) | `rssi_analysis.py` | — |
| **socket** (stdlib) | Komunikacja TCP z serwerem ESPAR | `espar_client.py`, `room_detector.py` | — |
| **threading** (stdlib) | Równoległe skanowanie portów anten ESPAR | `room_detector.py` | — |
| **json** (stdlib) | Serializacja/deserializacja danych | Wszystkie moduły | — |
| **subprocess** (stdlib) | Uruchamianie GUI jako podprocesu, otwieranie wykresów xdg-open | `calibration.py`, `session.py`, `main.py`, `utils.py` | — |
| **math** (stdlib) | Obliczenia trygonometryczne (pozycje beaconów, odległości) | `calibration.py`, `wknn.py`, `validate.py`, `gui/canvas.py` | — |
| **signal** (stdlib) | Reset handlera SIGINT (Ctrl+C) | `main.py` | — |

---

## 18. Słownik projektu

### Klasy

| Nazwa | Znaczenie |
|---|---|
| `SessionManager` | Zarządca sesji pomiarowej (origin siatki) |
| `EsparClient` | Klient TCP do serwera anteny ESPAR |
| `Calibrator` | Moduł zbierania danych kalibracyjnych |
| `Fingerprint` | Odcisk radiowy z jednego punktu pomiarowego |
| `MapCanvas` | Widget mapy SVG z nawigacją i rysowaniem |
| `InfoPanel` | Panel boczny z informacjami o pozycji |
| `LiveThread` | Wątek tła — odbiór danych i estymacja pozycji |
| `MapWindow` | Główne okno aplikacji GUI |

### Moduły

| Nazwa | Znaczenie |
|---|---|
| `config` | Centralizacja stałych konfiguracyjnych |
| `session` | Zarządzanie sesją pomiarową |
| `espar_client` | Klient połączenia z anteną |
| `telnet_reader` | Parser ramek BLE z telnet |
| `fingerprint` | Przetwarzanie odcisków radiowych |
| `calibration` | Logika kalibracji (fingerprinting) |
| `wknn` | Algorytm Weighted k-Nearest Neighbors |
| `validate` | Walidacja dokładności lokalizacji |
| `rssi_analysis` | Analiza stabilności RSSI |
| `room_detector` | Detekcja najsilniejszej anteny ESPAR |
| `utils` | Funkcje pomocnicze |
| `map_viewer` | Wrapper CLI → GUI |

### Skróty

| Skrót | Pełna nazwa | Opis |
|---|---|---|
| **ESPAR** | Electronically Steerable Parasitic Array Radiator | Antena z elektronicznie sterowaną wiązką |
| **BLE** | Bluetooth Low Energy | Protokół bezprzewodowy nadajników (beaconów) |
| **IPS** | Indoor Positioning System | System lokalizacji wewnątrzbudynkowej |
| **WkNN** | Weighted k-Nearest Neighbors | Algorytm estymacji pozycji |
| **RSSI** | Received Signal Strength Indicator | Wskaźnik siły sygnału [dBm] |
| **RSS** | Received Signal Strength | Siła sygnału odbieranego |
| **CDF** | Cumulative Distribution Function | Dystrybuanta błędu lokalizacji |
| **RMSE** | Root Mean Square Error | Pierwiastek średniego błędu kwadratowego |
| **P90** | 90th Percentile | 90. percentyl błędu |
| **SVG** | Scalable Vector Graphics | Format mapy budynku |
| **TCP** | Transmission Control Protocol | Protokół połączenia z anteną |
| **char_int** | Antenna characteristic integer | 12-bitowy wektor sterujący anteną (dziesiętnie) |
| **tripod** | Zestaw beaconów (statyw) | Konfiguracja wielu beaconów w linii |
| **origin** | Punkt odniesienia sesji | Lokalne (0,0) do pomiarów taśmą |
| **fingerprint** | Odcisk radiowy | Wektor RSSI z 12 konfiguracji anteny |
| **radio_map** | Mapa radiowa | Baza odcisków kalibracyjnych |
| **test_set** | Zbiór testowy | Punkty z prawdziwą pozycją (ground truth) |
| **confidence** | Pewność estymacji | Miara jakości dopasowania [0–1] |
| **grid search** | Przeszukiwanie siatki | Metoda optymalizacji K (próbuj wszystkie wartości) |
| **meander** | Zygzak | Kolejność odwiedzania punktów siatki |
| **snapshot / migawka** | Zrzut RSSI | Surowe dane RSSI z jednego pomiaru |

---

## 19. Podsumowanie architektury

### Najważniejsze moduły
1. **`wknn.py`** — serce systemu: algorytm WkNN + I/O mapy radiowej
2. **`calibration.py`** — logika zbierania danych kalibracyjnych (pojedynczo i siatką)
3. **`gui/window.py`** — centralne okno GUI łączące wszystkie tryby wizualizacji
4. **`telnet_reader.py`** — parser strumienia BLE z anteny ESPAR
5. **`room_detector.py`** — automatyczne skanowanie portów i wykrywanie najsilniejszej anteny ESPAR
6. **`config.py`** — centralizacja stałych (importowany wszędzie)

### Główne zależności
```
main.py → calibration.py → wknn.py → config.py
       ├── room_detector.py → telnet_reader.py → config.py
       ↕ (subprocess)
 map_viewer.py → gui/window.py → gui/canvas.py
                               → gui/panel.py
                               → gui/threads.py → espar_client.py
                                                → telnet_reader.py
                                                → wknn.py
```

### Sposób działania projektu

1. **Faza offline (kalibracja):** Użytkownik chodzi po budynku z anteną ESPAR i zbiera odciski radiowe w znanych punktach. Każdy punkt to wektor 12 wartości RSSI (po jednej na konfigurację anteny). Dane zapisywane do `radio_map.json`.

2. **Faza online (pozycjonowanie):** System ciągle odbiera ramki BLE, co `WINDOW_SEC` (domyślnie 7s) oblicza średnie RSSI i porównuje z mapą radiową algorytmem WkNN (metryka Pearsona lub Euklidesa). K najbliższych sąsiadów wyznacza estymowaną pozycję (ważona suma z wagą $1/(d + \alpha)^2$).

3. **Walidacja & Detekcja:** System zbiera punkty testowe (ground truth) i porównuje estymowane pozycje z rzeczywistymi, a także umożliwia dynamiczne skanowanie portów anten ESPAR w celu wyznaczenia lokalizacji o najwyższym poziomie RSSI.
