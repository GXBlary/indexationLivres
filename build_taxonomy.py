import json
import os
import re
import spacy
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
import ollama
from tqdm import tqdm
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_FILE = os.path.join(SCRIPT_DIR, "resumes.json")
THESAURUS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
CACHE_FILE = os.path.join(SCRIPT_DIR, "concepts_cache.json")

MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"

DOMAIN_STOP_WORDS = [
    # Bruit structurel identifié dans les tests
    'paper', 'study', 'highlights', 'based', 'research', 'approach', 'analysis', 'key', 'model', 'results', 'data', 'ai', '10', '2025', 'doi',
    # Lexique de publication académique
    'article', 'author', 'literature', 'review', 'focus', 'propose', 'discuss', 'show', 'aim', 'examine', 'context', 'provide', 'include', 'abstract', 'summary', 'conclusion', 'section', 'chapter', 'figure', 'table', 'methodology', 'framework',
    # Tics de langage typiques des résumés LLM
    'report', 'overview', 'insight', 'explore', 'present', 'demonstrate', 'highlight', 'outline', 'findings', 'impact', 'use', 'case', 'application', 'important', 'significant'
]

IT_VOCAB_EXCEPTIONS = {
    "data": "data",
    "cyber": "cyber",
    "ai": "ai",
    "genai": "genai",
    "ml": "ml",
    "it": "it",
    "saas": "saas",
    "iot": "iot",
    "agentic": "agentic" # Protège contre les déformations type "Argentic"
}

# =========================================================================
# UTILITIES
# =========================================================================

def label_cluster(concepts_in_cluster):
    """Find the most representative label for a cluster."""
    if not concepts_in_cluster: return "Empty"
    if len(concepts_in_cluster) == 1: return concepts_in_cluster[0]
    word_freq = defaultdict(int)
    for c in concepts_in_cluster:
        for word in c.lower().split(): word_freq[word] += 1
    best_score = -1
    best_label = concepts_in_cluster[0]
    for c in concepts_in_cluster:
        words = c.lower().split()
        score = sum(word_freq[w] for w in words) / max(len(words), 1)
        length_bonus = 1.0 / max(len(words), 1)
        total = score + length_bonus * 2
        if total > best_score:
            best_score = total
            best_label = c
    return best_label

# =========================================================================
# CLUSTERING ENGINES (APPROACH E)
# =========================================================================

def run_hybrid_clustering(resumes, concepts, n_topics=8, n_sub_clusters=4):
    """Approach C: LDA for root, HAC for subcategories."""
    summaries = list(resumes.values())
    from sklearn.feature_extraction import text
    stop_words = list(text.ENGLISH_STOP_WORDS.union(DOMAIN_STOP_WORDS))
    
    # 1. LDA Roots
    count_vec = CountVectorizer(max_df=0.85, min_df=2, stop_words=stop_words)
    dtm = count_vec.fit_transform(summaries)
    lda = LatentDirichletAllocation(n_components=n_topics, random_state=42)
    doc_topics = lda.fit_transform(dtm)
    feature_names = count_vec.get_feature_names_out()
    
    topic_labels = {}
    for i, weights in enumerate(lda.components_):
        top = [feature_names[idx] for idx in weights.argsort()[-3:][::-1]]
        topic_labels[i] = " / ".join(top).title()
        
    # 2. Assign
    topic_concepts = defaultdict(list)
    for concept in concepts:
        cl = concept.lower()
        best_t, best_s = None, 0
        for d_idx, summ in enumerate(summaries):
            if cl in summ.lower():
                t_id = np.argmax(doc_topics[d_idx])
                if doc_topics[d_idx][t_id] > best_s:
                    best_s = doc_topics[d_idx][t_id]
                    best_t = t_id
        if best_t is None:
            # Fallback overlap
            cw = set(cl.split())
            best_o, best_tf = 0, 0
            for i, weights in enumerate(lda.components_):
                tw = set([feature_names[idx] for idx in weights.argsort()[-20:]])
                ov = len(cw & tw)
                if ov > best_o: best_o, best_tf = ov, i
            best_t = best_tf
        topic_concepts[best_t].append(concept)
        
    # 3. Sub-cluster
    tfidf = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
    taxonomy = {}
    for t_id, members in topic_concepts.items():
        root = topic_labels.get(t_id, f"Topic {t_id}")
        if len(members) > 15:
            sub_X = tfidf.fit_transform(members).toarray()
            hac = AgglomerativeClustering(n_clusters=min(n_sub_clusters, len(members)), linkage='ward')
            lbls = hac.fit_predict(sub_X)
            sub_map = defaultdict(list)
            for i, l in enumerate(lbls): sub_map[l].append(members[i])
            taxonomy[root] = {label_cluster(m): m for m in sub_map.values()}
        else:
            taxonomy[root] = members
    return taxonomy

