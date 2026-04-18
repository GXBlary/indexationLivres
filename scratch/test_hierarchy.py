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

def get_wikidata_ancestors_with_depth(qid):
    # This query finds ancestors and their distance from the entity
    # We use a trick: count the number of P279/P31 hops
    # Note: Wikidata is a DAG, so we might have multiple paths. 
    # For a simple hierarchy string, we'll pick the path through the "most important" parents.
    query = f"""
    SELECT ?parent ?parentLabel (COUNT(?mid) AS ?distance) WHERE {{
      wd:{qid} (wdt:P279|wdt:P31)* ?mid .
      ?mid (wdt:P279|wdt:P31)+ ?parent .
      ?parent rdfs:label ?parentLabel .
      FILTER(LANG(?parentLabel) = "en")
    }}
    GROUP BY ?parent ?parentLabel
    ORDER BY ?distance
    """
    try:
        url = f"https://query.wikidata.org/sparql?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Antigravity_Research/1.0', 'Accept': 'application/sparql-results+json'})
        ancestors = []
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            for item in data.get('results', {}).get('bindings', []):
                ancestors.append({
                    'id': item['parent']['value'].split('/')[-1],
                    'label': item['parentLabel']['value'],
                    'distance': int(item['distance']['value'])
                })
        return ancestors
    except Exception as e:
        print(f"Error getting ancestors for {qid}: {e}")
        return []

def build_hierarchy(tag):
    qid, label, desc = search_wikidata_entity(tag)
    if not qid:
        return tag.title()
    
    ancestors = get_wikidata_ancestors_with_depth(qid)
    # Sort by distance (furthest first to build the root-to-leaf string)
    # But wait, we want the path. 
    # Let's keep only ancestors that are in canonical_tags
    hits = []
    for anc in ancestors:
        if anc['label'].lower() in canonical_lower_map:
            hits.append(canonical_lower_map[anc['label'].lower()])
    
    # Simple deduplication while preserving order (distance)
    unique_hits = []
    for h in hits:
        if h not in unique_hits:
            unique_hits.append(h)
            
    # Add the tag itself at the end if it's not already there
    tag_standardized = label if label else tag.title()
    if tag_standardized not in unique_hits:
        unique_hits.append(tag_standardized)
        
    return ".".join(unique_hits)

terms = ["Cybernetics", "Philosophy", "Deep Learning", "Machine Learning"]
for term in terms:
    print(f"\n--- Hierarchy for: {term} ---")
    hierarchy = build_hierarchy(term)
    print(f"Result: {hierarchy}")
