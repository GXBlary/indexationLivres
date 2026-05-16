import os
import json
import re
import subprocess
import zipfile

from kreuzberg import extract_file_sync

CALIBRE_LIBRARY_PATH = os.getenv("CALIBRE_LIBRARY_PATH") # Can be None if using default

def extract_document_text(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""
    try:
        result = extract_file_sync(file_path)
        return result.content
    except Exception as e:
        print(f"  -> [Kreuzberg Error] {e}")
        return ""

def get_calibre_summaries():
    """Fetches all book summaries from Calibre in one bulk operation."""
    print("  -> Récupération des résumés depuis Calibre (opération groupée)...")
    cmd = ["calibredb", "list", "--fields", "title,authors,comments", "--for-machine"]
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        books = json.loads(result.stdout)
        # Create a mapping (title, authors) -> summary
        mapping = {}
        for b in books:
            t = b.get('title')
            a = b.get('authors')
            c = b.get('comments', "")
            if t and a:
                mapping[(t, a)] = c
        return mapping
    except Exception as e:
        print(f"  -> [Attention] Impossible de récupérer les données Calibre : {e}")
        return {}

BOOK_REGISTRY_FILE = "book_registry.json"
TAG_MAPPING_FILE = "tag_mapping.json"
VAULT_DIR = "vault"
DOCS_DIR = os.path.join(VAULT_DIR, "docs")
TAGS_DIR = os.path.join(VAULT_DIR, "tags")

def to_pascal_case(text):
    if not text:
        return "Unknown"
    words = re.findall(r'[a-zA-Z0-9]+', text)
    return "".join(word.capitalize() for word in words)

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default

def get_tag_hierarchy(tag, tag_mapping):
    tag_lower = tag.lower()
    return tag_mapping.get(tag_lower, tag)

def extract_leaf_and_segments(hierarchy):
    if not hierarchy:
        return "", []
    segments = [s.strip() for s in hierarchy.split('.')]
    leaf = segments[-1]
    return leaf, segments

def prune_taxonomy(registry, tag_mapping):
    total_docs = len(registry)
    if total_docs == 0: return tag_mapping, set()
    
    min_docs = max(2, int(total_docs * 0.01))
    print(f"  -> [Pruning] Seuil de spécialisation: {min_docs} documents (1%).")
    
    changed = True
    blacklisted = set()
    
    # Pre-populate missing tags to ensure they can be pruned
    for book in registry:
        for raw_tag in book.get("tags", []):
            if raw_tag.lower() not in tag_mapping:
                tag_mapping[raw_tag.lower()] = raw_tag
                
    while changed:
        changed = False
        tag_docs = {}
        children_map = {}
        
        for book in registry:
            doc_id = (book.get("title"), book.get("authors"))
            raw_tags = book.get("tags", [])
            for raw_tag in raw_tags:
                hierarchy = tag_mapping.get(raw_tag.lower(), raw_tag)
                if not hierarchy: continue
                segments = [s.strip() for s in hierarchy.split('.')]
                for seg in segments:
                    seg_pc = to_pascal_case(seg)
                    if seg_pc not in tag_docs: tag_docs[seg_pc] = set()
                    tag_docs[seg_pc].add(doc_id)
                
                for i in range(len(segments) - 1):
                    p = to_pascal_case(segments[i])
                    c = to_pascal_case(segments[i+1])
                    if p not in children_map: children_map[p] = set()
                    children_map[p].add(c)
                    
        tags_to_remove = set()
        
        for tag, children in children_map.items():
            if len(children) == 1:
                tags_to_remove.add(tag)
                blacklisted.add(tag)
                print(f"     - Tag '{tag}' supprimé et blacklisté (trop générique, 1 seul enfant).")
                
        for tag, docs in tag_docs.items():
            if len(docs) < min_docs:
                tags_to_remove.add(tag)
                print(f"     - Tag '{tag}' supprimé (trop spécialisé, {len(docs)} documents).")
                
        if tags_to_remove:
            new_mapping = {}
            for key, path in tag_mapping.items():
                if not path:
                    new_mapping[key] = path
                    continue
                segments = [s.strip() for s in path.split('.')]
                new_segments = []
                for s in segments:
                    if to_pascal_case(s) not in tags_to_remove:
                        new_segments.append(s)
                new_mapping[key] = ".".join(new_segments)
            
            if new_mapping != tag_mapping:
                changed = True
                tag_mapping = new_mapping

    return tag_mapping, blacklisted

def main(output_dir=VAULT_DIR):
    print(f"\n{'='*50}")
    print(f"PHASE 4 : EXPORT MARKDOWN")
    print(f"{'='*50}")
    
    registry = load_json(BOOK_REGISTRY_FILE, [])
    tag_mapping = load_json(TAG_MAPPING_FILE, {})
    calibre_summaries = get_calibre_summaries()

    # Apply Pruning Rules
    tag_mapping, newly_blacklisted = prune_taxonomy(registry, tag_mapping)
    
    # Save the updated tag mapping
    with open(TAG_MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump(tag_mapping, f, ensure_ascii=False, indent=4)
        
    # Append newly blacklisted tags to blacklist.json
    if newly_blacklisted:
        blacklist = load_json("blacklist.json", [])
        blacklist.extend(list(newly_blacklisted))
        blacklist = sorted(list(set(blacklist)))
        with open("blacklist.json", "w", encoding="utf-8") as f:
            json.dump(blacklist, f, ensure_ascii=False, indent=4)

    if not registry:
        print("  -> Aucun livre trouvé dans le registre.")
        return

    os.makedirs(os.path.join(output_dir, "docs"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "tags"), exist_ok=True)
    
    docs_dir = os.path.join(output_dir, "docs")
    tags_dir = os.path.join(output_dir, "tags")

    tag_docs = {} # segment_pascal -> set(doc_names)
    tag_levels = {} # segment_pascal -> min_level
    parent_map = {} # segment_pascal -> set(parent_pascals)
    children_map = {} # segment_pascal -> set(child_pascals)
    
    # First pass: identify all tags and their hierarchies
    print("  -> Analyse de la hiérarchie des tags...")
    all_hierarchy_paths = set()
    for book in registry:
        raw_tags = book.get("tags", [])
        for raw_tag in raw_tags:
            hierarchy = get_tag_hierarchy(raw_tag, tag_mapping)
            if hierarchy:
                all_hierarchy_paths.add(hierarchy)
                
    for path in all_hierarchy_paths:
        segments = [s.strip() for s in path.split('.')]
        for i, segment in enumerate(segments):
            seg_pc = to_pascal_case(segment)
            level = i + 1
            if seg_pc not in tag_levels or level < tag_levels[seg_pc]:
                tag_levels[seg_pc] = level
            
            if seg_pc not in parent_map: parent_map[seg_pc] = set()
            if seg_pc not in children_map: children_map[seg_pc] = set()
            
            for p in segments[:i]:
                parent_map[seg_pc].add(to_pascal_case(p))
            for c in segments[i+1:]:
                children_map[seg_pc].add(to_pascal_case(c))

    print(f"  -> Génération des fichiers Markdown dans '{output_dir}/'...")

    title_to_filename = {}
    for b in registry:
        b_title = b.get("title", "")
        b_authors = b.get("authors", "Anonymous")
        b_author_first = b_authors.split(',')[0].split('&')[0].split(' and ')[0]
        b_doc_filename = f"{to_pascal_case(b_author_first)}_{to_pascal_case(b_title)}"
        if len(b_doc_filename) > 150: b_doc_filename = b_doc_filename[:150]
        if b_title:
            title_to_filename[b_title.lower()] = b_doc_filename

    for book in registry:
        title = book.get("title", "Unknown Title")
        authors = book.get("authors", "Anonymous")
        year = book.get("year", "0000")
        raw_tags = book.get("tags", [])
        summary = book.get("summary", calibre_summaries.get((title, authors), ""))

        leaf_tags_pascal = set()
        all_segments = set()

        for raw_tag in raw_tags:
            hierarchy = get_tag_hierarchy(raw_tag, tag_mapping)
            if not hierarchy: continue
            leaf, segments = extract_leaf_and_segments(hierarchy)
            if leaf: leaf_tags_pascal.add(to_pascal_case(leaf))
            for segment in segments: all_segments.add(segment)

        author_first = authors.split(',')[0].split('&')[0].split(' and ')[0]
        author_pc = to_pascal_case(author_first)
        title_pc = to_pascal_case(title)
        
        doc_filename = f"{author_pc}_{title_pc}"
        if len(doc_filename) > 150: doc_filename = doc_filename[:150]
        doc_name_link = doc_filename
        doc_path = os.path.join(docs_dir, doc_filename + ".md")

        # Bibliography propagation
        for segment in all_segments:
            seg_pc = to_pascal_case(segment)
            if seg_pc not in tag_docs: tag_docs[seg_pc] = set()
            tag_docs[seg_pc].add(doc_name_link)

        # Tags line with levels
        tags_parts = []
        for t in sorted(leaf_tags_pascal):
            lvl = tag_levels.get(t, "?")
            tags_parts.append(f"#{t} #lvl{lvl}")
        tags_line = " ".join(tags_parts)
        
        kg_line = " ".join(f"[[{to_pascal_case(s)}]]" for s in sorted(all_segments))

        full_text = ""
        txt_filename = f"{author_pc}_{title_pc}.txt"
        if len(txt_filename) > 150: txt_filename = txt_filename[:150] + ".txt"
        txt_path = os.path.join(output_dir, "texts", txt_filename)
        
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as tf:
                    full_text = tf.read()
            except: pass
                
        if not full_text:
            file_path = book.get("file_path", "")
            if file_path:
                full_text = extract_document_text(file_path)
                if full_text:
                    os.makedirs(os.path.dirname(txt_path), exist_ok=True)
                    try:
                        with open(txt_path, "w", encoding="utf-8") as tf:
                            tf.write(full_text)
                    except: pass

        references = book.get("references", [])
        ref_lines = []
        if references:
            for ref in references:
                matched = False
                for t_lower, doc_fname in title_to_filename.items():
                    if t_lower and len(t_lower) > 3 and t_lower in ref.lower():
                        ref_lines.append(f"- [[{doc_fname}]] (In Vault)")
                        matched = True
                        break
                if not matched:
                    ref_lines.append(f"- {ref} *(To Download)*")
            ref_section = "\n## References\n\n" + "\n".join(ref_lines) + "\n"
        else:
            ref_section = ""

        doc_content = f"""---
title: "{title}"
authors: "{authors}"
year: "{year}"
---

## Tags

{tags_line}

---

### Summary
{summary}

### Content
{full_text if full_text else "*(Full text not available)*"}

---
{ref_section}
## KG

{kg_line}
"""
        try:
            with open(doc_path, "w", encoding="utf-8") as df:
                df.write(doc_content)
        except: pass

    print(f"  -> Génération des fiches tags dans '{tags_dir}'...")
    for segment_pascal, docs in tag_docs.items():
        tag_file_path = os.path.join(tags_dir, f"{segment_pascal}.md")
        
        parents = sorted(list(parent_map.get(segment_pascal, set())), key=lambda x: tag_levels.get(x, 0))
        children = sorted(list(children_map.get(segment_pascal, set())), key=lambda x: tag_levels.get(x, 0))
        level = tag_levels.get(segment_pascal, 1)
        
        parents_list = [p for p in parents if p != segment_pascal]
        children_list = [c for c in children if c != segment_pascal]
        
        hierarchy_items = []
        for p in parents_list: hierarchy_items.append(f"[[{p}]]")
        hierarchy_items.append(f"**[[{segment_pascal}]]**")
        for c in children_list: hierarchy_items.append(f"[[{c}]]")
            
        hierarchy_str = "\n".join(f"{i+1}. {item}" for i, item in enumerate(hierarchy_items)) if hierarchy_items else f"1. **[[{segment_pascal}]]**"
        biblio_str = "\n".join(f"{i+1}. [[{doc}]]" for i, doc in enumerate(sorted(list(docs)))) if docs else "*(No documents)*"

        mermaid_lines = ["```mermaid", "graph TD"]
        for p in parents_list:
            mermaid_lines.append(f"    {p}(({p})) --> {segment_pascal}[**{segment_pascal}**]")
        for c in children_list:
            mermaid_lines.append(f"    {segment_pascal}[**{segment_pascal}**] --> {c}(({c}))")
        if not parents_list and not children_list:
            mermaid_lines.append(f"    {segment_pascal}[**{segment_pascal}**]")
        mermaid_lines.append("```")
        mermaid_str = "\n".join(mermaid_lines)

        tag_content = f"""#{segment_pascal} #lvl{level}

## Diagram

{mermaid_str}

## Hierarchy

{hierarchy_str}

## Bibliography

{biblio_str}
"""
        try:
            with open(tag_file_path, "w", encoding="utf-8") as tf:
                tf.write(tag_content)
        except: pass

    print(f"  -> [Succès] {len(registry)} documents exportés.")
    print(f"  -> [Succès] {len(tag_docs)} tags exportés.")


if __name__ == "__main__":
    main()
