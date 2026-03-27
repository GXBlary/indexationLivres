import os
import fitz  # PyMuPDF
import ollama
import json
import re
import subprocess
import tkinter as tk
from tkinter import filedialog

MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"

def select_directory():
    """Ouvre une fenêtre pour sélectionner calmement la bibliothèque."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    directory = filedialog.askdirectory(title="Sélectionnez le dossier racine de la bibliothèque Calibre")
    return directory

def get_calibredb_path():
    """Cherche l'outil de ligne de commande Calibre."""
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

def extract_full_text(pdf_path, max_chars=120000):
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text += page.get_text() + "\n"
            if len(text) > max_chars:
                print("    -> Texte tronqué à la limite de sécurité (32k tokens).")
                break
        doc.close()
    except Exception as e:
        print(f"    -> Erreur lors de la lecture du PDF {pdf_path}: {e}")
    return text[:max_chars]

def parse_opf_info(opf_content, file_path):
    # Regex plus tolérante aux autres attributs (ex: id="calibre_id")
    id_match = re.search(r'<dc:identifier[^>]*opf:scheme="calibre"[^>]*>([^<]+)</dc:identifier>', opf_content, re.IGNORECASE)
    book_id = id_match.group(1) if id_match else None
    
    # Si l'ID est introuvable dans le XML, on le récupère depuis le nom du dossier qui finit par "(ID)" (ex: "Livre (189)")
    if not book_id:
        parent_dir = os.path.basename(os.path.dirname(file_path))
        folder_id_match = re.search(r'\(([0-9]+)\)$', parent_dir.strip())
        if folder_id_match:
            book_id = folder_id_match.group(1)
            
    author_match = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', opf_content, re.IGNORECASE)
    author = author_match.group(1) if author_match else "Inconnu(e)"
    
    title_match = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf_content, re.IGNORECASE)
    title = title_match.group(1) if title_match else "Inconnu"
    
    return book_id, author, title

def get_metadata_from_llm(current_author, current_title, full_text):
    prompt = f"""
Voici le texte extrait d'un article scientifique, d'un papier ou d'un livre (tronqué si trop long).

Actuellement dans la base de données :
- Titre : "{current_title}"
- Auteur : "{current_author}"

Ta tâche est de générer ou corriger les métadonnées de ce document.
CONSIGNES OBLIGATOIRES :
1. Titre et Auteur : Parfois, le titre et l'auteur ont été intervertis dans la base. Vérifie dans le texte si c'est le cas et remets-les à l'endroit. S'ils sont marqués "Inconnu(e)", trouve les vrais dans le texte. Renvoie toujours le titre complet et l'auteur complet et correct.
2. Mots-clés (mots_cles) : DOIVENT être EN ANGLAIS. Recopie STRICTEMENT la section "Keywords" de l'article si elle existe. N'invente pas de synonymes ni de mots-clés génériques pour que la liste reste propre et exploitable. S'il n'y a pas de section keywords explicite, trouve 3 ou 4 mots-clés hyper précis en anglais.
3. Résumé (resume) : DOIT être EN ANGLAIS. Recopie STRICTEMENT la section "Abstract" ou "Summary" si présente, sinon rédige un résumé très précis et factuel en anglais.

Réponds EXCLUSIVEMENT avec un objet JSON strictement valide au format suivant :
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
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'user',
                'content': prompt
            }
        ], format='json', options={'num_ctx': 32768}) 
        
        result = json.loads(response['message']['content'])
        return result
    except Exception as e:
        print(f"    -> Erreur avec le LLM: {e}")
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
            print("    -> Base de données Calibre synchronisée avec succès.")
            return True
        else:
            print(f"    -> ERREUR Calibre: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"    -> Exception lors de l'appel à calibredb: {e}")
        return False

def process_directory(directory):
    if not os.path.exists(directory):
        print(f"[ERREUR] Le dossier {directory} n'existe pas.")
        return

    calibredb_path = get_calibredb_path()
    if not calibredb_path:
        print("[ERREUR CRITIQUE] calibredb est introuvable sur le système. Vérifiez qu'il est dans le PATH.")
        return
    else:
        print(f"[INFO] calibredb trouvé à : {calibredb_path}\n")

    # ----- STATISTIQUES POUR LES LOGS -----
    nb_fichiers_opf_trouves = 0
    nb_sans_id = 0
    nb_sans_pdf = 0
    nb_traites = 0

    for root_dir, dirs, files in os.walk(directory):
        for filename in files:
            if filename.lower() == 'metadata.opf':
                nb_fichiers_opf_trouves += 1
                file_path = os.path.join(root_dir, filename)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        opf_content = f.read()
                except Exception as e:
                    print(f"[-] Erreur de lecture sur {file_path} : {e}")
                    continue
                
                book_id, author, title = parse_opf_info(opf_content, file_path)
                if not book_id:
                    print(f"[-] Ignoré (pas d'ID de la forme opf:scheme=\"calibre\" trouvé) : {file_path}")
                    nb_sans_id += 1
                    continue
                
                pdf_path = None
                for sibling in files:
                    if sibling.lower().endswith('.pdf'):
                        pdf_path = os.path.join(root_dir, sibling)
                        break
                
                if not pdf_path:
                    print(f"[-] Ignoré (pas de document .pdf associé dans le dossier) : {file_path}")
                    nb_sans_pdf += 1
                    continue 
                
                print(f"\n=======================================================")
                print(f"[!] Traitement du livre ID={book_id} | Dossier: {root_dir}")
                print(f"    -> Auteur actuel : {author}")
                print(f"    -> Titre actuel : {title}")
                print(f"    -> Extraction de l'article en cours...")
                
                full_text = extract_full_text(pdf_path)
                
                if not full_text.strip():
                    print("    -> ERREUR: Aucun texte lisé n'a pu être extrait. Fichier scanné en image ?")
                    continue
                    
                print(f"    -> Appel au LLM (~{len(full_text)} caractères extraits)...")
                
                llm_data = get_metadata_from_llm(author, title, full_text)
                nb_traites += 1
                
                if llm_data:
                    print(f"    -> Données générées et formatées validées :")
                    print(json.dumps(llm_data, indent=4, ensure_ascii=False))
                    
                    print("    -> Envoi direct à la base de données Calibre...")
                    update_calibre_metadata(calibredb_path, directory, book_id, llm_data)
                else:
                    print("    -> Echec lors de la génération par le LLM.")

    print("\n================= RÉSUMÉ ======================")
    print(f"Fichiers metadata.opf parcourus : {nb_fichiers_opf_trouves}")
    print(f"-> Ignorés car sans ID Calibre  : {nb_sans_id}")
    print(f"-> Ignorés car sans format .pdf : {nb_sans_pdf}")
    print(f"TOTAL Analysés et passés à l'IA : {nb_traites}")
    print("===============================================")


if __name__ == "__main__":
    print("Sélectionnez la racine de votre bibliothèque Calibre (ou de votre exportation)...")
    folder_path = select_directory()
    
    if folder_path:
        print(f"\nBIBLIOTHEQUE: {folder_path}")
        print("Lancement de l'analyse intégrale.\n")
        process_directory(folder_path)
        print("\n=== Terminé ! ===")
    else:
        print("Annulé.")
        
    input("\nAppuyez sur Entrée pour fermer la fenêtre...")
