import os
import sys
import shutil
import json
import time

def print_result(check, status, message=""):
    color = "\033[92m" if status == "PASS" else "\033[91m"
    reset = "\033[0m"
    print(f"[{color}{status}{reset}] {check:35} {message}")

def run_checks():
    print(f"\n{'='*60}\nANTIGRAVITY SYSTEM VALIDATION SUITE\n{'='*60}")
    
    # --- GATE 0: Imports & Environment ---
    try:
        import indexer
        print_result("Indexer Module Load", "PASS")
    except Exception as e:
        print_result("Indexer Module Load", "FAIL", f"Error: {e}")
        return

    required_vars = ["GOOGLE_API_KEY", "LLM_BACKEND", "CALIBRE_LIBRARY_PATH"]
    from dotenv import load_dotenv
    load_dotenv()
    
    for var in required_vars:
        val = os.getenv(var)
        if val:
            print_result(f"Env Variable: {var}", "PASS", f"(Set: {val[:5]}...)")
        else:
            print_result(f"Env Variable: {var}", "FAIL", "Missing from .env")

    # --- GATE 1: Taxonomy Logic ---
    print(f"\n{'-'*60}\nGATE 1: Taxonomy Normalization Logic\n{'-'*60}")
    test_paths = [
        ("business.management", "Business.Management"),
        ("computing.software development.testing", "Technology.Software Engineering.Testing"),
        ("Economy.Macroeconomics.Fiscal Policy.USA.2024.Deepness", "Economy.Macroeconomics.Fiscal Policy.USA.2024"), # Truncate to 5
        ("AI.bias.analysis", "Technology.AI.Bias.Analysis"),
        ("Business.Strategy.Business.Business", "Business.Strategies"), # De-duplicate
    ]
    
    for inp, expected in test_paths:
        try:
            result = indexer.normalize_taxonomy_path(inp)
            status = "PASS" if result == expected else "FAIL"
            msg = f"Result: {result}" if status == "FAIL" else ""
            print_result(f"Taxonomy: {inp[:20]}...", status, msg)
        except Exception as e:
            print_result(f"Taxonomy: {inp[:20]}...", "FAIL", f"Error: {e}")

    # --- GATE 2: Model Discovery ---
    print(f"\n{'-'*60}\nGATE 2: Model Discovery Connectivity\n{'-'*60}")
    
    # Ollama Test
    try:
        models = indexer.get_ollama_models()
        status = "PASS" if len(models) > 0 else "WARN"
        print_result("Ollama Model Discovery", status, f"Found {len(models)} models.")
    except Exception as e:
        print_result("Ollama Model Discovery", "FAIL", f"Error: {e}")

    # Gemini Test (Dry Run initialize)
    try:
        import google.genai as genai
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        models = indexer.get_gemini_models(client)
        status = "PASS" if len(models) > 0 else "FAIL"
        print_result("Gemini Model Discovery", status, f"Found {len(models)} models.")
    except Exception as e:
        print_result("Gemini Model Discovery", "FAIL", f"Error: {e}")

    # --- GATE 3: Pipeline Components ---
    print(f"\n{'-'*60}\nGATE 3: Functional Components\n{'-'*60}")
    
    # Check Registry
    registry_file = "book_registry.json"
    if os.path.exists(registry_file):
        try:
            with open(registry_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print_result("Book Registry Integrity", "PASS", f"Contains {len(data)} books.")
        except Exception as e:
            print_result("Book Registry Integrity", "FAIL", f"Corrupted: {e}")
    else:
        print_result("Book Registry Integrity", "PASS", "File not yet created.")

    # Check Calibre DB Accessible
    calibre_bin = shutil.which("calibredb")
    if calibre_bin:
        print_result("Calibre Binary Search", "PASS", f"Found at {calibre_bin}")
    else:
        print_result("Calibre Binary Search", "FAIL", "calibredb NOT in system PATH.")

    print(f"\n{'='*60}\nVALIDATION COMPLETE\n{'='*60}")

if __name__ == "__main__":
    run_checks()
