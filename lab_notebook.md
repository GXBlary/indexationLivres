# Lab Notebook — Knowledge Graph Ontology Pipeline

## Project Context — Ontology Mining

This project is an **ontology mining** pipeline. The goal is to build a Knowledge Graph that enables transversal exploitation and inference of new knowledge from an unstructured document corpus (~311 documents, Calibre library).

The knowledge concentration funnel is:

```
Documents (PDF)                    ← raw corpus
    ↓ LLM summarization
resumes.json (311 summaries)       ← concentrated knowledge
    ↓ LLM keyword extraction
concepts_cache.json (~900 terms)   ← atomic concepts
    ↓ clustering / categorization
thesaurus.json (nested taxonomy)   ← T-Box / ontology
    ↓ Open IE pipeline (V5)
Knowledge Graph (triplets)         ← exploitable graph (Neo4j / Obsidian)
```

Each stage compresses the knowledge further. The ontology (`thesaurus.json`) serves as the T-Box reference for the entity resolution engine (vector anchoring) during triplet extraction.

**Key architectural decision** : The summaries in `resumes.json` were generated via LLM. This has not yet been challenged but has implications on vocabulary homogeneity (see Experiment 4, LDA analysis).

---

## Experiment 1 — Open IE V5 Pipeline (2026-03-22)

### Hypothesis
A local SLM (Qwen 2.5 7B, 8GB VRAM) can extract structured knowledge triplets from unstructured PDF corpus if the pipeline enforces strict structural validation (Pydantic), ontology control (whitelist/blacklist), and entity resolution (vector anchoring).

### Setup
- **Corpus** : ~311 documents (Calibre library, résumés stockés dans `resumes.json`)
- **Model** : Qwen 2.5:7b-instruct-q4_K_M via Ollama
- **Stack** : Python, Pydantic, spaCy, nomic-embed-text

### Architecture
4 briques séquentielles :
1. **Semantic Chunking** — Découpe au paragraphe (PyMuPDF) avec overlap contextuel (3 derniers paragraphes).
2. **Validation Pydantic (Hard-Fail)** — Le schéma JSON est poussé au LLM pendant l'inférence (Structured Outputs). Erreur → retry automatique.
3. **Contrôle Ontologique (Soft-Fail)** — Blacklist de prédicats vagues (`concerne`, `détaille`). Nouveaux prédicats valides marqués `[À RÉVISER]`. Chargement dynamique depuis `thesaurus.json > Predicates`.
4. **Ancrage Vectoriel (Entity Resolution)** — Cosine similarity (nomic-embed-text) entre entités extraites et registre officiel. Seuil 82-85% → écrasement automatique. `extract_all_strings()` indexe aussi les clés structurelles de l'ontologie.

### Results
- ✅ Triplets structurellement valides (0 crash JSON)
- ✅ Duplication des nœuds réduite de ~70% grâce à l'ancrage vectoriel
- ⚠️ Le thesaurus (`keywords_registry.json` → renommé `thesaurus.json`) se pollue au fil des passages : accumulation dans `Uncategorized_New`

---

## Experiment 2 — Thesaurus Cleanup via SLM (2026-03-26)

### Hypothesis
Un SLM peut nettoyer et restructurer le thesaurus en une passe : pruning du bruit, traduction FR→EN, déduplication, et redistribution dans la taxonomie.

### Setup
- Ajout d'une méthode `clean_thesaurus()` en fin de pipeline
- Traitement séquentiel par catégorie (AI, Business, etc.) pour éviter le context overflow
- Pré-traitement NLP : lemmatisation spaCy (lowercased), scission des mots-clés composés (`and`/`or`), nesting JSON profond

### Results
- ✅ La lemmatisation singularise correctement (`models` → `model`) quand le texte est lowercasé avant parsing
- ⚠️ Catégories fourre-tout persistantes (`AI.Agents`, `General`)
- ⚠️ Dot-notation (`AI.Agents`) au lieu de nesting JSON propre
- ❌ Catégories vides après fusion récursive
- ❌ Termes français résiduels

### Decision
Abandonner la restructuration incrémentale. Reconstruire le thesaurus from scratch depuis `resumes.json`.

