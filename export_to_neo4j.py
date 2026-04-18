import os
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "z?gCS%hg9pyB?:9c")

TAG_MAPPING_FILE = "tag_mapping.json"

def clean_database(session):
    print("-> Nettoyage de l'ancienne taxonomie dans Neo4j...")
    session.run("MATCH (n:Tag) DETACH DELETE n")

def create_hierarchy(session, hierarchy_str):
    segments = [s.strip() for s in hierarchy_str.split('.') if s.strip()]
    if not segments: return
    
    # Création du chemin en remontant de la feuille vers la racine
    for i in range(len(segments) - 1, 0, -1):
        child = segments[i].title()
        parent = segments[i-1].title()
        
        query = """
        MERGE (c:Tag {name: $child})
        MERGE (p:Tag {name: $parent})
        MERGE (c)-[:HAS_PARENT]->(p)
        """
        session.run(query, child=child, parent=parent)
        
    # S'il n'y a qu'un seul segment (racine), on s'assure qu'il existe
    if len(segments) == 1:
        query = "MERGE (n:Tag {name: $name})"
        session.run(query, name=segments[0].title())

def main():
    print(f"Connexion à Neo4j ({uri})...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database="tags") as session:
            clean_database(session)
            
            with open(TAG_MAPPING_FILE, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            total = len(mapping)
            print(f"-> Export de {total} chemins hiérarchiques vers Neo4j...")
            
            for k, val in mapping.items():
                if val:
                    create_hierarchy(session, val)
                    
            result = session.run("MATCH (n:Tag) RETURN count(n) as node_count")
            nodes = result.single()[0]
            
            result_rels = session.run("MATCH ()-[r:HAS_PARENT]->() RETURN count(r) as rel_count")
            rels = result_rels.single()[0]
            
            print(f"\n-> Export Neo4j terminé !")
            print(f"   Graph structuré : {nodes} Noeuds 'Tag' et {rels} Relations 'HAS_PARENT'")
            
        driver.close()
    except Exception as e:
        print(f"Erreur Neo4j: {e}")

if __name__ == "__main__":
    main()
