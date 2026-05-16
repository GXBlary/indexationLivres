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
from tkinter import filedialog, messagebox, ttk
import subprocess
import shutil
import sys
import zipfile
import argparse
import base64
from kreuzberg import extract_file_sync
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
from dotenv import load_dotenv
import datetime
import export_to_neo4j # Export vers la base de graphes

class LoggerTee:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")
        
    def write(self, message):
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            # Fallback pour les terminaux Windows limités (CP1252)
            self.terminal.write(message.encode('ascii', 'replace').decode('ascii'))
            
        if self.log:
            try:
                self.log.write(message)
                self.log.flush()
            except: pass
            
    def flush(self):
        try:
            self.terminal.flush()
        except: pass
        if self.log: 
            try: self.log.flush()
            except: pass
from typing import Any
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception
import pydantic
import google.genai as genai
from google.genai import types

load_dotenv()

HAS_OCR = True # Assume true since kreuzberg handles it
def to_pascal_case(text):
    if not text: return "Unknown"
    # Supprimer les caractères spéciaux et garder alphanumeric, puis PascalCase
    words = re.findall(r'[a-zA-Z0-9]+', text)
    return "".join(word.capitalize() for word in words)

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
        seg = re.sub(r'\bAnalysi[s]*\b', 'Analysis', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bMathematic[s]*\b', 'Mathematics', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bTechnologic\b', 'Technology', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bResourc[e]?\b', 'Resources', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bBia\b', 'Bias', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bStatistic\b', 'Statistics', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bLinguistic\b', 'Linguistics', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bMethod\b', 'Methods', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bAnalytic\b', 'Analytics', seg, flags=re.IGNORECASE)
        seg = re.sub(r'\bStrategy\b', 'Strategies', seg, flags=re.IGNORECASE)
        
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
        norm_seg = " ".join(capitalized_words)

        # Déduplication globale
        if norm_seg.lower() not in seen and norm_seg:
            seen.add(norm_seg.lower())
            segments.append(norm_seg)
            
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
        # On garde les 5 niveaux les plus hauts (plus stable pour la racine)
        segments = segments[:5]

    # Reconstruction
    final_path = '.'.join(segments)
        
    return final_path

def get_gemini_models(client):
    """Récupère la liste des modèles Gemini supportant la génération de contenu."""
    try:
        models = [m.name for m in client.models.list() if 'generateContent' in (m.supported_actions or [])]
        return sorted([m.replace('models/', '') for m in models if 'gemini' in m.lower()])
    except Exception as e:
        print(f"  -> [Avertissement] Impossible de lister les modèles Gemini : {e}")
        return ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]

def get_ollama_models():
    """Récupère la liste des modèles Ollama installés."""
    try:
        models_info = ollama.list()
        # Gestion des différentes versions de l'API Ollama
        if hasattr(models_info, 'models'):
            return sorted([m.model for m in models_info.models])
        elif isinstance(models_info, dict) and 'models' in models_info:
            return sorted([m.get('name', m.get('model')) for m in models_info['models']])
        return ["[Ollama Offline (Fallback to qwen2.5)]"]
    except:
        return ["[Ollama Offline (Fallback to qwen2.5)]"]

# Configuration (Valeurs par défaut)
LLM_BACKEND = os.getenv("LLM_BACKEND", "gemini").lower()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip()
CALIBRE_LIBRARY_PATH = os.getenv("CALIBRE_LIBRARY_PATH")
TAG_LIST_FILE = "tag_list.json"
TAG_MAPPING_FILE = "tag_mapping.json"
BOOK_REGISTRY_FILE = "book_registry.json"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
VISION_API_KEY = os.getenv("VISION_API_KEY", GOOGLE_API_KEY)
OCR_BACKEND = os.getenv("OCR_BACKEND", "local").lower()

gemini_client = None
GEMINI_QUOTA_EXHAUSTED = False

def setup_llm():
    """Initialise le client LLM choisi et valide le modèle."""
    global gemini_client, MODEL_NAME
    
    if LLM_BACKEND == "gemini":
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY manquante dans le .env")
            
        print(f"-> Connexion au backend Gemini...")
        gemini_client = genai.Client(api_key=GOOGLE_API_KEY, http_options={'timeout': 300000})
        
        # Nettoyage automatique du préfixe models/ pour éviter les erreurs 400
        if MODEL_NAME.startswith("models/"):
            MODEL_NAME = MODEL_NAME.replace("models/", "")
            
        if not MODEL_NAME:
            # Fallback automatique si aucun modèle n'est défini
            available = get_gemini_models(gemini_client)
            MODEL_NAME = available[0] if available else "gemini-2.0-flash"
            
        print(f"  -> [OK] Utilisation du modèle Gemini : {MODEL_NAME}")
    else:
        print(f"-> Vérification de la connexion Ollama...")
        try:
            ollama.list()
            if not MODEL_NAME:
                models = get_ollama_models()
                MODEL_NAME = models[0] if models else "qwen2.5:7b-instruct-q4_K_M"
            print(f"  -> [OK] Utilisation du modèle Ollama : {MODEL_NAME}")
        except Exception as e:
            raise ConnectionError(f"Impossible de contacter Ollama : {e}")
            
    if OCR_BACKEND == "local":
        print(f"-> Utilisation de Kreuzberg pour l'extraction.")

def is_quota_error(e: Exception) -> bool:
    """Détecte si une exception est liée à un épuisement de quota (429, Resource Exhausted)."""
    # Si c'est une RetryError de tenacity, on regarde la dernière tentative
    if hasattr(e, "last_attempt") and e.last_attempt and e.last_attempt.failed:
        e = e.last_attempt.exception()
        
    err_msg = str(e).lower()
    return any(kw in err_msg for kw in ("429", "exhausted", "quota")) or "clienterror" in err_msg

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

class BatchHierarchyResponse(pydantic.BaseModel):
    hierarchies: dict[str, str]

class MetadataResponse(pydantic.BaseModel):
    titre: str
    auteur: str
    resume: str
    mots_cles: list[str]
    references: list[str] = []

