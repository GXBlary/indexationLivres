import os
import sys
import subprocess
import time
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Définition des cibles à purger
CACHE_FILE = os.path.join(SCRIPT_DIR, "concepts_cache.json")
THESAURUS_FILE = os.path.join(SCRIPT_DIR, "thesaurus.json")
GRAPH_FILE = os.path.join(SCRIPT_DIR, "knowledge_graph.json")
OBSIDIAN_VAULT = os.path.join(SCRIPT_DIR, "Obsidian_Vault")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def purge_environment():
    """Détruit le cache, l'ontologie et les anciens fichiers Markdown pour un Reset propre."""
    print("\n>>> [PURGE] Nettoyage de l'environnement en cours...")
    
    # Suppression des fichiers JSON
    for file_path in [CACHE_FILE, THESAURUS_FILE, GRAPH_FILE]:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"    - Supprimé : {os.path.basename(file_path)}")
            except Exception as e:
                print(f"    - [ERREUR] Impossible de supprimer {os.path.basename(file_path)} : {e}")

    # Purge totale du dossier Obsidian
    if os.path.exists(OBSIDIAN_VAULT):
        try:
            shutil.rmtree(OBSIDIAN_VAULT)
            print(f"    - Supprimé : Dossier {os.path.basename(OBSIDIAN_VAULT)} et son contenu")
        except Exception as e:
            print(f"    - [ERREUR] Impossible de purger {os.path.basename(OBSIDIAN_VAULT)} : {e}")
            
    print(">>> [PURGE] Environnement stérile. Prêt pour la réinitialisation.\n")

def run_script(script_name):
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"\n[ERREUR] Le script '{script_name}' est introuvable.")
        return False
    
    print(f"\n>>> Lancement de {script_name}...")
    try:
        subprocess.run([sys.executable, script_path], check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"\n[ERREUR] Le script '{script_name}' a échoué.")
        return False
    except KeyboardInterrupt:
        print("\n[INFO] Interruption par l'utilisateur.")
        return False

def main_menu():
    while True:
        clear_screen()
        print("=================================================================")
        print("       INDUSTRIAL KNOWLEDGE GRAPH PIPELINE (V6 ORCHESTRATOR)     ")
        print("=================================================================")
        print(" --- WORKFLOWS AUTOMATIQUES ---")
        print(" [A] INITIALISATION (COLD START)")
        print("     Séquence : Renommage -> Création Taxonomie -> Extraction -> Nettoyage")
        print(" [B] MISE À JOUR (INCREMENTAL)")
        print("     Séquence : Renommage -> Extraction -> Nettoyage")
        print(" [C] RESET (REPROCESSING)")
        print("     Séquence : Purge Totale -> Taxonomie -> Extraction -> Nettoyage (Bypass Renommage)")
        print("\n --- EXÉCUTION MANUELLE ---")
        print(" [1] Étape 0 : Renommer les fichiers PDF (renamer.py)")
        print(" [2] Étape 1 : Construire la Taxonomie T-Box (build_taxonomy.py)")
        print(" [3] Étape 2 : Extraire le Graphe & Enrichir (fix_metadata_v6.py)")
        print(" [4] Étape 3 : Nettoyage Avancé du Thésaurus (thesaurus_manager.py)")
        print(" ---------------------------------------------------------------")
        print(" [Q] Quitter")
        print("=================================================================")
        
        choice = input("\nVotre choix : ").strip().upper()
        
        if choice == 'A':
            print("\n>>> DÉMARRAGE : INITIALISATION COMPLÈTE (COLD START)")
            if run_script("renamer.py") and run_script("build_taxonomy.py"):
                if run_script("fix_metadata_v6.py"):
                    run_script("thesaurus_manager.py")
            input("\nInitialisation terminée. Appuyez sur Entrée...")
            
        elif choice == 'B':
            print("\n>>> DÉMARRAGE : MISE À JOUR AU FIL DE L'EAU (INCREMENTAL)")
            if run_script("renamer.py") and run_script("fix_metadata_v6.py"):
                run_script("thesaurus_manager.py")
            input("\nMise à jour terminée. Appuyez sur Entrée...")
            
        elif choice == 'C':
            print("\n>>> DÉMARRAGE : RESET ET REPROCESSING (PURGE)")
            confirmation = input("ATTENTION : Cela va supprimer tout le graphe actuel et le cache. Continuer ? (O/N) : ").strip().upper()
            if confirmation == 'O':
                purge_environment()
                if run_script("build_taxonomy.py") and run_script("fix_metadata_v6.py"):
                    run_script("thesaurus_manager.py")
                input("\nReset terminé. Appuyez sur Entrée...")
            else:
                print("Reset annulé.")
                time.sleep(1)
            
        elif choice == '1':
            run_script("renamer.py")
            input("\nAppuyez sur Entrée...")
            
        elif choice == '2':
            run_script("build_taxonomy.py")
            input("\nAppuyez sur Entrée...")
            
        elif choice == '3':
            run_script("fix_metadata_v6.py")
            input("\nAppuyez sur Entrée...")
            
        elif choice == '4':
            run_script("thesaurus_manager.py")
            input("\nAppuyez sur Entrée...")
            
        elif choice == 'Q':
            print("\nFermeture du pipeline. Au revoir !")
            break
        else:
            print("\nChoix invalide.")
            time.sleep(1)

if __name__ == "__main__":
    main_menu()