def run_sequential_clustering(resumes, concepts):
    """Approach E: D Pillars -> C Fallback."""
    print("-> [Phase 3] Building Taxonomy (Sequential D->C)...")
    summaries = list(resumes.values())
    
    # 1. Create Matrix (Concept x Doc)
    matrix = np.zeros((len(concepts), len(summaries)))
    valid_indices = []
    
    for c_idx, c in enumerate(concepts):
        # Création d'une regex flexible pour absorber l'asymétrie morphologique
        base_term = re.escape(c.lower())
        flexible_pattern = re.compile(r'\b' + base_term + r'(?:s|es|d|ed|ing)?\b')
        
        found = False
        for s_idx, s in enumerate(summaries):
            if flexible_pattern.search(s.lower()):
                matrix[c_idx, s_idx] = 1
                found = True
                
        if found: 
            valid_indices.append(c_idx)
    
    filtered_matrix = matrix[valid_indices]
    filtered_concepts = [concepts[i] for i in valid_indices]
    
    # 2. D Pillars (Ancrage documentaire fort)
    hac = AgglomerativeClustering(n_clusters=10, linkage='average', metric='cosine')
    root_labels = hac.fit_predict(filtered_matrix)
    
    root_clusters = defaultdict(list)
    root_indices = defaultdict(list)
    for idx, lbl in enumerate(root_labels):
        root_clusters[lbl].append(filtered_concepts[idx])
        root_indices[lbl].append(idx)
        
    taxonomy = {}
    for r_id, members in root_clusters.items():
        root_lbl = label_cluster(members)
        if len(members) > 15:
            # NOUVEAU : Fragmentation dynamique et équilibrée
            # Calcule un nombre optimal de sous-clusters (environ 1 cluster pour 10 à 15 concepts)
            optimal_k = max(4, len(members) // 12)
            
            sub_matrix = filtered_matrix[root_indices[r_id]]
            # NOUVEAU : Utilisation de 'ward' et 'euclidean' pour casser le "trou noir"
            # Ward pénalise les clusters géants et force une répartition plus homogène
            hac_s = AgglomerativeClustering(n_clusters=optimal_k, linkage='ward', metric='euclidean')
            sub_lbls = hac_s.fit_predict(sub_matrix)
            
            sub_map = defaultdict(list)
            for i, sl in enumerate(sub_lbls): 
                sub_map[sl].append(members[i])
                
            taxonomy[root_lbl] = {label_cluster(m): m for m in sub_map.values()}
        else:
            taxonomy[root_lbl] = members
            
    # 3. Fallback for orphans (Concepts sans correspondance stricte)
    assigned = set()
    def collect(d):
        for k, v in d.items(): 
            if isinstance(v, list): assigned.update(v)
            elif isinstance(v, dict): collect(v)
            
    collect(taxonomy)
    orphans = [c for c in concepts if c not in assigned]
    
    # Monitoring de l'efficacité de l'ancrage
    print(f"   - Pillars: {len(assigned)} concepts. Orphans: {len(orphans)}")
    
    # Traitement LDA dépollué pour le reliquat
    if orphans:
        taxonomy["New / Unmapped Domains"] = run_hybrid_clustering(resumes, orphans)
        
    return taxonomy

# =========================================================================
# PIPELINE
# =========================================================================

def extract_concepts_from_resumes(resumes_path: str) -> set[str]:
    with open(resumes_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    all_concepts = set()
    print("-> [Phase 1] Extracting concepts from resumes...")
    for title, summary in tqdm(data.items(), total=len(data)):
        prompt = f"Extract 3 to 7 high-value technical concepts from: {title}\n{summary}"
        try:
            res = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], format={'type': 'object', 'properties': {'concepts': {'type': 'array', 'items': {'type': 'string'}}}})
            parsed = json.loads(res['message']['content'])
            for c in parsed.get('concepts', []): all_concepts.add(c.lower().strip())
        except Exception: pass
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

def run_pipeline():
    with open(RESUMES_FILE, 'r', encoding='utf-8') as f: resumes = json.load(f)
    
    if os.path.exists(CACHE_FILE):
        print(f"-> Loading concepts from {CACHE_FILE}")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f: cleaned_concepts = json.load(f)
    else:
        raw = extract_concepts_from_resumes(RESUMES_FILE)
        cleaned_concepts = clean_and_normalize(raw)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(cleaned_concepts, f)
    
    # Phase 3: Sequential Clustering
    taxonomy = run_sequential_clustering(resumes, cleaned_concepts)
    
    with open(THESAURUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(taxonomy, f, indent=4, ensure_ascii=False)
    print(f"-> [SUCCESS] Taxonomy saved to {THESAURUS_FILE}")

if __name__ == "__main__":
    run_pipeline()