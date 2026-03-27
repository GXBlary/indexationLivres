import os
import fitz  # PyMuPDF
import ollama
import json
import re
import subprocess
import tkinter as tk
from tkinter import filedialog
import time

MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "keywords_registry.json")

def select_directory():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    directory = filedialog.askdirectory(title="Sélectionnez le dossier racine de la bibliothèque Calibre")
    return directory

def get_calibredb_path():
    common_paths = [
        "calibredb",
        r"C:\Program Files\Calibre2\calibredb.exe",
        r"C:\Program Files (x86)\Calibre2\calibredb.exe"
    ]
    for p in common_paths:
        try:
            subprocess.run([p, '--version'], capture_output=True, check=True)
            return p
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None

def extract_all_strings(data):
    """Extrait récursivement toutes les chaînes de caractères d'un JSON (pour supporter les taxonomies complexes)."""
    result = set()
    if isinstance(data, dict):
        for val in data.values():
            result.update(extract_all_strings(val))
    elif isinstance(data, list):
        for item in data:
            result.update(extract_all_strings(item))
    elif isinstance(data, str):
        result.add(data.strip())
    return result

def load_keywords_registry():
    """Charge le dictionnaire de mots-clés existants, qu'il soit une simple liste ou une taxonomie imbriquée."""
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return extract_all_strings(data), data
        except Exception as e:
            print(f"[ERREUR] Le fichier keywords_registry.json est illisible ou corrompu : {e}")
    else:
        print(f"[INFO] Aucun fichier {KEYWORDS_FILE} trouvé.")
    return set(), []

def save_keywords_registry(current_registry, new_keywords, original_data):
    """Ajoute les nouveaux mots-clés sans détruire la structure JSON complexe de l'utilisateur."""
    new_ones = [k.strip() for k in new_keywords if k.strip() and k.strip() not in current_registry]
    if not new_ones:
        return current_registry
        
    if isinstance(original_data, dict):
        if "Uncategorized_New" not in original_data:
            original_data["Uncategorized_New"] = []
        if isinstance(original_data["Uncategorized_New"], list):
            original_data["Uncategorized_New"].extend(new_ones)
            original_data["Uncategorized_New"] = sorted(list(set(original_data["Uncategorized_New"])))
    elif isinstance(original_data, list):
        original_data.extend(new_ones)
        original_data = sorted(list(set(original_data)))
        
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, indent=4, ensure_ascii=False)
    except PermissionError:
        print(f"        -> [WARNING] Impossible de mettre à jour '{KEYWORDS_FILE}' (Permission refusée). Le fichier est probablement ouvert et verrouillé dans votre éditeur de texte.")
    except Exception as e:
        print(f"        -> [WARNING] Erreur inattendue lors de la sauvegarde du registre : {e}")
        
    return current_registry.union(new_ones)

def extract_full_text(pdf_path, max_chars=120000):
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text += page.get_text() + "\n"
            if len(text) > max_chars:
                print("        -> (Texte tronqué à la limite de sécurité - 32k tokens)")
                break
        doc.close()
    except Exception as e:
        print(f"        -> Erreur de lecture du PDF: {e}")
    return text[:max_chars]

def parse_opf_info(opf_content, file_path):
    # ID Calibre (Regex robuste ou chemin)
    id_match = re.search(r'<dc:identifier[^>]*opf:scheme="calibre"[^>]*>([^<]+)</dc:identifier>', opf_content, re.IGNORECASE)
    book_id = id_match.group(1) if id_match else None
    if not book_id:
        parent_dir = os.path.basename(os.path.dirname(file_path))
        folder_id_match = re.search(r'\(([0-9]+)\)$', parent_dir.strip())
        if folder_id_match:
            book_id = folder_id_match.group(1)
            
    # Titre et Auteur Actuels
    author_match = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', opf_content, re.IGNORECASE)
    author = author_match.group(1) if author_match else "Inconnu(e)"
    
    title_match = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf_content, re.IGNORECASE)
    title = title_match.group(1) if title_match else "Inconnu"
    
    # Mots-clés Actuels (<dc:subject>)
    tags_matches = re.findall(r'<dc:subject[^>]*>([^<]+)</dc:subject>', opf_content, re.IGNORECASE)
    tags = [t.strip() for t in tags_matches if t.strip()]
    
    # Résumé actuel (<dc:description>)
    desc_match = re.search(r'<dc:description[^>]*>([^<]+)</dc:description>', opf_content, re.IGNORECASE)
    description = desc_match.group(1) if desc_match else ""
    
    return book_id, author, title, tags, description

