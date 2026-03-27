import os
import sys
import fitz
import ollama
from pydantic import BaseModel, Field, model_validator
import json
import re
import subprocess
import tkinter as tk
from tkinter import filedialog
import time
import traceback
import math

# =========================================================================
# CONFIGURATION V5 (OPEN IE, PYDANTIC & VECTOR ANCHORING)
# =========================================================================
MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"
EMBED_MODEL = "nomic-embed-text"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
OBSIDIAN_VAULT_PATH = os.path.join(SCRIPT_DIR, "Obsidian_Vault")
GRAPH_EXPORT_FILE = os.path.join(SCRIPT_DIR, "knowledge_graph.json")

CHUNK_CHARS = 10000  # ~2500-3000 tokens
HEADER_PAGES = 5     

# =========================================================================
# L'ONTOLOGIE STRUCTURÉE (ZOD/PYDANTIC MUR)
# =========================================================================
ALLOWED_PREDICATES = ['mentions', 'wrote', 'co-authored', 'uses', 'is_defined_as', 'impacts', 'optimizes', 'regulates']
BANNED_PREDICATES = ['details', 'concerns', 'is_about', 'talks_about', 'explores', 'examines']

class Triplet(BaseModel):
    subject: str = Field(description="The source entity of the relationship (e.g. 'Abdelaziz Joudar', 'Generative AI')")
    predicate: str = Field(description="The action verb of the T-Box (or a very PRECISE new verb if necessary)")
    object: str = Field(description="The target entity of the relationship")
    validation_status: str = Field(default="validated", description="Internal flag, do not generate")
    
    @model_validator(mode='after')
    def flag_unrecognized_predicates(self) -> 'Triplet':
        pred = self.predicate.lower().strip()
        if pred in BANNED_PREDICATES:
            raise ValueError(f"The predicate '{pred}' is blacklisted because its semantic value is too weak.")
            
        if pred not in ALLOWED_PREDICATES:
            self.validation_status = "to_review"
        else:
            self.validation_status = "validated"
            
        self.predicate = pred
        return self

class OpenIEMining(BaseModel):
    title: str = Field(default="Unknown", description="The full title of the document if found in these pages")
    author: str = Field(default="Unknown", description="The primary author if found")
    summary: str = Field(default="No summary", description="A strict abstract of the document in ENGLISH")
    keywords: list[str] = Field(description="The 8 most crucial formal concepts (EN) anchored to the vocabulary")
    triplets: list[Triplet] = Field(description="The complete list of Graph relations for this fragment")

class ChunkMining(BaseModel):
    triplets: list[Triplet] = Field(description="The list of Graph relations found in this fragment")

# =========================================================================
# MOTEUR VECTORIEL (ENTITY RESOLUTION)
# =========================================================================
def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(x*y for x, y in zip(v1, v2))
    n1 = sum(x*x for x in v1)
    n2 = sum(x*x for x in v2)
    if n1 == 0 or n2 == 0: return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))

class VectorAnchor:
    def __init__(self, embed_model=EMBED_MODEL):
        self.model = embed_model
        self.ontology_vectors = {}
        
    def index_ontology(self, concepts: list):
        if not concepts: return
        print(f"-> [Vector Anchoring] Indexation mathématique de {len(concepts)} concepts T-Box...")
        for c in concepts:
            c_clean = str(c).strip()
            if not c_clean: continue
            try:
                res = ollama.embeddings(model=self.model, prompt=c_clean)
                self.ontology_vectors[c_clean] = res['embedding']
            except Exception as e:
                print(f"   [ERREUR Embedding] 'ollama pull {self.model}' requis. L'ancrage est désactivé. ({e})")
                self.ontology_vectors = {}
                return
                
    def resolve(self, raw_entity: str, threshold: float = 0.85) -> tuple[str, float]:
        """Fusionne l'hallucination si elle a une similarité cosinus > 0.85 avec la T-Box."""
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
            
            if best_score >= threshold:
                return best_match, best_score
            return raw_entity, best_score
        except: return raw_entity, 0.0

