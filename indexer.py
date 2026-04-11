import os
import fitz  # PyMuPDF
import ollama
import json
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog
import subprocess
import shutil
import sys
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

# Vérification Calibre
if not shutil.which("calibredb"):
    print("================================================================")
    print("ERREUR FATALE : 'calibredb' n'a pas été trouvé dans votre système.")
    print("Veuillez installer Calibre et ajouter son dossier d'installation ")
    print("à vos variables d'environnement (PATH) Windows.")
    print("================================================================")
    sys.exit(1)

# Configuration
MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"
CALIBRE_LIBRARY_PATH = os.getenv("CALIBRE_LIBRARY_PATH")

def get_calibre_tags():
    """Récupère l'ensemble des tags uniques existants dans Calibre."""
    print("-> Récupération du dictionnaire de mots-clés Calibre existant...")
    cmd = ["calibredb", "list", "-f", "tags", "--for-machine"]
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        tags = set()
        for item in data:
            for t in item.get('tags', []):
                tags.add(t.strip())
        print(f"   ({len(tags)} tags uniques trouvés)")
        return list(tags)
    except Exception as e:
        print(f"  -> [Avertissement] Impossible de récupérer les tags Calibre actuels : {e}")
        return []

def extract_text_from_document(file_path, num_pages=2):
    """Extrait le texte des premières pages du document (PDF ou EPUB)."""
    text = ""
    try:
        # PyMuPDF supporte nativement le PDF, EPUB, XPS, etc.
        doc = fitz.open(file_path)
        for i in range(min(num_pages, len(doc))):
            text += doc[i].get_text()
        doc.close()
    except Exception as e:
        print(f"Erreur lors de la lecture de {file_path}: {e}")
    return text

def get_metadata_from_llm(text, global_tags):
    """Envoie le texte à Ollama et récupère le JSON en s'alignant sur les tags."""
    
    if global_tags:
        # On limite le nombre de tags injectés pour ne pas saturer la fenêtre de contexte du LLM
        tags_str = ", ".join(global_tags[:250]) 
        tags_instruction = f"Limitation: Choisis 3 à 5 mots-clés en piochant PRIORITAIREMENT dans cette liste officielle de tags existants : [{tags_str}]. Si aucun tag ne correspond au sujet du document, tu es autorisé à en proposer des nouveaux, très génériques et pertinents."
    else:
        tags_instruction = "Génère 3 à 5 mots-clés techniques ou thématiques pertinents."

    prompt = f"""
Tu es un bibliothécaire expert traitant principalement des articles scientifiques et professionnels. 
Voici le texte extrait des premières pages d'un document (PDF ou EPUB).
Ta tâche est d'extraire le titre principal, l'auteur, le résumé (abstract) et les mots-clés (keywords).

Règles strictes :
1. "titre" : Le titre exact du document. Tronque-le s'il est démesurément long.
2. "auteur" : Extrais de préférence le nom de famille suivi de l'initiale du prénom (ex: "Einstein_A"). ATTENTION : Si le document provient d'une institution ou entreprise (ex: McKinsey, Gartner, OCDE, Kpmg), utilise UNIQUEMENT le nom de l'institution comme auteur. Si l'auteur ou l'institution est absolument introuvable après analyse du texte, utilise exactement "Anonymous".
3. "resume" : Le résumé DOIT IMPÉRATIVEMENT ÊTRE EN ANGLAIS. S'il y a une section "Abstract" dans le document, recopie-le EXACTEMENT en gardant ou traduisant en anglais. S'il n'y en a pas, rédige un court résumé factuel EN ANGLAIS.
4. "mots_cles" : Les mots-clés DOIVENT IMPÉRATIVEMENT ÊTRE EN ANGLAIS sous forme de liste. {tags_instruction}
5. Format : Réponds UNIQUEMENT avec un objet JSON valide. Ne génère pas de markdown ni aucun texte autour.

Format attendu:
{{
    "titre": "Titre exact du document",
    "auteur": "NomAuteur ou Institution",
    "resume": "Abstract in English...",
    "mots_cles": ["Keyword 1", "Keyword 2", "Keyword 3"]
}}

Texte :
{text[:3000]}
"""
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'user',
                'content': prompt
            }
        ], format='json')
        
        raw_response = response['message']['content']
        cleaned = raw_response.replace('```json', '').replace('```', '').strip()
        
        result = json.loads(cleaned)
        return (
            result.get('titre', '').strip(), 
            result.get('auteur', '').strip(), 
            result.get('resume', '').strip(),
            result.get('mots_cles', [])
        )
    except Exception as e:
        print(f"Erreur avec le LLM ou le JSON: {e}")
        return "", "", "", []

