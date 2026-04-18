import json
import urllib.request
import urllib.parse
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

TAG_LIST_FILE = "d:/Users/Gehiks/Documents/Applis/IndexationLivres/tag_list.json"
canonical_tags = load_json(TAG_LIST_FILE, [])
canonical_lower_map = {t.lower(): t for t in canonical_tags}

def search_wikidata_entity(term):
    try:
        url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={urllib.parse.quote(term)}&language=en&format=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Antigravity_Research/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data.get('search'):
                return data['search'][0]['id'], data['search'][0].get('label'), data['search'][0].get('description')
    except Exception as e:
        print(f"Error searching {term}: {e}")
    return None, None, None

def get_wikidata_parents(qid):
    # Modified query to potentially imply depth or reachability
    query = f"""
    SELECT ?parent ?parentLabel WHERE {{
      wd:{qid} (wdt:P279|wdt:P31)+ ?parent.
      ?parent rdfs:label ?parentLabel.
      FILTER(LANG(?parentLabel) = "en")
    }}
    """
    try:
        url = f"https://query.wikidata.org/sparql?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Antigravity_Research/1.0', 'Accept': 'application/sparql-results+json'})
        parents = []
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            for item in data.get('results', {}).get('bindings', []):
                parents.append((item['parent']['value'].split('/')[-1], item['parentLabel']['value']))
        return parents
    except Exception as e:
        print(f"Error getting parents for {qid}: {e}")
        return []

terms = ["pandemic", "hnsw", "deep learning", "chatgpt"]
for term in terms:
    print(f"\n--- Testing term: {term} ---")
    qid, label, desc = search_wikidata_entity(term)
    if qid:
        print(f"Found QID: {qid} ({label}) - {desc}")
        parents = get_wikidata_parents(qid)
        found_hits = []
        for pqid, plabel in parents:
            if plabel.lower() in canonical_lower_map:
                found_hits.append(plabel)
        
        print(f"Hits found in canonical tags: {found_hits}")
    else:
        print("Not found on Wikidata")