---

## Experiment 3 — Thesaurus Rebuild V2 (2026-03-27)

### Hypothesis
Un pipeline en 3 phases (extraction LLM → nettoyage NLP → catégorisation LLM batchée) peut produire une taxonomie nested propre.

### Setup — `build_taxonomy.py`

| Phase | Technique | Durée |
|-------|-----------|-------|
| Phase 1 — Extraction | LLM (Qwen) + Pydantic `ExtractedConcepts`, 3-7 concepts/résumé | ~16 min |
| Phase 2 — Nettoyage | spaCy lemma + pyspellchecker + scission `and`/`or`, filtre ≤4 mots | ~1.5 min |
| Phase 3 — Catégorisation | LLM batché (70 concepts/batch, 13 batches) + `deep_merge()` | ~10 min |

Cache intermédiaire : `concepts_cache.json` sauvegardé entre Phase 2 et 3.

### Results

**Phase 1** ✅ : 1007 concepts bruts extraits. Qualité correcte.

**Phase 2** ❌ `pyspellchecker` corrompt le vocabulaire technique :

| Entrée | "Correction" | Cause |
|--------|-------------|-------|
| Data Governance | Datum Governance | `data` → `datum` (mot anglais archaïque) |
| Cyber Resilience | Caber Resilience | `cyber` inconnu du dictionnaire |
| Agentic AI | Argentic AI | `agentic` inconnu |
| Robo-Advisor | Rob-Advice | double corruption |

**Phase 3** ❌ Le mode `format="json"` libre produit une structure incohérente après deep-merge :

| Problème | Quantité |
|----------|----------|
| Catégories racines | ~60 (attendu : 6-12) |
| Duplication inter-catégories | Même terme dans 5+ catégories |
| Catch-all "General Concepts" | 1 bloc de 40 termes |
| Termes absurdes infiltrés | `Urine`, `Ice`, `Reveille`, `Bullshit Job` |

**Cause racine** : Chaque batch LLM invente sa propre structure. La fusion mécanique (`deep_merge`) accumule toutes les incohérences sans arbitrage.

### Lessons Learned
1. **Ne jamais corriger l'orthographe de termes techniques avec un dictionnaire généraliste**
2. **Ne jamais laisser un LLM inventer une structure libre quand on a besoin de cohérence globale**
3. **Le cache `concepts_cache.json` est un asset précieux** : la Phase 1 est la plus coûteuse et la plus stable

---

## Experiment 4 — Skeleton Discovery (Phase 2.5) — DESIGN PHASE

### Hypothesis
Le clustering non-supervisé sur les données du pipeline peut produire automatiquement les catégories racines, les sous-catégories, et l'assignation exclusive — sans LLM.

### Approach A — HAC sur concepts_cache.json (mots-clés)

Le clustering hiérarchique agglomératif (HAC) produit un **dendrogramme** = un arbre binaire complet :

```
                    [Racine]
                   /        \
          [Cluster A]     [Cluster B]
          /     \          /     \
      [A.1]   [A.2]   [B.1]   [B.2]
       /  \     |       |      /  \
    t1  t2    t3,t4   t5,t6  t7  t8
```

- **Coupe au niveau 1** → catégories racines (8-12 clusters)
- **Coupe au niveau 2** (par cluster) → sous-catégories
- **Feuilles** → concepts assignés (exclusivité garantie)
- **Labels** : terme le plus proche du centroïde, ou n-gram le plus fréquent

**Vectorisation** : TF-IDF (H1) ou embeddings spaCy (H2). Voir `roadmap.md`.

**Limitation** : Les mots-clés sont des termes courts (2-3 mots). La similarité TF-IDF entre "Machine Learning" et "Deep Learning" est faible (aucun mot commun). Les embeddings (H2) capturent mieux cette proximité sémantique.

### Approach B — LDA sur resumes.json (résumés complets)

LDA (Latent Dirichlet Allocation) est un modèle de topic modeling conçu pour des **documents** (paragraphes, pas des mots isolés). `resumes.json` contient 311 résumés structurés — c'est exactement le type d'entrée idéal.