@retry(
    wait=wait_random_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(lambda e: any(kw in str(e).lower() for kw in ("timeout", "connection", "503", "unavailable")) and not any(q in str(e).lower() for q in ("429", "exhausted", "quota")))
)
def _ask_gemini_hierarchy(prompt: str) -> tuple[str, int]:
    rate_limiter.consume()
    try:
        response = gemini_client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HierarchyResponse,
                temperature=0.1,
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE")
                ],
                http_options={'timeout': 300000}
            ),
        )
        tokens = 0
        if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens = response.usage_metadata.total_token_count
        
        if response and response.text:
            try:
                data = json.loads(response.text)
                return data.get("hierarchy", ""), tokens
            except:
                pass
        return "", tokens
    except Exception as e:
        # Propager l'erreur pour permettre le fallback dans la fonction parente
        raise e

def _ask_ollama_hierarchy(prompt: str) -> tuple[str, int]:
    schema = HierarchyResponse.model_json_schema()
    local_model = "qwen2.5:7b-instruct-q4_K_M" if LLM_BACKEND == "gemini" else MODEL_NAME
    options = {'temperature': 0.1, 'num_predict': 256}
    try:
        response = ollama.chat(
            model=local_model, 
            messages=[{'role': 'user', 'content': prompt}], 
            format=schema,
            options=options
        )
        content = response['message']['content']
        tokens = response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
        try:
            res = json.loads(content)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', content, re.DOTALL)
            res = json.loads(m.group(0)) if m else {}
        return res.get('hierarchy', ""), tokens
    except Exception as e:
        print(f"Ollama error: {e}")
        return "", 0

