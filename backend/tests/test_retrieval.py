import math
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Message, SemanticIndex
from app.main import create_app
from app.retrieval import LocalEmbeddings, make_chunks


class FakeEmbeddings:
    """Deterministic vectors test plumbing, not the real model's language ability."""

    model = "test/topics-v1"

    def __init__(self):
        self.fail = False
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        if self.fail:
            raise RuntimeError("Simulated embedding failure")
        return [[1.0, 0.0, 0.0] if any(word in text.lower() for word in ("pasta", "meal", "restaurant"))
                else [0.0, 1.0, 0.0] if "python" in text.lower()
                else [0.0, 0.0, 1.0] for text in texts]


@pytest.fixture
def semantic_client(tmp_path):
    embedder = FakeEmbeddings()
    with TestClient(create_app(tmp_path / "echo.db", embedder=embedder)) as client:
        yield client, embedder


def profile(client):
    return client.post("/profiles", json={"name": "Semantic sample"}).json()["id"]


def ingest(client, pid, text, day=14):
    result = client.post(f"/profiles/{pid}/imports", json={
        "title": "Fictional sample", "date_order": "day-first",
        "transcript": f"{day}/10/2026, 09:00 - Ali: {text}",
    })
    assert result.status_code == 201, result.text
    return result.json()["id"]


def build(client, pid):
    return client.post(f"/profiles/{pid}/memories/index")


def search(client, pid, query="meal", **params):
    return client.get(f"/profiles/{pid}/memories/search", params={"q": query, **params})


def test_build_rank_sources_threshold_and_profile_isolation(semantic_client):
    client, _ = semantic_client
    pid, other = profile(client), profile(client)
    meal = ingest(client, pid, "Let's get pasta at the restaurant.")
    ingest(client, pid, "Let's study Python.", day=15)
    ingest(client, other, "Private restaurant discussion.")
    assert build(client, pid).json()["chunks"] == 2
    assert build(client, other).status_code == 200
    result = search(client, pid, limit=1).json()
    hit = result["items"][0]
    assert hit["conversation_id"] == meal
    assert hit["score"] == pytest.approx(1)
    source = hit["messages"][0]
    assert source["text"] == "Let's get pasta at the restaurant."
    assert hit["spans"][0]["message_id"] == source["id"]
    assert source["source_line_start"] == 1
    assert all("Private" not in hit["text"] for hit in result["items"])
    assert len(search(client, pid, min_score=0.8).json()["items"]) == 1


def test_new_import_requires_reindex_and_uses_no_stale_results(semantic_client):
    client, _ = semantic_client
    pid = profile(client)
    assert search(client, pid).status_code == 409
    ingest(client, pid, "Python lesson")
    assert build(client, pid).status_code == 200
    ingest(client, pid, "Pasta dinner", day=15)
    assert search(client, pid).status_code == 409
    assert build(client, pid).status_code == 200
    assert search(client, pid).json()["items"][0]["messages"][0]["text"] == "Pasta dinner"


def test_failed_rebuild_keeps_previous_snapshot(semantic_client):
    client, embedder = semantic_client
    pid = profile(client)
    ingest(client, pid, "Pasta dinner")
    assert build(client, pid).status_code == 200
    with client.app.state.database.sessions() as session:
        original = session.get(SemanticIndex, pid).collection_name
    embedder.fail = True
    assert build(client, pid).status_code == 503
    with client.app.state.database.sessions() as session:
        assert session.get(SemanticIndex, pid).collection_name == original
    embedder.fail = False
    assert search(client, pid).status_code == 200


def test_empty_and_system_only_profiles_need_no_embeddings(semantic_client):
    client, embedder = semantic_client
    pid = profile(client)
    assert build(client, pid).json()["chunks"] == 0
    assert search(client, pid).json()["items"] == []
    client.post(f"/profiles/{pid}/imports", json={
        "title": "Notice", "date_order": "day-first",
        "transcript": "14/10/2026, 09:00 - Messages and calls are encrypted.",
    })
    assert build(client, pid).json()["chunks"] == 0
    assert embedder.calls == []


def test_index_survives_restart_and_model_changes_require_rebuild(tmp_path):
    path = tmp_path / "echo.db"
    with TestClient(create_app(path, embedder=FakeEmbeddings())) as first:
        pid = profile(first)
        ingest(first, pid, "Pasta dinner")
        assert build(first, pid).status_code == 200
    with TestClient(create_app(path, embedder=FakeEmbeddings())) as restarted:
        assert search(restarted, pid).status_code == 200
        restarted.app.state.retrieval.embedder.model = "test/new-model"
        assert search(restarted, pid).status_code == 409