**Avantages significatifs :**
- LDA produit K topics, chaque topic étant une **distribution de mots pondérés** → les mots dominants d'un topic SONT le label de la catégorie, naturellement
- Chaque document reçoit une **distribution sur les topics** → on sait quels résumés (et donc quels concepts extraits de ces résumés) appartiennent à quel topic
- On travaille en amont dans le funnel (résumés, pas mots-clés) : la granularité est plus riche, le contexte sémantique est préservé
- 100% déterministe, rapide (~secondes), pas de LLM

**Risques identifiés :**

| Risque | Sévérité | Mitigation |
|--------|----------|------------|
| **Homogénéité du vocabulaire LLM** : les résumés ont été générés par un LLM, qui a tendance à utiliser un vocabulaire lissé et répétitif. Cela peut réduire la distinctiveness des topics. | ⚠️ Moyen | Vérifiable empiriquement. Si les topics sont trop vagues, c'est un signal que les résumés manquent de diversité lexicale. |
| **Corpus petit** (311 docs) : LDA fonctionne mieux sur des milliers de documents. | ⚠️ Moyen | 311 est suffisant pour 8-12 topics. Peut être amplifié en traitant chaque résumé comme N sous-documents (paragraphe splitting). |
| **Mélange de topics** : un résumé peut couvrir plusieurs thématiques (ex: "AI applied to cybersecurity"). LDA modélise cela nativement (mélange de topics par document). | ✅ Faible | C'est un avantage, pas un risque : les concepts multi-domaines seront naturellement associés au topic dominant. |
| **Hyperparamètres** : Choix de K (nombre de topics), alpha, beta. | ⚠️ Moyen | Utiliser la cohérence de topic (UMass / CV) pour choisir K automatiquement. |
| **Mapping concepts → topics** : Il faut un pont entre les topics LDA (sur les résumés) et les mots-clés (de `concepts_cache.json`) | 🔧 Technique | Pour chaque concept, chercher dans quel(s) résumé(s) source il a été extrait, et hériter du topic dominant de ces résumés. Ou : projeter le concept dans l'espace LDA et l'assigner au topic le plus probable. |

### Approach C — Hybride LDA→HAC

1. **LDA sur `resumes.json`** → K topics avec labels naturels (top-words)
2. **Attribution** : chaque concept de `concepts_cache.json` hérite du topic dominant du/des résumé(s) dont il a été extrait
3. **HAC intra-topic** : pour chaque topic >30 concepts, lancer un clustering fin pour produire les sous-catégories

Cette approche combine la granularité sémantique du LDA (contexte documentaire) avec la précision du HAC (similarité lexicale locale). Le LLM n'intervient à aucun moment.

### Key Question
Le LLM n'est-il utile que pour le **renommage cosmétique** des labels, ou est-il structurellement nécessaire ?

### Alternatives en cours d'évaluation
Voir `roadmap.md` pour les hypothèses H1-H4.

### Correction — Provenance de resumes.json (Vérifiée via code)

L'analyse de `fix_metadata_advanced.py` et `fix_metadata_v5.py` confirme que les résumés sont un **hybride** :
- `fix_metadata_advanced.py` : Instruction "Recopie STRICTEMENT la section Abstract... sinon rédige un résumé".
- `fix_metadata_v5.py` (Header Prompt) : Instruction "Write a condensed abstract in ENGLISH".
- Le résultat est stocké dans le champ `comments` de Calibre (`set_metadata --field comments`).

`resumes.json` est donc une extraction de ces champs `comments`. Conséquence : le bruit sémantique ("study", "paper", "based") observé dans LDA provient du style de synthèse de l'extraction V5.

---

## Experiment 5 — A/B Test Results (2026-03-27 03:10)

### Setup
Script `ab_test_taxonomy.py`, 100% déterministe (scikit-learn, 0 LLM), ~3 secondes total.
- **A** : TF-IDF (`char_wb`, n-grams 3-5) + HAC (Ward, K=10) sur `concepts_cache.json`
- **B** : LDA (CountVectorizer, K=10) sur `resumes.json`, mapping concept→topic par co-occurrence textuelle
- **C** : Hybride B→A (LDA pour racines, HAC intra-topic pour sous-catégories)

