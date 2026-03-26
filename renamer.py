import os
import fitz  # PyMuPDF
import ollama
import json
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog

# Modèle recommandé
MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"

def extract_text_from_pdf(pdf_path, num_pages=2):
    """Extrait le texte des premières pages du PDF."""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(num_pages, len(doc))):
            text += doc[i].get_text()
        doc.close()
    except Exception as e:
        print(f"Erreur lors de la lecture de {pdf_path}: {e}")
    return text

def get_metadata_from_llm(text):
    """Envoie le texte à Ollama et récupère le JSON."""
    prompt = f"""
Voici le texte extrait des premières pages d'un document PDF (souvent un article scientifique ou un livre).
Ta tâche est de trouver le titre principal du document et le nom du premier auteur.
Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte avant ou après.
Format attendu:
{{
    "titre": "Titre du document",
    "auteur": "Nom du premier auteur, Prénom du premier auteur"
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
        
        result = json.loads(response['message']['content'])
        return result.get('titre', '').strip(), result.get('auteur', '').strip()
    except Exception as e:
        print(f"Erreur avec le LLM: {e}")
        return "", ""

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

def process_directory(directory):
    if not os.path.exists(directory):
        print(f"Le dossier {directory} n'existe pas.")
        return

    for filename in os.listdir(directory):
        # On ignore les fichiers .py ou autre pour ne prendre que les pdfs
        if filename.lower().endswith('.pdf'):
            file_path = os.path.join(directory, filename)
            print(f"\nTraitement de : {filename}")
            
            text = extract_text_from_pdf(file_path, num_pages=2)
            if not text.strip():
                print(f"  -> PDF sans texte ou image scannée. Ignoré (à faire manuellement).")
                continue
                
            titre, auteur = get_metadata_from_llm(text)
            
            if titre and auteur:
                clean_titre = sanitize_filename(titre)
                clean_auteur = sanitize_filename(auteur)
                
                # Nom de base sans extension, tronqué si trop long pour Windows (~250 car max)
                base_new_name = f"{clean_auteur}_{clean_titre}"[:240]
                
                # Vérifier les doublons
                new_filename, new_file_path = get_unique_filename(directory, base_new_name)
                
                if file_path == new_file_path:
                    print("  -> Le fichier a déjà le bon nom.")
                    continue
                
                try:
                    os.rename(file_path, new_file_path)
                    print(f"  -> Renommé avec succès en : {new_filename}")
                except Exception as e:
                    print(f"  -> Erreur lors du renommage : {e}")
            else:
                print(f"  -> Informations incomplètes renvoyées par le LLM (Auteur: {auteur}, Titre: {titre}).")

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
