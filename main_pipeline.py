import os
import sys
import subprocess
import time
import shutil

# =========================================================================
# CONFIGURATION DES CHEMINS
# =========================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Fichiers de données et cache
CACHE_FILE = os.path.join(SCRIPT_DIR, "concepts_cache.json")
THESAURUS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
GRAPH_JSONL_FILE = os.path.join(SCRIPT_DIR, "knowledge_graph.jsonl")

# Dossiers sources et destination
INBOX_PATH = os.path.join(SCRIPT_DIR, "Inbox")
OBSIDIAN_VAULT = os.path.join(SCRIPT_DIR, "Obsidian_Vault")
SOURCES_PATH = os.path.join(OBSIDIAN_VAULT, "Sources")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# =========================================================================
# MODULES DE PURGE ET SÉCURITÉ
# =========================================================================

def purge_neo4j():
    """Connecte et vide la base Neo4j de manière sécurisée via le loader."""
    try:
        # Import dynamique pour éviter les erreurs si la lib neo4j n'est pas là
        from neo4j_loader import KnowledgeGraphLoader, URI, USER, PASSWORD
        loader = KnowledgeGraphLoader(URI, USER, PASSWORD)
        loader.clear_database()
        loader.close()
        print("    - [SUCCESS] Base Neo4j purgée.")
    except Exception as e:
        print(f"    - [WARNING] Purge Neo4j échouée (Vérifiez si Neo4j est démarré) : {e}")

def purge_environment():
    """
    Détruit le cache, l'ontologie et le Vault. 
    Rapatrie les PDF de 'Sources' vers 'Inbox' avant destruction.
    """
    print("\n>>> [PURGE] Nettoyage complet de l'environnement...")
    
    # 1. Purge de la base de données Neo4j
    purge_neo4j()

    # 2. Sauvetage des fichiers physiques (PDF)
    os.makedirs(INBOX_PATH, exist_ok=True)
    if os.path.exists(SOURCES_PATH):
        count_saved = 0
        for pdf in os.listdir(SOURCES_PATH):
            if pdf.lower().endswith('.pdf'):
                try:
                    shutil.move(os.path.join(SOURCES_PATH, pdf), os.path.join(INBOX_PATH, pdf))
                    count_saved += 1
                except Exception:
                    pass
        if count_saved > 0:
            print(f"    - [INFO] {count_saved} PDF rapatriés dans l'Inbox.")

    # 3. Suppression des fichiers JSON de travail
    for f in [CACHE_FILE, THESAURUS_FILE, GRAPH_JSONL_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"    - Supprimé : {os.path.basename(f)}")
            except Exception:
                pass
    
    # 4. Suppression du Vault Obsidian
    if os.path.exists(OBSIDIAN_VAULT):
        try:
            shutil.rmtree(OBSIDIAN_VAULT)
            print("    - Supprimé : Dossier Obsidian_Vault")
        except Exception:
            pass
    
    print(">>> [PURGE] Terminée. L'environnement est prêt pour une réinitialisation.\n")

# =========================================================================
# EXÉCUTION DES SCRIPTS
# =========================================================================

def run_script(script_name):
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"\n[ERREUR] Le script '{script_name}' est introuvable.")
        return False
    
    print(f"\n>>> Lancement de {script_name}...")
    try:
        # Utilise l'interpréteur Python actuel pour garantir l'environnement
        subprocess.run([sys.executable, script_path], check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"\n[ERREUR] Le script '{script_name}' a échoué.")
        return False
    except KeyboardInterrupt:
        print("\n[INFO] Interruption par l'utilisateur.")
        return False

# =========================================================================
# INTERFACE MENU
# =========================================================================

def main_menu():
    while True:
        clear_screen()
        print("=================================================================")
        print("       INDUSTRIAL KNOWLEDGE GRAPH PIPELINE (V6 ORCHESTRATOR)      ")
        print("=================================================================")
        print(" --- WORKFLOWS AUTOMATIQUES ---")
        print(" [A] INITIALISATION (Cold Start)")
        print("     (Renamer -> Taxonomy -> Extract -> Ingest)")
        print(" [B] MISE À JOUR (Incremental)")
        print("     (Renamer -> Extract -> Ingest)")
        print(" [C] RESET TOTAL (Reprocessing)")
        print("     (Purge -> Taxonomy -> Extract -> Ingest)")
        
        print("\n --- EXÉCUTION MANUELLE ---")
        print(" [1] Étape 0 : Renommer les fichiers PDF (renamer.py)")
        print(" [2] Étape 1 : Construire la Taxonomie T-Box (build_taxonomy.py)")
        print(" [3] Étape 2 : Extraire le Graphe & Enrichir (fix_metadata.py)")
        print(" [4] Étape 3 : Nettoyage Avancé du Thésaurus (thesaurus_manager.py)")
        print(" [5] Étape 4 : Ingestion dans Neo4j (neo4j_loader.py)")
        print(" ---------------------------------------------------------------")
        print(" [Q] Quitter")
        print("=================================================================")
        
        choice = input("\nVotre choix : ").strip().upper()
        
        if choice == 'A':
            print("\n>>> DÉMARRAGE : INITIALISATION COMPLÈTE")
            if run_script("renamer.py") and run_script("build_taxonomy.py"):
                if run_script("fix_metadata.py") and run_script("thesaurus_manager.py"):
                    run_script("neo4j_loader.py")
            input("\nTerminé. Appuyez sur Entrée...")
            
        elif choice == 'B':
            print("\n>>> DÉMARRAGE : MISE À JOUR AU FIL DE L'EAU")
            if run_script("renamer.py") and run_script("fix_metadata.py"):
                if run_script("thesaurus_manager.py"):
                    run_script("neo4j_loader.py")
            input("\nTerminé. Appuyez sur Entrée...")
            
        elif choice == 'C':
            print("\n>>> DÉMARRAGE : RESET ET REPROCESSING")
            confirm = input("ATTENTION : Cela va purger Neo4j et Obsidian. Continuer ? (O/N) : ").strip().upper()
            if confirm == 'O':
                purge_environment()
                if run_script("build_taxonomy.py") and run_script("fix_metadata.py"):
                    if run_script("thesaurus_manager.py"):
                        run_script("neo4j_loader.py")
                input("\nReset terminé. Appuyez sur Entrée...")
            else:
                print("Opération annulée.")
                time.sleep(1)
            
        elif choice == '1':
            run_script("renamer.py")
            input("\nAppuyez sur Entrée...")
        elif choice == '2':
            run_script("build_taxonomy.py")
            input("\nAppuyez sur Entrée...")
        elif choice == '3':
            run_script("fix_metadata.py")
            input("\nAppuyez sur Entrée...")
        elif choice == '4':
            run_script("thesaurus_manager.py")
            input("\nAppuyez sur Entrée...")
        elif choice == '5':
            run_script("neo4j_loader.py")
            input("\nAppuyez sur Entrée...")
        elif choice == 'Q':
            print("\nFermeture du pipeline. Au revoir !")
            break
        else:
            print("\nChoix invalide.")
            time.sleep(1)

if __name__ == "__main__":
    main_menu()