### Results

| | Approach A (HAC) | Approach B (LDA) | Approach C (Hybrid) |
|---|---|---|---|
| Temps | ~1s | ~2s | ~3s |
| Racines | 10 | 10 | 10 |
| Plus gros cluster | **740/899 (82%)** ❌ | **260/899 (29%)** ⚠️ | 260 (HAC 227 dans un sous-cluster) ⚠️ |
| Qualité labels | Termes du corpus (OK) | Top-words LDA (vagues) | Top-words LDA (vagues) |

**LDA Topics discovered (Approach B)** :
```
Topic 0: ai, data, highlights            ← trop générique
Topic 1: digital, ambidexterity, study    ← mélange domaines
Topic 2: risk, management, financial      ← lisible ✅
Topic 3: ai, governance, framework        ← lisible ✅
Topic 4: digital, transformation, study   ← "study" = bruit
Topic 5: organizational, ambidexterity    ← lisible ✅
Topic 6: paper, models, based            ← LLM boilerplate
Topic 7: digital, transformation, organizational
Topic 8: change, model, changes
Topic 9: innovation, knowledge, business  ← lisible ✅
```

### Analysis

**Approach A — Échec de la vectorisation** : TF-IDF `char_wb` (n-grams de caractères) mesure la similarité lexicale de surface. Tous les termes techniques courts (2-3 mots) ont des profils de n-grams similaires → un cluster géant absorbe 82%. La vectorisation TF-IDF par caractères est inadaptée à ce type de données.

**Approach B — LDA prometteur mais bruité** : ~4/10 topics sont sémantiquement lisibles (risk/management, governance, organizational, innovation). Les autres sont pollués par des mots-balises LLM ("highlights", "study", "paper", "based") qui reflètent la structure d'extraction, pas le contenu.

**Approach C** : Hérite des labels faibles de B et du déséquilibre de A dans les sous-clusters.

### Lessons Learned

1. **TF-IDF `char_wb` est inadapté** aux termes courts. Il faudrait une vectorisation par **co-occurrence documentaire** (voir ci-dessous).
2. **Les top-words LDA contiennent du bruit structurel** ("study", "paper", "highlights", "based") → ajouter ces termes en **stop-words de domaine**.
3. **Les labels de cluster devraient être extraits de `concepts_cache.json`**, pas des top-words bruts.
4. **Les embeddings denses (sentence-transformers, etc.) sont du compute neural** — pas fondamentalement différent d'un LLM en termes de dépendance technologique. À éviter si l'objectif est un pipeline purement algorithmique.

### Proposition — Vectorisation par co-occurrence documentaire

Au lieu de vectoriser les **mots** des concepts (TF-IDF) ou d'utiliser des **embeddings neuraux**, on peut vectoriser par **co-occurrence dans les résumés** :

```
Pour chaque concept C :
  vecteur_C[i] = 1 si le concept C apparaît dans le résumé i, 0 sinon
```

Deux concepts qui apparaissent dans les mêmes documents sont sémantiquement proches. C'est la logique du **filtrage collaboratif item-item** (recommandation), appliquée à des concepts textuels.

**Avantages** :
- 100% déterministe, aucun modèle neural
- Capture la proximité **sémantique documentaire** (pas juste lexicale)
- Le vecteur a 311 dimensions (un par résumé) → compact et rapide
- Compatible HAC, K-Means, ou tout autre algorithme de clustering

---

### Expérience : Approche Séquentielle (D → Fallback)
**Date** : 2026-03-27
**Hypothèse** : L'approche D est robuste car elle s'appuie sur la co-occurrence réelle (ancrage documentaire). Si on l'utilise pour créer les **catégories piliers**, on peut ensuite traiter les concepts orphelins (les 54% restants) via un repli (Approach C ou similarité vectorielle vers les piliers) pour étendre la couverture sans diluer la précision du noyau.

