import json
import os

TAG_MAPPING_FILE = "tag_mapping.json"

def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    mapping = load_json(TAG_MAPPING_FILE, {})
    initial_count = len(mapping)
    
    # We remove any entry that maps to "work" or "Work" exactly,
    # or any entry that seems to be a single-word generic tag that we want to re-evaluate.
    # The user specifically mentioned "Work".
    
    cleaned_mapping = {
        k: v for k, v in mapping.items() 
        if v.lower() != "work"
    }
    
    removed_count = initial_count - len(cleaned_mapping)
    save_json(TAG_MAPPING_FILE, cleaned_mapping)
    
    print(f"-> Nettoyage terminé.")
    print(f"   Entrées totales avant : {initial_count}")
    print(f"   Entrées supprimées (Work sink) : {removed_count}")
    print(f"   Entrées restantes : {len(cleaned_mapping)}")
    print(f"-> Les tags supprimés seront recalculés hiérarchiquement lors du prochain passage de l'indexer.")