def ask_llm_hierarchy(tag: str, roots: list, mapping: dict) -> tuple[str, int]:
    global GEMINI_QUOTA_EXHAUSTED
    
    # Stratégie d'échantillonnage pour éviter l'explosion du prompt (max ~300 tags)
    all_paths = list(mapping.values())
    unique_paths = sorted(list(set(all_paths)))
    
    if len(unique_paths) > 300:
        from collections import defaultdict
        roots_map = defaultdict(list)
        for p in unique_paths:
            roots_map[p.split('.')[0]].append(p)
        
        subset = []
        per_root = max(1, 300 // (len(roots_map) or 1))
        for r_paths in roots_map.values():
            subset.extend(r_paths[:per_root])
        unique_paths = sorted(subset[:400])
    
    roots_str = ", ".join(roots)
    canonicals_str = "\n".join([f"- {p}" for p in unique_paths])
    
    prompt = f"""
You are a library taxonomy expert. Create a logical English hierarchical path for the concept "{tag}".
RULES:
1. EXCLUSIVELY output English. Use PascalCase (e.g. "Artificial Intelligence").
2. The path MUST start with one of these ROOT domains: [{roots_str}].
3. Follow the style of existing examples below to maintain semantic consistency.
4. Avoid "parallel paths": if the concept (leaf) already exists in a branch, reuse it.
5. Keep it shallow: 3-5 segments max.
6. NO ONTOLOGICAL NOISE: Avoid unnecessary segments like "Memory", "Philosophy", "Science".

Existing Taxonomy Examples:
{canonicals_str}

Return a JSON object with a single key "hierarchy".
"""
    if LLM_BACKEND == "gemini" and gemini_client and not GEMINI_QUOTA_EXHAUSTED:
        try:
            return _ask_gemini_hierarchy(prompt)
        except Exception as e:
            if is_quota_error(e):
                GEMINI_QUOTA_EXHAUSTED = True
                print(f"  -> [Alerte] Quota Gemini épuisé pour cette session. Bascule définitive sur Ollama.")
            else:
                print(f"  -> [Avertissement] Erreur Gemini ({e}), bascule temporaire sur Ollama...")
            return _ask_ollama_hierarchy(prompt)
    else:
        return _ask_ollama_hierarchy(prompt)

def process_gemini_batch(tags_to_process):
    """Gère l'alignement massif via l'API Gemini Batch (Asynchrone)."""
    if not tags_to_process:
        return
    
    if LLM_BACKEND != "gemini" or not gemini_client:
        print(f"  -> [Info] Backend local/incompatible. Passage au traitement séquentiel optimisé...")
        total = len(tags_to_process)
        for i, tag in enumerate(tags_to_process):
            align_single_tag(tag, i+1, total, force_wikidata=True)
            if (i + 1) % 10 == 0:
                save_json(TAG_MAPPING_FILE, tag_mapping)
        save_json(TAG_MAPPING_FILE, tag_mapping)
        return

    print(f"\n{'='*50}")
    print(f"PHASE 1.5 : BATCH GEMINI ASYNCHRONE ({len(tags_to_process)} tags)")
    print(f"{'='*50}")
    
    # 1. Préparation
    chunks = [tags_to_process[i:i + 40] for i in range(0, len(tags_to_process), 40)]
    batch_file_path = "gemini_batch_requests.jsonl"
    roots_str = ", ".join(WIKIDATA_ROOTS)
    
    # Échantillonnage de la taxonomie existante pour le contexte
    all_paths = list(set(tag_mapping.values()))
    context_str = "\n".join([f"- {p}" for p in all_paths[:300]])
    
    with open(batch_file_path, "w", encoding="utf-8") as f:
        for i, chunk in enumerate(chunks):
            prompt = f"""
You are a library taxonomy expert. Create a logical English hierarchical path for EACH concept: {json.dumps(chunk)}.
RULES:
1. EXCLUSIVELY English & PascalCase.
2. Root domains: [{roots_str}].
3. Semantic consistency with existing examples:
{context_str}
4. Shallow hierarchy (3-5 segments).
Return JSON: {{ "hierarchies": {{ "original_tag": "Path.Value" }} }}
"""
            request = {
                "request": {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "config": {
                        "response_mime_type": "application/json",
                        "response_schema": BatchHierarchyResponse,
                    }
                }
            }
            f.write(json.dumps(request) + "\n")
            
    # 2. Upload et Exécution
    print(f"  -> Upload du fichier batch...")
    try:
        # En utilisant le SDK google-genai
        with open(batch_file_path, "rb") as f:
            uploaded_file = gemini_client.files.upload(file=f, config={'display_name': 'batch_tags'})
        
        print(f"  -> Création du Job Batch ({MODEL_NAME})...")
        batch_job = gemini_client.batches.create(
            model=f"models/{MODEL_NAME}" if not MODEL_NAME.startswith("models/") else MODEL_NAME,
            requests_file_uri=uploaded_file.uri
        )
        
        job_id = batch_job.name
        print(f"  -> Job lancé : {job_id}. Attente de complétion...")
        
        # 3. Polling
        start_wait = time.time()
        while True:
            job = gemini_client.batches.get(name=job_id)
            state = str(job.state)
            elapsed = time.time() - start_wait
            print(f"     [{datetime.datetime.now().strftime('%H:%M:%S')}] État: {state} ({int(elapsed)}s écoulés)")
            
            if "SUCCEEDED" in state:
                break
            if any(s in state for s in ["FAILED", "EXPIRED", "CANCELLED"]):
                print(f"  -> [ERREUR] Le job a échoué : {state}")
                return
            time.sleep(30)
            
        # 4. Récupération
        print(f"  -> Récupération des résultats...")
        # Le job réussi contient l'URI du fichier de sortie
        output_uri = getattr(job, 'output_file_uri', None)
        if not output_uri:
            # Tenter de chercher dans la réponse si non présent directement
            response = getattr(job, 'response', None)
            if response:
                output_uri = getattr(response, 'output_file_uri', None)
        
        if not output_uri:
            print("  -> [ERREUR] Impossible de trouver l'URI du fichier de sortie.")
            return

        output_file_name = output_uri.split('/')[-1]
        output_data = gemini_client.files.download(name=output_file_name)
        
        lines = output_data.decode('utf-8').splitlines()
        success_count = 0
        for line in lines:
            try:
                data = json.loads(line)
                # Structure du résultat Batch
                response = data.get('response', {})
                candidates = response.get('candidates', [])
                if candidates:
                    text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
                    res_json = json.loads(text)
                    hierarchies = res_json.get('hierarchies', {})
                    for tag, path in hierarchies.items():
                        tag_mapping[tag.lower()] = normalize_taxonomy_path(path)
                        success_count += 1
            except: pass
            
        save_json(TAG_MAPPING_FILE, tag_mapping)
        print(f"  -> [OK] {success_count} tags alignés via Batch Gemini.")
        
    except Exception as e:
        print(f"  -> [ERREUR CRITIQUE BATCH] {e}")

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
    req = urllib.request.Request(url, headers={'User-Agent': 'JunoDoc_Pipeline/2.0 (https://github.com/gehiks/JunoDoc; mailto:admin@junodoc.com)'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode())
        if data.get('search'):
            return data['search'][0]['id']
    return None

LOC_ROOT_MAP = {
    'A': 'Society', 'B': 'Philosophy', 'C': 'History', 'D': 'History', 'E': 'History', 
    'F': 'History', 'G': 'Geography', 'H': 'Business', 'J': 'Politics', 'K': 'Law', 
    'L': 'Education', 'M': 'Art', 'N': 'Art', 'P': 'Culture', 'Q': 'Science', 
    'R': 'Medicine', 'S': 'Technology', 'T': 'Technology', 'U': 'Society', 
    'V': 'Society', 'Z': 'Technology'
}

def map_loc_to_root(loc_code):
    if not loc_code: return None
    first_letter = loc_code[0].upper()
    return LOC_ROOT_MAP.get(first_letter)

BISAC_ROOT_MAP = {
    'BUS': 'Business', 'COM': 'Technology', 'PHI': 'Philosophy', 'SOC': 'Society',
    'SCI': 'Science', 'LAW': 'Law', 'ECO': 'Economics', 'MAT': 'Mathematics',
    'MED': 'Medicine', 'HIS': 'History', 'LAN': 'Communication', 'ART': 'Art',
    'EDU': 'Education', 'TEC': 'Technology', 'COM': 'Technology', 'PSY': 'Society',
    'POL': 'Politics'
}

def map_bisac_to_root(bisac_code):
    if not bisac_code: return None
    prefix = bisac_code[:3].upper()
    return BISAC_ROOT_MAP.get(prefix)

def map_dewey_to_root(dewey_code):
    if not dewey_code: return None
    try:
        first_digit = dewey_code[0]
        mapping = {
            '0': 'Technology', '1': 'Philosophy', '2': 'Society', '3': 'Society',
            '4': 'Communication', '5': 'Science', '6': 'Technology', '7': 'Art',
            '8': 'Culture', '9': 'History'
        }
        return mapping.get(first_digit)
    except: return None

@retry(wait=wait_random_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def get_wikidata_taxonomy(qid):
    """Récupère des informations de classification LOD (LoC, Dewey, BISAC, Sujet) pour un QID."""
    query = f"""
    SELECT ?prop ?val ?valLabel WHERE {{
      VALUES (?prop) {{ (wdt:P1149) (wdt:P1036) (wdt:P12164) (wdt:P921) (wdt:P361) (wdt:P279) }}
      wd:{qid} ?prop ?val .
      OPTIONAL {{ ?val rdfs:label ?valLabel . FILTER(LANG(?valLabel) = "en") }}
    }}
    """
    url = f"https://query.wikidata.org/sparql?query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'JunoDoc_Pipeline/2.0 (https://github.com/gehiks/JunoDoc; mailto:admin@junodoc.com)', 'Accept': 'application/sparql-results+json'})
    
    results = {'loc': [], 'dewey': [], 'bisac': [], 'subjects': [], 'parents': []}
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode())
            for item in data.get('results', {}).get('bindings', []):
                prop = item['prop']['value'].split('/')[-1]
                val = item['val']['value']
                label = item.get('valLabel', {}).get('value')
                
                if prop == 'P1149': results['loc'].append(val)
                elif prop == 'P1036': results['dewey'].append(val)
                elif prop == 'P12164': results['bisac'].append(val)
                elif prop == 'P921' or prop == 'P361': 
                    if label: results['subjects'].append(label)
                elif prop == 'P279':
                    if label: results['parents'].append(label)
    except: pass
    return results

WIKIDATA_ROOTS = {
    "science", "technology", "engineering", "mathematics", "business", 
    "management", "artificial intelligence", "society", "philosophy", 
    "economics", "environment", "history", "medicine", "communication",
    "art", "law", "education", "computing", "psychology", "biology",
    "physics", "chemistry", "geography", "politics", "culture", "industry"
}

ONTOLOGICAL_BLACKLIST = {
    "work", "content", "knowledge sharing", "object", "entity", "thing", 
    "artificial object", "concept", "abstract concept", "class", "attribute",
    "property", "item", "information"
}
try:
    with open("blacklist.json", "r", encoding="utf-8") as f:
        dynamic_blacklist = set([item.lower() for item in json.load(f)])
        ONTOLOGICAL_BLACKLIST.update(dynamic_blacklist)
except Exception:
    pass

def align_single_tag(tag, progress="", force_wikidata=False):
    tag_clean = tag.strip()
    if not tag_clean: return None
    tag_lower = tag_clean.lower()
    start_t = time.time()
    tokens = 0
    progress_str = f" {progress}" if progress else ""
    
    # 1. Cache (Skip if force_wikidata is True)
    if not force_wikidata and tag_lower in tag_mapping:
        hierarchy = tag_mapping[tag_lower]
        if "." in hierarchy:
            elapsed = time.time() - start_t
            print(f"  -> [Alignement]{progress_str} '{tag_clean}' (Cache) -> {hierarchy} | {elapsed:.3f}s | {tokens} tx")
            return hierarchy
        
    tag_final = canonical_lower_map.get(tag_lower, tag_clean.title())
    
    # 2. Wikidata (Smarter LOD pass)
    try:
        # Si le tag est déjà hiérarchique, on cherche sur la feuille
        leaf = tag_clean.split('.')[-1].split(' > ')[-1].strip()
        qid = search_wikidata_entity(leaf)
        if qid:
            print(f"    -> [Wikidata] QID trouv : {qid} pour '{leaf}'")
            info = get_wikidata_taxonomy(qid)
            path_segments = []
            
            # Priorité 1: Library of Congress (LoC)
            if info['loc']:
                root = map_loc_to_root(info['loc'][0])
                if root: path_segments.append(root)
            
            # Priorité 2: Dewey Decimal Classification
            if not path_segments and info['dewey']:
                root = map_dewey_to_root(info['dewey'][0])
                if root: path_segments.append(root)

            # Priorité 3: BISAC Subject Headings
            if not path_segments and info['bisac']:
                root = map_bisac_to_root(info['bisac'][0])
                if root: path_segments.append(root)

            # Priorité 4: Sujets et Parents directs Wikidata
            # On fusionne et on déduplique
            potential_anc = list(dict.fromkeys(info['subjects'] + info['parents']))
            for anc in potential_anc:
                label_lower = anc.lower()
                if label_lower in ONTOLOGICAL_BLACKLIST: continue
                
                if label_lower in canonical_lower_map or label_lower in WIKIDATA_ROOTS:
                    raw_label = canonical_lower_map.get(label_lower, anc)
                    canonical_label = " ".join(w.capitalize() for w in raw_label.split())
                    
                    if canonical_label not in path_segments and canonical_label.lower() != tag_lower:
                        path_segments.append(canonical_label)
            
            # Limiter la profondeur Wikidata pour éviter le bruit
            if len(path_segments) > 3:
                path_segments = path_segments[:3]
                
            tag_final_norm = normalize_taxonomy_path(tag_final)
            hierarchy = ".".join(path_segments + [tag_final_norm]) if path_segments else tag_final_norm
            hierarchy = normalize_taxonomy_path(hierarchy)
            
            if hierarchy and hierarchy != tag_final:
                elapsed = time.time() - start_t
                print(f"  -> [Alignement]{progress_str} '{tag_clean}' (Wikidata LOD) -> {hierarchy} | {elapsed:.2f}s | {tokens} tx")
                tag_mapping[tag_lower] = hierarchy
                save_json(TAG_MAPPING_FILE, tag_mapping)
                return hierarchy
    except Exception:
        pass # Fallback to LLM
        
    if force_wikidata:
        # Mesure d'impact Wikidata uniquement : on ne tombe pas en LLM
        return None
        
    # 3. LLM Fallback (si pas de hiérarchie trouvée ou échec)
    # Note: En mode synchrone (indexation individuelle), on garde l'appel direct.
    print(f"  -> [LLM Fallback]{progress_str} Recherche d'alignement pour '{tag}'...")
    try:
        hierarchy_llm, tokens = ask_llm_hierarchy(tag_clean, list(WIKIDATA_ROOTS), tag_mapping)
        if hierarchy_llm:
            elapsed = time.time() - start_t
            if hierarchy_llm != tag_final:
                # Normalisation finale de la réponse LLM
                hierarchy_llm = normalize_taxonomy_path(hierarchy_llm)
                print(f"  -> [Alignement]{progress_str} '{tag_clean}' (LLM) -> {hierarchy_llm} | {elapsed:.2f}s | {tokens} tx")
            else:
                hierarchy_llm = normalize_taxonomy_path(tag_final)
                print(f"  -> [Alignement]{progress_str} '{tag_clean}' (LLM) -> {hierarchy_llm} (Format plat) | {elapsed:.2f}s | {tokens} tx")
            tag_mapping[tag_lower] = hierarchy_llm
            save_json(TAG_MAPPING_FILE, tag_mapping)
            return hierarchy_llm
    except Exception as e:
        print(f"  -> [Erreur LLM Fallback] {e}")

    # Echec total, on garde le format plat
    elapsed = time.time() - start_t
    print(f"  -> [Alignement]{progress_str} '{tag_clean}' (Défaut) -> {tag_final} | {elapsed:.2f}s | {tokens} tx")
    tag_mapping[tag_lower] = tag_final
    save_json(TAG_MAPPING_FILE, tag_mapping)
    return tag_final

def add_to_calibre(file_path, title, author, tags):
    """Ajoute un nouveau livre à Calibre avec les métadonnées de base."""
    print(f"  -> [Calibre] Importation de '{title}'...")
    cmd = ["calibredb", "add", file_path, "--title", title, "--authors", author]
    if tags:
        # Calibre attend les tags séparés par des virgules
        cmd.extend(["--tags", ",".join(tags)])
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        # Note: 'add' ne supporte pas '--field', on mettra à jour le résumé après l'ajout
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"  -> [Succès] Livre ajouté à Calibre.")
        return True
    except Exception as e:
        print(f"  -> [Erreur Calibre Add] {e}")
        if hasattr(e, 'stderr') and e.stderr:
            err = e.stderr.lower()
            if "database is locked" in err or "another program" in err:
                print(f"\n[IMPORTANT] La base Calibre est verrouillée. VEUILLEZ FERMER CALIBRE DESKTOP.")
        return False

def is_book_in_calibre(title, author):
    """Vérifie si un livre avec le même titre et auteur existe déjà dans Calibre."""
    # Recherche exacte (=) pour éviter les faux positifs
    search_query = f'title:"={title}" and authors:"={author}"'
    cmd = ["calibredb", "list", "--search", search_query, "--fields", "id", "--for-machine"]
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        books = json.loads(result.stdout)
        if books:
            return str(books[0]['id'])
    except Exception as e:
        # On ne bloque pas le processus si la recherche échoue, on retourne juste None
        return None

def update_calibre_metadata(book_id, authors, tags, summary):
    """Met à jour les métadonnées d'un livre existant."""
    print(f"  -> [Calibre] Mise à jour des métadonnées pour le livre ID {book_id}...")
    cmd = ["calibredb", "set_metadata", book_id]
    if authors:
        cmd.extend(["--field", f"authors:{authors}"])
    if tags:
        cmd.extend(["--field", f"tags:{','.join(tags)}"])
    if summary:
        cmd.extend(["--field", f"comments:{summary}"])
    if CALIBRE_LIBRARY_PATH:
        cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"  -> [Succès] Métadonnées mises à jour dans Calibre.")
        return True
    except Exception as e:
        print(f"  -> [Erreur Calibre Update] {e}")
        return False