**Résultats Finaux (Approach E)** :
- **Couverture** : 867 / 899 concepts (96%).
- **Précision** : Les "Anchors" (Approach D) fournissent des clusters indiscutables (ex: "Digital Innovation", "Poisson Law").
- **Structure** : Les orphelins sont regroupés dans un domaine "New / Unmapped Domains" organisé par LDA (Approach C), ce qui permet de maintenir une hiérarchie même pour les concepts non-ancrés.
- **Bruit** : Contrôlé par les `DOMAIN_STOP_WORDS`.

**Conclusion** : Cette approche séquentielle est validée pour la production.

**Note sur l'implémentation** : Le mapping `concept → résumé(s) source` est désormais recalculé dynamiquement en Phase 3 via une recherche regex, évitant ainsi de modifier le format de `concepts_cache.json`.

---

### Expérience 6 : Optimisations de Précision et Équilibrage (V3 Finale)
**Date** : 2026-03-27
**Hypothèse** : L'introduction d'exceptions lexicales et d'une flexibilité morphologique permettra d'éliminer les distorsions de termes (ex: Agentic → Argentic) et d'augmenter la sensibilité de l'ancrage documentaire.

#### Améliorations Apportées
1. **Protection Lexicale (`IT_VOCAB_EXCEPTIONS`)** : Mise en place d'un dictionnaire de termes protégés pour empêcher `spacy` de déformer les acronymes techniques lors de la lemmatisation.
2. **Regex Morphologique** : Utilisation de `\b[terme](?:s|es|d|ed|ing)?\b` pour capturer les déclinaisons (pluriels, congugaisons) dans les résumés. Gain significatif de sensibilité pour la matrice de co-occurrence.
3. **Équilibrage Structurel** :
    - **Calcul Dynamique de K** : `optimal_k = max(4, len(members) // 12)` pour adapter le nombre de clusters à la taille des domaines.
    - **Ward Linkage & Euclidean Distance** : Passage au critère de Ward pour les sous-clusters. Cela minimise la variance intra-cluster et "casse" les clusters géants (effet "boule de neige") pour une répartition homogène.
4. **Dépollution Avancée** : Extension des `DOMAIN_STOP_WORDS` au lexique structurel académique (`author`, `doi`, `abstract`) et aux tics de résumés LLM (`insight`, `overview`, `explore`).

#### Résultats
- **Stabilité** : Les erreurs de lemmatisation sont résolues.
- **Granularité** : La structure est plus équilibrée avec des racines comme `Community` et `Digital Transformation` parfaitement segmentées.
- ---

## Phase 3.1 — Optimisation : Outlier Quarantine (V4.1)
**Date** : 2026-03-27
**Hypothèse** : L'introduction d'un seuil d'exclusion sémantique permettra d'isoler les concepts "bruit" ou trop spécifiques qui polluent les racines majeures.

### Détails Techniques
- **Seuil d'Outlier** (`0.40`) : Si la similarité cosinus vers la racine la plus proche est < 0.40, le concept est placé en quarantaine.
- **Root Redundancy** (`0.60`) : Seuil abaissé pour garantir que les 12 racines choisies sont suffisamment distinctes.
- **Outlier Key** : `"Outliers / Niche Concepts"` regroupant tous les termes non-ancrés.

### Résultats
- ✅ **Pureté des racines** : Les domaines "Innovation" et "Risk Management" ne contiennent plus de termes orphelins sans rapport.
- ✅ **Signal / Bruit** : Les concepts de niche (ex: noms propres très rares, termes isolés) sont isolés sans être supprimés, permettant une révision manuelle ultérieure.

---

## Phase 5 — Design : Open IE V5 (Asymmetric Anchoring)
**Date** : 2026-03-27
**Contexte** : Raffinement de la stratégie d'extraction pour maximiser la fidélité à la T-Box tout en permettant la découverte de nouvelles relations.

### Architecture Raffinée
1. **Cold Start (RAM)** : Pré-calcul des embeddings de la T-Box (`thesaurus.json`) pour éviter les lenteurs de recherche lors de l'extraction.
2. **Idempotence & Sécurité** :
    - Registre `processed_docs.txt` pour permettre la reprise après interruption.
    - Format `.jsonl` (append-only) pour garantir l'intégrité des données en cas de crash.
