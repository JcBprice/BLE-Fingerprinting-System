import json
import os

def fix_radio_map(path):
    if not os.path.exists(path):
        return
        
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    for item in data:
        # Remove _tripod field if it exists
        if '_tripod' in item:
            del item['_tripod']
            
        # Ensure labels are unique by appending beacon ID if there is exactly 1 beacon
        if 'beacons' in item and len(item['beacons']) == 1:
            bid = list(item['beacons'].keys())[0]
            # Check if it doesn't already have the beacon ID at the end
            if not item['label'].endswith(f"_{bid}") and not item['label'].endswith(f"_b{bid}"):
                item['label'] = f"{item['label']}_{bid}"
                
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Paths to fix
files_to_fix = [
    "ESPAR/data/radio_map.json",
    "old_fingerprints/radio_map_korytarz_podwojne_etykiety.json"
]

for file in files_to_fix:
    fix_radio_map(file)
    print(f"Fixed {file}")