def sync_calibre_library():
    """Synchronise toute la bibliothèque Calibre avec notre taxonomie hiérarchique."""
    print(f"\n{'='*50}")
    print(f"SYNC PHASE 0 : SYNCHRONISATION GLOBALE CALIBRE")
    print(f"{'='*50}")
    print("  -> Mise à jour des tags de la bibliothèque existante...")
    
    list_cmd = ["calibredb", "list", "-f", "tags", "--for-machine"]
    if CALIBRE_LIBRARY_PATH: list_cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        books = json.loads(result.stdout)
        
        updated_count = 0
        for book in books:
            book_id = str(book.get('id'))
            current_tags = book.get('tags', [])
            new_tags = set()
            changed = False
            
            for t in current_tags:
                t_clean = t.strip()
                t_lower = t_clean.lower()
                
                # Si le tag contient un point (vieux format), on le split
                if "." in t_clean:
                    for part in t_clean.split("."):
                        new_tags.add(part.strip())
                    continue
                
                # Si le tag existe dans notre mapping et contient une hiérarchie (.)
                if t_lower in tag_mapping:
                    mapped_value = tag_mapping[t_lower]
                    if "." in mapped_value:
                        for part in mapped_value.split("."):
                            new_tags.add(part.strip())
                    else:
                        new_tags.add(mapped_value)
                else:
                    new_tags.add(t_clean)
            
            if set(current_tags) != new_tags:
                changed = True
            
            if changed:
                # Mise à jour des métadonnées dans Calibre
                set_cmd = ["calibredb", "set_metadata", book_id, "--field", f"tags:{','.join(new_tags)}"]
                if CALIBRE_LIBRARY_PATH: set_cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
                try:
                    subprocess.run(set_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    updated_count += 1
                except subprocess.CalledProcessError as e:
                    err_msg = e.stderr.lower() if e.stderr else str(e).lower()
                    if "autre programme calibre" in err_msg or "database is locked" in err_msg or "running" in err_msg:
                        print(f"\n[ERROR] La base de données Calibre est verrouillée (Calibre est probablement ouvert).")
                        print(f"      Veuillez fermer Calibre et relancer l'indexeur pour synchroniser la bibliothèque.")
                        return # On arrête proprement la phase de sync
                    else:
                        print(f"  -> [Erreur Sync] Impossible de mettre à jour le livre {book_id}: {e.stderr}")

        if updated_count > 0:
            print(f"  -> [OK] {updated_count} livres mis à jour avec la nouvelle taxonomie.")
        else:
            print("  -> Aucun changement nécessaire sur les livres existants.")
    except Exception as e:
        print(f"  -> [Erreur Sync Globale] {e}")

def update_book_registry(title, authors, year, tags, summary="", file_path="", references=None):
    """Enregistre ou met à jour un livre dans le registre local pour Neo4j."""
    registry = load_json(BOOK_REGISTRY_FILE, [])
    if references is None:
        references = []
    
    # Chercher si le livre existe déjà (par titre et auteurs)
    found = False
    for book in registry:
        if book.get('title') == title and book.get('authors') == authors:
            book['year'] = year
            book['tags'] = list(tags)
            book['summary'] = summary
            if file_path: book['file_path'] = file_path
            if references: book['references'] = references
            found = True
            break
    
    if not found:
        registry.append({
            "title": title,
            "authors": authors,
            "year": year,
            "tags": list(tags),
            "summary": summary,
            "file_path": file_path,
            "references": references
        })
    
    save_json(BOOK_REGISTRY_FILE, registry)
    print(f"  -> [Registre] '{title}' enregistré/mis à jour.")

def batch_harmonize_calibre_tags():
    # Initialisation de la synchronisation automatique réclamée par l'utilisateur
    sync_calibre_library()
    
    print(f"\n{'='*50}")
    print(f"SYNC PHASE 1 : ANALYSE ET ALIGNEMENT LOD (Wikidata)")
    print(f"{'='*50}")
    print("  -> Vérification des tags nécessitant un alignement...")
    
    cmd = ["calibredb", "list", "-f", "tags", "--for-machine"]
    if CALIBRE_LIBRARY_PATH: cmd.extend(["--with-library", CALIBRE_LIBRARY_PATH])
    
    try:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
            data = json.loads(result.stdout)
            all_tags = set()
            for item in data:
                for t in item.get('tags', []): all_tags.add(t.strip())
            to_process = list(all_tags)
        except Exception as e:
            print(f"  -> [Avertissement] Impossible de lire Calibre ({e}). Utilisation de {TAG_LIST_FILE} comme base.")
            to_process = load_json(TAG_LIST_FILE, [])
        tags_for_llm = []
        total = len(to_process)
        print(f"  -> {total} tags à analyser. Lancement de la passe Wikidata LOD...")
        
        for i, t in enumerate(to_process, 1):
            t_clean = t.strip()
            if not t_clean: continue
            
            # On FORCE Wikidata
            res = align_single_tag(t_clean, progress=f"[{i}/{total}]", force_wikidata=True)
            
            if not res:
                print(f"  -> [Alignement] [{i}/{total}] '{t_clean}' : Aucun résultat Wikidata.")
            
            if (i % 10 == 0):
                save_json(TAG_MAPPING_FILE, tag_mapping)
            
            time.sleep(2.0) # Rate limit safety
                
            if not res or "." not in res:
                tags_for_llm.append(t_clean)
            
            # Petit délai pour éviter le 429 Wikidata sur 1400 tags
            # time.sleep(0.5)
        
        # Phase 2 : DÉSACTIVÉE pour mesure d'impact Wikidata
        print(f"\n  -> [Info] Phase Gemini Batch sautée ({len(to_process)} tags analysés via Wikidata).")
            
        # Re-synchronisation finale de la bibliothèque
        print("\n  -> Synchronisation finale de la bibliothèque...")
        sync_calibre_library()
            
    except Exception as e:
        print(f"  -> Erreur de synchronisation globale: {e}")

def extract_book_content(file_path):
    try:
        result = extract_file_sync(file_path)
        return result.content
    except Exception as e:
        print(f"  -> [Erreur Kreuzberg Extraction] {e}")
        return ""

@retry(
    wait=wait_random_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
    # On ne réessaie PAS sur les erreurs de quota (429) pour basculer immédiatement sur Ollama
    retry=retry_if_exception(lambda e: any(kw in str(e).lower() for kw in ("timeout", "connection", "503", "unavailable")) and not any(q in str(e).lower() for q in ("429", "exhausted", "quota")))
)
def _ask_gemini_metadata(prompt: str) -> tuple[dict, int]:
    rate_limiter.consume()
    try:
        response = gemini_client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MetadataResponse,
                temperature=0.1,
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE")
                ],
                http_options={'timeout': 300000}
            ),
        )
        tokens = 0
        if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens = response.usage_metadata.total_token_count
        
        if response and response.text:
            return json.loads(response.text), tokens
    except Exception as e:
        # Propager l'erreur pour activer le fallback Ollama dans get_metadata_from_llm
        raise e

