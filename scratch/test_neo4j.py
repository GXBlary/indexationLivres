import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "z?gCS%hg9pyB?:9c")

print(f"Connecting to {uri} as {user}")

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        result = session.run("MATCH (n:Tag) RETURN count(n) as count")
        for record in result:
            print(f"Number of Tag nodes in Neo4j: {record['count']}")
    driver.close()
    print("Connection successful.")
except Exception as e:
    print(f"Connection failed: {e}")
