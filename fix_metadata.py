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
import requests

# =========================================================================
# CONFIGURATION V6 (OPEN IE, PYDANTIC, VECTOR ANCHORING & WIKIDATA LOD)
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
ALLOWED_PREDICATES = ['mentions', 'wrote', 'co-authored', 'uses', 'is_defined_as', 'impacts', 'optimizes', 'regulates', 'integrates', 'depends_on']
BANNED_PREDICATES = ['details', 'concerns', 'is_about', 'talks_about', 'explores', 'examines']

class Triplet(BaseModel):
    subject: str = Field(description="The source entity of the relationship (e.g. 'Abdelaziz Joudar', 'Generative AI')")
    predicate: str = Field(description="The action verb of the T-Box (or a very PRECISE new verb if necessary)")
    object: str = Field(description="The target entity of the relationship")
    validation_status: str = Field(default="validated", description="Internal flag, do not generate")
    subject_uri: str = Field(default="", description="Wikidata URI if found")
    object_uri: str = Field(default="", description="Wikidata URI if found")
    
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
# WIKIDATA API (RÉCONCILIATION LOD)
# =========================================================================
def search_wikidata_entity(term: str) -> tuple[str, str]:
    """Interroge Wikidata pour trouver le label canonique et l'URI."""
    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": term,
        "language": "en",
        "format": "json",
        "limit": 1
    }
    headers = {"User-Agent": "OpenIE_Pipeline/1.0 (contact@local.dev)"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=3).json()
        if response.get('search'):
            q_id = response['search'][0]['id']
            label = response['search'][0]['label']
            return label.title(), f"http://www.wikidata.org/entity/{q_id}"
    except Exception:
        pass
    return term.title(), ""

# =========================================================================
# MOTEUR VECTORIEL (ENTITY RESOLUTION ENTONNOIR)
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
                print(f"   [ERREUR Embedding] 'ollama pull {self.model}' requis. ({e})")
                self.ontology_vectors = {}
                return
                
    def resolve(self, raw_entity: str, threshold: float = 0.82) -> tuple[str, float, str]:
        """
        Entonnoir à 3 niveaux : 
        1. T-Box Vectorielle
        2. Wikidata (LOD)
        3. Texte brut (Outlier)
        Renvoie: (Label_Canonique, Score_Cosinus, Wikidata_URI)
        """
        best_score = 0.0
        # Niveau 1 : T-Box Locale
        if self.ontology_vectors:
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
                    return best_match, best_score, "" # Ancrage T-Box réussi
            except: 
                pass
                
        # Niveau 2 : Wikidata LOD (Si l'ancrage T-Box a échoué)
        wiki_label, wiki_uri = search_wikidata_entity(raw_entity)
        if wiki_uri:
            return wiki_label, 1.0, wiki_uri # Ancrage Wikidata réussi
            
        # Niveau 3 : True Outlier
        return raw_entity.title(), best_score, ""

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
            if key not in ["Predicates", "Entities"]:
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

def save_keywords_registry(current_registry, resolved_tags_dict, original_data):
    """
    Sépare les vrais nouveaux termes (Uncategorized_New) 
    des termes validés par Wikidata (Entities -> Wikidata_Aligned).
    """
    new_ones = []
    
    for tag, uri in resolved_tags_dict.items():
        if tag.strip() and tag.strip() not in current_registry:
            if uri:
                if "Entities" not in original_data: original_data["Entities"] = {}
                if "Wikidata_Aligned" not in original_data["Entities"]: original_data["Entities"]["Wikidata_Aligned"] = []
                if tag not in original_data["Entities"]["Wikidata_Aligned"]:
                    original_data["Entities"]["Wikidata_Aligned"].append(tag)
            else:
                new_ones.append(tag.strip())
    
    if new_ones:
        if "Uncategorized_New" not in original_data: original_data["Uncategorized_New"] = []
        original_data["Uncategorized_New"].extend(new_ones)
        original_data["Uncategorized_New"] = sorted(list(set(original_data["Uncategorized_New"])))
        
    original_data["Predicates"] = {"Allowed": ALLOWED_PREDICATES, "Banned": BANNED_PREDICATES}
        
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return current_registry.union(new_ones).union(resolved_tags_dict.keys())

