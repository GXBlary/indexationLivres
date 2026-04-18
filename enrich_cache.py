import json
import os
import time
import sys

# Ensure we can import from the current directory
sys.path.append('.')
from indexer import align_single_tag, TAG_MAPPING_FILE, load_json, save_json

def enrich_cache():
    print(f"-> Déchargement du cache actuel ({TAG_MAPPING_FILE})...")
    mapping = load_json(TAG_MAPPING_FILE, {})
    total = len(mapping)
    print(f"-> {total} entrées à traiter.")
    
    count = 0
    updated = 0
    
    # Sort keys to have a deterministic order
    keys = sorted(mapping.keys())
    
    for tag_lower in keys:
        count += 1
        current_val = mapping[tag_lower]
        
        # Si c'est déjà une hiérarchie (contient un point), on peut passer 
        # (sauf si on veut tout rafraîchir, mais restons prudents)
        if "." in current_val:
            continue
            
        print(f"[{count}/{total}] Enrichissement de '{tag_lower}' (actuellement: '{current_val}')...")
        
        # On tente de (re)aligner le tag avec la nouvelle logique hiérarchique
        # On utilise le tag_lower d'origine pour la recherche
        try:
            # Note: align_single_tag va automatiquement mettre à jour le cache global 
            # et le fichier via save_json à chaque succès interne, mais on peut le refaire ici.
            new_hierarchy = align_single_tag(tag_lower)
            
            if new_hierarchy and new_hierarchy != current_val:
                updated += 1
                # print(f"      => Nouveau chemin : {new_hierarchy}")
            
            # Petite pause pour éviter de saturer l'API Wikidata
            time.sleep(0.5)
            
        except Exception as e:
            print(f"      !! Erreur sur '{tag_lower}': {e}")
            
        # Sauvegarde de sécurité toutes les 10 itérations (déjà fait par indexer.py mais doublon utile)
        if count % 10 == 0:
            save_json(TAG_MAPPING_FILE, mapping)
            
    print(f"\n-> Enrichissement terminé !")
    print(f"   Tags mis à jour : {updated}")
    print(f"   Total tags dans le cache : {len(mapping)}")

if __name__ == "__main__":
    enrich_cache()