3. **Ancrage Asymétrique** :
    - **Sujet (Strict, >0.82)** : Le sujet doit être un concept maîtrisé de l'ontologie.
    - **Objet (Tolérant, >0.65)** : L'objet peut être un concept libre pour capturer des nuances hors-domaine (métriques, conséquences).
4. **Audit Final** : Compilation de statistiques d'ancrage pour valider la qualité du graphe avant injection Neo4j.

---

## Réflexion : Alignement d'Ontologies Externes & Entity Linking
**Date** : 2026-03-27
**Contexte** : Analyse de l'opportunité de coupler le pipeline local avec des API externes (Linked Open Data - LOD) comme l'INRAE, Wikidata ou DBpedia.

### Défis Structurels Identifiés
1. **Domain Mismatch (Agriculture vs Tech)** : L'ontologie INRAE est sectorielle. Un corpus IA/Stratégie risque des faux positifs systématiques.
2. **Obsolescence vs Innovation** : Les termes "Graphrag", "Agentic Workflow" ou "Prompt Chain" ne sont pas encore stabilisés dans les ontologies académiques. Un filtrage externe strict effacerait les signaux faibles et l'innovation.
3. **Architecture "Local First"** : Le passage au réseau synchronisé briserait l'autonomie actuelle (Qwen/Ollama/Sentence-Transformers) et introduirait une latence importante.

### Variables de Conception à Clarifier
- **Référentiel** : Wikidata/DBpedia ou CSO (Computer Science Ontology) seraient plus pertinents que des sources sectorielles inadaptées.
- **Rôle de l'API** : Filtre (Arbitre) ou Enrichisseur (Recours) ? L'enrichissement de repli est privilégié pour conserver la capacité de découverte locale.
- **Écosystème** : Arbitrage entre autonomie offline et précision normalisée par des tiers.

---

## Résultats PoC : Alignement Wikidata & "Le Piège de l'Ontologie Supérieure"
**Date** : 2026-03-27
**Contexte** : Analyse des résultats du script `poc_wikidata_alignment.py` sur 5 outliers types (Adversarial Attack, Fuzzy Set, etc.).

### Analyse des Rejets (Scores < 0.46)
L'ascension hiérarchique (P279/P31) à une profondeur de 2 niveaux a révélé un **décalage sémantique majeur** :
- **3D Print** -> Wikidata remonte `recreation`, `technique`, `hobby`.
- **Adversarial Attack** -> Wikidata remonte `deception`, `abuse`, `communication`.
- **Fuzzy Set** -> Wikidata remonte `concept`, `class`, `set`.

**Conclusion** : Les parents universels de Wikidata sont trop abstraits pour s'ancrer vectoriellement sur des racines IT locales spécialisées (ex: `Agentic Ai`). C'est le **Upper Ontology Trap**.

### Pivot Stratégique : De l'Alignement à la Canonisation
Plutôt que de forcer un pont hiérarchique, nous optons pour une stratégie de **Canonisation des Entités** :
1. **Ancrage Local (Prio 1)** : Similarité > 0.80 -> Absorption par une racine locale.
2. **Canonisation Wikidata (Prio 2)** : Pour les Outliers (ou non-ancrés), interrogation du endpoint de recherche uniquement pour récupérer le **label normalisé** et l'**ID Q**.
3. **Interopérabilité Neo4j** : Stockage systématisé de l'URI Wikidata (`http://www.wikidata.org/entity/Q...`) pour chaque nœud identifié.

**Impact** : Le Knowledge Graph devient ouvert et normalisé sans sacrifier la précision du domaine local.

**Statut** : Stratégie de canonisation par ID Q validée pour la Phase 5.

---

## Phase 4 — Design : Semantic Gravity Clustering (V4)
**Date** : 2026-03-27
**Contexte** : Transition vers une approche par "Gravité Sémantique" pour éliminer les biais résiduels du co-occurrence (ex: fausse proximité entre termes co-présents mais sémantiquement distincts) et du LDA (inventions de thématiques).