def _ask_ollama_metadata(prompt: str) -> tuple[dict, int]:
    schema = MetadataResponse.model_json_schema()
    local_model = "qwen2.5:7b-instruct-q4_K_M" if LLM_BACKEND == "gemini" else MODEL_NAME
    options = {'temperature': 0.1, 'num_predict': 1024}
    try:
        response = ollama.chat(
            model=local_model, 
            messages=[{'role': 'user', 'content': prompt}], 
            format=schema,
            options=options
        )
        tokens = response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
        content = response['message']['content']
        try:
            res = json.loads(content)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', content, re.DOTALL)
            res = json.loads(m.group(0)) if m else {}
        return res, tokens
    except Exception as e:
        raise ValueError(f"Ollama extraction failed: {e}")

def get_metadata_from_llm(text):
    global GEMINI_QUOTA_EXHAUSTED
    
    if len(text) > 8000:
        text_chunk = text[:4000] + "\n\n... [CONTENT OMITTED] ...\n\n" + text[-4000:]
    else:
        text_chunk = text
        
    prompt = f"""
Extract metadata from the following text (English only).
First, analyze the text and select the best method among (Minto, SPRI, Exec. Sum., Toulmin, Dialectic, BLUF, Feynman, etc.) to summarize the text.
Generate the summary using this method. The summary must be a 'Flash Summary' (Subject + 3 key themes) followed by a 'Detailed Summary' strictly following the structure of the chosen method.

Extract metadata:
1. Title: Canonical title of the work.
2. Author: Full name of the author(s). If unknown or not specified, strictly return "Anonymous".
3. Summary: The generated summary (Flash + Detailed).
4. Keywords: 3-5 keywords in ENGLISH. NO ABBREVIATIONS.
5. Year: The publication year (4 digits). If unknown, return "0000".
6. References: Extract the bibliography or list of references found at the end of the text. Provide a list of titles or citations.

Text: {text_chunk}
"""
    res = {}
    tokens = 0
    start_t = time.time()
    
    if LLM_BACKEND == "gemini" and gemini_client and not GEMINI_QUOTA_EXHAUSTED:
        print(f"  -> [LLM] Extraction des métadonnées du document avec Gemini ({MODEL_NAME})...")
        try:
            res, tokens = _ask_gemini_metadata(prompt)
        except Exception as e:
            if is_quota_error(e):
                GEMINI_QUOTA_EXHAUSTED = True
                print(f"  -> [Alerte] Quota Gemini épuisé pour cette session. Bascule définitive sur Ollama.")
            else:
                print(f"  -> [Avertissement] Erreur Gemini ({e}). Bascule temporaire sur Ollama Locale...")
            try:
                res, tokens = _ask_ollama_metadata(prompt)
            except Exception as e2:
                print(f"  -> [Erreur LLM Local] {e2}")
    else:
        method = "Ollama Locale" if LLM_BACKEND != "gemini" else "Ollama (Fallback Quota)"
        print(f"  -> [LLM] Extraction des métadonnées avec {method} ({MODEL_NAME})...")
        try:
            res, tokens = _ask_ollama_metadata(prompt)
        except Exception as e:
            print(f"  -> [Erreur LLM Local] {e}")
            
    elapsed = time.time() - start_t
    print(f"  -> [Stats] Temps d'exécution LLM: {elapsed:.2f}s | Tokens: {tokens}")
    
    author = res.get('auteur', 'Anonymous')
    if not author or any(u in author.lower() for u in ["unknown", "not specified", "n/a", "pas spécifié"]):
        author = "Anonymous"
        
    kw_list = res.get('mots_cles', [])
    kw = [align_single_tag(k, progress=f"[{i+1}/{len(kw_list)}]") for i, k in enumerate(kw_list)]
    return res.get('titre', ''), author, res.get('resume', ''), filter(None, kw), res.get('references', [])

