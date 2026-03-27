import os
import fitz  # PyMuPDF
import ollama
import json
import re
import subprocess
import tkinter as tk
from tkinter import filedialog
import time
import traceback

# --- CONFIGURATION V4 ---
MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "keywords_registry.json")
OBSIDIAN_VAULT_PATH = os.path.join(SCRIPT_DIR, "Obsidian_Vault")
GRAPH_EXPORT_FILE = os.path.join(SCRIPT_DIR, "knowledge_graph.json")

# Paramètres de chunking pour 8GB de VRAM
CHUNK_CHARS = 10000  # Environ 2500-3000 tokens
HEADER_PAGES = 5      # Pages pour l'analyse initiale (Titre/Auteur/Abstract)

def ensure_dirs():
    if not os.path.exists(OBSIDIAN_VAULT_PATH):
        os.makedirs(OBSIDIAN_VAULT_PATH)
    for sub in ["Nodes", "Relations"]:
        p = os.path.join(OBSIDIAN_VAULT_PATH, sub)
        if not os.path.exists(p):
            os.makedirs(p)

def extract_all_strings(data):
    """Extrait récursivement toutes les chaînes d'une taxonomie JSON."""
    result = set()
    if isinstance(data, dict):
        for val in data.values(): result.update(extract_all_strings(val))
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
                return extract_all_strings(data), data
        except Exception as e:
            print(f"[ERREUR] Registre illisible : {e}")
    return set(), {}

def save_keywords_registry(current_registry, new_keywords, original_data):
    new_ones = [k.strip() for k in new_keywords if k.strip() and k.strip() not in current_registry]
    if not new_ones: return current_registry
    if isinstance(original_data, dict):
        if "Uncategorized_New" not in original_data: original_data["Uncategorized_New"] = []
        original_data["Uncategorized_New"].extend(new_ones)
        original_data["Uncategorized_New"] = sorted(list(set(original_data["Uncategorized_New"])))
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(original_data, f, indent=4, ensure_ascii=False)
    return current_registry.union(new_ones)

def extract_pdf_content(pdf_path):
    header_text = ""
    body_chunks = []
    current_chunk = ""
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(HEADER_PAGES, len(doc))):
            header_text += doc[i].get_text() + "\n"
        for i in range(HEADER_PAGES, len(doc)):
            page_text = doc[i].get_text()
            if len(current_chunk) + len(page_text) > CHUNK_CHARS:
                body_chunks.append(current_chunk)
                current_chunk = page_text
            else:
                current_chunk += "\n" + page_text
        if current_chunk: body_chunks.append(current_chunk)
        doc.close()
    except Exception as e: print(f"        -> Erreur PDF: {e}")
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

def ask_llm(prompt, stage_name="LLM"):
    print(f"        -> [{stage_name}] Analyse par l'IA en cours...")
    try:
        t0 = time.time()
        res = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': prompt}], format='json', options={'num_ctx': 8192})
        t1 = time.time()
        duration = t1 - t0
        
        p_eval_count = res.get('prompt_eval_count', 0)
        eval_count = res.get('eval_count', 0)
        eval_rate = (eval_count / duration) if duration > 0 else 0
        print(f"           [Métriques] Temps: {duration:.1f}s | Vitesse: {eval_rate:.1f} t/s | Lu: {p_eval_count} t -> Écrit: {eval_count} t")
        
        return json.loads(res['message']['content']), res
    except Exception as e:
        print(f"           [ERREUR LLM] {e}")
        return None, None

def save_to_obsidian(book_id, metadata, all_triplets):
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', metadata['titre'])
    doc_path = os.path.join(OBSIDIAN_VAULT_PATH, "Nodes", f"{safe_title}.md")
    content = f"---\nid: {book_id}\ntitle: \"{metadata['titre']}\"\nauthors: \"{metadata['auteur']}\"\ntags: {json.dumps(metadata['mots_cles'])}\n---\n\n# {metadata['titre']}\n\n## Summary (EN)\n{metadata['resume']}\n\n## Relationships\n"
    
    for triplet in all_triplets:
        if isinstance(triplet, list) and len(triplet) >= 3:
            content += f"- [[{triplet[0]}]] --{triplet[1]}--> [[{triplet[2]}]]\n"
        elif isinstance(triplet, list) and len(triplet) == 2:
            content += f"- [[{triplet[0]}]] --mentionne--> [[{triplet[1]}]]\n"
            
    with open(doc_path, 'w', encoding='utf-8') as f: f.write(content)