# =========================================================================
# UTILITAIRES FICHIERS & CALIBRE
# =========================================================================
def ensure_dirs():
    os.makedirs(OBSIDIAN_VAULT_PATH, exist_ok=True)
    for sub in ["Nodes", "Relations"]:
        os.makedirs(os.path.join(OBSIDIAN_VAULT_PATH, sub), exist_ok=True)

def extract_all_strings(data):
    result = set()
    if isinstance(data, dict):
        for key, val in data.items():
            if key != "Predicates":
                result.add(key.strip())
            result.update(extract_all_strings(val))
    elif isinstance(data, list):
        for item in data: result.update(extract_all_strings(item))
    elif isinstance(data, str):
        result.add(data.strip())
    return result

def load_keywords_registry():
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Load Predicates if they exist
                if "Predicates" in data:
                    allowed = data["Predicates"].get("Allowed", [])
                    banned = data["Predicates"].get("Banned", [])
                    if allowed:
                        ALLOWED_PREDICATES.clear()
                        ALLOWED_PREDICATES.extend(allowed)
                    if banned:
                        BANNED_PREDICATES.clear()
                        BANNED_PREDICATES.extend(banned)
                else:
                    data["Predicates"] = {"Allowed": ALLOWED_PREDICATES.copy(), "Banned": BANNED_PREDICATES.copy()}
                    
                return extract_all_strings(data), data
        except Exception as e: print(f"[ERREUR] Registre JSON illisible : {e}")
    return set(), {}

def save_keywords_registry(current_registry, new_keywords, original_data):
    new_ones = [k.strip() for k in new_keywords if k.strip() and k.strip() not in current_registry]
    
    if isinstance(original_data, dict):
        if "Uncategorized_New" not in original_data: original_data["Uncategorized_New"] = []
        original_data["Uncategorized_New"].extend(new_ones)
        original_data["Uncategorized_New"] = sorted(list(set(original_data["Uncategorized_New"])))
        
        # Ensure Predicates are saved
        original_data["Predicates"] = {"Allowed": ALLOWED_PREDICATES, "Banned": BANNED_PREDICATES}
        
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, indent=4, ensure_ascii=False)
    except PermissionError:
        print(f"        -> [WARNING] Impossible d'écrire '{KEYWORDS_FILE}' (fichier ouvert).")
    except Exception as e:
        print(f"        -> [WARNING] Erreur inattendue d'écriture JSON : {e}")
    return current_registry.union(new_ones)

def extract_pdf_content(pdf_path):
    header_text = ""
    body_chunks = []
    
    try:
        doc = fitz.open(pdf_path)
        
        # 1. Extraction de l'En-tête Brut (Titre, Auteur, Abstract)
        for i in range(min(HEADER_PAGES, len(doc))):
            header_text += doc[i].get_text() + "\n"
            
        # 2. Semantic Chunking (Corps du document par blocs/paragraphes)
        current_chunk_blocks = []
        current_chunk_len = 0
        OVERLAP_BLOCKS = 3 # On garde les 3 derniers paragraphes pour le contexte du chunk suivant
        
        for i in range(HEADER_PAGES, len(doc)):
            page = doc[i]
            # get_text("blocks") extrait intelligemment les vrais paragraphes sémantiques (index 4 = texte)
            blocks = page.get_text("blocks")
            
            for b in blocks:
                block_text = str(b[4]).strip() # [x0, y0, x1, y1, texte, block_no, block_type]
                if not block_text: continue
                block_len = len(block_text)
                
                # Le bloc sémantique dépasse le plafond du chunk actuel ?
                if current_chunk_len + block_len > CHUNK_CHARS and current_chunk_blocks:
                    body_chunks.append("\n\n".join(current_chunk_blocks))
                    
                    # On prépare le prochain chunk en conservant le chevauchement (Overlap)
                    overlap_slice = current_chunk_blocks[-OVERLAP_BLOCKS:] if len(current_chunk_blocks) >= OVERLAP_BLOCKS else current_chunk_blocks
                    current_chunk_blocks = overlap_slice + [block_text]
                    current_chunk_len = sum(len(bloc) for bloc in current_chunk_blocks)
                else:
                    current_chunk_blocks.append(block_text)
                    current_chunk_len += block_len
                    
        # Exporter le dernier chunk s'il n'est pas vide
        if current_chunk_blocks:
            body_chunks.append("\n\n".join(current_chunk_blocks))
            
        doc.close()
    except Exception as e:
        print(f"        -> [WARNING] Erreur sémantique lors de l'extraction PDF: {e}")
        
    return header_text, body_chunks

