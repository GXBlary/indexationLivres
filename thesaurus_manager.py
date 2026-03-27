import json
import os
import re
import spacy
import subprocess
import sys
import time
import ollama
import math

# Use the same configuration as the main scripts
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"
EMBED_MODEL = "nomic-embed-text"

def cosine_similarity(v1, v2):
    dot = sum(x*y for x, y in zip(v1, v2))
    n1 = sum(x*x for x in v1)
    n2 = sum(x*x for x in v2)
    if n1 == 0 or n2 == 0: return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))

class VectorAnchor:
    def __init__(self, embed_model=EMBED_MODEL):
        self.model = embed_model
        self.ontology_vectors = {}
        
    def index_ontology(self, concepts):
        if not concepts: return
        print(f"-> [Vector Anchoring] Indexation mathématique de {len(concepts)} concepts...")
        for c in concepts:
            c_clean = str(c).strip()
            if not c_clean: continue
            try:
                res = ollama.embeddings(model=self.model, prompt=c_clean)
                self.ontology_vectors[c_clean] = res['embedding']
            except Exception as e:
                print(f"   [ERREUR Embedding] {e}")
                self.ontology_vectors = {}
                return
                
    def resolve(self, raw_entity, threshold=0.91):
        if not self.ontology_vectors: return raw_entity, 0.0
        try:
            res = ollama.embeddings(model=self.model, prompt=raw_entity)
            emb = res['embedding']
            best_score = -1.0
            best_match = raw_entity
            for concept, ref_emb in self.ontology_vectors.items():
                score = cosine_similarity(emb, ref_emb)
                if score > best_score:
                    best_score = score
                    best_match = concept
            return (best_match, best_score) if best_score >= threshold else (raw_entity, best_score)
        except: return raw_entity, 0.0

def flat_merge(target, source):
    """Fusionne un dictionnaire source plat dans le dictionnaire cible (T-Box)."""
    if isinstance(source, dict):
        for k, v in source.items():
            if k in target and isinstance(target[k], list):
                if isinstance(v, list):
                    clean_terms = [str(x).title() for x in v]
                    target[k].extend(clean_terms)
                elif isinstance(v, str):
                    target[k].append(str(v).title())
                # Déduplication
                target[k] = sorted(list(set(target[k])))
    return target

def run_advanced_cleanup():
    print("\n=================================================================")
    print("   EXÉCUTION DU NETTOYAGE AVANCÉ DU THESAURUS (V6 HYBRID)")
    print("=================================================================")
    
    if not os.path.exists(KEYWORDS_FILE):
        print(f"-> Erreur : {KEYWORDS_FILE} introuvable.")
        return
        
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"-> Erreur lecture thesaurus: {e}")
        return
        
    uncategorized = data.get("Uncategorized_New", [])
    if not uncategorized:
        print("-> Aucun terme 'Uncategorized_New' à nettoyer.")
        return
        
    print(f"-> Traitement de {len(uncategorized)} termes orphelins...")
    
    # 1. Nettoyage Python Deterministe
    cleaned_terms = set()
    for t in uncategorized:
        raw_val = re.sub(r'\(.*?\)', '', str(t)).strip()
        parts = re.split(r'\s+and\s+|\s+or\s+', raw_val, flags=re.IGNORECASE)
        for part in parts:
            term = part.strip()
            if not term or len(term.split()) > 5 or bool(re.match(r'^\d', term)): continue
            cleaned_terms.add(term)
    
    # 2. Filtrage NLP (spaCy)
    try:
        nlp = spacy.load("en_core_web_sm")
        nlp_filtered = set()
        for term in cleaned_terms:
            doc = nlp(term.lower())
            if not any(token.pos_ in ["VERB", "AUX"] for token in doc):
                lemma_tokens = [t.lemma_ if t.tag_ in ["NNS", "NNPS"] else t.text for t in doc]
                nlp_filtered.add(" ".join(lemma_tokens).title())
        terms_to_route = list(nlp_filtered)
    except:
        terms_to_route = list({t.title() for t in cleaned_terms})

 # 3. Ancrage Vectoriel FAISS (Architecture Plate)
    anchor = VectorAnchor()
    top_cats = [k for k in data.keys() if k not in ["Uncategorized_New", "Predicates", "Entities"]]
    
    # Création d'une carte plate { "Concept_existant": "Catégorie_Racine" }
    flat_ontology_map = {}
    for root in top_cats:
        for term in data.get(root, []):
            flat_ontology_map[term] = root
            
    anchor.index_ontology(list(flat_ontology_map.keys()))
    
    slm_fallback = []
    auto_routed = 0
    for term in terms_to_route:
        best_match, score = anchor.resolve(term, threshold=0.91)
        if best_match != term: 
            # On retrouve la racine du concept maté et on y ajoute le nouveau terme
            target_root = flat_ontology_map[best_match]
            data[target_root].append(term)
            data[target_root] = sorted(list(set(data[target_root])))
            auto_routed += 1
        else:
            slm_fallback.append(term)
    
    print(f"-> {auto_routed} termes auto-catégorisés par FAISS.")
    
    # 4. Batch SLM (Qwen) avec Contrainte Stricte
    if slm_fallback:
        print(f"-> {len(slm_fallback)} termes complexes envoyés au SLM...")
        batch_size = 50
        failed = []
        for i in range(0, len(slm_fallback), batch_size):
            batch = slm_fallback[i:i+batch_size]
            prompt = f"""Categorize these Title Case English keywords strictly under the following top-level categories: {json.dumps(top_cats)}. 
CRITICAL RULES:
1. Output MUST be a FLAT JSON dictionary where keys are the categories and values are arrays of strings.
2. NO deep hierarchy. NO sub-dictionaries.
Keywords to categorize: {json.dumps(batch)}"""
            try:
                res = ollama.chat(model=MODEL_NAME, format='json', messages=[{'role': 'user', 'content': prompt}])
                flat_merge(data, json.loads(res['message']['content']))
            except Exception as e: 
                print(f"   [WARNING] Échec du batch LLM : {e}")
                failed.extend(batch)
                
        data["Uncategorized_New"] = sorted(list(set(failed)))
    else:
        data["Uncategorized_New"] = []

    # Sauvegarde directe sans la fonction récursive complexe
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("-> [SUCCESS] Nettoyage V6 terminé (Taxonomie Plate garantie).")

if __name__ == "__main__":
    run_advanced_cleanup()
