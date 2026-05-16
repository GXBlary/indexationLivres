# Roadmap - PDFRenamer, Calibre & Neo4j Taxonomy

Ce document trace les évolutions de l'utilitaire d'indexation. Initialement abandonnée, la piste **"Knowledge Graph" (Neo4j, Wikidata) a été officiellement réintégrée et achevée** pour offrir une navigation hiérarchique profonde des mots-clés, couplée à une intelligence artificielle cloud (Gemini) et locale (Ollama).

## 🎯 Statut Actuel

| Composant | Statut | Fichier |
|-----------|--------|---------|
| Extraction Titre/Auteur | ✅ Stable (Gemini 2.5 + Fallback Ollama) | `indexer.py` |
| Traitement Institutions | ✅ Opérationnel | `indexer.py` |
| Extraction Résumé/Keywords | ✅ Stable (Gemini 2.5 + Fallback Ollama) | `indexer.py` |
| Renommage FS Safe | ✅ Stable | `indexer.py` |
| Indexation Calibre | ✅ Opérationnel (`calibredb`) | `indexer.py` |
| Taxonomie Hiérarchique | ✅ En prod. (LOD: Wikidata LoC/Dewey/BISAC) | `indexer.py` |
| Optimisation Coûts | ✅ Gemini Batch API intégré | `indexer.py` |
| Visualisation Neo4j | ✅ Opérationnel (Base 'tags') | `export_to_neo4j.py` |

---

## 🚀 Évolutions Morales & Techniques (Backlog)

### 1. Robustesse de l'Orchestration Calibre
- **Problème** : Gérer proprement les messages d'erreur si `calibredb` n'est pas dans le PATH.
- **Idée** : Vérifier la disponibilité de la CLI au démarrage de l'application plutôt que lors du traitement du premier fichier.

### 2. Gestion Avancée des Fichiers dans Calibre
- **Actuel** : Le fichier PDF original est bien déplacé dans le sous-dossier `indexed/` de l'espace de travail après succès de l'extraction, et Calibre le copie dans sa propre bibliothèque.
- **Idée** : Valider via le statut de retour de `calibredb` que l'import a bien fonctionné *avant* de déplacer le fichier dans `indexed/` afin de garantir qu'aucun document n'est archivé s'il n'est pas sécurisé dans Calibre.

### 3. Modélisation LLM & Structuration Pydantic
- **Actuel** : Transition réussie vers un modèle hybride : **Gemini 2.5 Flash** (via SDK `google.genai` avec Pydantic Structuring) couplé à un `TokenBucket` anti-quota, et **Ollama (Qwen2.5 7B)** en fallback de sécurité.
- **Prochaine Étape** : Monitorer à long terme les temps de réponse et l'impact sur le "Daily Quota" gratuit de Gemini pour rééquilibrer le trafic Cloud/Local si nécessaire.

### 4. Audit & Rationalisation de la Taxonomie
- **Statut** : En cours.
- **Objectif** : Utiliser le `consistency_report.md` pour identifier les feuilles orphelines et les conflits de branches.
- **Action** : Finaliser l'indexation globale via la logique Wikidata forcée pour établir un baseline propre avant toute intervention manuelle.
