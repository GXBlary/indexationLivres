# Architecture d'Extraction de Connaissances (Open IE V5)

## 1. Contexte et Objectif
Ce projet (actuellement prototypé en Python, destiné à être industrialisé en Node.js) vise à résoudre le problème complexe de la construction de **Graphes de Connaissances (Knowledge Graphs)** fiables à partir d'un corpus de documents d'entreprise totalement non structurés (ex: rapports PDF dans le cadre d'une société du CAC40).

L'objectif final est d'alimenter une **CMDB (Configuration Management Database)** interconnectée (Neo4j) requêtable par une IA (GraphRAG), tout en gardant une interface d'édition humaine manipulable au quotidien (Obsidian).

---

## 2. Le Problème de l'Extraction LLM Naïve
Lorsqu'on demande naïvement à un Grand Modèle de Langage (LLM) d'extraire des concepts d'un texte, quatre problèmes majeurs détruisent irrémédiablement la qualité de la base de données :

1. **L'Explosion des Nœuds (Duplication)** : L'IA va créer un nœud `IA`, un nœud `Intelligence Artificielle` et un nœud `AI` pour désigner la même machine abstraite.
2. **L'Amnésie de Découpage** : Si on coupe le document tous les 10 000 caractères, et qu'une coupe tombe au milieu d'une phrase, le lien complexe `[Sujet] -> [Objet]` est tronqué et ignoré. L'IA perd son contexte (ex: un pronom "Il" renvoyant au bloc d'avant).
3. **L'Hallucination Structurelle** : L'IA oublie de fermer le JSON, omet des champs obligatoires, ou invente des clés de sortie, faisant crasher les scripts d'insertion SQL/NoSQL.
4. **La Faiblesse Sémantique** : Le modèle va utiliser des verbes/prédicats extrêmement vagues (`impacte`, `concerne`, `fait_partie`), rendant le graphe complètement in-requêtable pour des inférences logiques par la suite.

---

## 3. La Solution V5 : Le Pipeline Open Information Extraction
Pour tourner fiablement sur un matériel contraint (8GB VRAM) et garantir une base de données de qualité quasi-déterministe, nous avons implémenté un pipeline robuste articulé autour de **4 briques fondamentales**.

### Brique 1 : Le Semantic Chunking (Pré-traitement Contextuel)
La découpe du document ne se fait plus de manière aveugle (aux caractères), mais au **bloc logique** (via PyMuPDF). Le texte est lu méticuleusement paragraphe par paragraphe.
* **Intégrité de la découpe** : Si l'accumulation de paragraphes dépasse la limite autorisée par la VRAM (ex: 3000 tokens), la coupe se fait *exclusivement* au niveau d'un point final de paragraphe.
* **Le Chevauchement (Overlap)** : Chaque nouveau fragment (Chunk) embarque obligatoirement le contexte de la fin du fragment précédent (ex: les 3 derniers paragraphes). Ainsi, l'IA ne perd jamais la résolution sémantique des concepts.

### Brique 2 : La Validation Structurelle Cadrée (Le Mur Zod / Pydantic)
La chaîne de caractères recrachée par l'IA n'est plus traitée par un simple parseur JSON tolérant. Elle est écrasée contre un **schéma strict fortement typé** (Pydantic en Python, l'équivalent parfait de **Zod** en TypeScript/Node.js).
Grâce à la fonctionnalité de *Structured Outputs* (désormais native sur Ollama, OpenAI et Anthropic), ce schéma Zod est poussé au LLM **pendant** l'inférence. Le modèle est physiquement contraint de respecter le squelette de sortie à la lettre sous peine de générer des erreurs (Hard-Fail).

### Brique 3 : Contrôle de l'Ontologie (Soft-Fail & Hard-Fail)
Dans une approche d'Ontology Mining, nous voulons que l'IA respecte le socle officiel de la CMDB (la **T-Box** / Ontologie) tout en ayant la souplesse algorithmique de nous faire découvrir de nouveaux concepts métiers qu'elle détecterait.
- **La Blacklist (Rejet Strict / Hard-Fail)** : Si l'IA utilise un verbe d'action de la liste d'interdiction (ex: `concerne` ou `détaille`), Pydantic lève une exception violente (`ValueError`). L'Orchestrateur attrape l'erreur et **déclenche un Retry automatique** (`"Ta réponse a causé une erreur Zod au niveau du prédicat, corrige-toi !"`). L'IA est obligée de converger.
- **Human-In-The-Loop (Tolérance / Soft-Fail)** : Si l'IA invente un nouveau prédicat valide et intensément sémantique (ex: `régule`), le mur le marque silencieusement d'un Flag `[À RÉVISER]`. L'humain (Administrateur de la CMDB) l'inspectera manuellement dans l'interface finale pour le fusionner ou l'approuver.
- **Alignement Dynamique de l'Ontologie** : Le script intègre désormais dynamiquement une clé "Predicates" dans `keywords_registry.json`. Cela vous permet d'ajouter de nouveaux verbes autorisés ou bannis directement dans le JSON et de les charger dynamiquement à l'exécution pour ajuster le "Mur Zod".

### Brique 4 : L'Ancrage Vectoriel (Entity Resolution)
C'est la brique ultime contre l'explosion d'hallucinations et la duplication des nœuds (*Le problème n°1*).
Avant la mutation de la base de données, chaque *Sujet* et *Objet* extraits "librement" par l'IA est **vectorisé mathématiquement** via un modèle d'Embedding dense et rapide (ex: `nomic-embed-text`).
1. Le script calcule automatiquement la similarité cosinus (Cosine Similarity) entre cette nouvelle entité et le registre officiel des instances (A-Box).
2. **Optimisation du Moteur Vectoriel** : La fonction d'extraction du vocabulaire `extract_all_strings()` indexe désormais également les clés structurelles de votre ontologie (ex: "AI.Agents"), améliorant considérablement l'algorithme d'alignement vectoriel des noeuds synonymes.
3. Exemple : *L'IA Générative* (Inventé) vs *Generative AI* (Officiel).
4. Si le score vectoriel mathématique dépasse un seuil de sécurité (ex: 82% à 85%), **la nouvelle entité est annihilée et foudroyée en vol par le script, qui la remplace chirurgicalement par son équivalent officiel.** 
5. Si elle n'a aucun équivalent, elle est conservée, devient une nouvelle entité noble du graphe, et est immédiatement injectée dans le moteur de similarité en RAM pour bénéficier aux documents suivants de la file d'attente !

### Brique 5 : Restructuration Automatique de l'Ontologie (Thesaurus Cleanup)
Pour pallier la pollution naturelle induite par de nombreux passages d'une IA sur des documents, la dernière étape du script orchestre un effondrement du bruit (Noise Removal).
L'Orchestrateur lit toutes les entités de l'espace non-catégorisé (`Uncategorized_New`), qui agissent comme une zone de "quarantaine", et soumet l'intégralité du Thesaurus à un modèle Small Language Model (SLM) avec des directives sévères :
1. **Élagage (Pruning)** : Les fausses entités (phrases complexes, blocs statistiques) sont brutalement supprimées.
2. **Traduction Intégrale** : Tous les concepts valides frôlant d'autres langues sont traduits vers l'anglais pour unifier l'espace latent.
3. **Déduplication & Normalisation** : Fusion sémantique des variantes de casse, d'orthographe et d'abréviations (ex: `AI` et `ai` fusionnent sous `Artificial Intelligence`).
4. **Catégorisation Dynamique** : Les termes nobles restants sont redistribués de force dans les branches sémantiques mères du Knowledge Graph, avec l'autorisation pour l'IA de forger de nouvelles sous-disciplines (`Industries`, `Legal & Regulation`) si nécessaire. Le nouveau dictionnaire `thesaurus.json` est réécrit proprement, clos pour la prochaine exécution.

---

## 5. Conclusion & Transposabilité
Cette ingénierie (Zod validation + Vector Anchoring Threshold + Semantic Chunking Overlap) est l'état de l'art actuel pour l'automatisation sérielle et fiable d'un graphe de connaissances. 
Le modèle est 100% transposable au monde de Node.js via les bibliothèques équivalentes (Zod, LangChain.js, une fonction de cosine-similarity native, et un parser PDF structurel).
