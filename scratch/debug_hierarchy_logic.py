import sys
import json
sys.path.append('.')
from indexer import get_wikidata_ancestors, search_wikidata_entity, canonical_lower_map

WIKIDATA_ROOTS = {
    "science", "technology", "engineering", "mathematics", "business", 
    "management", "artificial intelligence", "society", "philosophy", 
    "economics", "environment", "history", "medicine", "communication"
}

def debug_tag(tag):
    print(f"--- Debugging: {tag} ---")
    qid = search_wikidata_entity(tag)
    print(f"QID: {qid}")
    if not qid: return
    
    ancestors = get_wikidata_ancestors(qid)
    print(f"Ancestors found: {len(ancestors)}")
    
    path_segments = []
    for anc in ancestors:
        label_lower = anc['label'].lower()
        is_canonical = label_lower in canonical_lower_map
        is_root = label_lower in WIKIDATA_ROOTS
        
        if is_canonical or is_root:
            print(f"  [HIT] {anc['label']} (Distance: {anc['distance']}, Canonical: {is_canonical}, Root: {is_root})")
            canonical_label = canonical_lower_map.get(label_lower, anc['label'].title())
            if canonical_label not in path_segments:
                path_segments.append(canonical_label)
        else:
            # print(f"  [skip] {anc['label']}")
            pass
            
    print(f"Final Path segments: {path_segments}")
    hierarchy = ".".join(path_segments)
    print(f"Resulting Hierarchy: {hierarchy}")

if __name__ == "__main__":
    debug_tag("Machine Learning")
    debug_tag("Artificial Intelligence")
    debug_tag("Deep Learning")
    debug_tag("reinforcement learning")
