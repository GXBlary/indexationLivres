import os
import json
import time
import pydantic
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite-preview"

if not GEMINI_API_KEY:
    print("Error: GOOGLE_API_KEY not found in environment.")
    exit(1)

class HierarchyResponse(pydantic.BaseModel):
    hierarchy: str

client = genai.Client(api_key=GEMINI_API_KEY)

ROOT_BRANCHES = [
    "Technology", "Science", "Management", "Business", "Law", "Society", 
    "Arts", "History", "Environment", "Economy", "Philosophy", "Medicine",
    "Education", "Geography", "Leisure", "Language"
]

def is_problematic(key, val):
    noise = ["knowledge sharing", "Philosophy", "Memory", "Science", "Education", "Society", "Industry", "information", "work."]
    parts = val.split('.')
    # 1. Depth check (User rule: median + 2*stddev approx 5)
    if len(parts) > 5: return True
    # 2. Casing and Lemmatization check (Simplified)
    if any(p.endswith('s') and not p.endswith('ss') for p in parts): return True # Likely plural
    if any(p[0].islower() for p in parts if p): return True # Not PascalCase
    if "AI" in val or "Ai" in val: return True # Canonical name check
    # 3. Noise pollution
    if any(n in val for n in noise) and not any(n.lower() in key.lower() for n in noise):
        return True
    # 4. French/Accents
    if any(c in val for c in "éàèïôû"): return True
    return False

def get_prompt(tag_key, current_hierarchy):
    return f"""
    You are a professional library curator specializing in taxonomy and knowledge organization.
    Your task is to CLEAN, TRANSLATE to English, and RATIONALIZE a hierarchical tag branch.
    
    Rules:
    1. EXCLUSIVELY output English. Translate any French terms.
    2. THE HIERARCHY MUST BE LOGICAL, GRANULAR but SHALLOW (ideal: 3-4 segments, MAX: 5).
    3. REMOVE repetitive or abstract "ontological bloating" like "Memory", "Philosophy", "knowledge sharing", "Science" unless they are the PRIMARY topic.
    4. Start with one of these logical root branches: {', '.join(ROOT_BRANCHES)}.
    5. The branches must move from generic to specific.
    6. Use PascalCase for all segments (e.g., "Software Development").
    7. Use SINGULAR forms for all segments where appropriate (e.g., "Algorithms" -> "Algorithm").
    8. Use "Artificial Intelligence" (full name) as the canonical name, never "AI".
    9. The last segment MUST be the singularized, PascalCase version of the tag itself: "{tag_key}".
    10. Use dot notation (e.g., "Technology.Artificial Intelligence.Machine Learning").
    11. Return a JSON object with a single key "hierarchy".
    
    Current Tag (Key): "{tag_key}"
    Current Dirty/Polluted Hierarchy: "{current_hierarchy}"
    
    Cleaned English Hierarchy:
    """

def main():
    try:
        with open("tag_mapping.json", "r", encoding="utf-8") as f:
            mapping = json.load(f)
    except FileNotFoundError:
        print("tag_mapping.json not found.")
        return

    keys = sorted(mapping.keys())
    problematic_keys = [k for k in keys if is_problematic(k, mapping[k])]
    
    if not problematic_keys:
        print("No problematic tags found. Everything is clean!")
        return

    print(f"Found {len(problematic_keys)} problematic tags. Creating Gemini Batch Job...")

    # Prepare requests
    inline_requests = []
    for key in problematic_keys:
        inline_requests.append({
            'contents': [{
                'parts': [{'text': get_prompt(key, mapping[key])}],
                'role': 'user'
            }],
            'config': {
                'response_mime_type': 'application/json',
                'response_schema': HierarchyResponse,
                'temperature': 0.1
            }
        })

    # Create Batch Job
    try:
        batch_job = client.batches.create(
            model=MODEL_NAME,
            src=inline_requests,
            config={'display_name': f"SanitizeTags_{int(time.time())}"}
        )
        job_name = batch_job.name
        print(f"Batch job created: {job_name}")
    except Exception as e:
        print(f"Error creating batch job: {e}")
        return

    # Poll for completion
    print("Polling status for job...")
    while True:
        status = client.batches.get(name=job_name)
        state = status.state.name
        if state in ('JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED', 'JOB_STATE_EXPIRED'):
            break
        print(f"Job state: {state}. Waiting 20s...")
        time.sleep(20)

    if state != 'JOB_STATE_SUCCEEDED':
        print(f"Job failed or cancelled with state: {state}")
        return

    print("Job succeeded! Applying results...")
    
    # Apply results
    new_mapping = mapping.copy()
    success_count = 0
    # Map responses back to keys using order (Batch API preserves order for inline requests)
    for i, inline_response in enumerate(status.dest.inlined_responses):
        if inline_response.response and inline_response.response.text:
            try:
                data = json.loads(inline_response.response.text)
                sanitized = data.get("hierarchy")
                if sanitized:
                    new_mapping[problematic_keys[i]] = sanitized
                    success_count += 1
            except Exception as e:
                print(f"Error parsing response {i}: {e}")

    # Final save
    with open("tag_mapping.json", "w", encoding="utf-8") as f:
        json.dump(new_mapping, f, indent=4, ensure_ascii=False)

    print(f"\nPhase complete! {success_count} tags updated via Batch API.")

if __name__ == "__main__":
    main()
