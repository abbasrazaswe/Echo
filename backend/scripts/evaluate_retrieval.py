"""Opt-in real-model smoke evaluation: python -m scripts.evaluate_retrieval.

Downloads the model on first use. Uses fictional data and a temporary database.
This small ranking check is not a representative retrieval benchmark.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import create_app
from app.retrieval import LocalEmbeddings


CASES = [
    ("Let's book a table at the Italian restaurant and order pasta tonight.",
     "Where are we going for our evening meal?"),
    ("The taxi is collecting us at six before our flight.",
     "How will we travel to the airport?"),
    ("Tomorrow we will study Python functions and practice programming together.",
     "What are our plans for learning to code?"),
]


def main():
    backend = Path(__file__).resolve().parents[1]
    embedder = LocalEmbeddings(backend / "data/profiles/models/all-MiniLM-L6-v2")
    with TemporaryDirectory(prefix="echo-evaluation-") as directory:
        with TestClient(create_app(Path(directory) / "echo.db", embedder=embedder)) as client:
            response = client.post("/profiles", json={"name": "Fictional retrieval evaluation"})
            response.raise_for_status()
            pid = response.json()["id"]
            conversations = []
            for i, (text, _) in enumerate(CASES):
                response = client.post(f"/profiles/{pid}/imports", json={
                    "title": f"Evaluation topic {i + 1}", "date_order": "day-first",
                    "transcript": f"{14 + i}/10/2026, 09:00 - Ali: {text}",
                })
                response.raise_for_status()
                conversations.append(response.json()["id"])
            response = client.post(f"/profiles/{pid}/memories/index")
            if response.status_code != 200:
                # Include the underlying cause for a developer running this diagnostic.
                response.raise_for_status()
            print("Index:", response.json())
            for (_, query), expected in zip(CASES, conversations, strict=True):
                response = client.get(f"/profiles/{pid}/memories/search", params={
                    "q": query, "limit": 1, "min_score": 0,
                })
                response.raise_for_status()
                hit = response.json()["items"][0]
                assert hit["conversation_id"] == expected, f"Wrong top result for: {query}"
                assert hit["messages"] and hit["spans"]
                print(f"PASS ({hit['score']:.3f}): {query} -> {hit['text']}")
            print("3/3 fictional paraphrase queries ranked the expected source first.")


if __name__ == "__main__":
    main()
