import os
import time
import asyncio
import threading
import fitz  # PyMuPDF
import ollama
import json
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog
import subprocess
import shutil
import sys
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
from dotenv import load_dotenv
from typing import Any
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception
import pydantic
import google.genai as genai
from google.genai import types

load_dotenv()

# Suppression du logging lourd de PaddleOCR
ocr_engine = None
HAS_OCR = False

def get_ocr_engine():
    global ocr_engine, HAS_OCR
    if ocr_engine is not None:
        return ocr_engine
    try:
        from paddleocr import PaddleOCR
        import logging
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        print("-> Initialisation du moteur OCR (PaddleOCR)...")
        ocr_engine = PaddleOCR(use_textline_orientation=True, lang='fr', enable_mkldnn=False)
        HAS_OCR = True
        return ocr_engine
    except ImportError:
        HAS_OCR = False
        return None

# Configuration
LLM_BACKEND = os.getenv("LLM_BACKEND", "gemini").lower()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash" if LLM_BACKEND == "gemini" else "qwen2.5:7b-instruct-q4_K_M")
CALIBRE_LIBRARY_PATH = os.getenv("CALIBRE_LIBRARY_PATH")
TAG_LIST_FILE = "tag_list.json"
TAG_MAPPING_FILE = "tag_mapping.json"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

gemini_client = None
if LLM_BACKEND == "gemini":
    gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

class SyncTokenBucket:
    """Implémentation synchrone d'un Token Bucket pour le RPM Gemini."""
    def __init__(self, rpm: int) -> None:
        self.capacity = float(rpm)
        self.tokens = float(rpm)
        self.updated_at = time.monotonic()
        self.interval = 60.0 / rpm
        self.lock = threading.Lock()

    def consume(self) -> None:
        with self.lock:
            while self.tokens < 1:
                now = time.monotonic()
                passed = now - self.updated_at
                new_tokens = passed / self.interval
                if new_tokens >= 1:
                    self.tokens = min(self.capacity, self.tokens + new_tokens)
                    self.updated_at = now
                if self.tokens < 1:
                    wait_time = max(0.1, self.interval - (now - self.updated_at))
                    time.sleep(wait_time)
            self.tokens -= 1

# Limite à 15 requêtes par minute (Quota Free Tier)
rate_limiter = SyncTokenBucket(15)

class HierarchyResponse(pydantic.BaseModel):
    hierarchy: str

@retry(
    wait=wait_random_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(lambda e: any(kw in str(e).lower() for kw in ("429", "exhausted", "quota", "timeout", "connection", "503", "unavailable")))
)
def _ask_gemini_hierarchy(prompt: str) -> str:
    rate_limiter.consume()
    response = gemini_client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=HierarchyResponse,
            temperature=0.2
        ),
    )
    if response and response.text:
        try:
            data = json.loads(response.text)
            return data.get("hierarchy", "")
        except:
            pass
    return ""

def _ask_ollama_hierarchy(prompt: str) -> str:
    schema = HierarchyResponse.model_json_schema()
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': prompt}], format=schema)
        res = json.loads(response['message']['content'])
        return res.get('hierarchy', "")
    except Exception as e:
        print(f"Ollama error: {e}")
        return ""

def ask_llm_hierarchy(tag: str, roots: list, canonicals: list) -> str:
    roots_str = ", ".join(roots)
    canonicals_str = ", ".join(canonicals)
    prompt = f"""
You are a taxonomy expert. Create a hierarchical path for the concept "{tag}".
RULES:
1. The path MUST start with one of these ROOT domains: [{roots_str}].
2. Prioritize using these existing terminology segments if applicable: [{canonicals_str}].
3. The leaf (last segment) MUST be "{tag.title()}".
4. Separate segments with dots (e.g. Technology.Artificial Intelligence.Machine Learning).
5. Do NOT create deep paths if unnecessary. Max 4 levels.
6. Return a valid JSON.
"""
    if LLM_BACKEND == "gemini" and gemini_client:
        return _ask_gemini_hierarchy(prompt)
    else:
        return _ask_ollama_hierarchy(prompt)

# =========================================================================
# GESTION DES TAGS (CACHE, WIKIDATA, LLM)
# =========================================================================

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception: pass
    return default

def save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"  -> [Avertissement] Impossible de sauvegarder {path} : {e}")

# CHARGEMENT GLOBAL
canonical_tags = load_json(TAG_LIST_FILE, [])
tag_mapping = load_json(TAG_MAPPING_FILE, {})
canonical_lower_map = {t.lower(): t for t in canonical_tags}

@retry(wait=wait_random_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def search_wikidata_entity(term):
    url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={urllib.parse.quote(term)}&language=en&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'JunoDoc_Pipeline/2.0'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode())
        if data.get('search'):
            return data['search'][0]['id']
    return None

@retry(wait=wait_random_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def get_wikidata_ancestors(qid):
    query = f"""
    SELECT ?parent ?parentLabel (COUNT(?mid) AS ?distance) WHERE {{
      wd:{qid} (wdt:P279|wdt:P31)* ?mid .
      ?mid (wdt:P279|wdt:P31)+ ?parent .
      ?parent rdfs:label ?parentLabel.
      FILTER(LANG(?parentLabel) = "en")
    }}
    GROUP BY ?parent ?parentLabel
    ORDER BY DESC(?distance)
    """
    url = f"https://query.wikidata.org/sparql?query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'JunoDoc_Pipeline/2.0', 'Accept': 'application/sparql-results+json'})
    ancestors = []
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())
        for item in data.get('results', {}).get('bindings', []):
            ancestors.append({
                'id': item['parent']['value'].split('/')[-1],
                'label': item['parentLabel']['value'],
                'distance': int(item['distance']['value'])
            })
    return ancestors

