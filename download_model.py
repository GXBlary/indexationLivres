import sys
import os
import socket

print("--- DEBUG INITIALIZATION ---")
print(f"Python Version: {sys.version}")
print(f"Current Directory: {os.getcwd()}")

# 1. Test de connectivité de base vers HuggingFace
def check_connectivity():
    print("-> Checking connectivity to huggingface.co...")
    try:
        socket.create_connection(("huggingface.co", 443), timeout=10)
        print("   - OK: hugginface.co is reachable.")
    except Exception as e:
        print(f"   - [ERROR] Cannot reach huggingface.co: {e}")
        print("     Vérifie ta connexion internet ou tes paramètres de Proxy.")
        return False
    return True

# 2. Importation différée pour isoler les erreurs de DLL/Dépendances
try:
    print("-> Loading sentence_transformers...")
    from sentence_transformers import SentenceTransformer
    print("   - OK: Library loaded.")
except ImportError as e:
    print(f"   - [ERROR] sentence-transformers non installé : {e}")
    sys.exit(1)
except Exception as e:
    print(f"   - [CRITICAL] Erreur lors de l'import : {e}")
    sys.exit(1)

def download():
    model_name = 'all-MiniLM-L6-v2'
    local_dir = os.path.join(os.path.dirname(__file__), "models", "all-MiniLM-L6-v2")
    
    if not check_connectivity():
        sys.exit(1)

    print(f"-> Starting download of {model_name}...")
    try:
        # Load (downloads to cache automatically)
        # On définit un timeout via les variables d'environnement si besoin
        os.environ["HTTP_TIMEOUT"] = "300" 
        
        model = SentenceTransformer(model_name)
        
        # Save to specific local directory
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)
            
        model.save(local_dir)
        print(f"\n-> [SUCCESS] Model saved locally at: {local_dir}")
        print(f"-> Usage : model = SentenceTransformer('{local_dir}')")
        
    except Exception as e:
        print(f"\n-> [ERROR] Download failed: {e}")
        print("   Astuce : Essaie de lancer le script avec 'python -u download_model.py' pour voir les logs en temps réel.")
        sys.exit(1)
    except BaseException as e:
        print(f"\n-> [HALTED] Interruption système : {type(e).__name__}")
        sys.exit(1)

if __name__ == "__main__":
    download()
