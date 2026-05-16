import json
import os
import re

TAG_MAPPING_FILE = r'd:\Users\Gehiks\Documents\Applis\IndexationLivres\tag_mapping.json'
BOOK_REGISTRY_FILE = r'd:\Users\Gehiks\Documents\Applis\IndexationLivres\book_registry.json'

MACRO_KEYWORDS = {
    'gdp', 'macroeconomic', 'monetary', 'fiscal', 'economic theory', 
    'national economy', 'economic cycle', 'inflation', 'capitalism', 
    'socialism', 'labor market', 'economic policy', 'global economy',
    'comparative economics', 'econometrics', 'microeconomics'
}

def normalize_taxonomy_path(path):
    """Normalise un chemin hiérarchique complet avec déduplication et Title Case strict (G-7)."""
    if not path: return ""
    
    # 1. Unification sémantique globale (AVANT split)
    path = re.sub(r'(\d)\.0\b', r'\1_0', path)
    path = re.sub(r'\bComputing\b', 'Technology', path, flags=re.IGNORECASE)
    path = re.sub(r'\bHuman Resource\b', 'Human Resources', path, flags=re.IGNORECASE)
    path = re.sub(r'\bSoftware Development\b', 'Software Engineering', path, flags=re.IGNORECASE)
    path = re.sub(r'\bBusiness Strategy\b', 'Strategy', path, flags=re.IGNORECASE)
    
    seen = set()
    segments = []
    raw_segments = path.split('.')
    
    # Supprimer les segments racines jugés trop génériques
    while raw_segments and raw_segments[0].strip().lower() in ["industry", "technology", "memory", "education"]:
        raw_segments.pop(0)

    for seg in raw_segments:
        # Correction orthographe et pluriels
        seg = re.sub(r'\bAnalysi[s]*\b', 'Analysis', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bMathematic[s]*\b', 'Mathematics', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bTechnologic\b', 'Technology', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bResourc[e]?\b', 'Resources', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bBia\b', 'Bias', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bStatistic\b', 'Statistics', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bLinguistic\b', 'Linguistics', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bMethod\b', 'Methods', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bAnalytic\b', 'Analytics', seg, flags=re.IGNORECASE).strip()
        seg = re.sub(r'\bStrategy\b', 'Strategies', seg, flags=re.IGNORECASE).strip()
        
        # TITLE CASE FORCE (avec espaces)
        seg = seg.replace('-', ' ').replace('_', ' ')
        
        # Smart Title Case (gestion des acronymes)
        words = seg.split()
        capitalized_words = []
        for w in words:
            w_clean = re.sub(r'[^a-zA-Z]', '', w).lower()
            if w_clean in ['ai', 'llm', 'nlp', 'it', 'hr', 'kg', 'api', 'saas', 'ml', 'ocr', 'rag', 'ceo', 'chro', 'coo', 'esg', 'gdpr', 'mlop']:
                capitalized_words.append(w.upper())
            else:
                capitalized_words.append(w.capitalize())
        seg = " ".join(capitalized_words)

        if seg and seg.lower() not in seen:
            segments.append(seg)
            seen.add(seg.lower())
            
    if not segments: return ""
    
    # 2. Gestion des racines
    root_low = segments[0].lower()
    
    # Unification Management -> Business.Management
    if root_low == 'management':
        segments.insert(0, 'Business')
        # On refait une passe de déduplication car Business existait peut-être déjà
        new_segments = []
        new_seen = set()
        for s in segments:
            if s.lower() not in new_seen:
                new_seen.add(s.lower())
                new_segments.append(s)
        segments = new_segments
        root_low = 'business'

    if root_low == 'ai':
        segments[0] = 'ArtificialIntelligence'
        root_low = 'artificialintelligence'

    if root_low in ['economy', 'economics']:
        path_low = '.'.join(segments).lower()
        is_macro = any(kw in path_low for kw in MACRO_KEYWORDS)
        segments[0] = 'Economy' if is_macro else 'Business'
    
    # 3. Règle de rabotage (Pruning) : Max 5 niveaux
    if len(segments) > 5:
        segments = segments[:5]

    return ".".join(segments)

def main():
    print("Starting taxonomy sanitization...")
    
    # Update tag_mapping.json
    if os.path.exists(TAG_MAPPING_FILE):
        with open(TAG_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        
        new_mapping = {}
        for k, v in mapping.items():
            new_mapping[k] = normalize_taxonomy_path(v)
            
        with open(TAG_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_mapping, f, indent=4, ensure_ascii=False)
        print(f"  -> [OK] Updated {TAG_MAPPING_FILE}")

    # Update book_registry.json
    if os.path.exists(BOOK_REGISTRY_FILE):
        with open(BOOK_REGISTRY_FILE, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        
        updated_books = 0
        for book in registry:
            if 'tags' in book:
                old_tags = book['tags']
                new_tags = list(filter(None, [normalize_taxonomy_path(t) for t in old_tags]))
                if old_tags != new_tags:
                    book['tags'] = new_tags
                    updated_books += 1
        
        with open(BOOK_REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)
        print(f"  -> [OK] Updated {updated_books} books in {BOOK_REGISTRY_FILE}")

if __name__ == "__main__":
    main()
