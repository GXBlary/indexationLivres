import sys
import json
import os
import google.genai as genai
from google.genai import types
import pydantic
from dotenv import load_dotenv

load_dotenv()

class MetadataResponse(pydantic.BaseModel):
    titre: str
    auteur: str
    resume: str
    mots_cles: list[str]

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

prompt = "Extract Title, Author, Summary, Keywords from this text: The Self-Evolving Memory System. By Turing. it talks about stuff. Keywords: AI."

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MetadataResponse,
            temperature=0.2
        ),
    )
    print(response.text)
except Exception as e:
    print(f"ERROR: {e}")
