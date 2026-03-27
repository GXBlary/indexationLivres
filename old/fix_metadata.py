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
    """Ouvre une boîte de dialogue Windows pour sélectionner un dossier."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    directory = filedialog.askdirectory(title="Sélectionnez le dossier racine de la bibliothèque Calibre")
    return directory

def get_calibredb_path():
    """Cherche l'exécutable calibredb sur le système Windows."""
    # On teste plusieurs chemins courants d'installation de Calibre
    common_paths = [
        "calibredb", # Si calibre est dans le PATH de Windows
        r"C:\Program Files\Calibre2\calibredb.exe",
        r"C:\Program Files (x86)\Calibre2\calibredb.exe"
    ]
    for p in common_paths:
        try:
            # On vérifie juste si calibredb version s'exécute sans crasher
            subprocess.run([p, '--version'], capture_output=True, check=True)
            return p
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None

def extract_text_from_pdf(pdf_path, num_pages=2):
    """Extrait le texte des premières pages de l'article PDF."""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(num_pages, len(doc))):
            text += doc[i].get_text()
        doc.close()
    except Exception as e:
        print(f"Erreur lors de la lecture du PDF {pdf_path}: {e}")
    return text

def get_author_from_llm(opf_content, article_text):
    """Envoie le fichier OPF ET le texte de l'article au LLM pour trouver l'auteur."""
    prompt = f"""
Voici le contenu d'un fichier de métadonnées (metadata.opf) et le texte extrait des premières pages de l'article (PDF) associé.
L'auteur est actuellement "Inconnu(e)".
À partir de ces deux éléments (surtout le texte de l'article où figurent souvent les auteurs), trouve le nom exact du premier auteur.
Réponds UNIQUEMENT avec un objet JSON valide, sans blabla.
Format attendu:
{{
    "auteur": "Prénom Nom"
}}

Contenu du fichier OPF :
{opf_content[:1500]}

Texte extrait de l'article PDF :
{article_text[:3000]}
"""
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'user',
                'content': prompt
            }
        ], format='json')
        
        result = json.loads(response['message']['content'])
        return result.get('auteur', '').strip()
    except Exception as e:
        print(f"Erreur avec le LLM: {e}")
        return ""

def process_directory(directory):
    if not os.path.exists(directory):
        print(f"Le dossier {directory} n'existe pas.")
        return

    # On vérifie si l'outil calibredb est accessible
    calibredb_path = get_calibredb_path()
    if not calibredb_path:
        print("ATTENTION: calibredb n'a pas été trouvé sur le système. La base de données Calibre ne sera pas mise à jour automatiquement.")
    else:
        print(f"Outil calibredb trouvé : {calibredb_path}")

    for root_dir, dirs, files in os.walk(directory):
        for filename in files:
            if filename.lower() == 'metadata.opf':
                file_path = os.path.join(root_dir, filename)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception as e:
                    print(f"Impossible de lire {file_path} : {e}")
                    continue
                
                target_string = '<dc:creator opf:file-as="Inconnu(e)" opf:role="aut">Inconnu(e)</dc:creator>'
                
                if target_string in content:
                    print(f"\n=======================================================\n[!] Auteur inconnu détecté dans : {file_path}")
                    
                    # 1. Chercher le fichier PDF dans le même répertoire que metadata.opf
                    article_text = ""
                    for sibling in files:
                        if sibling.lower().endswith('.pdf'):
                            pdf_path = os.path.join(root_dir, sibling)
                            print(f"  -> Analyse en complément du PDF trouvé : {sibling}")
                            article_text = extract_text_from_pdf(pdf_path, num_pages=2)
                            break  # On ne prend qu'un seul PDF
                    
                    if not article_text.strip():
                        print("  -> (Aucun texte de PDF n'a pu être extrait pour aider le LLM)")
                    
                    # 2. Demander au LLM
                    auteur = get_author_from_llm(content, article_text)
                    
                    # 3. Mettre à jour si un auteur a été trouvé
                    if auteur and auteur.lower() not in ["", "inconnu", "inconnue", "inconnu(e)"]:
                        print(f"  -> Auteur généré par le LLM : {auteur}")
                        
                        replacement_string = f'<dc:creator opf:file-as="{auteur}" opf:role="aut">{auteur}</dc:creator>'
                        new_content = content.replace(target_string, replacement_string)
                        
                        try:
                            # Sauvegarder d'abord le fichier OPF physique
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(new_content)
                            print(f"  -> Fichier metadata.opf local '[OK]' mis à jour.")
                            
                            # Mise à jour de la Base de données de l'application Calibre
                            if calibredb_path:
                                # Calibre identifie chaque livre/article par un ID précis contenu dans le OPF
                                id_match = re.search(r'<dc:identifier opf:scheme="calibre">(\d+)</dc:identifier>', content)
                                if id_match:
                                    book_id = id_match.group(1)
                                    print(f"  -> ID interne Calibre détecté : {book_id}. Mise à jour de la DB Calibre...")
                                    
                                    # La commande calibredb équivaut à taper dans le terminal:
                                    # calibredb set_metadata --with-library "C:\Mon\Dossier Calibre" 123 "C:\...\metadata.opf"
                                    result = subprocess.run(
                                        [calibredb_path, 'set_metadata', '--with-library', directory, book_id, file_path],
                                        capture_output=True, text=True
                                    )
                                    
                                    if result.returncode == 0:
                                        print("  -> Base de données Calibre synchronisée avec succès '[OK]'.")
                                    else:
                                        print(f"  -> ERREUR Calibre: {result.stderr.strip()}")
                                else:
                                    print("  -> Impossible de trouver l'identifiant <dc:identifier opf:scheme='calibre'> dans le OPF. DB non mise à jour.")

                        except Exception as e:
                            print(f"  -> Erreur lors de l'écriture : {e}")
                    else:
                        print("  -> Le LLM n'a pas réussi à déterminer l'auteur de manière certaine. Fichier inchangé.")

if __name__ == "__main__":
    print("Veuillez sélectionner le dossier racine de votre bibliothèque Calibre dans la fenêtre (Outils Windows)...")
    folder_path = select_directory()
    
    if folder_path:
        print(f"\nBibliothèque sélectionnée : {folder_path}")
        print("Analyse en cours, cela peut prendre un certain temps selon la taille de la bibliothèque...\n")
        process_directory(folder_path)
        print("\nAnalyse terminée !")
    else:
        print("Aucun dossier sélectionné. Opération annulée.")
