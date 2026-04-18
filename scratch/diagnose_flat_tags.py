import sys
import json
import urllib.request
import urllib.parse
import time

sys.path.append('.')
from indexer import search_wikidata_entity, get_wikidata_ancestors, canonical_lower_map

def debug_wikidata(tag):
    print(f"\n--- Investigating: '{tag}' ---")
    
    # 1. Search Entity
    print(f"Searching entity for '{tag}'...")
    url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={urllib.parse.quote(tag)}&language=en&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'JunoDoc_Pipeline/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if not data.get('search'):
                print("!! No Wikidata search result.")
                return
            
            top_hit = data['search'][0]
            qid = top_hit['id']
            label = top_hit.get('label', 'N/A')
            desc = top_hit.get('description', 'N/A')
            print(f"Top Hit: {qid} ({label}) - {desc}")
    except Exception as e:
        print(f"!! Search API Error: {e}")
        return

    # 2. Get Ancestors
    print(f"Fetching ancestors for {qid}...")
    ancestors = get_wikidata_ancestors(qid)
    print(f"Total ancestors found: {len(ancestors)}")
    
    if not ancestors:
        print("!! Ancestors list is empty. (Possible timeout or no parent relationships)")
        return

    hits = []
    roots = {
        "science", "technology", "engineering", "mathematics", "business", 
        "management", "artificial intelligence", "society", "philosophy", 
        "economics", "environment", "history", "medicine", "communication",
        "art", "law", "education", "computing", "psychology", "biology",
        "physics", "chemistry", "geography", "politics", "culture", "industry"
    }
    
    for a in ancestors:
        lbl = a['label'].lower()
        if lbl in canonical_lower_map or lbl in roots:
            hits.append(f"{a['label']} (dist: {a['distance']})")
    
    if hits:
        print(f"Potential Hierarchy Hits: {', '.join(hits)}")
    else:
        print("!! No hits in canonical tags or roots.")
        print("Sample raw ancestors (first 5):")
        for a in ancestors[:5]:
            print(f"  - {a['label']} ({a['id']})")

if __name__ == "__main__":
    tags = ['reinforcement learning', 'agentic framework', 'enterprise-grade systems', 'multimodal rag']
    for t in tags:
        debug_wikidata(t)
        time.sleep(1) # Be nice