def is_valid_author(author_str):
    """
    Vérifie avec une logique basique si le champ auteur semble gravement mal formaté 
    (contient des URL, des chiffres, ou est très long).
    """
    if not author_str or "inconnu" in author_str.lower():
        return False
    if len(author_str) > 60: # Souvent le titre a été glissé à la place du nom
        return False
    if any(char.isdigit() for char in author_str):
        return False
    weird = ['http', 'www', 'doi:', 'journal', 'volume', 'issue', 'page', 'abstract', 'university']
    if any(w in author_str.lower() for w in weird):
        return False
    return True

def ask_llm(mode, author, title, tags, description, full_text, registry):
    # Liste de mots clés formatée pour le prompt
    registry_str = ", ".join(sorted(list(registry)))
    
    if mode == "1": # NOUVEAUX
        prompt = f"""
Voici le texte extrait d'un document (article scientifique, papier ou livre).

Actuellement dans la base de données :
- Titre : "{title}"
- Auteur : "{author}"

Ta tâche est de générer ou corriger les métadonnées de ce document.
CONSIGNES STRICTES :
1. Titre et Auteur : Vérifie qu'ils ne sont pas intervertis ou mal formatés (ex: URL à la place du nom). Trouve les vrais s'ils sont inconnus.
2. Mots-clés (mots_cles) : EN ANGLAIS UNIQUEMENT. 
   -> TRES IMPORTANT : Voici le registre de mots-clés existants : [{registry_str}]. UTILISE CES MOTS-CLES EN PRIORITE pour l'alignement. N'invente des nouveaux que si c'est indispensable.
   -> Recherche d'abord la section "Keywords" dans le texte.
   -> Si le document est un livre de fiction (roman, conte...), ajoute obligatoirement le mot-clé "Fiction". S'il s'agit d'un article scientifique, ne le mets pas.
3. Résumé (resume) : EN ANGLAIS UNIQUEMENT. Recopie "Abstract" ou "Summary" si présent, sinon rédige un résumé très précis.

Réponds EXCLUSIVEMENT avec un objet JSON valide :
{{
  "titre": "Titre correct du document",
  "auteur": "Auteur(s) correct(s)",
  "mots_cles": ["keyword1", "keyword2"],
  "resume": "Abstract or summary IN ENGLISH."
}}

Texte intégral pour analyse :
---
{full_text}
---
"""
    else: # CORRECTION
        prompt = f"""
Voici le texte extrait d'un document ET ses métadonnées actuelles qui ont besoin d'être VÉRIFIÉES, CORRIGÉES ET TRADUITES.

Métadonnées actuelles :
- Titre : "{title}"
- Auteur : "{author}"
- Mots-clés actuels : {json.dumps(tags)}
- Résumé actuel : "{description[:1500]}..."

Ta tâche est de CORRIGER ces métadonnées selon ces CONSIGNES STRICTES :
1. Titre et Auteur : Vérifie qu'ils sont à l'endroit et proprement formatés. Corrige toute erreur ou inversion.
2. Mots-clés (mots_cles) : TRADUIS et ALIGNE-LES EN ANGLAIS.
   -> REMPLACE les synonymes ou mots français par les versions officielles du registre suivant : [{registry_str}].
   -> Si c'est une fiction, ajoute "Fiction".
3. Résumé (resume) : TRADUIS-LE EN ANGLAIS s'il est au format français ! S'il est de mauvaise qualité, rédige un nouvel "Abstract" en anglais d'après le texte. S'il est parfait et DÉJÀ en anglais, garde-le tel quel.

Réponds EXCLUSIVEMENT avec un objet JSON valide :
{{
  "titre": "Titre vérifié",
  "auteur": "Auteur(s) vérifié(s)",
  "mots_cles": ["aligned_keyword1", "aligned_keyword2"],
  "resume": "Summary in ENGLISH."
}}

Texte intégral en contexte :
---
{full_text}
---
"""
    try:
        t0 = time.time()
        
        # Le contexte max de 32k est essentiel pour l'ingestion de PDFs massifs
        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'user',
                'content': prompt
            }
        ], format='json', options={'num_ctx': 32768}) 
        
        t1 = time.time()
        duration = t1 - t0
        
        # Récupération des statistiques LLM (tokens prompt / tokens eval) natives de l'API Ollama
        p_eval_count = response.get('prompt_eval_count', 0)
        eval_count = response.get('eval_count', 0)
        eval_rate = (eval_count / duration) if duration > 0 else 0
        
        print(f"        [Métriques IA] Temps de traitement : {duration:.1f}s")
        print(f"        [Métriques IA] Vitesse de génération : {eval_count} tokens générés à {eval_rate:.1f} t/s (Contexte ingéré: {p_eval_count} t)")
        
        result = json.loads(response['message']['content'])
        return result
    except Exception as e:
        print(f"        -> Erreur critique du LLM: {e}")
        return None

