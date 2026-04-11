# Roadmap - PDFRenamer & Calibre

Ce document trace les évolutions passées et futures de l'utilitaire d'indexation. La piste "Knowledge Graph V7" (Neo4j, Extracteurs IE, Wikidata) a été abandonnée avec succès au profit d'une focalisation sur un utilitaire propre de renommage.

## 🎯 Statut Actuel

| Composant | Statut | Fichier |
|-----------|--------|---------|
| Extraction Titre/Auteur | ✅ Stable (LLM Local) | `indexer.py` |
| Traitement Institutions | ✅ Opérationnel | `indexer.py` |
| Extraction Résumé/Keywords | ✅ Opérationnel | `indexer.py` |
| Renommage FS Safe | ✅ Stable | `indexer.py` |
| Indexation Calibre | ✅ Opérationnel (`calibredb`) | `indexer.py` |

---

## 🚀 Évolutions Morales & Techniques (Backlog)

### 1. Robustesse de l'Orchestration Calibre
- **Problème** : Gérer proprement les messages d'erreur si `calibredb` n'est pas dans le PATH.
- **Idée** : Vérifier la disponibilité de la CLI au démarrage de l'application plutôt que lors du traitement du premier fichier.

### 2. Gestion Avancée des Fichiers (Post-Check)
- **Actuel** : Le fichier original est conservé dans le dossier sélectionné après indexation, il n'est renommé que sur place. Calibre le duplique.
- **Idée** : Ajouter un système de déplacement automatisé (vers un dossier de type `Inbox_Archive/`) ou proposer de supprimer le fichier original *seulement* si l'ajout Calibre retourne un statut `[Succès]`.

### 3. Modélisation LLM
- **Actuel** : Qwen 2.5 7B.
- **Idée** : Monitorer les temps de réponse pour voir s'il serait pertinent de scinder l'extraction métadonnées via un modèle encore plus léger (Phi-3, Gemma-2B) et plus focalisé sur le formatage JSON pour de petits chunks.