def sanitize_filename(filename):
    """Supprime les diacritiques, remplace les espaces par des underscores, et supprime les caractères invalides."""
    # 1. Enlever les accents/diacritiques (ex: 'é' -> 'e', 'ç' -> 'c')
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('utf-8')
    # 2. Remplacer les espaces et tirets par des underscores
    filename = re.sub(r'[\s\-]+', '_', filename)
    # 3. Supprimer tout ce qui n'est pas alphanumérique ou underscore
    filename = re.sub(r'[^a-zA-Z0-9_]', '', filename)
    # 4. S'assurer qu'il n'y a pas de multiples underscores consécutifs
    filename = re.sub(r'_+', '_', filename)
    return filename.strip('_')

def get_unique_filename(directory, base_name, extension=".pdf"):
    """Génère un nom de fichier unique en ajoutant un suffixe numérique si nécessaire."""
    counter = 1
    new_filename = f"{base_name}{extension}"
    new_file_path = os.path.join(directory, new_filename)
    
    # Si le fichier existe déjà, on ajoute _1, _2, etc.
    while os.path.exists(new_file_path):
        new_filename = f"{base_name}_{counter}{extension}"
        new_file_path = os.path.join(directory, new_filename)
        counter += 1
        
    return new_filename, new_file_path

def check_calibre_duplicate(title):
    """Recherche si un document existe déjà dans Calibre avec ce titre exact."""
    # Échapper les guillemets pour éviter de casser la ligne de commande
    safe_title = title.replace('"', '\\"')
    cmd = ["calibredb", "search", f'title:"={safe_title}"']
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        if out:
            # Calibre retourne les IDs trouvés séparés par des virgules
            ids = [x.strip() for x in out.split(',')]
            if ids and ids[0].isdigit():
                return ids[0]
    except Exception as e:
        print(f"  -> [Avertissement] Erreur lors de la recherche de doublon dans Calibre : {e}")
    return None

def update_calibre_metadata(book_id, summary, keywords):
    """Vérifie les métadonnées existantes via OPF et met à jour uniquement les champs vides."""
    cmd = ["calibredb", "show_metadata", book_id, "--as-opf"]
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
        
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        opf_data = result.stdout
        
        # Le namespace officiel de Dublin Core dans l'OPF de Calibre
        namespaces = {'dc': 'http://purl.org/dc/elements/1.1/'}
        root = ET.fromstring(opf_data)
        
        desc_node = root.find(".//dc:description", namespaces)
        has_summary = desc_node is not None and desc_node.text and desc_node.text.strip()
        
        subj_nodes = root.findall(".//dc:subject", namespaces)
        has_tags = len(subj_nodes) > 0
        
        updates = []
        if not has_summary and summary:
            updates.extend(["--field", f"comments:{summary}"])
        if not has_tags and keywords:
            tags_str = ",".join(keywords) if isinstance(keywords, list) else str(keywords)
            updates.extend(["--field", f"tags:{tags_str}"])
            
        if updates:
            print(f"  -> [Mise à jour Calibre] Ajout des métadonnées (Résumé / Tags) manquantes pour l'ID {book_id}...")
            update_cmd = ["calibredb", "set_metadata", book_id] + updates
            if CALIBRE_LIBRARY_PATH:
                update_cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
            subprocess.run(update_cmd, capture_output=True, text=True, check=True)
            print("  -> [Succès Calibre] Métadonnées complétées avec succès.")
        else:
            print(f"  -> [Calibre] Le document ID {book_id} a déjà son résumé et ses mots-clés de renseignés. Aucune modification.")
            
    except Exception as e:
        print(f"  -> [Avertissement] Échec de la lecture ou de la mise à jour OPF (ID {book_id}) : {e}")

