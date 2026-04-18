import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "z?gCS%hg9pyB?:9c")

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session(database="tags") as session:
        result = session.run("CALL db.labels()")
        labels = [record[0] for record in result]
        print(f"Labels in DB 'tags': {labels}")
        
        result2 = session.run("CALL db.relationshipTypes()")
        rels = [record[0] for record in result2]
        print(f"Relationships in DB 'tags': {rels}")
        
        result3 = session.run("MATCH (n) RETURN COUNT(n) as node_count")
        for record in result3:
            print(f"Node count: {record['node_count']}")
            
    driver.close()
except Exception as e:
    print(f"Error: {e}")