def parse_opf_info(opf_content, file_path):
    id_match = re.search(r'<dc:identifier[^>]*opf:scheme="calibre"[^>]*>([^<]+)</dc:identifier>', opf_content, re.IGNORECASE)
    book_id = id_match.group(1) if id_match else None
    if not book_id:
        parent_dir = os.path.basename(os.path.dirname(file_path))
        f_id = re.search(r'\(([0-9]+)\)$', parent_dir.strip())
        book_id = f_id.group(1) if f_id else None
    author = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', opf_content, re.IGNORECASE)
    title = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf_content, re.IGNORECASE)
    tags = re.findall(r'<dc:subject[^>]*>([^<]+)</dc:subject>', opf_content, re.IGNORECASE)
    return book_id, author.group(1) if author else "Inconnu", title.group(1) if title else "Inconnu", [t.strip() for t in tags if t.strip()]

def save_to_obsidian(book_id, titre, auteur, mots_cles, resume, all_triplets):
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', titre)
    doc_path = os.path.join(OBSIDIAN_VAULT_PATH, "Nodes", f"{safe_title} - {book_id}.md")
    content = f"---\nid: {book_id}\ntitle: \"{titre}\"\nauthors: \"{auteur}\"\ntags: {json.dumps(list(mots_cles))}\n---\n\n# {titre}\n\n## Abstract\n{resume}\n\n## CMDB Relationships\n"
    
    for triplet in all_triplets:
        # Affichage du statut
        statut_md = "" if triplet.validation_status == "validated" else " ⚠️#review"
        content += f"- [[{triplet.subject}]] --{triplet.predicate}--> [[{triplet.object}]]{statut_md}\n"
        
        # Sauvegarde d'un fichier de relation (Edge)
        safe_subject = re.sub(r'[\\/:*?"<>|]', '_', triplet.subject)
        safe_object = re.sub(r'[\\/:*?"<>|]', '_', triplet.object)
        edge_filename = f"{safe_subject} - {triplet.predicate} - {safe_object}.md"
        edge_path = os.path.join(OBSIDIAN_VAULT_PATH, "Relations", edge_filename)
        
        edge_content = f"---\nsource: \"[[{triplet.subject}]]\"\ntarget: \"[[{triplet.object}]]\"\npredicate: \"{triplet.predicate}\"\ndocument: \"[[{safe_title} - {book_id}]]\"\nstatus: \"{triplet.validation_status}\"\n---\n\n# Relation: {triplet.subject} -> {triplet.predicate} -> {triplet.object}\n\nExtracted from document: [[{safe_title} - {book_id}]]\n"
        try:
            with open(edge_path, 'w', encoding='utf-8') as fEdge:
                fEdge.write(edge_content)
        except Exception as eEdge:
            print(f"Erreur d'écriture de la relation: {eEdge}")
            
    try:
        with open(doc_path, 'w', encoding='utf-8') as f: f.write(content)
    except Exception as e: print(f"Erreur d'écriture Obsidian: {e}")

# =========================================================================
# L'ORCHESTRATEUR LLM
# =========================================================================
def ask_llm_pydantic(prompt: str, pydantic_schema, stage_name="LLM"):
    print(f"        -> [{stage_name}] Inférence avec Pydantic Constraint en cours...")
    schema_json = pydantic_schema.model_json_schema()
    
    # Stratégie anti-blocage (jusqu'à 2 essais si Hard-Fail Zod)
    for attempt in range(2):
        try:
            t0 = time.time()
            res = ollama.chat(
                model=MODEL_NAME, 
                messages=[{'role': 'user', 'content': prompt}], 
                format=schema_json, 
                options={'num_ctx': 8192}
            )
            duration = time.time() - t0
            raw_json = res['message']['content']
            
            # Application du Mur Pydantic
            validated_obj = pydantic_schema.model_validate_json(raw_json)
            
            # Affichage métriques
            p_eval = res.get('prompt_eval_count', 0)
            eval_c = res.get('eval_count', 0)
            rate = (eval_c / duration) if duration > 0 else 0
            print(f"           [Métriques] {duration:.1f}s | {rate:.1f} t/s | Lu: {p_eval} t -> Écrit: {eval_c} t")
            
            return validated_obj
            
        except Exception as e:
            print(f"           [Retry {attempt+1}] Hard-Fail intercepté : {e}")
            prompt += f"\n\n!!! ATTENTION, ta réponse précédente a causé l'erreur Pydantic suivante :\n{e}\nCorrige impérativement le prédicat ou le format avant de répondre de nouveau."
            
    return None