def add_to_calibre(file_path, title, author, summary, keywords):
    """Indexe le document dans Calibre. Met à jour si doublon."""
    print(f"  -> Vérification des doublons par Titre : {title}")
    book_id = check_calibre_duplicate(title)
    
    if book_id:
        print(f"  -> [Doublon Calibre] Le document '{title}' est déjà au catalogue (ID: {book_id}). Fichier ignoré.")
        update_calibre_metadata(book_id, summary, keywords)
        return
        
    print(f"  -> Ajout d'un nouveau document dans Calibre...")
    cmd = ["calibredb", "add", file_path, "--title", title, "--authors", author]
    
    if summary:
        cmd.extend(["--comments", summary])
        
    if keywords:
        # Calibre attend les tags sous forme de chaîne séparée par des virgules
        tags_str = ",".join(keywords) if isinstance(keywords, list) else str(keywords)
        cmd.extend(["--tags", tags_str])
        
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
        
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  -> [Succès Calibre] {result.stdout.strip().splitlines()[-1] if result.stdout else 'Ajouté.'}")
    except subprocess.CalledProcessError as e:
        print(f"  -> [Erreur Calibre] Échec de l'indexation. {e.stderr.strip()}")

def process_directory(directory):
    if not os.path.exists(directory):
        print(f"Le dossier {directory} n'existe pas.")
        return

    # Récupérer les tags existants au démarrage pour tout le dossier
    global_tags = get_calibre_tags()

    files_to_process = [f for f in os.listdir(directory) if f.lower().endswith(('.pdf', '.epub'))]
    total_files = len(files_to_process)
    
    if total_files == 0:
        print(f"\nAucun fichier PDF ou EPUB trouvé dans le dossier {directory}.")
        return

    print(f"\n=======================================================")
    print(f"  Début du traitement de {total_files} document(s)...")
    print(f"=======================================================")

    for i, filename in enumerate(files_to_process, 1):
        file_path = os.path.join(directory, filename)
        print(f"\n[{i}/{total_files}] Traitement de : {filename}")
        print("  -> Extraction du texte par PyMuPDF...")
        
        text = extract_text_from_document(file_path, num_pages=2)
        if not text.strip():
            print(f"  -> [Ignoré] Document sans texte détectable ou image scannée.")
            continue
            
        # Si le fichier semble déjà avoir été renommé par nos soins, on esquive le LLM
        if "_-_" in filename:
            print("  -> [Bypass] Fichier déjà renommé (présence de '_-_'). Extraction directe depuis le nom.")
            name_part = os.path.splitext(filename)[0]
            parts = name_part.split("_-_", 1)
            auteur = parts[0].replace("_", " ").strip()
            titre = parts[1].replace("_", " ").strip()
            resume, mots_cles = "", []
        else:
            print("  -> Interrogation de l'IA locale (Ollama), merci de patienter...")
            titre, auteur, resume, mots_cles = get_metadata_from_llm(text, global_tags)
        
        if titre and auteur:
            clean_titre = sanitize_filename(titre)
            clean_auteur = sanitize_filename(auteur)
            
            # Nom de base sans extension, tronqué à 120 caractères max
            base_new_name = f"{clean_auteur}_-_{clean_titre}"[:120]
            
            # Vérifier les doublons physiques pour le renommage
            new_filename, new_file_path = get_unique_filename(directory, base_new_name, os.path.splitext(filename)[1])
            
            if file_path != new_file_path:
                try:
                    os.rename(file_path, new_file_path)
                    print(f"  -> Renommé avec succès en : {new_filename}")
                    file_path = new_file_path
                except Exception as e:
                    print(f"  -> Erreur lors du renommage : {e}")
            else:
                print("  -> Le fichier a déjà le bon format de nom sur le disque.")

            # Indexation dans Calibre
            add_to_calibre(file_path, title=titre, author=auteur, summary=resume, keywords=mots_cles)
        else:
            print(f"  -> [Erreur] Informations incomplètes (Auteur: {auteur}, Titre: {titre}).")
            
    print(f"\n=======================================================")
    print(f"  Terminé : {total_files} document(s) analysé(s).")
    print(f"=======================================================")

def select_directory():
    """Ouvre une boîte de dialogue Windows pour sélectionner un dossier."""
    root = tk.Tk()
    root.withdraw() # Masquer la petite fenêtre principale Tkinter
    root.attributes('-topmost', True) # S'assurer que la fenêtre est bien visible au premier plan
    
    directory = filedialog.askdirectory(title="Sélectionnez le dossier contenant les PDFs à renommer")
    return directory

if __name__ == "__main__":
    print("Veuillez sélectionner le dossier dans la fenêtre (Outils Windows) qui vient de s'ouvrir...")
    folder_path = select_directory()
    
    if folder_path:
        print(f"Dossier sélectionné : {folder_path}")
        process_directory(folder_path)
    else:
        print("Aucun dossier sélectionné. Opération annulée.")
