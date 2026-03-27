import json
import os
from pydantic import BaseModel, Field, field_validator
from typing import List
from openai import OpenAI
import instructor
from tqdm import tqdm

# =========================================================================
# CONFIGURATION
# =========================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_FILE = os.path.join(SCRIPT_DIR, "resumes.json")
OUTPUT_TRIPLETS_FILE = os.path.join(SCRIPT_DIR, "extracted_triplets.json")

# Connexion à Ollama local via l'interface compatible OpenAI
client = instructor.from_openai(
    OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama", # Clé requise par l'API OpenAI, mais ignorée par Ollama
    ),
    mode=instructor.Mode.JSON,
)

MODEL_NAME = "qwen2.5:7b-instruct-q4_K_M"

# =========================================================================
# SCHÉMAS PYDANTIC (Règles Métier)
# =========================================================================

class Triplet(BaseModel):
    subject: str = Field(
        description="L'entité source (le concept actif). Idéalement un terme technique court."
    )
    predicate: str = Field(
        description="""L'action ou la relation. DOIT ÊTRE UN VERBE CANONIQUE EN MAJUSCULES À LA VOIX ACTIVE. 
        Exemples valides : IMPROVES, REDUCES, DEPENDS_ON, USES, CREATES, MANAGES, INTEGRATES."""
    )
    object: str = Field(
        description="L'entité cible (le concept passif impacté par le sujet)."
    )

    # Validateur : Force automatiquement la normalisation si le LLM l'oublie
    @field_validator('predicate')
    @classmethod
    def normalize_predicate(cls, v):
        cleaned = v.upper().strip().replace(" ", "_")
        # Filtre anti-bruit (Soft-fail)
        banned_words = ["CONCERNS", "DETAILS", "TALKS_ABOUT", "IS"]
        if cleaned in banned_words:
            raise ValueError(f"Le prédicat {cleaned} est trop vague. Utilisez un verbe d'action spécifique.")
        return cleaned

    @field_validator('subject', 'object')
    @classmethod
    def clean_entities(cls, v):
        return v.title().strip()

class KnowledgeExtraction(BaseModel):
    triplets: List[Triplet] = Field(
        description="Liste des triplets de connaissances extraits du texte."
    )

# =========================================================================
# MOTEUR D'EXTRACTION
# =========================================================================

def extract_knowledge_from_text(text: str) -> KnowledgeExtraction:
    prompt = f"""
    Rôle : Tu es un extracteur de graphe de connaissances expert (Open IE). 
    Ton but est d'extraire des relations techniques claires à partir du texte fourni.

    Règles d'extraction obligatoires :
    1. Extraction Contextuelle : Isole les relations de cause à effet, d'utilisation ou d'architecture.
    2. Voix Active Stricte (Directionnalité) : Si le texte dit "A est amélioré par B", tu DOIS inverser le triplet pour qu'il devienne : Sujet: B -> Prédicat: IMPROVES -> Objet: A. Le Sujet doit toujours être l'acteur de l'action.
    3. Normalisation des Prédicats : N'utilise PAS les verbes exacts du texte. Résume l'action en utilisant une macro-relation canonique, toujours en MAJUSCULES (ex: REDUCES, ACCELERATES, IMPLEMENTS, MITIGATES).

    Texte source :
    {text}
    """

    # Instructor gère le Pydantic et les retries automatiques (max_retries=3)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        response_model=KnowledgeExtraction,
        max_retries=3, 
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return response

# =========================================================================
# PIPELINE
# =========================================================================

def run_extraction():
    print("-> Loading resumes...")
    with open(RESUMES_FILE, 'r', encoding='utf-8') as f:
        resumes = json.load(f)

    all_triplets = []
    
    # Mode test : On ne traite que les 5 premiers résumés pour valider le comportement
    test_resumes = list(resumes.values())[:5]
    
    print("-> Extracting triplets via Qwen 2.5 + Instructor...")
    for text in tqdm(test_resumes):
        try:
            extraction = extract_knowledge_from_text(text)
            for t in extraction.triplets:
                all_triplets.append({
                    "subject": t.subject,
                    "predicate": t.predicate,
                    "object": t.object
                })
        except Exception as e:
            print(f"Erreur d'extraction (limite de retries atteinte) : {e}")

    with open(OUTPUT_TRIPLETS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_triplets, f, indent=4, ensure_ascii=False)
        
    print(f"-> [SUCCESS] Extracted {len(all_triplets)} triplets. Saved to {OUTPUT_TRIPLETS_FILE}")

if __name__ == "__main__":
    run_extraction()