def test_chunk_bounds_offsets_system_media_and_conversations(semantic_client):
    client, _ = semantic_client
    pid = profile(client)
    long_text = "سلام🙂 Python " * 60
    first = ingest(client, pid, long_text)
    second = ingest(client, pid, "Pasta dinner", day=15)
    ingest(client, pid, "<Media omitted>", day=16)
    with client.app.state.database.sessions() as session:
        messages = list(session.scalars(select(Message).order_by(Message.conversation_id, Message.sequence_number)))
        chunks = make_chunks(messages)
    assert all(len(chunk.text) <= 220 for chunk in chunks)
    long_chunks = [chunk for chunk in chunks if chunk.conversation_id == first]
    assert "".join(long_text[span["start_char"]:span["end_char"]]
                   for chunk in long_chunks for span in chunk.spans) == long_text
    assert len([chunk for chunk in chunks if chunk.conversation_id == second]) == 1
    assert all("Media omitted" not in chunk.text for chunk in chunks)


def test_partial_batch_failure_does_not_publish_an_index(semantic_client):
    client, embedder = semantic_client
    pid = profile(client)
    ingest(client, pid, "Pasta " * 2000)
    original = embedder.embed
    calls = 0

    def fail_second_batch(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Second batch failed")
        return original(texts)

    embedder.embed = fail_second_batch
    assert build(client, pid).status_code == 503
    assert calls == 2
    assert search(client, pid).status_code == 409
    assert client.app.state.retrieval.client.list_collections() == []


@pytest.mark.parametrize("params", [{"q": " "}, {"q": "a" * 221}, {"limit": 0}, {"limit": 21}, {"min_score": -1}, {"min_score": 1.1}])
def test_search_validation(semantic_client, params):
    client, _ = semantic_client
    assert search(client, profile(client), **params).status_code == 422


def test_missing_profile_and_invalid_vectors(semantic_client):
    client, embedder = semantic_client
    assert build(client, "missing").status_code == 404
    assert search(client, "missing").status_code == 404
    pid = profile(client)
    ingest(client, pid, "Pasta dinner")
    embedder.embed = lambda texts: [[math.nan, 0.0, 1.0] for _ in texts]
    assert build(client, pid).status_code == 503


def test_local_provider_does_not_load_or_download_on_startup(tmp_path):
    provider = LocalEmbeddings(tmp_path / "model-cache")
    assert "function" not in provider.__dict__
    assert not (tmp_path / "model-cache").exists()


def test_neighbouring_turns_share_context_without_crossing_conversations(semantic_client):
    client, _ = semantic_client
    pid = profile(client)
    ingest(client, pid, "Shall we eat pasta?\n14/10/2026, 09:01 - Sara: Yes, tonight!")
    assert build(client, pid).json()["chunks"] == 1
    hit = search(client, pid).json()["items"][0]
    assert len(hit["messages"]) == 2
    assert "Ali: Shall we eat pasta?\nSara: Yes, tonight!" == hit["text"]
    assert search(client, pid, "unrelated weather", min_score=0.8).json()["items"] == []


def test_search_model_failure_returns_service_unavailable(semantic_client):
    client, embedder = semantic_client
    pid = profile(client)
    ingest(client, pid, "Pasta dinner")
    assert build(client, pid).status_code == 200
    embedder.fail = True
    assert search(client, pid).status_code == 503


def test_rebuild_preserves_chunk_and_message_references(semantic_client):
    client, _ = semantic_client
    pid = profile(client)
    ingest(client, pid, "Pasta dinner")
    build(client, pid)
    original = search(client, pid).json()["items"][0]
    build(client, pid)
    rebuilt = search(client, pid).json()["items"][0]
    assert original["chunk_id"] == rebuilt["chunk_id"]
    assert original["spans"] == rebuilt["spans"]


def test_import_during_build_does_not_publish_outdated_snapshot(semantic_client):
    client, embedder = semantic_client
    pid = profile(client)
    ingest(client, pid, "Pasta dinner")
    original = embedder.embed

    def import_during_embedding(texts):
        ingest(client, pid, "Python lesson", day=15)
        return original(texts)

    embedder.embed = import_during_embedding
    assert build(client, pid).status_code == 409
    assert search(client, pid).status_code == 409