def remove_empty_elements(d):
    """Récursivement supprime les dictionnaires ou listes vides."""
    if not isinstance(d, (dict, list)):
        return d
    if isinstance(d, list):
        return [v for v in (remove_empty_elements(v) for v in d) if v is not None and v != "" and v != [] and v != {}]
    if isinstance(d, dict):
        cleaned = {k: remove_empty_elements(v) for k, v in d.items()}
        return {k: v for k, v in cleaned.items() if v is not None and v != "" and v != [] and v != {}}

def deep_merge(target, source):
    """Fusionne récursivement un json généré par le LLM (source) dans le dataset complet (target)."""
    if isinstance(source, dict):
        for k, v in source.items():
            if k not in target:
                if isinstance(v, list): target[k] = []
                elif isinstance(v, dict): target[k] = {}
            
            if isinstance(target.get(k), list) and isinstance(v, list):
                clean_t = [str(x).title() for x in v]
                target[k].extend(clean_t)
                target[k] = sorted(list(set(target[k])))
            elif isinstance(target.get(k), dict) and isinstance(v, dict):
                deep_merge(target[k], v)
    return target

def extract_ontology_keys(d, parent_keys=None):
    if parent_keys is None: parent_keys = []
    keys_map = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, dict):
                keys_map[k] = parent_keys + [k]
                keys_map.update(extract_ontology_keys(v, parent_keys + [k]))
            elif isinstance(v, list):
                keys_map[k] = parent_keys + [k]
    return keys_map

def insert_deep(d, path_list, term):
    current = d
    for i, p in enumerate(path_list):
        if i == len(path_list) - 1:
            if p not in current:
                current[p] = []
            if isinstance(current[p], list):
                current[p].append(term)
                current[p] = sorted(list(set(current[p])))
            elif isinstance(current[p], dict):
                if "General" not in current[p]: current[p]["General"] = []
                current[p]["General"].append(term)
                current[p]["General"] = sorted(list(set(current[p]["General"])))
        else:
            if p not in current:
                current[p] = {}
            current = current[p]