def process_directory(directory, sync_tags=True):
    if sync_tags:
        batch_harmonize_calibre_tags()
    
    print(f"\n{'='*50}")
    print(f"[Dir] PHASE 2 : TRAITEMENT DES DOCUMENTS")
    print(f"{'='*50}")
    
    indexed_dir = os.path.join(directory, "indexed")
    skipped_dir = os.path.join(directory, "skipped")
    if not os.path.exists(indexed_dir): os.makedirs(indexed_dir)
    if not os.path.exists(skipped_dir): os.makedirs(skipped_dir)
    
    for f in os.listdir(directory):
        if not (f.lower().endswith('.pdf') or f.lower().endswith('.epub')): continue
        path = os.path.join(directory, f)
        
        print(f"\n{'='*50}")
        print(f"[Doc] DOCUMENT : {f}")
        print(f"{'='*50}")
        
        try:
            print("  -> Lecture du fichier et extraction du texte...")
            txt = extract_book_content(path)
            
            if not txt.strip():
                print(f"  -> [Avertissement] Aucun texte extrait (même après OCR le cas échéant). Déplacement vers 'skipped/'...")
                shutil.move(path, os.path.join(skipped_dir, f))
                continue

            # 1. Extraction des métadonnées via LLM
            title, author, summary, tags, references = get_metadata_from_llm(txt)
            
            if title and author:
                # Récupération de l'année (si disponible dans le texte original via un autre appel ou stockée)
                # Note: get_metadata_from_llm retourne actuellement title, author, summary, tags
                # On va extraire l'année de manière simple si possible ou utiliser 0000
                year = "0000"
                # On pourrait améliorer get_metadata_from_llm pour qu'il retourne un dict riche
                
                print(f"  -> [Succès] Métadonnées extraites :")
                print(f"     - Titre  : {title}")
                print(f"     - Auteur : {author}")
                
                # Convertir tags (filter object) en liste et conserver la hiérarchie pour Neo4j dans mapping
                tags_list = list(tags)
                print(f"     - Tags hiérarchiques : {', '.join(tags_list)}")
                
                calibre_tags = set()
                for t in tags_list:
                    if "." in t:
                        for part in t.split("."):
                            calibre_tags.add(part.strip())
                    else:
                        calibre_tags.add(t.strip())
                calibre_tags_list = list(calibre_tags)
                print(f"     - Tags indép. Calibre: {', '.join(calibre_tags_list)}")
                
                # 2. Vérification de doublons dans Calibre
                existing_id = is_book_in_calibre(title, author)
                
                if existing_id:
                    print(f"  -> [Doublon] Livre déjà présent dans Calibre (ID {existing_id}).")
                    calibre_ok = update_calibre_metadata(existing_id, author, calibre_tags_list, summary)
                else:
                    # Importation nouveau livre (les champs étendus comme 'summary' sont faits via update)
                    calibre_ok = add_to_calibre(path, title, author, calibre_tags_list)
                    if calibre_ok:
                        # Récupérer l'ID pour mettre à jour le résumé (car 'add' ne le supporte pas directement via CLI)
                        new_id = is_book_in_calibre(title, author)
                        if new_id:
                            update_calibre_metadata(new_id, None, None, summary)
                
                if calibre_ok:
                    # Récupérer le chemin réel dans Calibre (plus stable)
                    calibre_info = is_book_in_calibre(title, author)
                    actual_path = ""
                    if calibre_info:
                        # On pourrait faire un calibredb list --search id:... pour avoir le format
                        pass # Pour l'instant on se fie au registre ou au backfill futur
                    
                    # Mise à jour du registre local pour Neo4j
                    update_book_registry(title, author, year, tags_list, summary=summary, references=references)

                    # Renommage en PascalCase avec séparateurs underscore : Auteur_Titre_Année
                    # On utilise l'auteur principal (premier de la liste)
                    author_first = author.split(',')[0].split('&')[0].split(' and ')[0]
                    author_pc = to_pascal_case(author_first)
                    title_pc = to_pascal_case(title)
                    ext = os.path.splitext(f)[1].lower()
                    
                    if year and year != "0000":
                        new_filename = f"{author_pc}_{title_pc}_{year}{ext}"
                    else:
                        new_filename = f"{author_pc}_{title_pc}{ext}"
                    
                    print(f"  -> Déplacement du fichier vers le dossier 'indexed/' en tant que {new_filename}...")
                    try:
                        shutil.move(path, os.path.join(indexed_dir, new_filename))
                        
                        # Sauvegarde du texte extrait pour le Markdown
                        texts_dir = os.path.join("vault", "texts")
                        os.makedirs(texts_dir, exist_ok=True)
                        txt_filename = f"{author_pc}_{title_pc}.txt"
                        if len(txt_filename) > 150: txt_filename = txt_filename[:150] + ".txt"
                        
                        with open(os.path.join(texts_dir, txt_filename), "w", encoding="utf-8") as tf:
                            tf.write(txt)
                            
                        print(f"[OK] Opération terminée pour {f}.")
                    except Exception as e:
                        print(f"  -> [Avertissement] Erreur de déplacement ou de sauvegarde texte : {e}. Le fichier reste à la racine.")
                else:
                    print(f"[WARN] Échec de l'action Calibre. Déplacement vers 'skipped/' pour vérification.")
                    shutil.move(path, os.path.join(skipped_dir, f))
            else:
                print(f"[ERROR] Échec de l'extraction des métadonnées pour {f}. Déplacement vers 'skipped/'...")
                shutil.move(path, os.path.join(skipped_dir, f))
        except Exception as e:
            print(f"[CRASH] [CRASH ÉTENDU] Erreur critique sur {f}: {e}")
            print(f"  -> Tentative de sauvegarde du processus en déplaçant le fichier vers 'skipped/'...")
            try:
                shutil.move(path, os.path.join(skipped_dir, f))
            except: pass

