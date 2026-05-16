# Methodology for Hierarchical Taxonomy Alignment

**Target Audience:** Human Developers and Large Language Models (LLMs) instructed to build or maintain similar taxonomy pipelines in other tech stacks.

## 1. Context and Objective

When indexing a large corpus of documents (like a library of research papers, PDFs, or books), using flat, raw tags extracted by an LLM quickly leads to an unmanageable taxonomy. You end up with thousands of inconsistent tags (e.g., `NLP`, `Natural Language Processing`, `Machine Learning`, `machine learning`, `AI`).

**The Goal:** Transform raw, noisy keywords into a clean, canonical, **hierarchical structure** (e.g., `Artificial Intelligence.Machine Learning.Natural Language Processing`) that leverages nested navigation in tools like Calibre. 

The depth must be strictly controlled (ideally 2 to 5 levels maximum) to remain human-readable.

---

## 2. The Pitfall: "Semantic Black Holes" in Ontologies

The naive approach is to query a knowledge graph like **Wikidata** to find the ancestors of a concept (using properties like `P279` subclass of, or `P31` instance of).

**The Problem:** Wikidata is a pure, rigorous ontology. If you ask for the ancestors of a specific paper or software concept, the graph traversal will often end up at hyper-abstract nodes. 

For instance, the concept **"Work" (Q386724)** is defined broadly as "the result of human effort". Consequently, algorithms, books, frameworks, and methodologies all end up subclassed under "Work" or "Object" or "Entity". A naive script mapping concepts to their top-level ancestors will classify 80% of your library under `Work.Entity.[Your Tag]`. 
This destroys domain-specific clarity (like `Technology` vs `Business`).

---

## 3. The Solution: A Hybrid Alignment Engine

To build a usable taxonomy, we implemented a 3-step pipeline: **Cache -> Wikidata (Filtered) -> LLM Fallback**.

### Step A: The Ontological Blacklist & Allowed Roots
Before routing through Wikidata, establish two core lists:
1.  **Allowed Roots (`WIKIDATA_ROOTS`)**: A list of ~20 broad domains you *want* at the top of your hierarchy.
    *   *Examples:* `Science`, `Technology`, `Business`, `Artificial Intelligence`, `Management`, `Economics`.
2.  **The Ontological Blacklist (`ONTOLOGICAL_BLACKLIST`)**: A list of "black hole" concepts to actively ignore during graph traversal.
    *   *Examples:* `work`, `content`, `object`, `entity`, `thing`, `concept`, `information`, `knowledge sharing`.

### Step B: The Processing Pipeline

When a raw tag (e.g., `LLM`) is received:

1.  **Cache Lookup (`O(1)`)**: Check a persistent local mapping (e.g., `tag_mapping.json`). If the tag has been aligned before, return the cached hierarchical path immediately.
2.  **Wikidata SPARQL Query**: 
    *   Find the entity Q-ID matching the tag.
    *   Fetch professional classification signals:
        *   **LoC (P1149)**: Library of Congress.
        *   **Dewey (P1036)**: Decimal Classification.
        *   **BISAC (P12164)**: Subject Headings.
    *   **Prioritization**: Build the root segment using the following priority: LoC > Dewey > BISAC > Semantic Subjects (P921).
    *   **Filtering**: Reconstruct the hierarchical path from top to bottom, but *skip* any ancestor present in the `ONTOLOGICAL_BLACKLIST`. Only keep ancestors that are either in your `WIKIDATA_ROOTS` or in an approved canonical list.
3.  **LLM Harmonization (Fallback)**: If Wikidata fails (concept too new, unavailable, or yields a messy path), delegate to an LLM.

---

## 4. Prompt Engineering for Taxonomy LLMs

When utilizing an LLM for Fallback Harmonization, the prompt must be highly constrained. 

