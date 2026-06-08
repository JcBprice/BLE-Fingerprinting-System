"""
Czyści radio_map.json z wpisów stanów przejściowych anteny ESPAR:
  - "0"    (000000000000) — brak aktywnych prętów
  - "4095" (111111111111) — wszystkie pręty aktywne jednocześnie
Te wartości char_int są generowane przez mikrokontroler podczas przełączania
konfiguracji i nie niosą informacji o kierunkowości wiązki.
"""
import json
import os

RADIO_MAP_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "radio_map.json")
)

INVALID_CHARS = {"0", "4095"}  # klucze do usunięcia (string, bo JSON klucze są stringami)

with open(RADIO_MAP_PATH, "r", encoding="utf-8") as f:
    radio_map = json.load(f)

removed_total = 0

for point in radio_map:
    for beacon_id, beacon_data in point.get("beacons", {}).items():
        for section in ("avg", "norm"):
            before = set(beacon_data.get(section, {}).keys())
            beacon_data[section] = {
                k: v for k, v in beacon_data.get(section, {}).items()
                if k not in INVALID_CHARS
            }
            after = set(beacon_data[section].keys())
            removed = before - after
            if removed:
                removed_total += len(removed)
                print(f"  [{point['label']}] beacon {beacon_id} / {section}: usunięto klucze {removed}")

with open(RADIO_MAP_PATH, "w", encoding="utf-8") as f:
    json.dump(radio_map, f, indent=2, ensure_ascii=False)

print(f"\n[OK] Gotowe. Usunięto {removed_total} wpisów z {len(radio_map)} punktów kalibracyjnych.")
print(f"     Plik zapisany: {RADIO_MAP_PATH}")
