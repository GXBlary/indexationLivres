import json
import os
import time
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.append('.')
from indexer import align_single_tag, TAG_MAPPING_FILE, load_json, save_json, tag_mapping

def enrich_tag(tag_lower):
    try:
        current_val = tag_mapping.get(tag_lower, "")
        if "." in current_val:
            return False # Déjà riche
            
        new_hierarchy = align_single_tag(tag_lower)
        return new_hierarchy and new_hierarchy != current_val
    except Exception as e:
        # print(f"Error on {tag_lower}: {e}")
        return False

def fast_enrich():
    print(f"-> Démarrage de l'enrichissement parallèle (focus sur tags plats)...")
    keys = [k for k, v in tag_mapping.items() if "." not in v]
    total = len(keys)
    print(f"-> {total} tags sans hiérarchie à vérifier.")
    
    updated_count = 0
    start_time = time.time()
    
    # On utilise 3 threads pour respecter la limitation 15RPM (gemini free tier) / requêtes Wikidata.
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(enrich_tag, keys))
        updated_count = sum(1 for r in results if r)

    save_json(TAG_MAPPING_FILE, tag_mapping)
    duration = time.time() - start_time
    print(f"\n-> Enrichissement terminé en {duration:.1f}s !")
    print(f"   Tags mis à jour : {updated_count}")
    print(f"   Total dans le cache : {len(tag_mapping)}")

if __name__ == "__main__":
    fast_enrich()