def extract_pdf_content(pdf_path):
    header_text = ""
    body_chunks = []
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(HEADER_PAGES, len(doc))):
            header_text += doc[i].get_text() + "\n"
            
        current_chunk_blocks = []
        current_chunk_len = 0
        OVERLAP_BLOCKS = 3 
        
        for i in range(HEADER_PAGES, len(doc)):
            page = doc[i]
            blocks = page.get_text("blocks")
            for b in blocks:
                block_text = str(b[4]).strip() 
                if not block_text: continue
                block_len = len(block_text)
                if current_chunk_len + block_len > CHUNK_CHARS and current_chunk_blocks:
                    body_chunks.append("\n\n".join(current_chunk_blocks))
                    overlap_slice = current_chunk_blocks[-OVERLAP_BLOCKS:] if len(current_chunk_blocks) >= OVERLAP_BLOCKS else current_chunk_blocks
                    current_chunk_blocks = overlap_slice + [block_text]
                    current_chunk_len = sum(len(bloc) for bloc in current_chunk_blocks)
                else:
                    current_chunk_blocks.append(block_text)
                    current_chunk_len += block_len
                    
        if current_chunk_blocks:
            body_chunks.append("\n\n".join(current_chunk_blocks))
        doc.close()
    except Exception as e:
        print(f"        -> [WARNING] Erreur sémantique PDF: {e}")
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

