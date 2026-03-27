# Roadmap – Thesaurus Pipeline

## Statut Actuel

| Composant | Statut | Fichier |
|-----------|--------|---------|
| Phase 1 – Extraction LLM | ✅ Stable | `build_taxonomy.py` |
| Phase 2 – Nettoyage NLP | ⚠️ À revoir (pyspellchecker nocif) | `build_taxonomy.py` |
| Phase 2.5 – Skeleton Discovery | 🔲 À implémenter | — |
| Phase 3 – Catégorisation LLM | ⚠️ À revoir (batches incohérents) | `build_taxonomy.py` |
| Cache concepts | ✅ Disponible | `concepts_cache.json` (~899 termes) |

---

## Hypothèses Alternatives pour Phase 2.5 (Skeleton Discovery)

### H1 : TF-IDF + Clustering Hiérarchique Agglomératif (Ward)

| | |
|---|---|
| **Technique** | Vectorisation TF-IDF sur les n-grams des concepts, puis Ward HAC avec seuil de distance |
| **Avantages** | Déterministe, reproductible, léger (scikit-learn), pas de LLM, contrôle du nombre de clusters via le seuil |
| **Inconvénients** | TF-IDF est lexical (pas sémantique) : "Machine Learning" et "Deep Learning" pourraient être séparés si les mots sont trop différents |
| **Labellisation** | Terme le plus proche du centroïde |
| **Bénéfice attendu** | 8-12 clusters stables et reproductibles |

### H2 : Embeddings spaCy (en_core_web_md) + K-Means

| | |
|---|---|
| **Technique** | Vecteurs denses spaCy (300 dim) + K-Means avec silhouette score pour choisir K |
| **Avantages** | Sémantique : capture que "ML" et "Deep Learning" sont proches même sans mots communs |
| **Inconvénients** | Les vecteurs spaCy `sm` sont faibles ; nécessite `md` ou `lg` (~40-90 MB). K-Means impose de fixer K a priori (silhouette peut aider) |
| **Labellisation** | Terme le plus proche du centroïde dans l'espace embedding |
| **Bénéfice attendu** | Clusters plus sémantiquement cohérents que H1 |

### H3 : LDA (Latent Dirichlet Allocation)

| | |
|---|---|
| **Technique** | Topic modeling sur les termes traités comme des "documents courts" |
| **Avantages** | Produit des topics avec des mots-clés pondérés → labels naturels |
| **Inconvénients** | LDA fonctionne mal sur des documents très courts (2-3 mots par concept). Nécessite un corpus de phrases pour être efficace |
| **Labellisation** | Mots les plus probables du topic |
| **Bénéfice attendu** | Limité sur ce type de données |

### H4 : Hybride TF-IDF + Embeddings (Concaténation)

| | |
|---|---|
| **Technique** | Concaténer les vecteurs TF-IDF (lexicaux) et spaCy (sémantiques), puis HAC |
| **Avantages** | Combine la précision lexicale (acronymes, noms propres) et la proximité sémantique |
| **Inconvénients** | Plus complexe, nécessite normalisation des dimensions |
| **Labellisation** | Double centroïde |
| **Bénéfice attendu** | Meilleur compromis, mais complexité accrue |

---

## Hypothèses pour Phase 2 (Nettoyage Amélioré)

### Remplacement de pyspellchecker

| Alternative | Description | Bénéfice |
|-------------|-------------|----------|
| **Filtrage POS-tag spaCy** | Ne garder que NOUN, PROPN, ADJ | Élimine les verbes/adverbes parasites sans corrompre le vocabulaire technique |
| **Whitelist technique** | Maintenir manuellement une liste de termes techniques protégés | Précis mais non scalable |
| **Pas de correction orthographique** | Faire confiance au LLM d'extraction (Phase 1) | Simple ; la qualité de `concepts_cache.json` montre que c'est suffisant |

---

## Hypothèses pour Phase 3 (Catégorisation)

### Dispatch vs. Génération libre

| Approche | Description | Bénéfice |
|----------|-------------|----------|
| **Dispatch imposé** (Recommandé) | Le LLM reçoit le squelette JSON pré-rempli et ne fait que créer des sous-catégories | Pas de catch-all, pas de duplication, structure cohérente |
| **Génération libre batchée** (V2 actuelle) | Le LLM invente la structure à chaque batch | Flexible mais incohérent |
| **Dispatch + sous-catégorisation récursive** | Phase 3a : dispatch dans les racines. Phase 3b : pour chaque racine >30 concepts, demander au LLM de créer des sous-catégories | Profondeur contrôlée |

---

## Construction du Squelette JSON (Phase 2.5)

### Pré-remplissage des clusters

Le clustering (H1/H2/H4) produit directement un dict `{label: [concepts]}` déjà **pré-rempli** avec les concepts de `concepts_cache.json`.

```
Entrée  : concepts_cache.json (899 termes)
          ↓ TF-IDF / Embeddings
          ↓ HAC (Ward, seuil auto)
Sortie  : skeleton.json = {
              "Artificial Intelligence": ["Deep Learning", "Reinforcement Learning", ...],
              "Digital Transformation": ["Digital Strategy", "Digital Maturity", ...],
              ...
          }
```

Ce squelette sert ensuite de **contrainte structurelle** pour la Phase 3 :
- Le LLM ne peut PAS créer de nouvelles catégories racines
- Il ne peut QUE sous-catégoriser les concepts déjà assignés
- Chaque concept appartient à exactement un cluster (exclusivité garantie par le clustering)

### Questions ouvertes

1. **Quelle profondeur de sous-catégorisation ?** Faut-il limiter à 2-3 niveaux ou laisser le LLM décider ?
2. **Combien de clusters ?** Seuil automatique (dendrogramme) vs. K fixe ?
3. **Faut-il une passe de validation humaine** sur le squelette avant la Phase 3 ?