def clean_thesaurus():
    print("\n=================================================================")
    print("   EXÉCUTION DE LA PASSE DE NETTOYAGE DU THESAURUS (DEEP-HYBRID)")
    print("=================================================================")
    
    if not os.path.exists(KEYWORDS_FILE):
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
        
    print(f"-> Nettoyage de {len(uncategorized)} termes sauvages en cours...")
    
    # 1. Nettoyage Python (Deduplication, Parens, Regex, & and/or split)
    cleaned_terms = set()
    for t in uncategorized:
        raw_val = str(t)
        # Supprimer ce qui est entre parenthèses
        raw_val = re.sub(r'\(.*?\)', '', raw_val).strip()
        
        # Split on " and " and " or "
        parts = re.split(r'\s+and\s+|\s+or\s+', raw_val, flags=re.IGNORECASE)
        for part in parts:
            term = part.strip()
            if not term: continue
            if len(term.split()) > 5: continue
            if bool(re.match(r'^\d', term)): continue
            cleaned_terms.add(term) # Will titlecase later
        
    print(f"   [Étape 1] Split & Regex : {len(uncategorized)} -> {len(cleaned_terms)} termes")
    
    # 2. Filtrage NLP (spaCy) : Grammaire et Lemmatisation Strict
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("   -> Installation du modèle spaCy (en_core_web_sm) requise en arrière-plan...")
            subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], capture_output=True)
            nlp = spacy.load("en_core_web_sm")
            
        nlp_filtered = set()
        for term in cleaned_terms:
            # Lowercase avant l'analyse pour que spaCy détecte bien les pluriels communs (NNS) au lieu des Noms Propres (NNP)
            doc = nlp(term.lower())
            has_verb = any(token.pos_ in ["VERB", "AUX"] for token in doc)
            if not has_verb:
                # Lemmatisation des pluriels (NNS, NNPS) vers singulier
                lemma_tokens = []
                for token in doc:
                    if token.tag_ in ["NNS", "NNPS"]:
                        lemma_tokens.append(token.lemma_)
                    else:
                        lemma_tokens.append(token.text)
                
                # Reconstitue et force le Title Case
                lemma_term = " ".join(lemma_tokens).title()
                if lemma_term:
                    nlp_filtered.add(lemma_term)
                
        print(f"   [Étape 2] Filtrage NLP & Lemmatisation (spaCy) : {len(cleaned_terms)} -> {len(nlp_filtered)} termes")
        terms_to_route = list(nlp_filtered)
    except ImportError:
        print("   [Étape 2] Librairie spaCy introuvable. Étape ignorée.")
        terms_to_route = list({t.title() for t in cleaned_terms})

    # 3. Ancrage Vectoriel FAISS Récursif
    print("   [Étape 3] Auto-Catégorisation Vectorielle Strict (Nomic)...")
    anchor = VectorAnchor()
    ontology_map = {}
    
    # Construction récursive de toutes les branches du graphe
    for top_lvl, content in data.items():
        if top_lvl in ["Uncategorized_New", "Predicates", "Entities"]: continue
        if isinstance(content, dict) or isinstance(content, list):
            keys = extract_ontology_keys({top_lvl: content})
            ontology_map.update(keys)
            
    anchor.index_ontology(list(ontology_map.keys()))
    
    slm_fallback = []
    auto_routed = 0
    
    # Seuil extrêmement strict (0.91)
    for term in terms_to_route:
        best_match, score = anchor.resolve(term, threshold=0.91)
        if best_match != term: 
            path_list = ontology_map[best_match]
            insert_deep(data, path_list, term)
            auto_routed += 1
        else:
            slm_fallback.append(term)
            
    print(f"   -> {auto_routed} termes ont été catégorisés mathématiquement (Seuil > 0.91) !")
    
    # 4. Traitement SLM (Ollama Batched)
    if not slm_fallback:
        print("   [Étape 4] Aucun terme isolé restant pour le SLM.")
        data["Uncategorized_New"] = []
    else:
        print(f"   [Étape 4] Traitement des {len(slm_fallback)} termes complexes par Qwen (Batches)...")
        batch_size = 50
        top_cats = [k for k in data.keys() if k not in ["Uncategorized_New", "Predicates", "Entities"]]
        
        failed_terms = []
        for i in range(0, len(slm_fallback), batch_size):
            batch = slm_fallback[i:i+batch_size]
            print(f"      -> Batch SLM [{i+1} à min({i+batch_size}, {len(slm_fallback)})]...")
            
            prompt = f"""Role: Expert Data Architect and Ontologist.
Task: Meticulously process this batch of diverse keywords. 
1. TRANSLATION: You MUST absolutely translate all non-English terms (especially French terms) to English.
2. Ensure everything is Title Case.
3. Categorize them logically under the exact Top-Level Categories provided as root keys.
4. DEEP HIERARCHY: You are allowed to create deeply nested sub-categories (e.g., "Artificial Intelligence" -> "Generative AI" -> "LLMs" -> ["GPT-4", "Claude"]). Do not clump everything in generic arrays. Create precise N-level dictionary structures where appropriate, ending with an array of the leaf keywords.

Allowed Top-Level Categories (MUST be exactly these Root Keys): {json.dumps(top_cats)}

Input Keywords Batch:
{json.dumps(batch)}

Output Constraints:
Output ONLY a valid JSON object matching the exact Top-Level categories as root keys. DO NOT output markdown."""

            try:
                t0 = time.time()
                res = ollama.chat(
                    model=MODEL_NAME, 
                    messages=[
                        {'role': 'system', 'content': 'You must output ONLY valid JSON without markdown wrapping. Your sub-categories must be extremely precise, nested dictionary trees if needed.'},
                        {'role': 'user', 'content': prompt}
                    ], 
                    format='json',
                    options={'num_ctx': 8192, 'temperature': 0.1}
                )
                
                raw_json = res['message']['content']
                slm_parsed = json.loads(raw_json)
                duration = time.time() - t0
                print(f"         [OK] Batch analysé en {duration:.1f}s")
                
                # Fusion des résultats récursifs dans 'data'
                deep_merge(data, slm_parsed)
            except Exception as e:
                print(f"         [ERREUR] Batch échoué : {e}")
                failed_terms.extend(batch)

        data["Uncategorized_New"] = sorted(list(set(failed_terms)))
    
    # Nettoyage final des structures vides générées par le LLM ou vidées par le processus
    data = remove_empty_elements(data)
        
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print("-> Registre thesaurus.json nettoyé et sauvegardé avec succès.")
    except Exception as e:
        print(f"-> Erreur d'écriture finale: {e}")