### Nouvelle Architecture
L'objectif est d'utiliser un modèle d'embedding léger (`sentence-transformers/all-MiniLM-L6-v2`) pour projeter les concepts dans un espace vectoriel dense.

#### 1. Calcul de la Gravité (Racines)
Chaque concept $c$ reçoit un score de gravité composite :
$$Weight(c) = DocFrequency(c) \times \sum_{i=1}^{k} CosineSimilarity(c, neighbor_i)$$
- **Ancrage Réel** (`DocFrequency`) : Fréquence d'apparition dans les résumés.
- **Ancrage Sémantique** (`Semantic Density`) : Nombre de voisins gravitant autour du concept dans l'espace vectoriel.
Les $N$ concepts (ex: top 15) ayant le score le plus élevé deviennent les **Catégories Racines**. Ces racines sont de vrais termes du corpus (ex: Machine Learning, Data Governance).

#### 2. Affiliation par Similarité
Chaque concept restant est rattaché à la racine la plus proche sémantiquement via mesure cosinus. Cela résout le problème de "Data Store" (Data Governance) vs "Community" (Organizational Culture) même s'ils partagent le même document.

#### 3. Nettoyage Curatife (Absorption des Singletons)
Règle empirique : Toute catégorie/racine ayant moins de 3 concepts est dissoute. Ses membres sont redistribués vers la deuxième racine la plus pertinente.

---

## Expérience 7 : Résultats - Semantic Gravity Clustering (V4 Gold)
**Date** : 2026-03-27
**Hypothèse** : L'approche par "Gravité" (Embeddings `all-MiniLM-L6-v2`) produira une structure 2-level plus propre et sémantiquement plus juste que le co-occurrence ou le LDA.

### Résultats Finaux
L'implémentation a généré une taxonomie de **12 racines majeures**, regroupant les ~900 concepts de manière exclusive et équilibrée.

#### 1. Racines de Gravité (Top 12)
1. **Digital Transformation** (Ancre centrale)
2. **Digital Strategy**
3. **Digital Leadership**
4. **Innovation**
5. **Agentic Ai** (Succès : regroupement de "Workflow", "Agentop", "Tool-call")
6. **Governance**
7. **Business Model**
8. **Risk Management** (Succès : "Sustainability", "Incident Response")
9. **Strategic Alignment**
10. **Ambidexterity**
11. **Organizational Ambidexterity**
12. **Compliance** (Succès : "GDPR", "Secure Multiparty Computation")

#### 2. Analyse Qualitative
- **Exclusivité** : Chaque concept est rattaché à sa racine la plus dense sémantiquement. Le biais "Community" (fausse proximité documentaire) est rompu.
- **Structure** : Le dictionnaire est strictement de **niveau 2** (`Root -> [List]`), éliminant les erreurs de récursion lors de l'extraction de triplets.
- **Couverture** : 100% des concepts extraits en Phase 1 sont mappés.
- **Absence de Bruit** : Les singletons (< 3 concepts) ont été absorbés par les racines voisines, garantissant une densité minimale par cluster.

---

## Phase 6 — Design : Unified Knowledge Engineering Pipeline (V6)
**Date** : 2026-03-27
**Contexte** : Consolidation des prototypes en un moteur maître industriel combinant Open IE, Pydantic, Vector Anchoring et Entity Linking Wikidata.

### Architecture à 3 Niveaux (L'Entonnoir Asymétrique)
1. **Prio 1 : T-Box Locale** (Score > 0.82) -> Raccrochement aux racines de `thesaurus.json`.
2. **Prio 2 : Wikidata LOD** (Entity Linking) -> Normalisation via API REST et stockage de l'ID Q.
3. **Prio 3 : True Outlier** -> Conservation du texte brut pour les concepts ultra-spécifiques.

### Évolutions Techniques
- **Modèle Pydantic** : Extension avec `subject_uri` / `object_uri`.
- **Obsidian Sync** : Injection de `wikidata_uri` dans le YAML frontmatter pour l'interopérabilité.
- **Hygiène du Thésaurus** : Catégorisation interne dédiée aux entités alignées (`Wikidata_Aligned`).

**Statut** : Prêt pour le déploiement de la V6.
