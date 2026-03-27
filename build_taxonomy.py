import json
import os
import re
import spacy
import numpy as np
import ollama
from tqdm import tqdm
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_FILE = os.path.join(SCRIPT_DIR, "resumes.json")
THESAURUS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
CACHE_FILE = os.path.join(SCRIPT_DIR, "concepts_cache.json")

MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"

IT_VOCAB_EXCEPTIONS = {
    "data": "data",
    "cyber": "cyber",
    "ai": "ai",
    "genai": "genai",
    "ml": "ml",
    "it": "it",
    "saas": "saas",
    "iot": "iot",
    "agentic": "agentic"
}

# =========================================================================
# PHASE 1 & 2 : EXTRACTION ET NETTOYAGE
# =========================================================================

def extract_concepts_from_resumes(resumes_path: str) -> set[str]:
    with open(resumes_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    all_concepts = set()
    print("-> [Phase 1] Extracting concepts from resumes via LLM...")
    for title, summary in tqdm(data.items(), total=len(data)):
        prompt = f"Extract 3 to 7 high-value technical concepts from: {title}\n{summary}"
        try:
            res = ollama.chat(
                model=MODEL_NAME, 
                messages=[{"role": "user", "content": prompt}], 
                format={'type': 'object', 'properties': {'concepts': {'type': 'array', 'items': {'type': 'string'}}}}
            )
            parsed = json.loads(res['message']['content'])
            for c in parsed.get('concepts', []): 
                all_concepts.add(c.lower().strip())
        except Exception: 
            pass
    return all_concepts

def clean_and_normalize(concepts: set[str]) -> list[str]:
    print("-> [Phase 2] Cleaning and normalizing with protected IT rules...")
    nlp = spacy.load("en_core_web_sm")
    cleaned = set()
    
    for c in tqdm(concepts):
        doc = nlp(c)
        normalized_tokens = []
        for t in doc:
            token_lower = t.text.lower()
            if token_lower in IT_VOCAB_EXCEPTIONS:
                normalized_tokens.append(IT_VOCAB_EXCEPTIONS[token_lower])
            else:
                normalized_tokens.append(t.lemma_)
        
        normalized_concept = " ".join(normalized_tokens).title()
        word_count = len(normalized_concept.split())
        if 0 < word_count <= 4 and len(normalized_concept) > 2:
            cleaned.add(normalized_concept)
            
    return sorted(list(cleaned))

# =========================================================================
# PHASE 3 : SEMANTIC GRAVITY CLUSTERING (V3.1 - Avec Quarantaine)
# =========================================================================

def run_semantic_gravity_clustering(resumes: dict, concepts: list, num_roots=12, min_cluster_size=3):
    print("-> [Phase 3] Semantic Gravity Clustering with Outlier Quarantine...")
    summaries = list(resumes.values())
    
    OUTLIER_THRESHOLD = 0.40
    OUTLIER_KEY = "Outliers / Niche Concepts"

    # 1. Calcul de la Fréquence Documentaire (DF)
    print("   - Calculating Document Frequencies...")
    df_scores = np.zeros(len(concepts))
    for c_idx, c in enumerate(tqdm(concepts)):
        base_term = re.escape(c.lower())
        flexible_pattern = re.compile(r'\b' + base_term + r'(?:s|es|d|ed|ing)?\b')
        count = sum(1 for s in summaries if flexible_pattern.search(s.lower()))
        df_scores[c_idx] = count

    # 2. Vectorisation Sémantique et Densité
    print("   - Generating Semantic Embeddings (using local all-MiniLM-L6-v2)...")
    local_model_path = os.path.join(os.path.dirname(__file__), "models", "all-MiniLM-L6-v2")
    
    if os.path.exists(local_model_path):
        model = SentenceTransformer(local_model_path)
    else:
        print(f"   - [WARNING] Local model not found at {local_model_path}, falling back to Hub...")
        model = SentenceTransformer('all-MiniLM-L6-v2')
    
    embeddings = model.encode(concepts, show_progress_bar=True)
    sim_matrix = cosine_similarity(embeddings)
    
    density_scores = np.sum(sim_matrix > 0.6, axis=1)

    # 3. Élection des Racines (Roots)
    gravity_scores = df_scores * density_scores
    top_indices = np.argsort(gravity_scores)[::-1]
    
    roots_idx = []
    for idx in top_indices:
        if df_scores[idx] == 0: continue
        
        is_distinct = True
        for r_idx in roots_idx:
            # CORRECTION 1 : Seuil abaissé à 0.60 pour éviter les racines redondantes
            if sim_matrix[idx, r_idx] > 0.60: 
                is_distinct = False
                break
        if is_distinct:
            roots_idx.append(idx)
        if len(roots_idx) == num_roots:
            break

    roots = [concepts[i] for i in roots_idx]
    print(f"   - Selected Roots: {roots}")

    # 4. Affiliation par Similarité Cosinus (Avec Seuil d'Exclusion)
    clusters = defaultdict(list)
    root_embeddings = embeddings[roots_idx]

    for c_idx, c in enumerate(concepts):
        if c_idx in roots_idx:
            clusters[concepts[c_idx]].append(c)
            continue
        
        sims_to_roots = cosine_similarity([embeddings[c_idx]], root_embeddings)[0]
        best_root_idx = np.argmax(sims_to_roots)
        best_sim = sims_to_roots[best_root_idx]
        
        # CORRECTION 2 : Mise en quarantaine si trop éloigné sémantiquement
        if best_sim >= OUTLIER_THRESHOLD:
            clusters[roots[best_root_idx]].append(c)
        else:
            clusters[OUTLIER_KEY].append(c)

    # 5. Nettoyage Curatif (Absorption des Singletons et Re-filtrage)
    valid_clusters = defaultdict(list)
    orphans_to_reassign = []

    for root, members in clusters.items():
        if root == OUTLIER_KEY:
            valid_clusters[OUTLIER_KEY].extend(members)
            continue
            
        if len(members) < min_cluster_size:
            orphans_to_reassign.extend(members)
        else:
            valid_clusters[root] = members

    if orphans_to_reassign and valid_clusters:
        valid_roots = [k for k in valid_clusters.keys() if k != OUTLIER_KEY]
        if valid_roots:
            valid_root_idx = [concepts.index(r) for r in valid_roots]
            valid_root_embeddings = embeddings[valid_root_idx]

            for o in orphans_to_reassign:
                o_idx = concepts.index(o)
                sims = cosine_similarity([embeddings[o_idx]], valid_root_embeddings)[0]
                best_root_idx = np.argmax(sims)
                best_sim = sims[best_root_idx]
                
                # CORRECTION 3 : Second contrôle lors de la réaffectation
                if best_sim >= OUTLIER_THRESHOLD:
                    valid_clusters[valid_roots[best_root_idx]].append(o)
                else:
                    valid_clusters[OUTLIER_KEY].append(o)
        else:
            valid_clusters[OUTLIER_KEY].extend(orphans_to_reassign)

    # Tri final pour la lisibilité
    for k in valid_clusters:
        valid_clusters[k] = sorted(list(set(valid_clusters[k])))

    return dict(valid_clusters)

# =========================================================================
# EXÉCUTION DU PIPELINE
# =========================================================================

def run_pipeline():
    with open(RESUMES_FILE, 'r', encoding='utf-8') as f: 
        resumes = json.load(f)
    
    # N'oubliez pas de supprimer le cache corrompu avant le premier run !
    if os.path.exists(CACHE_FILE):
        print(f"-> Loading concepts from {CACHE_FILE}")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f: 
            cleaned_concepts = json.load(f)
    else:
        raw = extract_concepts_from_resumes(RESUMES_FILE)
        cleaned_concepts = clean_and_normalize(raw)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f: 
            json.dump(cleaned_concepts, f)
    
    taxonomy = run_semantic_gravity_clustering(resumes, cleaned_concepts, num_roots=12, min_cluster_size=3)
    
    with open(THESAURUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(taxonomy, f, indent=4, ensure_ascii=False)
    print(f"-> [SUCCESS] Flat Taxonomy saved to {THESAURUS_FILE}")

if __name__ == "__main__":
    run_pipeline()