WIKIDATA_ROOTS = {
    "science", "technology", "engineering", "mathematics", "business", 
    "management", "artificial intelligence", "society", "philosophy", 
    "economics", "environment", "history", "medicine", "communication",
    "art", "law", "education", "computing", "psychology", "biology",
    "physics", "chemistry", "geography", "politics", "culture", "industry"
}

def align_single_tag(tag):
    tag_clean = tag.strip()
    if not tag_clean: return None
    tag_lower = tag_clean.lower()
    
    # 1. Cache
    if tag_lower in tag_mapping:
        if "." in tag_mapping[tag_lower]:
            return tag_mapping[tag_lower]
        
    tag_final = canonical_lower_map.get(tag_lower, tag_clean.title())
    
    # 2. Wikidata
    try:
        qid = search_wikidata_entity(tag_clean)
        if qid:
            ancestors = get_wikidata_ancestors(qid)
            path_segments = []
            for anc in ancestors:
                label_lower = anc['label'].lower()
                if label_lower in canonical_lower_map or label_lower in WIKIDATA_ROOTS:
                    canonical_label = canonical_lower_map.get(label_lower, anc['label'].title())
                    if canonical_label not in path_segments and canonical_label.lower() != tag_lower:
                        path_segments.append(canonical_label)
            
            hierarchy = ".".join(path_segments + [tag_final]) if path_segments else ""
            
            if hierarchy and hierarchy != tag_final:
                tag_mapping[tag_lower] = hierarchy
                save_json(TAG_MAPPING_FILE, tag_mapping)
                return hierarchy
    except Exception as e:
        pass # Fallback to LLM
        
    # 3. LLM Fallback (si pas de hiérarchie trouvée ou échec)
    print(f"  -> [LLM Fallback] Generating hierarchy for '{tag}'...")
    try:
        hierarchy_llm = ask_llm_hierarchy(tag_clean, list(WIKIDATA_ROOTS), canonical_tags)
        if hierarchy_llm and hierarchy_llm != tag_final:
            tag_mapping[tag_lower] = hierarchy_llm
            save_json(TAG_MAPPING_FILE, tag_mapping)
            return hierarchy_llm
    except Exception as e:
        print(f"  -> [Erreur LLM Fallback] {e}")

    # Echec total, on garde le format plat
    tag_mapping[tag_lower] = tag_final
    save_json(TAG_MAPPING_FILE, tag_mapping)
    return tag_final

def batch_harmonize_calibre_tags():
    cmd = ["calibredb", "list", "-f", "tags", "--for-machine"]
    if CALIBRE_LIBRARY_PATH: cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        all_tags = set()
        for item in data:
            for t in item.get('tags', []): all_tags.add(t.strip())
        unmapped = [t for t in all_tags if t.lower() not in tag_mapping]
        for t in unmapped: align_single_tag(t)
    except: pass

def extract_text_with_ocr(page):
    engine = get_ocr_engine()
    if not engine: return ""
    try:
        import numpy as np
        from PIL import Image
        import io
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert('RGB')
        results = engine.ocr(np.array(img))
        return " ".join([line[1][0] for line in results[0]]) if results and results[0] else ""
    except: return ""

def extract_text_from_document(file_path, max_pages=10):
    text = ""
    try:
        doc = fitz.open(file_path)
        for i in range(min(max_pages, len(doc))):
            t = doc[i].get_text().strip()
            if len(t) < 100: t = extract_text_with_ocr(doc[i])
            text += t + "\n"
            if len(text) > 2000: break
        doc.close()
    except: pass
    return text

def get_metadata_from_llm(text):
    prompt = f"Extract Title, Author, Summary (English), Keywords (3-5) from this text: {text[:3000]}. Return JSON format: {{\"titre\": \"\", \"auteur\": \"\", \"resume\": \"\", \"mots_cles\": []}}"
    try:
        if LLM_BACKEND == "gemini" and gemini_client:
            rate_limiter.consume()
            response = gemini_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            res = json.loads(response.text)
        else:
            response = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': prompt}], format='json')
            res = json.loads(response['message']['content'])
            
        kw = [align_single_tag(k) for k in res.get('mots_cles', [])]
        return res.get('titre', ''), res.get('auteur', ''), res.get('resume', ''), filter(None, kw)
    except: return "", "", "", []

def process_directory(directory):
    batch_harmonize_calibre_tags()
    indexed_dir = os.path.join(directory, "indexed")
    if not os.path.exists(indexed_dir): os.makedirs(indexed_dir)
    for f in os.listdir(directory):
        if not f.lower().endswith('.pdf'): continue
        path = os.path.join(directory, f)
        txt = extract_text_from_document(path)
        title, author, summary, tags = get_metadata_from_llm(txt)
        if title and author:
            print(f"-> Indexé: {title} ({author})")
            shutil.move(path, os.path.join(indexed_dir, f))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_directory(sys.argv[1])
    else:
        print("Usage: python indexer.py <directory>")
