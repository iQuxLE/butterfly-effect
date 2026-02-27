"""
Push butterfly-effect graph data to Neo4j Aura.

Uses the Neo4j Bolt driver to push sample causal-chain graph data.
"""

import json
import os
import sys

import certifi
from neo4j import GraphDatabase

os.environ["SSL_CERT_FILE"] = certifi.where()

# --- Configuration ---
NEO4J_URI = "neo4j+s://cc16b147.databases.neo4j.io"
USERNAME = "neo4j"
PASSWORD = "Nk0yDtxAlIqC8SGdJX9tUCJ9aYSTfDDBFp90q7CtSDM"
DATABASE = "neo4j"

# Sample butterfly-effect graph data
SAMPLE_DATA = {
    "headline": "TESTER2 Court strikes down Trump tariffs",
    "branches": [
        {
            "economist": "US importers scramble to renegotiate contracts as tariff uncertainty lifts",
            "geopolitical": "China signals willingness to restart bilateral trade talks",
            "social": "Consumer prices on electronics drop 8-12%, boosting retail sentiment",
            "futurist": "Free-trade consensus hardens into constitutional precedent, limiting future executive trade powers",
        },
        {
            "economist": "Stock market rallies 3% on renewed trade predictability",
            "geopolitical": "EU fast-tracks new trade agreement with the US",
            "social": "Rust Belt workers protest as cheap imports threaten manufacturing jobs again",
            "futurist": "Global supply chains permanently restructure around judicial risk in US trade policy",
        },
    ],
}


def upload_graph(driver):
    """Upload sample graph data to Neo4j."""
    with driver.session(database=DATABASE) as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("Cleared existing data.")

        # Create headline node
        session.run(
            "CREATE (h:Headline {text: $text})",
            text=SAMPLE_DATA["headline"],
        )
        print(f"Created headline: {SAMPLE_DATA['headline']}")

        # Create branch chains
        for i, branch in enumerate(SAMPLE_DATA["branches"]):
            session.run(
                """
                MATCH (h:Headline {text: $headline})
                CREATE (e:Prediction {text: $econ, agent: 'Economist', timeframe: 'days', branch: $branch, depth: 0})
                CREATE (g:Prediction {text: $geo, agent: 'Geopolitical Strategist', timeframe: 'weeks', branch: $branch, depth: 1})
                CREATE (s:Prediction {text: $social, agent: 'Social Analyst', timeframe: 'months', branch: $branch, depth: 2})
                CREATE (f:Prediction {text: $futurist, agent: 'Futurist', timeframe: '1-5 years', branch: $branch, depth: 3})
                CREATE (h)-[:CAUSES]->(e)
                CREATE (e)-[:CAUSES]->(g)
                CREATE (g)-[:CAUSES]->(s)
                CREATE (s)-[:CAUSES]->(f)
                """,
                headline=SAMPLE_DATA["headline"],
                econ=branch["economist"],
                geo=branch["geopolitical"],
                social=branch["social"],
                futurist=branch["futurist"],
                branch=i,
            )
            print(f"  Created branch {i}")

        # Verify
        print("\nVerifying...")
        result = session.run("MATCH (n) RETURN labels(n) AS labels, count(n) AS count")
        for record in result:
            print(f"  {record['labels']}: {record['count']}")

        result = session.run("MATCH ()-[r:CAUSES]->() RETURN count(r) AS count")
        print(f"  CAUSES relationships: {result.single()['count']}")


def main():
    global SAMPLE_DATA
    if len(sys.argv) > 1:
        SAMPLE_DATA = json.loads(sys.argv[1])
        print(f"[NEO4J] Received data: {SAMPLE_DATA['headline'][:60]}...", flush=True)

    print(f"Neo4j URI: {NEO4J_URI}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(USERNAME, PASSWORD))
    try:
        driver.verify_connectivity()
        print("Connected to Neo4j Aura.")
        upload_graph(driver)
        print("\nDone! Graph data uploaded successfully.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
