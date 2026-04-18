import sys
import json
import time
sys.path.append('.')
from indexer import align_single_tag, TAG_MAPPING_FILE, load_json, save_json, tag_mapping

def test_enrichment_small():
    print("-> Test d'enrichissement sur 10 tags...")
    keys = sorted(tag_mapping.keys())[:10]
    
    for k in keys:
        old_val = tag_mapping[k]
        print(f"Indexation de '{k}' (actuel: {old_val})...")
        new_val = align_single_tag(k)
        print(f"   => Résultat: {new_val}")
        if new_val != old_val:
            print(f"   [!] MISE À JOUR DÉTECTÉE : {old_val} -> {new_val}")
            tag_mapping[k] = new_val
            
    save_json(TAG_MAPPING_FILE, tag_mapping)
    print("-> Test terminé et sauvegardé.")

if __name__ == "__main__":
    test_enrichment_small()
