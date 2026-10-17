import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.database import DerivedArtifact
from app.main import create_app


TRANSCRIPT = "\n".join([
    "14/10/2026, 09:00 - Messages and calls are encrypted.",
    "14/10/2026, 09:01 - Ali: Shall we study Python functions tomorrow?",
    "14/10/2026, 09:02 - Sara: Yes, Python practice will help us learn programming.",
    "14/10/2026, 09:03 - Ali: Our meeting is tomorrow at the library.",
    "14/10/2026, 09:04 - Sara: <Media omitted>",
])


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "echo.db")) as client:
        yield client


def setup_profile(client, transcript=TRANSCRIPT):
    pid = client.post("/profiles", json={"name": "Artifact tutorial"}).json()["id"]
    response = client.post(f"/profiles/{pid}/imports", json={
        "title": "Python plans", "date_order": "day-first", "transcript": transcript,
    })
    assert response.status_code == 201, response.text
    return pid, response.json()["id"]


def generate(client, pid, **params):
    return client.post(f"/profiles/{pid}/artifacts/generate", params=params)


def listed(client, pid, **params):
    response = client.get(f"/profiles/{pid}/artifacts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_generation_sources_uncertainty_and_inspection(client):
    pid, cid = setup_profile(client)
    assert generate(client, pid).status_code == 200
    items = listed(client, pid)["items"]
    assert {item["kind"] for item in items} == {"summary", "person", "event", "topic"}
    summary = next(item for item in items if item["kind"] == "summary")
    result = client.get(f"/profiles/{pid}/artifacts/{summary['id']}").json()
    assert summary["status"] == "pending"
    assert not summary["uncertain"]
    assert "Media omitted" not in summary["content"]
    assert "encrypted" not in summary["content"]
    for source in result["sources"]:
        assert source["conversation_id"] == cid
        assert f"{source['speaker']}: {source['text']}" in summary["content"]
    assert {source["id"] for source in result["sources"]} == set(summary["source_message_ids"])
    assert {item["content"] for item in items if item["kind"] == "person"} == {
        "Participant label: Ali", "Participant label: Sara",
    }
    assert all(item["uncertain"] for item in items if item["kind"] != "summary")
    assert any(item["kind"] == "topic" and item["content"] == "python" for item in items)
    assert "meeting" in next(item["content"] for item in items if item["kind"] == "event")


def test_regeneration_deduplicates_and_preserves_review_decisions(client):
    pid, _ = setup_profile(client)
    generate(client, pid)
    items = listed(client, pid)["items"]
    for item, status in zip(items[:3], ["confirmed", "corrected", "rejected"], strict=True):
        body = {"revision": item["revision"], "status": status}
        if status == "corrected":
            body["content"] = "Reviewed label"
        response = client.patch(f"/profiles/{pid}/artifacts/{item['id']}", json=body)
        assert response.status_code == 200, response.text
    response = generate(client, pid).json()
    assert response["created"] == 0
    assert response["preserved"] == 3
    after = listed(client, pid)["items"]
    assert len(after) == len(items)
    for original, updated in zip(items[:3], after[:3], strict=True):
        assert original["id"] == updated["id"]
        assert updated["revision"] == 2
    assert after[1]["content"] == "Reviewed label"


def test_corrections_keep_original_output_and_source_messages_unchanged(client):
    pid, _ = setup_profile(client)
    original_messages = client.get(f"/profiles/{pid}/messages").json()
    generate(client, pid)
    artifact = listed(client, pid, kind="summary")["items"][0]
    source_id = artifact["source_message_ids"][0]
    response = client.patch(f"/profiles/{pid}/artifacts/{artifact['id']}", json={
        "revision": 1, "status": "corrected", "content": "Python study plans.",
        "source_message_ids": [source_id, source_id],
    })
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["source_message_ids"] == [source_id]
    assert edited["generated_content"] == artifact["content"]
    assert edited["generated_source_message_ids"] == artifact["source_message_ids"]
    assert len(edited["generated_sources"]) == len(artifact["source_message_ids"])
    assert client.get(f"/profiles/{pid}/messages").json() == original_messages
    assert client.patch(f"/profiles/{pid}/artifacts/{artifact['id']}", json={
        "revision": 1, "status": "rejected",
    }).status_code == 409


def test_cross_profile_and_cross_conversation_sources_are_rejected(client):
    pid, _ = setup_profile(client)
    other, other_cid = setup_profile(client)
    generate(client, pid)
    artifact = listed(client, pid)["items"][0]
    assert client.get(f"/profiles/{other}/artifacts/{artifact['id']}").status_code == 404
    assert client.patch(f"/profiles/{other}/artifacts/{artifact['id']}", json={"revision": 1, "status": "confirmed"}).status_code == 404
    assert client.post(f"/profiles/{pid}/artifacts/generate", params={"conversation_id": other_cid}).status_code == 404
    assert client.get(f"/profiles/{pid}/artifacts", params={"conversation_id": other_cid}).status_code == 404
    bad_source = client.get(f"/profiles/{other}/messages").json()["items"][0]["id"]
    assert client.patch(f"/profiles/{pid}/artifacts/{artifact['id']}", json={
        "revision": 1, "status": "corrected", "source_message_ids": [bad_source],
    }).status_code == 422


@pytest.mark.parametrize("body", [
    {"revision": 1, "status": "corrected"},
    {"revision": 1, "status": "corrected", "content": "  "},
    {"revision": 1, "status": "confirmed", "content": "Changing it"},
    {"revision": 1, "status": "corrected", "source_message_ids": []},
    {"revision": 1, "status": "corrected", "source_message_ids": ["missing"]},
    {"revision": 0, "status": "rejected"},
    {"revision": 1, "status": "pending"},
    {"revision": 1, "status": "confirmed", "generated_content": "Overwrite"},
])
def test_review_validation(client, body):
    pid, _ = setup_profile(client)
    generate(client, pid)
    artifact = listed(client, pid)["items"][0]
    assert client.patch(f"/profiles/{pid}/artifacts/{artifact['id']}", json=body).status_code == 422


def test_segment_summaries_keep_late_messages_and_bound_excerpts(client):
    lines = [f"14/10/2026, 09:00 - Ali: Python practice session {i}" for i in range(21)]
    pid, _ = setup_profile(client, "\n".join(lines))
    generate(client, pid)
    summaries = listed(client, pid, kind="summary")["items"]
    assert len(summaries) == 2
    assert any("session 20" in item["content"] for item in summaries)


def test_long_event_excerpt_keeps_event_cue(client):
    pid, _ = setup_profile(client, "14/10/2026, 09:00 - Ali: " + "Python " * 200 + "meeting tomorrow")
    generate(client, pid)
    event = listed(client, pid, kind="event")["items"][0]
    assert "meeting tomorrow" in event["content"]
    assert "[excerpt starts later]" in event["content"]
    summary = listed(client, pid, kind="summary")["items"][0]
    assert "[excerpt continues]" in summary["content"]


def test_empty_profile_and_system_only_conversation(client):
    pid = client.post("/profiles", json={"name": "Empty"}).json()["id"]
    assert generate(client, pid).json()["created"] == 0
    assert listed(client, pid)["total"] == 0
    pid, _ = setup_profile(client, "14/10/2026, 09:00 - Messages are encrypted.")
    assert generate(client, pid).json()["created"] == 0


def test_artifacts_survive_restart(tmp_path):
    path = tmp_path / "echo.db"
    with TestClient(create_app(path)) as first:
        pid, _ = setup_profile(first)
        generate(first, pid)
        before = listed(first, pid)
    with TestClient(create_app(path)) as restarted:
        assert listed(restarted, pid) == before


def test_atomic_generation_rollback(client):
    pid, _ = setup_profile(client)

    def fail_insert(*_):
        raise RuntimeError("Simulated artifact storage failure")

    event.listen(DerivedArtifact, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="Simulated artifact storage failure"):
            generate(client, pid)
    finally:
        event.remove(DerivedArtifact, "before_insert", fail_insert)
    with client.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DerivedArtifact)) == 0
    assert generate(client, pid).status_code == 200


def test_filters_pagination_and_missing_records(client):
    pid, cid = setup_profile(client)
    generate(client, pid, conversation_id=cid)
    page = listed(client, pid, kind="person", status="pending", limit=1, offset=1)
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get(f"/profiles/{pid}/artifacts?limit=201").status_code == 422
    assert client.get(f"/profiles/{pid}/artifacts?kind=unknown").status_code == 422
    assert client.get(f"/profiles/{pid}/artifacts/missing").status_code == 404
    assert generate(client, "missing").status_code == 404
