"""
A/B Test — Taxonomy Generation Approaches
==========================================
Approach A: TF-IDF + Hierarchical Agglomerative Clustering (HAC) on concepts_cache.json
Approach B: LDA Topic Modeling on resumes.json  
Approach C: Hybrid LDA→HAC (LDA for root categories, HAC for subcategories)

Outputs: taxonomy_a.json, taxonomy_b.json, taxonomy_c.json
"""

import json
import os
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import LatentDirichletAllocation
from scipy.cluster.hierarchy import linkage, fcluster
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONCEPTS_FILE = os.path.join(SCRIPT_DIR, "concepts_cache.json")
RESUMES_FILE = os.path.join(SCRIPT_DIR, "resumes.json")

DOMAIN_STOP_WORDS = ['paper', 'study', 'highlights', 'based', 'research', 'approach', 'analysis', 'key', 'model', 'results', 'data', 'ai', '10', '2025', 'doi']

# =========================================================================
# SHARED UTILITIES
# =========================================================================

def load_concepts():
    with open(CONCEPTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_resumes():
    with open(RESUMES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def label_cluster(concepts_in_cluster):
    """Find the most representative label for a cluster.
    Strategy: pick the shortest term that shares the most words with other members."""
    if not concepts_in_cluster:
        return "Empty"
    if len(concepts_in_cluster) == 1:
        return concepts_in_cluster[0]
    
    # Count word frequency across all concepts in cluster
    word_freq = defaultdict(int)
    for c in concepts_in_cluster:
        for word in c.lower().split():
            word_freq[word] += 1
    
    # Score each concept by how many of its words are frequent
    best_score = -1
    best_label = concepts_in_cluster[0]
    for c in concepts_in_cluster:
        words = c.lower().split()
        score = sum(word_freq[w] for w in words) / max(len(words), 1)
        # Prefer shorter, more general terms
        length_bonus = 1.0 / max(len(words), 1)
        total = score + length_bonus * 2
        if total > best_score:
            best_score = total
            best_label = c
    return best_label

def save_taxonomy(taxonomy, filename):
    filepath = os.path.join(SCRIPT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(taxonomy, f, indent=4, ensure_ascii=False)
    print(f"  → Saved to {filepath}")

def count_concepts(data):
    """Recursively count strings (concepts) in the taxonomy structure."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return sum(count_concepts(v) for v in data.values())
    return 0

def print_taxonomy_summary(taxonomy, name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    total_concepts = 0
    for cat, content in taxonomy.items():
        count = count_concepts(content)
        if isinstance(content, dict):
            print(f"  {cat} ({len(content)} branches, {count} concepts)")
        else:
            print(f"  {cat} [{count} concepts]")
        total_concepts += count
        
    print(f"  ─────────────────────────────────")
    print(f"  Total: {len(taxonomy)} root categories, {total_concepts} concepts")

# =========================================================================
# APPROACH A — TF-IDF + HAC on concepts_cache.json
# =========================================================================

def approach_a(concepts, n_root_clusters=10, n_sub_clusters=3):
    print("\n[Approach A] TF-IDF + HAC on keywords...")
    
    # 1. Vectorize concepts with TF-IDF (character n-grams for short terms)
    tfidf = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
    X = tfidf.fit_transform(concepts)
    
    # 2. Hierarchical clustering — Level 1 (root categories)
    hac_root = AgglomerativeClustering(n_clusters=n_root_clusters, linkage='ward')
    root_labels = hac_root.fit_predict(X.toarray())
    
    # 3. Group concepts by root cluster
    root_clusters = defaultdict(list)
    root_indices = defaultdict(list)
    for idx, label in enumerate(root_labels):
        root_clusters[label].append(concepts[idx])
        root_indices[label].append(idx)
    
    # 4. Sub-cluster large root clusters (Level 2)
    taxonomy = {}
    for root_id, members in root_clusters.items():
        root_label = label_cluster(members)
        
        if len(members) > 15 and n_sub_clusters > 1:
            # Sub-cluster
            sub_X = X[root_indices[root_id]].toarray()
            actual_sub_k = min(n_sub_clusters, len(members))
            if actual_sub_k < 2:
                taxonomy[root_label] = members
                continue
            hac_sub = AgglomerativeClustering(n_clusters=actual_sub_k, linkage='ward')
            sub_labels = hac_sub.fit_predict(sub_X)
            
            subcats = defaultdict(list)
            for i, sl in enumerate(sub_labels):
                subcats[sl].append(members[i])
            
            taxonomy[root_label] = {}
            for sub_id, sub_members in subcats.items():
                sub_label = label_cluster(sub_members)
                taxonomy[root_label][sub_label] = sub_members
        else:
            taxonomy[root_label] = members
    
    return taxonomy

# =========================================================================
# APPROACH B — LDA on resumes.json
# =========================================================================

def approach_b(resumes, concepts, n_topics=10):
    print("\n[Approach B] LDA on resumes.json...")
    
    titles = list(resumes.keys())
    summaries = list(resumes.values())
    
    # 1. Vectorize summaries with CountVectorizer (LDA needs raw counts)
    from sklearn.feature_extraction import text
    stop_words = list(text.ENGLISH_STOP_WORDS.union(DOMAIN_STOP_WORDS))
    
    count_vec = CountVectorizer(max_df=0.85, min_df=2, stop_words=stop_words)
    doc_term_matrix = count_vec.fit_transform(summaries)
    feature_names = count_vec.get_feature_names_out()
    
    # 2. Fit LDA
    lda = LatentDirichletAllocation(
        n_components=n_topics,
        random_state=42,
        max_iter=20,
        learning_method='batch'
    )
    doc_topics = lda.fit_transform(doc_term_matrix)
    
    # 3. Extract topic labels (top words)
    topic_labels = {}
    print("\n  LDA Topics discovered:")
    for topic_idx, topic_weights in enumerate(lda.components_):
        top_word_indices = topic_weights.argsort()[-5:][::-1]
        top_words = [feature_names[i] for i in top_word_indices]
        # Use top 2-3 words as label
        label = " / ".join(top_words[:3]).title()
        topic_labels[topic_idx] = label
        print(f"    Topic {topic_idx}: {', '.join(top_words)}")
    
    # 4. Assign each concept to a topic
    # Strategy: for each concept, find which summary(ies) it likely came from
    # then inherit the dominant topic of those summaries
    concept_lower = {c.lower(): c for c in concepts}
    topic_concepts = defaultdict(list)
    unassigned = []
    
    for concept in concepts:
        cl = concept.lower()
        # Find summaries that mention this concept (or parts of it)
        best_topic = None
        best_score = 0
        for doc_idx, summary in enumerate(summaries):
            if cl in summary.lower():
                topic_id = np.argmax(doc_topics[doc_idx])
                score = doc_topics[doc_idx][topic_id]
                if score > best_score:
                    best_score = score
                    best_topic = topic_id
        
        if best_topic is not None:
            topic_concepts[best_topic].append(concept)
        else:
            # Fallback: find closest topic via word overlap
            concept_words = set(cl.split())
            best_overlap = 0
            best_topic_fallback = 0
            for topic_idx, topic_weights in enumerate(lda.components_):
                top_indices = topic_weights.argsort()[-20:][::-1]
                topic_words = set(feature_names[i] for i in top_indices)
                overlap = len(concept_words & topic_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_topic_fallback = topic_idx
            topic_concepts[best_topic_fallback].append(concept)
    
    # 5. Build taxonomy
    taxonomy = {}
    for topic_id, members in topic_concepts.items():
        label = topic_labels.get(topic_id, f"Topic {topic_id}")
        taxonomy[label] = members
    
    return taxonomy

# =========================================================================
# APPROACH C — Hybrid LDA→HAC
# =========================================================================

def approach_c(resumes, concepts, n_topics=10, n_sub_clusters=3):
    print("\n[Approach C] Hybrid LDA→HAC...")
    
    # Phase 1: LDA for root categories (same as approach B)
    titles = list(resumes.keys())
    summaries = list(resumes.values())
    
    count_vec = CountVectorizer(max_df=0.85, min_df=2, stop_words='english')
    doc_term_matrix = count_vec.fit_transform(summaries)
    feature_names = count_vec.get_feature_names_out()
    
    lda = LatentDirichletAllocation(
        n_components=n_topics,
        random_state=42,
        max_iter=20,
        learning_method='batch'
    )
    doc_topics = lda.fit_transform(doc_term_matrix)
    
    # Topic labels from LDA
    topic_labels = {}
    for topic_idx, topic_weights in enumerate(lda.components_):
        top_word_indices = topic_weights.argsort()[-3:][::-1]
        top_words = [feature_names[i] for i in top_word_indices]
        topic_labels[topic_idx] = " / ".join(top_words).title()
    
    # Assign concepts to topics (same logic as approach B)
    topic_concepts = defaultdict(list)
    for concept in concepts:
        cl = concept.lower()
        best_topic = None
        best_score = 0
        for doc_idx, summary in enumerate(summaries):
            if cl in summary.lower():
                topic_id = np.argmax(doc_topics[doc_idx])
                score = doc_topics[doc_idx][topic_id]
                if score > best_score:
                    best_score = score
                    best_topic = topic_id
        
        if best_topic is not None:
            topic_concepts[best_topic].append(concept)
        else:
            concept_words = set(cl.split())
            best_overlap = 0
            best_topic_fallback = 0
            for topic_idx, topic_weights in enumerate(lda.components_):
                top_indices = topic_weights.argsort()[-20:][::-1]
                topic_words = set(feature_names[i] for i in top_indices)
                overlap = len(concept_words & topic_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_topic_fallback = topic_idx
            topic_concepts[best_topic_fallback].append(concept)
    
    # Phase 2: HAC for subcategories within each LDA topic
    tfidf = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
    tfidf.fit(concepts)  # Fit on all concepts for consistent vocabulary
    
    taxonomy = {}
    for topic_id, members in topic_concepts.items():
        root_label = topic_labels.get(topic_id, f"Topic {topic_id}")
        
        if len(members) > 15:
            # Sub-cluster with HAC
            sub_X = tfidf.transform(members).toarray()
            actual_k = min(n_sub_clusters, len(members))
            if actual_k < 2:
                taxonomy[root_label] = members
                continue
            hac = AgglomerativeClustering(n_clusters=actual_k, linkage='ward')
            sub_labels = hac.fit_predict(sub_X)
            
            subcats = defaultdict(list)
            for i, sl in enumerate(sub_labels):
                subcats[sl].append(members[i])
            
            taxonomy[root_label] = {}
            for sub_id, sub_members in subcats.items():
                sub_label = label_cluster(sub_members)
                taxonomy[root_label][sub_label] = sub_members
        else:
            taxonomy[root_label] = members
    
    return taxonomy

# =========================================================================
# APPROACH D — Documentary Co-occurrence (Pure Algorithmic)
# =========================================================================

def approach_d(resumes, concepts, n_root_clusters=10, n_sub_clusters=4):
    print("\n[Approach D] Documentary Co-occurrence + HAC...")
    
    summaries = list(resumes.values())
    
    # 1. Create Co-occurrence Matrix (Concept x Document)
    # Vector C[i] = 1 if concept C is in summary i
    matrix = np.zeros((len(concepts), len(summaries)))
    valid_indices = []
    
    for c_idx, concept in enumerate(concepts):
        # Match with word boundaries to be more precise but flexible
        cl = concept.lower().strip()
        # Escaping regex special chars in concept
        pattern = re.compile(r'\b' + re.escape(cl) + r'\b', re.IGNORECASE)
        
        found = False
        for s_idx, summary in enumerate(summaries):
            if pattern.search(summary):
                matrix[c_idx, s_idx] = 1
                found = True
        
        if found:
            valid_indices.append(c_idx)
            
    print(f"  → Found {len(valid_indices)}/{len(concepts)} concepts mentioned in resumes.")
    
    if not valid_indices:
        print("  [ERROR] No concepts found in resumes. Skipping Approach D.")
        return {}

    # Subset matrix and concepts
    filtered_matrix = matrix[valid_indices]
    filtered_concepts = [concepts[i] for i in valid_indices]
    
    # 2. Clustering on this sparse but semantic matrix
    # We use 'cosine' distance
    hac = AgglomerativeClustering(n_clusters=n_root_clusters, linkage='average', metric='cosine')
    root_labels = hac.fit_predict(filtered_matrix)
    
    # 3. Build Taxonomy
    root_clusters = defaultdict(list)
    root_indices = defaultdict(list)
    for idx, label in enumerate(root_labels):
        root_clusters[label].append(filtered_concepts[idx])
        root_indices[label].append(idx)
        
    taxonomy = {}
    for root_id, members in root_clusters.items():
        root_label = label_cluster(members)
        
        if len(members) > 15:
            # Sub-cluster using the same matrix slice
            sub_matrix = filtered_matrix[root_indices[root_id]]
            actual_k = min(n_sub_clusters, len(members))
            if actual_k < 2:
                taxonomy[root_label] = members
                continue
            hac_sub = AgglomerativeClustering(n_clusters=actual_k, linkage='average', metric='cosine')
            sub_labels = hac_sub.fit_predict(sub_matrix)
            
            subcats = defaultdict(list)
            for i, sl in enumerate(sub_labels):
                subcats[sl].append(members[i])
            
            taxonomy[root_label] = {}
            for sub_id, sub_members in subcats.items():
                sub_label = label_cluster(sub_members)
                taxonomy[root_label][sub_label] = sub_members
        else:
            taxonomy[root_label] = members
            
    return taxonomy

# =========================================================================
# APPROACH E — Sequential (D Pillars -> C Fallback)
# =========================================================================

def approach_e(resumes, concepts, n_topics=8, n_sub_clusters=4):
    print("\n[Approach E] Sequential D (Anchors) -> C (Fallback)...")
    
    # 1. Run D to get high-confidence pillars
    # We use a smaller n_clusters for root pillars to keep them robust
    tax_d = approach_d(resumes, concepts, n_root_clusters=8, n_sub_clusters=3)
    
    assigned_concepts = set()
    def collect_members(d):
        for k, v in d.items():
            if isinstance(v, list): 
                assigned_concepts.update(v)
            elif isinstance(v, dict): 
                collect_members(v)
    collect_members(tax_d)
    
    orphans = [c for c in concepts if c not in assigned_concepts]
    print(f"  → D Pillars: {len(assigned_concepts)} concepts. Orphans: {len(orphans)}")
    
    # 2. Run Hybrid approach on Orphans only
    if orphans:
        tax_c_orphans = approach_c(resumes, orphans, n_topics=n_topics, n_sub_clusters=n_sub_clusters)
        
        # Merge results
        final_taxonomy = tax_d
        final_taxonomy["New / Unmapped Domains"] = tax_c_orphans
        return final_taxonomy
    
    return tax_d

# =========================================================================
# MAIN
# =========================================================================

def main():
    concepts = load_concepts()
    resumes = load_resumes()
    
    print(f"Loaded {len(concepts)} concepts, {len(resumes)} resumes.")
    
    # Run all approaches
    tax_a = approach_a(concepts, n_root_clusters=10, n_sub_clusters=4)
    tax_b = approach_b(resumes, concepts, n_topics=10)
    tax_c = approach_c(resumes, concepts, n_topics=10, n_sub_clusters=4)
    tax_d = approach_d(resumes, concepts, n_root_clusters=12, n_sub_clusters=4)
    tax_e = approach_e(resumes, concepts, n_topics=8, n_sub_clusters=4)
    
    # Print summaries
    print_taxonomy_summary(tax_a, "APPROACH A — TF-IDF + HAC")
    print_taxonomy_summary(tax_b, "APPROACH B — LDA (Cleaned)")
    print_taxonomy_summary(tax_c, "APPROACH C — Hybrid LDA→HAC")
    print_taxonomy_summary(tax_d, "APPROACH D — Documentary Co-occurrence")
    print_taxonomy_summary(tax_e, "APPROACH E — Sequential D -> C")
    
    # Save
    save_taxonomy(tax_a, "taxonomy_a.json")
    save_taxonomy(tax_b, "taxonomy_b.json")
    save_taxonomy(tax_c, "taxonomy_c.json")
    save_taxonomy(tax_d, "taxonomy_d.json")
    save_taxonomy(tax_e, "taxonomy_e.json")
    
    print("\n✅ A/B test complete. Compare taxonomy_a/b/c/d/e.json")

if __name__ == "__main__":
    main()
