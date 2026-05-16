import os
import pydantic
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class HierarchyResponse(pydantic.BaseModel):
    hierarchy: str

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

tags_to_test = [
    ("adkar", "Industry.knowledge sharing.education.technology.data.Memory.Communication.human behavior.Adkar"),
    ("active inference", "work.representation.content.Memory.Active Inference"),
    ("lexicometrie", "Industry.knowledge sharing.education.technology.data.Philosophy.Memory.Science.methodology.linguistics.Lexicometrie")
]

ROOT_BRANCHES = ["Technology", "Science", "Management", "Business", "Law", "Society", "Arts", "History"]

for tag_key, current_val in tags_to_test:
    prompt = f"""
    You are a taxonomy expert. CLEAN and TRANSLATE to English.
    Rule: Start with one of {ROOT_BRANCHES}. Shallow (3-4 levels). No noise (Memory, Philosophy).
    Tag: "{tag_key}"
    Current: "{current_val}"
    Clean JSON:
    """
    
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=HierarchyResponse,
            temperature=0.1
        )
    )
    print(f"Tag: {tag_key}")
    print(f"Original: {current_val}")
    print(f"New: {response.text}")
    print("-" * 20)
