import json
from indexer import get_wikidata_ancestors, search_wikidata_entity

if __name__ == "__main__":
    t = "Cybernetics"
    qid = search_wikidata_entity(t)
    print(f"QID for {t}: {qid}")
    if qid:
        ancestors = get_wikidata_ancestors(qid)
        print(f"Ancestors found: {len(ancestors)}")
        for anc in ancestors:
            print(f"  {anc['distance']}: {anc['label']} ({anc['id']})")