def create_or_update_entity_node(entity_name, uri):
    """Crée un fichier Markdown pour l'entité avec ses métadonnées Wikidata."""
    if not entity_name: return
    safe_entity = re.sub(r'[\\/:*?"<>|]', '_', entity_name)
    node_path = os.path.join(OBSIDIAN_VAULT_PATH, "Nodes", f"{safe_entity}.md")
    
    if not os.path.exists(node_path):
        content = f"---\ntitle: \"{entity_name}\"\n"
        if uri:
            content += f"wikidata_uri: \"{uri}\"\nontology_status: \"LOD_Aligned\"\n"
        else:
            content += f"ontology_status: \"Local_Concept\"\n"
        content += f"---\n\n# {entity_name}\n"
        try:
            with open(node_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            pass

def save_to_obsidian(book_id, titre, auteur, resolved_tags_dict, resume, all_triplets):
    tags_list = list(resolved_tags_dict.keys())
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', titre)
    doc_path = os.path.join(OBSIDIAN_VAULT_PATH, "Nodes", f"{safe_title} - {book_id}.md")
    
    content = f"---\nid: {book_id}\ntitle: \"{titre}\"\nauthors: \"{auteur}\"\ntags: {json.dumps(tags_list)}\n---\n\n# {titre}\n\n## Abstract\n{resume}\n\n## CMDB Relationships\n"
    
    # Génération des pages Nœuds pour les tags globaux
    for tag, uri in resolved_tags_dict.items():
        create_or_update_entity_node(tag, uri)
    
    for triplet in all_triplets:
        # Génération des pages Nœuds pour le Sujet et l'Objet
        create_or_update_entity_node(triplet.subject, triplet.subject_uri)
        create_or_update_entity_node(triplet.object, triplet.object_uri)
        
        statut_md = "" if triplet.validation_status == "validated" else " ⚠️#review"
        content += f"- [[{triplet.subject}]] --{triplet.predicate}--> [[{triplet.object}]]{statut_md}\n"
        
        safe_subject = re.sub(r'[\\/:*?"<>|]', '_', triplet.subject)
        safe_object = re.sub(r'[\\/:*?"<>|]', '_', triplet.object)
        edge_filename = f"{safe_subject} - {triplet.predicate} - {safe_object}.md"
        edge_path = os.path.join(OBSIDIAN_VAULT_PATH, "Relations", edge_filename)
        
        edge_content = f"---\nsource: \"[[{triplet.subject}]]\"\ntarget: \"[[{triplet.object}]]\"\npredicate: \"{triplet.predicate}\"\ndocument: \"[[{safe_title} - {book_id}]]\"\nstatus: \"{triplet.validation_status}\"\n---\n\n# Relation: {triplet.subject} -> {triplet.predicate} -> {triplet.object}\n\nExtracted from document: [[{safe_title} - {book_id}]]\n"
        try:
            with open(edge_path, 'w', encoding='utf-8') as fEdge: fEdge.write(edge_content)
        except Exception: pass
            
    try:
        with open(doc_path, 'w', encoding='utf-8') as f: f.write(content)
    except Exception: pass

# =========================================================================
# L'ORCHESTRATEUR LLM
# =========================================================================
def ask_llm_pydantic(prompt: str, pydantic_schema, stage_name="LLM"):
    print(f"        -> [{stage_name}] Inférence avec Pydantic Constraint en cours...")
    schema_json = pydantic_schema.model_json_schema()
    
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
            validated_obj = pydantic_schema.model_validate_json(raw_json)
            
            p_eval = res.get('prompt_eval_count', 0)
            eval_c = res.get('eval_count', 0)
            rate = (eval_c / duration) if duration > 0 else 0
            print(f"           [Métriques] {duration:.1f}s | {rate:.1f} t/s | Lu: {p_eval} t -> Écrit: {eval_c} t")
            return validated_obj
        except Exception as e:
            print(f"           [Retry {attempt+1}] Hard-Fail intercepté : {e}")
            prompt += f"\n\n!!! ATTENTION, ta réponse précédente a causé l'erreur :\n{e}\nCorrige avant de répondre."
    return None

# =========================================================================
# MAIN PIPELINE
# =========================================================================
def main():
    ensure_dirs()
    print("=================================================================")
    print("   SCRIPT D'INDEXATION V6 (PYDANTIC, VECTOR ANCHORING & WIKIDATA) ")
    print("=================================================================\n")
    
    mode = input("Mode d'exécution (1=Nouveaux, 2=Complet) : ").strip()
    root_tk = tk.Tk(); root_tk.withdraw(); root_tk.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(title="Racine Calibre")
    if not folder_path: return

    calibredb_path = r"C:\Program Files\Calibre2\calibredb.exe" if os.path.exists(r"C:\Program Files\Calibre2\calibredb.exe") else "calibredb"
    registry_list, original_data = load_keywords_registry()
    
    high_level_categories = [str(k) for k in original_data.keys() if k not in ["Uncategorized_New", "Predicates", "Entities"]]
    registry_str = ", ".join(high_level_categories)
    
    anchor_engine = VectorAnchor()
    anchor_engine.index_ontology(list(registry_list))
    
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
    
    for i, data in enumerate(files_to_process):
        print(f"\n=================================================================")
        print(f"[{i+1}/{len(files_to_process)}] ID={data['bid']} | {data['tit']}")
        h_text, chunks = extract_pdf_content(data['pdf'])
        
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
        
        meta = ask_llm_pydantic(prompt_h, OpenIEMining, stage_name="En-tête")
        if not meta: continue
            
        all_triplets = meta.triplets
        all_tags = set(meta.keywords)
        
        for j, chunk in enumerate(chunks):
            prompt_c = f"""Enrich the Knowledge Graph from this fragment.
Strictly FORBIDDEN to use weak verbs: {BANNED_PREDICATES}.
Favor these strong predicates: {ALLOWED_PREDICATES}.
If possible, link your concepts to existing vocabulary (T-Box) context: {registry_str}

Text:
{chunk}"""
            c_data = ask_llm_pydantic(prompt_c, ChunkMining, stage_name=f"Graphe - Chunk {j+1}/{len(chunks)}")
            if c_data: all_triplets.extend(c_data.triplets)
        
        # --- ANCRAGE VECTORIEL ASYMÉTRIQUE ET WIKIDATA ---
        resolved_triplets = []
        print(f"        -> Ancrage vectoriel & Wikidata des {len(all_triplets)} triplets...")
        for triplet in all_triplets:
            # Sujet : Ancrage Fort (0.80)
            clean_s, _, uri_s = anchor_engine.resolve(triplet.subject, threshold=0.80)
            # Objet : Ancrage Stricte/Local (0.88) ou Fallback Wikidata
            clean_o, _, uri_o = anchor_engine.resolve(triplet.object, threshold=0.88)
            
            triplet.subject = clean_s
            triplet.subject_uri = uri_s
            triplet.object = clean_o
            triplet.object_uri = uri_o
            resolved_triplets.append(triplet)
            
        resolved_tags_dict = {}
        for t in all_tags:
            clean_t, _, uri_t = anchor_engine.resolve(t, threshold=0.80)
            resolved_tags_dict[clean_t] = uri_t
            
        print(f"        -> Triplets consolidés : {len(resolved_triplets)}")
        
        final_tags_list = list(resolved_tags_dict.keys())
        subprocess.run([calibredb_path, 'set_metadata', '--with-library', folder_path, data['bid'], 
                        '--field', f"title:{meta.title}", '--field', f"authors:{meta.author}",
                        '--field', f"tags:{', '.join(final_tags_list)}", '--field', f"comments:{meta.summary}"], capture_output=True)
        
        save_to_obsidian(data['bid'], meta.title, meta.author, resolved_tags_dict, meta.summary, resolved_triplets)
        registry_list = save_keywords_registry(registry_list, resolved_tags_dict, original_data)
        anchor_engine.index_ontology(list(registry_list))

if __name__ == "__main__":
    try:
        main()
        input("\nTerminé. Appuyez sur Entrée pour fermer la fenêtre...")
    except KeyboardInterrupt:
        print("\n\n[INFO] Interruption manuelle (Ctrl+C). Fermeture immédiate.")
    except Exception:
        traceback.print_exc()
        input("\n[ERREUR CRITIQUE] Appuyez sur Entrée pour fermer la fenêtre...")
