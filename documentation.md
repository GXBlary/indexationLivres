# PDFRenamer & Calibre Indexer

Ce projet est un utilitaire d'automatisation locale. Son but est d'analyser des documents PDF bruts, d'en extraire les métadonnées principales (Titre, Auteur, Résumé, Mots-clés) grâce à un modèle NLP local, de le renommer proprement pour garantir sa compatibilité système, et de l'indexer automatiquement dans **Calibre**.

## Fonctionnement Central (`indexer.py`)

### 1. Analyse Locale 
L'outil s'appuie sur `Ollama` et le modèle `qwen2.5:7b-instruct-q4_K_M` pour extraire intelligemment :
- **Titre**,
- **Auteur** (avec une logique spéciale pour identifier les publications d'Institutions comme McKinsey ou l'OCDE),
- **Résumé** (récupération de l'Abstract d'origine s'il existe),
- **Mots-clés / Tags**.

### 2. Renommage Qualitatif
Les PDF sont renommés sur le format `Auteur_-_Titre.pdf`.
Le script retire les diacritiques, remplace les espaces par des underscores, et gère les potentiels doublons en ajoutant un suffixe numérique.

### 3. Indexation Calibre
Le script s'interface avec la CLI de Calibre (`calibredb`) pour :
- Ajouter le PDF à la bibliothèque,
- Injecter les `Tags` et les `Comments` (Résumé),
- Assigner directement l'Auteur et le Titre conformes dans l'outil.

### 4. Alignement de Taxonomie LOD (Wikidata & Gemini)
Pour éviter l'accumulation de tags plats et incohérents, le script intègre un moteur d'alignement hiérarchique :
- **Wikidata First** : Utilisation des propriétés professionnelles **LoC (Library of Congress)**, **Dewey (DDC)** et **BISAC** pour ancrer les tags dans des ontologies standardisées.
- **Gemini Batch Optimization** : Utilisation de l'API Batch de Google pour traiter des milliers de tags à bas coût et haute vitesse.
- **Hygiène Strict** : Limitation à 5 niveaux de profondeur et expansion automatique des acronymes (ex: NLP -> Natural Language Processing).

## Installation & Configuration

1. **Environnement** : Installez un environnement Python et installez les prérequis (notamment `pymupdf`, `ollama` et `python-dotenv`).
2. **Variables d'environnement** : Configurez votre fichier `.env` à la racine :
   ```env
   # Chemin optionnel si différentes bibliothèques Calibre existent
   CALIBRE_LIBRARY_PATH="D:\Chemin\Vers\Bibliotheque"
   ```
3. **Calibre CLI** : Assurez-vous que l'exécutable de Calibre (`calibredb`) est disponible dans le `PATH` Windows.
4. **Ollama** : Assurez-vous qu'Ollama tourne en fond avec le modèle requis.

## Utilisation

Déposez vos PDF dans n'importe quel dossier (ex: `Inbox/`) puis lancez le script en exécutant :
```bash
python indexer.py
```
Un sélecteur de dossier s'ouvrira, choisissez le répertoire contenant les PDF à traiter et le script fera l'ingestion automatiquement.
