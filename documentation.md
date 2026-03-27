# Industrial Knowledge Graph Pipeline (V6/V7)

This project implements a deterministic, high-precision pipeline for mining semantic ontologies and building a Knowledge Graph from PDF documents.

## Workflow Orchestration

The entire pipeline is controlled via the central orchestrator:
`python main_pipeline.py`

This menu allows you to run the full sequence or selective steps.

---

## Pipeline Components

### Étape 0 : Renommage des Fichiers (`renamer.py`)
Nettoie les noms de fichiers PDF en utilisant le LLM pour extraire le titre et l'auteur. 
- **Sortie** : `Auteur_Titre_du_Document.pdf` (normalisé sans accents).

### Étape 1 : Construction de la Taxonomie (`build_taxonomy.py`)
Génère la **T-Box** (le schéma) via l'algorithme de **Semantic Gravity Clustering**.
- **Moteur** : Sentence-Transformers (`all-MiniLM-L6-v2`).
- **Sortie** : `thesaurus.json` (Taxonomie à 12 racines + Quarantaine d'Outliers).

### Étape 2 : Extraction & Enrichissement (`fix_metadata_v5.py`)
Moteur principal d'extraction **Open IE** utilisant Pydantic et un ancrage asymétrique à 3 niveaux :
1. **Ancrage Local** : Raccordement aux racines de la T-Box locale.
2. **LOD Fallback** : Réconciliation avec l'API REST Wikidata pour canonisation et Entity Linking (Q-ID).
3. **True Outlier** : Conservation du texte brut pour les concepts émergents.
- **Sortie** : Nœuds et Relations Markdown dans `Obsidian_Vault/`.

### Utilitaire : Maintenance du Thésaurus (`thesaurus_manager.py`)
Post-traitement du thésaurus pour intégrer les nouveaux concepts.
- **NLP** : Lemmatisation spaCy pour supprimer les pluriels et les verbes.
- **Vector Routing** : Auto-catégorisation via FAISS (seuil 0.91).
- **SLM Recovery** : Classification par lot via Qwen pour les cas complexes.

---

## Configuration
- **Model** : `qwen2.5:7b-instruct-q4_K_M`
- **Embeddings** : `nomic-embed-text` (Local)
- **Local Model Path** : `./models/all-MiniLM-L6-v2` (for gravity clustering)

---

## Glossary
- **T-Box** : Terminological Box (Schema/Ontology).
- **A-Box** : Assertion Box (The actual triplets extracted from document text).
- **Semantic Gravity** : Scoring based on Document Frequency combined with Local Semantic Density.
- **Entity Canonization** : Matching a raw term to a universal Wikidata identifier (Q-ID).