def update_calibre_metadata(calibredb_path, library_path, book_id, llm_data):
    args = [calibredb_path, 'set_metadata', '--with-library', library_path, str(book_id)]
    
    if "titre" in llm_data and llm_data["titre"]:
        args.extend(['--field', f'title:{llm_data["titre"]}'])
        
    if "auteur" in llm_data and llm_data["auteur"]:
        args.extend(['--field', f'authors:{llm_data["auteur"]}'])
        
    if "mots_cles" in llm_data and isinstance(llm_data["mots_cles"], list) and llm_data["mots_cles"]:
        tags_str = ", ".join(llm_data["mots_cles"])
        args.extend(['--field', f'tags:{tags_str}'])
        
    if "resume" in llm_data and llm_data["resume"]:
        args.extend(['--field', f'comments:{llm_data["resume"]}'])

    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            print("        -> DB Calibre synchronisée avec succès '[OK]'.")
            return True
        else:
            print(f"        -> ERREUR Calibre: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"        -> Exception calibredb: {e}")
        return False

def main():
    print("=======================================================")
    print("       SCRIPT D'INDEXATION AVANCÉE (CALIBRE V3)        ")
    print("=======================================================\n")
    print("Sélectionnez le type de traitement :")
    print("  [1] MODE BATCH (NOUVEAUX) : Traite uniquement les documents non traités (mots-clés vides) ou dont le champ Auteur semble mal formaté.")
    print("  [2] MODE CORRECTION       : Retraite même les documents finis pour aligner les mots-clés, forcer l'usage de l'anglais, et corriger les inversions persistantes.")
    
    mode = input("\nVotre choix (1 ou 2) : ").strip()
    if mode not in ["1", "2"]:
        print("Choix invalide. Annulation.")
        return
        
    folder_path = select_directory()
    if not folder_path:
        print("Annulé (aucun dossier bibliothèque sélectionné).")
        return

    calibredb_path = get_calibredb_path()
    if not calibredb_path:
        print("[ERREUR CRITIQUE] calibredb est introuvable sur le système Windows (introuvable dans Program Files).")
        return

    print("\n[INFO] Chargement du registre de mots-clés global ('keywords_registry.json')...")
    registry, original_data = load_keywords_registry()
    print(f"[INFO] {len(registry)} mot(s)-clé(s) unique(s) extrait(s) de la taxonomie.")
    
    print("\n[INFO] Phase 1 : Scan de la bibliothèque (pré-ciblage)...")
    
    files_to_process = []
    
    for root_dir, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.lower() == 'metadata.opf':
                file_path = os.path.join(root_dir, filename)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        opf_content = f.read()
                except:
                    continue
                
                book_id, author, title, tags, description = parse_opf_info(opf_content, file_path)
                
                if not book_id:
                    continue
                
                # Vérifier si l'article est physiquement lisible (au format PDF)
                pdf_path = None
                for sibling in files:
                    if sibling.lower().endswith('.pdf'):
                        pdf_path = os.path.join(root_dir, sibling)
                        break
                
                if not pdf_path:
                    continue 
                
                do_process = False
                
                if mode == "1":
                    # Le mode BATCH (NOUVEAU) s'active si la liste de mots-clés est vide OU SI le champ auteur est illisible
                    if len(tags) == 0:
                        do_process = True
                    elif not is_valid_author(author):
                        do_process = True
                elif mode == "2":
                    # Le mode CORRECTION repasse sur tout, c'est l'essence du mode
                    do_process = True
                
                if do_process:
                    # On le place dans la file d'attente
                    files_to_process.append({
                        'book_id': book_id,
                        'author': author,
                        'title': title,
                        'tags': tags,
                        'description': description,
                        'pdf_path': pdf_path,
                        'root_dir': root_dir
                    })

    total_docs = len(files_to_process)
    print(f"[INFO] Scan terminé : {total_docs} document(s) ciblé(s) selon le mode choisi.\n")
    
    if total_docs == 0:
        print("Il semblerait que tout soit déjà parfait.")
        return

    print("=======================================================")
    print("               LANCEMENT DE L'ANALYSE                  ")
    print("=======================================================\n")
    
    nb_success = 0
    t_start_global = time.time()
    
    for i, data in enumerate(files_to_process):
        idx = i + 1
        book_id = data['book_id']
        pdf_path = data['pdf_path']
        
        print(f"[{idx}/{total_docs}] Progression Globale - Traitement ID={book_id} | Dir: {os.path.basename(data['root_dir'])}")
        full_text = extract_full_text(pdf_path)
        
        if not full_text.strip():
            print("        -> [ERROR] Aucun texte extrait.")
            continue
            
        llm_data = ask_llm(mode, data['author'], data['title'], data['tags'], data['description'], full_text, registry)
        
        if llm_data:
            print(f"        -> [LLM OK] Liste de mots-clés : {llm_data.get('mots_cles', [])}")
            # Envoi interactif à Calibre
            if update_calibre_metadata(calibredb_path, folder_path, book_id, llm_data):
                nb_success += 1
                # Enregistrement des nouveaux mots clés dans la grande base pour éviter les synonymes futurs
                if "mots_cles" in llm_data and isinstance(llm_data["mots_cles"], list):
                    registry = save_keywords_registry(registry, llm_data["mots_cles"], original_data)
        else:
            print("        -> [ECHEC LLM] Le LLM a renvoyé une erreur de formatage JSON.")
            
        print("-" * 65)

    duration_total = time.time() - t_start_global
    print(f"\n====================== RÉSUMÉ =========================")
    print(f"Total des documents ciblés par la passe : {total_docs}")
    print(f"Traités avec succès en BDD de Calibre   : {nb_success}")
    print(f"Taille du registre JSON des mots-clés   : {len(registry)} mots")
    print(f"Temps pris pour le Batch complet        : {duration_total/60:.1f} minutes")
    print("=======================================================")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("\n[ERREUR CRITIQUE] Le script a rencontré une erreur inattendue :")
        traceback.print_exc()
    finally:
        input("\nAppuyez sur Entrée pour fermer la fenêtre...")
