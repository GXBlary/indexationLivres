import os
import json
from neo4j import GraphDatabase

# =========================================================================
# CONFIGURATION
# =========================================================================
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password" # À adapter lors de votre installation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_JSONL_FILE = os.path.join(SCRIPT_DIR, "knowledge_graph.jsonl")

class KnowledgeGraphLoader:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def clear_database(self):
        """Supprime TOUS les nœuds et relations pour un Reset propre."""
        with self.driver.session() as session:
            print("-> [NEO4J] Purge complète de la base de données...")
            session.run("MATCH (n) DETACH DELETE n")

    def create_constraints(self):
        with self.driver.session() as session:
            print("-> [NEO4J] Vérification des index et contraintes...")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.filename IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")

    def load_document_block(self, data):
        """Ingère un bloc JSONL avec traçabilité complète."""
        doc = data.get("document", {})
        meta = data.get("metadata", {})
        entities = data.get("entities", [])
        triplets = data.get("triplets", [])

        with self.driver.session() as session:
            # 1. Document & Auteur
            session.run("""
                MERGE (d:Document {filename: $filename})
                SET d.title = $title, d.summary = $summary
                MERGE (a:Author {name: $author})
                MERGE (a)-[:AUTHORED]->(d)
            """, filename=doc.get("filename"), title=doc.get("title"), 
                 summary=doc.get("summary"), author=doc.get("author", "Unknown"))

            # 2. Concepts & Mentions
            for ent in entities:
                session.run("""
                    MERGE (c:Concept {name: $name})
                    SET c.wikidata_uri = $uri
                    WITH c
                    MATCH (d:Document {filename: $filename})
                    MERGE (d)-[m:MENTIONS]->(c)
                    SET m.extraction_date = $date, m.model = $model
                """, name=ent.get("name"), uri=ent.get("uri"), filename=doc.get("filename"),
                     date=meta.get("extraction_date"), model=meta.get("extraction_model"))

            # 3. Triplets (Sémantique)
            for t in triplets:
                pred_clean = str(t.get("predicate", "RELATED_TO")).upper().replace(" ", "_")
                query = f"""
                    MERGE (s:Concept {{name: $s_name}})
                    SET s.wikidata_uri = $s_uri
                    MERGE (o:Concept {{name: $o_name}})
                    SET o.wikidata_uri = $o_uri
                    MERGE (s)-[r:{pred_clean}]->(o)
                    SET r.extracted_from = $filename, r.extraction_date = $date, r.model = $model
                """
                session.run(query, s_name=t.get("subject"), s_uri=t.get("subject_uri"),
                            o_name=t.get("object"), o_uri=t.get("object_uri"),
                            filename=doc.get("filename"), date=meta.get("extraction_date"), 
                            model=meta.get("extraction_model"))

def run_ingestion():
    if not os.path.exists(GRAPH_JSONL_FILE):
        print(f"[ERREUR] {GRAPH_JSONL_FILE} manquant.")
        return
    loader = KnowledgeGraphLoader(URI, USER, PASSWORD)
    loader.create_constraints()
    with open(GRAPH_JSONL_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip(): loader.load_document_block(json.loads(line))
    loader.close()
    print("-> [SUCCESS] Ingestion Neo4j terminée.")

if __name__ == "__main__":
    run_ingestion()