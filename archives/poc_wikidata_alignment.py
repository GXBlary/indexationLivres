import requests
import time
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# =========================================================================
# DONNÉES DE TEST
# =========================================================================

# 12 Racines issues de votre dernière exécution
ROOT_CATEGORIES = [
    'Digital Transformation', 'Innovation', 'Ambidexterity', 'Governance', 
    'Risk Management', 'Agentic Ai', 'Business Model', 'Compliance', 
    'Strategic Alignment', 'Engagement', 'Generative Ai', 'Operational Efficiency'
]

# 5 Outliers très distincts issus de votre thesaurus.json
TEST_OUTLIERS = [
    "Adversarial Attack",
    "Fuzzy Set",
    "Bullshit Job Phenomenon",
    "3D Print",
    "Quantum Probability"
]

# =========================================================================
# MOTEUR WIKIDATA & SPARQL
# =========================================================================

# User-Agent obligatoire pour ne pas être bloqué par l'API Wikimedia
HEADERS = {"User-Agent": "OntologyAlignmentPoC/1.0 (contact@local.dev)"}

def search_wikidata_q_id(term: str):
    """Étape 1 : Réconciliation - Trouve l'ID Q officiel pour un terme textuel."""
    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": term,
        "language": "en",
        "format": "json",
        "limit": 1
    }
    try:
        response = requests.get(url, params=params, headers=HEADERS).json()
        if response.get('search'):
            return response['search'][0]['id'], response['search'][0]['label']
    except Exception as e:
        print(f"Erreur API Search: {e}")
    return None, None

def get_wikidata_parents(q_id: str):
    """
    Étape 2 : Ascension Hiérarchique (Depth 1 to 2)
    Utilise SPARQL pour récupérer les concepts parents (instance of P31, subclass of P279 ou part of P361)
    à une profondeur maximale de 2 sauts.
    """
    url = "https://query.wikidata.org/sparql"
    
    # Correction SPARQL 1.1 : Utilisation de '/' (suivi de) et '?' (optionnel)
    # Intégration de P31 (Nature de l'élément / Instance of)
    query = f"""
    SELECT DISTINCT ?parentLabel WHERE {{
      wd:{q_id} (wdt:P31|wdt:P279|wdt:P361)/(wdt:P31|wdt:P279|wdt:P361)? ?parent .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT 50
    """
    
    sparql_headers = {
        "User-Agent": "OntologyAlignmentPoC/1.2 (contact@local.dev)",
        "Accept": "application/sparql-results+json"
    }
    
    params = {"query": query}
    
    try:
        response = requests.get(url, params=params, headers=sparql_headers)
        
        if response.status_code != 200:
            print(f"   [ERREUR HTTP {response.status_code}] Wikidata a bloqué la requête.")
            return []
            
        data = response.json()
        bindings = data.get('results', {}).get('bindings', [])
        
        # Extraction propre : on exclut les labels qui remontent sous forme d'ID Q bruts (non traduits)
        parents = [
            b['parentLabel']['value'] 
            for b in bindings 
            if 'parentLabel' in b and not b['parentLabel']['value'].startswith('Q')
        ]
        return parents
        
    except Exception as e:
        print(f"Erreur de traitement SPARQL: {e}")
        return []

# =========================================================================
# PIPELINE DE TEST
# =========================================================================

def run_poc():
    print("-> Chargement du modèle vectoriel (all-MiniLM-L6-v2)...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    print("-> Vectorisation des racines locales...")
    root_embeddings = model.encode(ROOT_CATEGORIES)
    
    SIMILARITY_THRESHOLD = 0.55 # Seuil d'acceptation du pont
    
    print("\n" + "="*50)
    print(" DÉBUT DU TEST D'ALIGNEMENT WIKIDATA")
    print("="*50 + "\n")
    
    for outlier in TEST_OUTLIERS:
        print(f"🎯 Traitement de l'Outlier : '{outlier}'")
        
        # 1. Résolution
        q_id, official_label = search_wikidata_q_id(outlier)
        if not q_id:
            print(f"   [ÉCHEC] Aucun concept Wikidata trouvé.\n")
            continue
            
        print(f"   [LINK] Connecté à Wikidata : {official_label} ({q_id})")
        
        # Pause de courtoisie pour l'API publique
        time.sleep(1) 
        
        # 2. Ascension
        parents = get_wikidata_parents(q_id)
        if not parents:
            print(f"   [ÉCHEC] Aucun parent trouvé à profondeur 2.\n")
            continue
            
        print(f"   [PATH] {len(parents)} parents/grands-parents trouvés (ex: {', '.join(parents[:3])}...)")
        
        # 3. Intersection Vectorielle
        parent_embeddings = model.encode(parents)
        similarity_matrix = cosine_similarity(parent_embeddings, root_embeddings)
        
        # Trouver la meilleure correspondance globale
        best_parent_idx, best_root_idx = np.unravel_index(np.argmax(similarity_matrix), similarity_matrix.shape)
        best_score = similarity_matrix[best_parent_idx, best_root_idx]
        
        if best_score >= SIMILARITY_THRESHOLD:
            bridging_parent = parents[best_parent_idx]
            target_root = ROOT_CATEGORIES[best_root_idx]
            print(f"   [SUCCÈS] Pont établi vers '{target_root}' (Score: {best_score:.2f})")
            print(f"   [LOGIQUE] {outlier} -> est lié à -> {bridging_parent} -> correspond vectoriellement à -> {target_root}\n")
        else:
            print(f"   [REJET] Aucun parent ne correspond à vos catégories (Meilleur score: {best_score:.2f}). Reste un Outlier absolu.\n")

if __name__ == "__main__":
    run_poc()