def get_ollama_models():
    """Récupère la liste des modèles Ollama installés."""
    try:
        models_info = ollama.list()
        # models_info['models'] est une liste d'objets ou dicts selon la version
        return [m.get('name', str(m)) if isinstance(m, dict) else getattr(m, 'model', str(m)) for m in models_info.get('models', [])]
    except:
        return ["qwen2.5:7b-instruct-q4_K_M"] # Fallback par défaut

if __name__ == "__main__":
    import argparse
    from datetime import datetime
    from tkinter import ttk, messagebox
    
    parser = argparse.ArgumentParser(description="Indexeur de PDF avec synchronisation Calibre et Neo4j.")
    parser.add_argument("directory", nargs="?", help="Dossier contenant les PDF à indexer")
    parser.add_argument("--skip-sync", action="store_true", help="Sauter la phase de synchronisation des tags")
    parser.add_argument("--local", action="store_true", help="Forcer l'utilisation d'Ollama (Local)")
    parser.add_argument("--model", help="Modèle Ollama à utiliser (mode local)")
    args = parser.parse_args()

    # Initialisation du logging
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sys.stdout = LoggerTee(os.path.join(log_dir, f"{timestamp}.log"))

    if args.directory:
        # Mode CLI
        if args.local:
            LLM_BACKEND = "ollama"
            if args.model:
                MODEL_NAME = args.model
            print(f"  -> [Mode] Mode LOCAL activé (Modèle: {MODEL_NAME}).")
        try:
            setup_llm()
            process_directory(args.directory, sync_tags=not args.skip_sync)
        except Exception as e:
            print(f"\n[ERREUR CRITIQUE] Initialisation du backend échouée : {e}")
            sys.exit(1)
        print(f"\n{'='*50}\n[Stats] PHASE 3 : SYNCHRONISATION NEO4J\n{'='*50}")
        try:
            export_to_neo4j.main()
        except Exception as e:
            print(f"  -> [Erreur] Échec Neo4j : {e}")
            
        print(f"\n{'='*50}\n[Stats] PHASE 4 : EXPORT MARKDOWN\n{'='*50}")
        try:
            import export_to_markdown
            export_to_markdown.main()
        except Exception as e:
            print(f"  -> [Erreur] Échec Export Markdown : {e}")
    else:
        root = tk.Tk()
        root.title("Antigravity - Indexation & Taxonomie")
        root.geometry("520x520")
        
        # Variables de l'interface
        dir_var = tk.StringVar()
        backend_var = tk.StringVar(value=LLM_BACKEND)
        ocr_var = tk.StringVar(value=OCR_BACKEND)
        
        # Cache pour éviter de requêter l'API à chaque clic
        gemini_models_cache = []
        ollama_models_cache = get_ollama_models()
        
        model_var = tk.StringVar()
        
        def update_models_list(*args):
            backend = backend_var.get()
            if backend == "gemini":
                if not gemini_models_cache:
                    print("  -> Chargement des modèles Gemini...")
                    try:
                        # Utilisation d'un client temporaire pour lister
                        if GOOGLE_API_KEY:
                            temp_client = genai.Client(api_key=GOOGLE_API_KEY)
                            gemini_models_cache.extend(get_gemini_models(temp_client))
                        else:
                            gemini_models_cache.extend(["gemini-2.0-flash", "gemini-1.5-flash"])
                    except:
                        gemini_models_cache.extend(["gemini-2.0-flash", "gemini-1.5-flash"])
                
                model_combo['values'] = gemini_models_cache
                if gemini_models_cache:
                    # Tente de restaurer le modèle du .env si compatible
                    env_model = os.getenv("MODEL_NAME", "").replace("models/", "")
                    if env_model in gemini_models_cache:
                        model_var.set(env_model)
                    else:
                        model_var.set(gemini_models_cache[0])
            else:
                model_combo['values'] = ollama_models_cache
                if ollama_models_cache:
                    env_model = os.getenv("MODEL_NAME", "").strip()
                    if env_model in ollama_models_cache:
                        model_var.set(env_model)
                    else:
                        model_var.set(ollama_models_cache[0])

        def browse_folder():
            folder = filedialog.askdirectory()
            if folder:
                dir_var.set(folder)
        
        def start_indexing():
            if not dir_var.get():
                messagebox.showerror("Erreur", "Veuillez sélectionner un dossier.")
                return
            
            global LLM_BACKEND, MODEL_NAME, OCR_BACKEND
            LLM_BACKEND = backend_var.get()
            OCR_BACKEND = ocr_var.get()
            MODEL_NAME = model_var.get()
            sync_tags = sync_var.get()
            
            try:
                # Validation physique de la connexion avant de fermer l'UI
                setup_llm()
                
                # Succès -> On ferme l'UI et on lance le pool
                root.destroy()
                
                print(f"  -> [Démarrage] Backend: {LLM_BACKEND.upper()} | Modèle: {MODEL_NAME} | OCR: {OCR_BACKEND.upper()}")
                process_directory(dir_var.get(), sync_tags=sync_tags)
                
                print(f"\n{'='*50}\n[Stats] PHASE 3 : SYNCHRONISATION NEO4J\n{'='*50}")
                try:
                    export_to_neo4j.main()
                except Exception as e:
                    print(f"  -> [Erreur] Échec Neo4j : {e}")

                print(f"\n{'='*50}\n[Stats] PHASE 4 : EXPORT MARKDOWN\n{'='*50}")
                try:
                    import export_to_markdown
                    export_to_markdown.main()
                except Exception as e:
                    print(f"  -> [Erreur] Échec Export Markdown : {e}")
            except Exception as e:
                print(f"  -> [Erreur Initialisation] {e}")
                messagebox.showerror("Erreur Initialisation", f"Le backend {LLM_BACKEND} n'a pas pu être initialisé :\n{e}")

        # Layout
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Antigravity Indexer", font=("Segoe UI", 16, "bold")).pack(pady=(0, 20))
        
        # Sélection dossier
        dir_frame = ttk.Frame(main_frame)
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Label(dir_frame, text="Dossier source :").pack(side=tk.LEFT)
        dir_entry = ttk.Entry(dir_frame, textvariable=dir_var, width=40)
        dir_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(dir_frame, text="...", command=browse_folder, width=3).pack(side=tk.LEFT)
        
        # Choix Backend
        backend_frame = ttk.LabelFrame(main_frame, text=" Backend LLM ", padding="10")
        backend_frame.pack(fill=tk.X, pady=10)
        ttk.Radiobutton(backend_frame, text="Cloud (Gemini)", variable=backend_var, value="gemini").pack(side=tk.LEFT, padx=20)
        ttk.Radiobutton(backend_frame, text="Local (Ollama)", variable=backend_var, value="ollama").pack(side=tk.LEFT, padx=20)
        
        # Choix OCR
        ocr_frame = ttk.LabelFrame(main_frame, text=" Moteur OCR ", padding="10")
        ocr_frame.pack(fill=tk.X, pady=10)
        ttk.Radiobutton(ocr_frame, text="Local (PaddleOCR)", variable=ocr_var, value="local").pack(side=tk.LEFT, padx=20)
        ttk.Radiobutton(ocr_frame, text="Cloud (Google Vision)", variable=ocr_var, value="cloud").pack(side=tk.LEFT, padx=20)
        
        # Sélection Modèle
        model_frame = ttk.LabelFrame(main_frame, text=" Configuration du Modèle ", padding="10")
        model_frame.pack(fill=tk.X, pady=10)
        ttk.Label(model_frame, text="Modèle :").pack(side=tk.LEFT, padx=(0, 10))
        model_combo = ttk.Combobox(model_frame, textvariable=model_var, width=40, state="readonly")
        model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Options
        opt_frame = ttk.Frame(main_frame)
        opt_frame.pack(fill=tk.X, pady=10)
        sync_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Synchroniser la taxonomie Calibre (Reindex)", variable=sync_var).pack(anchor=tk.W)
        
        # Initialisation du lien entre backend et modèles
        backend_var.trace_add("write", update_models_list)
        update_models_list() # Premier appel pour peupler
        
        # Bouton Start
        ttk.Button(main_frame, text="LANCER L'INDEXATION", command=start_indexing).pack(pady=20)
        
        root.mainloop()