def main():
    ensure_dirs()
    print("=======================================================")
    print("   SCRIPT D'INDEXATION V4 (CHUNKING & KNOWLEDGE GRAPH) ")
    print("=======================================================\n")
    print("Bienvenue. Ce script analyse votre bibliothèque Calibre et construit votre Graphe de Connaissances dans Obsidian.\n")
    print("Sélectionnez le mode de traitement :")
    print("  [1] MODE NOUVEAUX : Ne traite que les documents 'vierges' (ceux n'ayant actuellement aucun mot-clé dans Calibre).")
    print("                      Idéal pour ajouter rapidement vos dernières entrées à la base.")
    print("  [2] MODE COMPLET  : Force le (re)traitement de TOUS les documents de la bibliothèque (même ceux déjà indexés).")
    print("                      Idéal pour unifier l'anglais et aligner l'ensemble sur votre taxonomie commune.\n")
    print("-> (INFO) L'IA va scanner l'en-tête (5 p.) de chaque PDF, puis découper religieusement tout le reste")
    print("   du texte en morceaux séquentiels (~3000 tokens) pour extraire de force chaque élément sémantique.")
    
    mode = input("\nVotre choix (1 ou 2) : ").strip()
    root_tk = tk.Tk(); root_tk.withdraw(); root_tk.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(title="Racine Calibre")
    if not folder_path: return

    calibredb_path = r"C:\Program Files\Calibre2\calibredb.exe" if os.path.exists(r"C:\Program Files\Calibre2\calibredb.exe") else "calibredb"
    registry, original_data = load_keywords_registry()
    registry_str = ", ".join(list(registry)[:200]) # On limite pour éviter de saturer le prompt si registry est énorme
    
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
        print(f"\n=======================================================")
        print(f"[{i+1}/{len(files_to_process)}] ID={data['bid']} | {data['tit']}")
        print(f"        Extraction du texte PDF (en-tête + suite)...")
        h_text, chunks = extract_pdf_content(data['pdf'])
        
        # Passe 1: Header
        prompt_h = f"""Analyse ces pages. Récupère Titre, Auteur, Abstract (EN).
IMPORTANT : Extrais UNIQUEMENT les 8 mots-clés les plus centraux (EN). Ne sois pas trop bavard.
Extrais les triplets Knowledge Graph (Relations: mentionne, co-écrit, est écrit par).
JSON attendu: {{ "titre": "...", "auteur": "...", "mots_cles": ["..."], "resume": "...", "triplets": [["S", "P", "O"]] }}
Registre: [{registry_str}]
Texte:\n{h_text}"""
        meta, _ = ask_llm(prompt_h, stage_name="En-tête (Pages 1-5)")
        if not meta: continue
        
        print(f"        -> [DÉTECTÉ] Titre : {meta.get('titre', 'Inconnu')}")
        print(f"        -> [DÉTECTÉ] Auteur : {meta.get('auteur', 'Inconnu')}")
        
        all_triplets = meta.get('triplets', [])
        all_tags = set(meta.get('mots_cles', []))
        
        # Passes Chunks
        for j, chunk in enumerate(chunks):
            prompt_c = f"""Analyse ce fragment pour enrichir UNIQUEMENT le graphe (Relations: mentionne).
Ne génère PAS de nouveaux mots-clés globaux.
JSON attendu: {{ "triplets": [["S", "P", "O"]] }}
Texte:\n{chunk}"""
            c_data, _ = ask_llm(prompt_c, stage_name=f"Graphe - Morceau {j+1}/{len(chunks)}")
            if c_data:
                all_triplets.extend(c_data.get('triplets', []))
        
        meta['mots_cles'] = list(all_tags)
        print(f"        -> Bilan des mots-clés finaux : {meta['mots_cles']}")
        print(f"        -> Total des triplets (Knowledge Graph) extraits : {len(all_triplets)}")
        
        # Sync Calibre
        subprocess.run([calibredb_path, 'set_metadata', '--with-library', folder_path, data['bid'], 
                        '--field', f"title:{meta['titre']}", '--field', f"authors:{meta['auteur']}",
                        '--field', f"tags:{', '.join(meta['mots_cles'])}", '--field', f"comments:{meta['resume']}"], capture_output=True)
        
        # Sync Obsidian & Registry
        save_to_obsidian(data['bid'], meta, all_triplets)
        registry = save_keywords_registry(registry, meta['mots_cles'], original_data)
        print("    -> OK.")

if __name__ == "__main__":
    try:
        main()
        input("\nTerminé. Appuyez sur Entrée pour fermer la fenêtre...")
    except KeyboardInterrupt:
        print("\n\n[INFO] Interruption manuelle (Ctrl+C) détectée. Fermeture immédiate.")
    except Exception:
        import traceback
        traceback.print_exc()
        input("\n[ERREUR CRITIQUE] Appuyez sur Entrée pour fermer la fenêtre...")