**Core Rules for the LLM Prompt:**
1.  **Root Constraint**: "The path MUST start with one of the following root domains: [List your WIKIDATA_ROOTS]."
2.  **Punctuation**: "Separate segments with dots (e.g. `Technology.Artificial Intelligence`)"
3.  **Depth Limit**: "Keep it shallow: 2 to 4 levels max. Do not create deep paths unless absolutely necessary."
4.  **No Ontological Noise**: "Avoid prepending abstract roots (e.g. 'Philosophy', 'Memory', 'Entity') unless the tag is explicitly fundamentally about those fields."
5.  **Acronym Expansion**: "ALWAYS expand abbreviations. Do not use 'LLM' or 'NLP'. Use 'Large Language Model' and 'Natural Language Processing'. Exceptions are file formats (PDF) and enterprise names (AWS)."
6.  **Casing Constraints**: "Output the segments in PascalCase / Title Case."

### Example Fallback Prompt:
```text
You are a library taxonomy expert. Create a logical hierarchical path for the concept "{tag}".
RULES:
1. The path MUST start with one of these ROOT domains: [{roots_str}].
2. Reuse existing segments from this list ONLY if they are TOPICALLY RELEVANT: [{canonicals_str}].
3. The leaf (last segment) MUST be "{tag.title()}".
4. Separate segments with dots.
5. KEEP IT SHALLOW: 2 to 4 levels max. Avoid deep paths unless necessary.
6. NO ONTOLOGICAL NOISE: Avoid prepending abstract roots like "Philosophy", "Memory", "Science", "Education".
8. NO ABBREVIATIONS: Always expand terms (e.g. use "Large Language Model" instead of "LLM"). Keep only enterprise names (AWS) or file formats (PDF).
9. Output only the path as a string.
```

---

## 5. System Design Checklist for Portability 

If replicating this in another stack (e.g. Node.js, Go, Rust), ensure the following architectural traits:

- [ ] **Rate Limiting (Tokens / RPM)**: The pipeline must control outgoing API calls to LLMs using a Token Bucket or Semaphore algorithm, specifically handling `429 Too Many Requests` responses elegantly.
- [ ] **Local Fallback**: If using a Cloud LLM (like Gemini/OpenAI), implement a fallback to a fast, local LLM (like Ollama / Qwen / Llama3) triggered automatically upon quota exhaustion or connectivity loss.
- [ ] **Persistent Alignment Store**: Never rely purely on real-time processing. All alignments must be persisted to disk (e.g., JSON mapping) bridging the raw tag (key) to the hierarchical tag (value).
- [ ] **Duplicate Idempotency**: The indexing component pushing to the final Database (e.g., Calibre, Neo4j) must verify if an entity already exists (by exact Author/Title match, disregarding file bounds). If found, it should intelligently merge/update metadata (Tags, Summaries) instead of creating duplicate records.

---

## 6. Document Ingestion & Advanced Semantic Extraction

To ensure the highest quality of metadata and summaries, the pipeline integrates high-performance extraction and modern information architecture principles.

### A. High-Performance Extraction with Kreuzberg
The pipeline utilizes **Kreuzberg** to handle multi-format document extraction (PDF, EPUB, etc.). 
- **Native Markdown Output**: Unlike legacy tools that return raw text blocks, Kreuzberg generates structured Markdown, preserving semantic markers.
- **OCR Integration**: It transparently handles scanned documents, ensuring no content is lost even in image-only PDFs.

### B. Heuristic Summary Frameworks
Rather than asking for a generic summary, the system instructs the LLM to select an optimal professional framework (e.g., **Minto Pyramid**, **SPRI**, **BLUF**, **Feynman**) to structure the summary based on the document's nature. 
- **Flash Summary**: A one-sentence subject and three key themes.
- **Detailed Summary**: A structured breakdown following the selected framework.

### C. Bibliography & Citations Graph
To build a connected knowledge graph, the system scans the **tail of the document** (where bibliographies reside) to extract references.
- **Cross-Referencing**: Each reference is checked against the existing Vault registry.
- **Visual Links**: If a referenced work is already indexed, the system generates an internal wiki-link (`[[Author_Title]]`), highlighting existing connections in the library.

### D. Visual Taxonomy (Mermaid)
Each tag file in the vault includes a dynamic **Mermaid diagram** visualizing its specific branch in the taxonomy. This allows users to instantly perceive where a concept sits between its parents and sub-categories.