# =========================================================================
# MAIN PIPELINE
# =========================================================================
def main():
    ensure_dirs()
    print("=================================================================")
    print("   SCRIPT D'INDEXATION V5 (OPEN IE, PYDANTIC & VECTOR ANCHORING) ")
    print("=================================================================\n")
    print("Ce script industrialise votre CMDB dans Neo4j/Obsidian via la structuration Pydantic et FAISS.")
    print("  [1] MODE NOUVEAUX : Ne traite que les documents vierges de mots-clés Calibre.")
    print("  [2] MODE COMPLET  : Retraite absolument l'intégralité de la bibliothèque.\n")
    
    mode = input("Votre choix (1 ou 2) : ").strip()
    root_tk = tk.Tk(); root_tk.withdraw(); root_tk.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(title="Racine Calibre")
    if not folder_path: return

    calibredb_path = r"C:\Program Files\Calibre2\calibredb.exe" if os.path.exists(r"C:\Program Files\Calibre2\calibredb.exe") else "calibredb"
    
    registry_list, original_data = load_keywords_registry()
    
    high_level_categories = [str(k) for k in original_data.keys() if k not in ["Uncategorized_New", "Predicates", "Entities"]]
    entities_data = original_data.get("Entities", {})
    entities_categories = [str(k) for k in entities_data.keys()] if isinstance(entities_data, dict) else []
    registry_str = ", ".join(high_level_categories + ["Entities"] + entities_categories)
    
    # -------------------------------------------------------------
    # ÉTAPE 3 INITIALE : PRÉPARATION DU MOTEUR VECTORIEL
    # -------------------------------------------------------------
    anchor_engine = VectorAnchor()
    anchor_engine.index_ontology(list(registry_list))
    
    # Scan Calibre
    files_to_process = []
    for root, _, files in os.walk(folder_path):
        for fn in files:
            if fn.lower() == 'metadata.opf':
                file_path = os.path.join(root, fn)
                with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
                bid, auth, tit, tags = parse_opf_info(content, file_path)
                pdf_p = next((os.path.join(root, s) for s in files if s.lower().endswith('.pdf')), None)
                if bid and pdf_p and (mode == "2" or not tags):
                    files_to_process.append({'bid': bid, 'auth': auth, 'tit': tit, 'pdf': pdf_p, 'root': root})

    print(f"\n[INFO] {len(files_to_process)} documents à traiter.\n")
    global_kg_db = []
    
    for i, data in enumerate(files_to_process):
        print(f"\n=================================================================")
        print(f"[{i+1}/{len(files_to_process)}] ID={data['bid']} | {data['tit']}")
        print(f"        Extraction du texte PDF (en-tête + suite)...")
        h_text, chunks = extract_pdf_content(data['pdf'])
        
        # -------------------------------------------------------------
        # EXTRACTION HEADER (Titre, Auteur, 8 Keywords, Triplets Initiaux)
        # -------------------------------------------------------------
        prompt_h = f"""You are an Open Information Extraction Orchestrator.
Analyze the first 5 pages of this document.
1/ Extract the exact title and author. Calibre metadata gives us: Title='{data['tit']}', Author='{data['auth']}'. Use these unless the document text strongly suggests otherwise.
2/ Write a condensed abstract in ENGLISH.
3/ Extract ONLY the 8 most critical formal concepts (T-Box) in ENGLISH.
4/ Extract the very first semantic triplets.
Constraint: For triplets, you are strictly FORBIDDEN to use these weak verbs: {BANNED_PREDICATES}. Use preferably: {ALLOWED_PREDICATES}, or very precise new verbs.
Existing vocabulary high-level topics for context: {registry_str}

Text:
{h_text}"""
        
        meta = ask_llm_pydantic(prompt_h, OpenIEMining, stage_name="En-tête (Pages 1-5)")
        if not meta: 
            print("        -> Échec total de l'extraction sur ce fichier.")
            continue
            
        print(f"        -> [DÉTECTÉ] Titre : {meta.title}")
        print(f"        -> [DÉTECTÉ] Auteur : {meta.author}")
        
        all_triplets = meta.triplets
        all_tags = set(meta.keywords)
        
        # -------------------------------------------------------------
        # EXTRACTION CHUNKS (Uniquement des Triplets pour ne pas polluer les tags)
        # -------------------------------------------------------------
        for j, chunk in enumerate(chunks):
            prompt_c = f"""Enrich the Knowledge Graph from this fragment.
Strictly FORBIDDEN to use weak verbs: {BANNED_PREDICATES}.
Favor these strong predicates: {ALLOWED_PREDICATES}.
If possible, link your concepts to existing vocabulary (T-Box) context: {registry_str}

Text:
{chunk}"""
            c_data = ask_llm_pydantic(prompt_c, ChunkMining, stage_name=f"Graphe - Morceau {j+1}/{len(chunks)}")
            if c_data:
                all_triplets.extend(c_data.triplets)
        
        # -------------------------------------------------------------
        # ANCRAGE VECTORIEL (RÉSOLUTION D'ENTITÉS T-BOX)
        # -------------------------------------------------------------
        resolved_triplets = []
        print(f"        -> Ancrage vectoriel des {len(all_triplets)} triplets extraits...")
        for triplet in all_triplets:
            # Threshold de 0.85 (ou 0.82) pour `nomic-embed-text`
            clean_s, _ = anchor_engine.resolve(triplet.subject, threshold=0.82)
            clean_o, _ = anchor_engine.resolve(triplet.object, threshold=0.82)
            triplet.subject = clean_s
            triplet.object = clean_o
            resolved_triplets.append(triplet)
            
        # Résolution vectorielle des mots clés globaux aussi !
        resolved_tags = set()
        for t in all_tags:
            clean_t, _ = anchor_engine.resolve(t, threshold=0.82)
            resolved_tags.add(clean_t)
            
        final_tags = list(resolved_tags)
        
        print(f"        -> Bilan des mots-clés finaux : {final_tags}")
        print(f"        -> Nombre de triplets consolidés pour Neo4j/Obsidian : {len(resolved_triplets)}")
        
        # Sync Calibre
        subprocess.run([calibredb_path, 'set_metadata', '--with-library', folder_path, data['bid'], 
                        '--field', f"title:{meta.title}", '--field', f"authors:{meta.author}",
                        '--field', f"tags:{', '.join(final_tags)}", '--field', f"comments:{meta.summary}"], capture_output=True)
        
        # Sync Obsidian
        save_to_obsidian(data['bid'], meta.title, meta.author, final_tags, meta.summary, resolved_triplets)
        
        # Sync Registry (Seulement les tags ancrés, s'ils sont nouveaux ils sont "Uncategorized_New")
        registry_list = save_keywords_registry(registry_list, final_tags, original_data)
        
        # Update Anchor Engine in memory with new tags to benefit subsequent documents
        anchor_engine.index_ontology(list(registry_list))

        print("        -> Synchronisation terminée [OK]")

    # Passe de Nettoyage LLM à la fin de tous les documents
    clean_thesaurus()

if __name__ == "__main__":
    try:
        main()
        input("\nTerminé. Appuyez sur Entrée pour fermer la fenêtre...")
    except KeyboardInterrupt:
        print("\n\n[INFO] Interruption manuelle (Ctrl+C). Fermeture immédiate.")
    except Exception:
        traceback.print_exc()
        input("\n[ERREUR CRITIQUE] Appuyez sur Entrée pour fermer la fenêtre...")
