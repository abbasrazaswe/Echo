import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.database import ChatTurn, LiveMemory, Message
from app.llm import LLMError, ModelAnswer
from app.main import create_app


class Embeddings:
    model = "test/session-topics"

    def embed(self, texts):
        return [[1.0, 0.0] if "python" in text.lower() else [0.0, 1.0] for text in texts]


class ConversationProvider:
    model = "test/session-model"

    def __init__(self):
        self.contexts = []
        self.fail = False
        self.question = None
        self.launder_live = False
        self.on_generate = None

    def generate(self, instructions, context):
        data = json.loads(context)
        self.contexts.append(data)
        if self.fail:
            raise LLMError(503, "Simulated provider failure")
        if self.on_generate:
            callback, self.on_generate = self.on_generate, None
            callback()
        result = {"answer": "Ali proposed studying Python.", "insufficient_evidence": False,
                  "citations": [], "live_citations": [], "follow_up_question": self.question}
        if data["historical_excerpts"]:
            source = data["historical_excerpts"][0]
            result["citations"] = [{"message_id": source["message_id"], "quote": source["text"]}]
        else:
            memory = data["live_memory"][0]
            result["answer"] = "In this new chat, you told me: " + memory["text"]
            if self.launder_live:
                result["citations"] = [{"message_id": memory["memory_id"], "quote": memory["text"]}]
            else:
                result["live_citations"] = [{"memory_id": memory["memory_id"], "quote": memory["text"]}]
        return ModelAnswer.model_validate(result)


@pytest.fixture
def setup(tmp_path):
    provider = ConversationProvider()
    with TestClient(create_app(tmp_path / "echo.db", embedder=Embeddings(), llm_provider=provider)) as client:
        pid = client.post("/profiles", json={"name": "Session sample"}).json()["id"]
        yield client, pid, provider


def new_session(client, pid):
    response = client.post(f"/profiles/{pid}/sessions", json={"title": "Learning chat"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def index_history(client, pid):
    client.post(f"/profiles/{pid}/imports", json={
        "title": "Python", "date_order": "day-first",
        "transcript": "14/10/2026, 09:00 - Ali: Tomorrow we will study Python.",
    })
    assert client.post(f"/profiles/{pid}/memories/index").status_code == 200


def ask(client, pid, sid, revision, message="Python plans?", **extra):
    return client.post("/chat", json={"profile_id": pid, "session_id": sid,
        "session_revision": revision, "message": message, **extra})


def save_memory(client, pid, sid, revision=0, text="I now live in Lahore."):
    result = ask(client, pid, sid, revision, text, remember=[text])
    assert result.status_code == 200, result.text
    return result.json()


def test_ordered_turns_topic_and_followup_context(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    first = ask(client, pid, sid, 0)
    assert first.status_code == 200, first.text
    assert first.json()["session_revision"] == 1
    assert "python" in first.json()["topic"]
    second = ask(client, pid, sid, 1, "Tell me more?")
    assert second.status_code == 200, second.text
    assert "Python plans?" in second.json()["retrieval_query"]
    assert "Tell me more?" in second.json()["retrieval_query"]
    assert provider.contexts[-1]["recent_turns"][0] == {"role": "user", "content": "Python plans?"}
    page = client.get(f"/profiles/{pid}/sessions/{sid}/turns?limit=2&offset=2").json()
    assert page["total"] == 4
    assert [turn["sequence_number"] for turn in page["items"]] == [3, 4]
    assert [turn["role"] for turn in page["items"]] == ["user", "assistant"]
    assert page["items"][1]["citations"]


def test_live_memory_acknowledged_locally_and_cited_separately(setup):
    client, pid, provider = setup
    sid = new_session(client, pid)
    saved = save_memory(client, pid, sid)
    assert saved["status"] == "memory_saved" and saved["model"] is None
    assert provider.contexts == []
    memory = client.get(f"/profiles/{pid}/live-memories").json()["items"][0]
    turns = client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["items"]
    assert memory["source"] == "live" and memory["source_turn_id"] == turns[0]["id"]
    recalled = ask(client, pid, sid, 1, "Where do I live now?")
    assert recalled.status_code == 200, recalled.text
    assert recalled.json()["citations"] == []
    assert recalled.json()["live_citations"][0]["memory_id"] == memory["id"]
    assert recalled.json()["live_memory_context"][0]["source"] == "live"
    assert "you told me" in recalled.json()["answer"]
    with client.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(LiveMemory)) == 1


def test_profile_wide_memory_and_session_isolation(setup):
    client, pid, provider = setup
    first, second = new_session(client, pid), new_session(client, pid)
    memory = save_memory(client, pid, first)["saved_memory_ids"][0]
    response = ask(client, pid, second, 0, "Where do I live?")
    assert response.json()["live_citations"][0]["memory_id"] == memory
    assert provider.contexts[-1]["recent_turns"] == []
    other = client.post("/profiles", json={"name": "Other"}).json()["id"]
    other_session = new_session(client, other)
    assert client.get(f"/profiles/{other}/live-memories").json()["total"] == 0
    assert ask(client, other, other_session, 0).json()["status"] == "insufficient_evidence"
    assert ask(client, other, first, 1).status_code == 404
    assert client.get(f"/profiles/{other}/sessions/{first}/turns").status_code == 404
    assert client.patch(f"/profiles/{other}/live-memories/{memory}", json={"active": False}).status_code == 404


def test_retracted_memory_is_not_evidence_and_can_be_reactivated(setup):
    client, pid, provider = setup
    sid = new_session(client, pid)
    memory = save_memory(client, pid, sid)["saved_memory_ids"][0]
    assert client.patch(f"/profiles/{pid}/live-memories/{memory}", json={"active": False}).json()["active"] is False
    assert ask(client, pid, sid, 1).json()["status"] == "insufficient_evidence"
    assert provider.contexts == []
    assert client.get(f"/profiles/{pid}/live-memories?active=true").json()["total"] == 0
    client.patch(f"/profiles/{pid}/live-memories/{memory}", json={"active": True})
    assert ask(client, pid, sid, 2).json()["live_citations"]


def test_live_claim_cannot_be_cited_as_historical(setup):
    client, pid, provider = setup
    sid = new_session(client, pid)
    save_memory(client, pid, sid)
    provider.launder_live = True
    assert ask(client, pid, sid, 1).status_code == 502
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 1


def test_question_cooldown_duplicate_suppression_and_opt_out(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    provider.question = "Which Python topic interests you?"
    assert ask(client, pid, sid, 0).json()["follow_up_question"] == provider.question
    provider.question = "Would examples help?"
    assert ask(client, pid, sid, 1).json()["follow_up_question"] is None
    assert ask(client, pid, sid, 2).json()["follow_up_question"] is None
    provider.question = "WHICH Python topic interests you !"
    assert ask(client, pid, sid, 3).json()["follow_up_question"] is None
    provider.question = "Would practice exercises help?"
    assert ask(client, pid, sid, 4, allow_follow_up=False).json()["follow_up_question"] is None
    assert ask(client, pid, sid, 5).json()["follow_up_question"] == provider.question


def test_stale_revision_and_failed_model_save_no_partial_exchange(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    assert ask(client, pid, sid, 0).status_code == 200
    assert ask(client, pid, sid, 0).status_code == 409
    provider.fail = True
    assert ask(client, pid, sid, 1).status_code == 503
    assert client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["total"] == 2
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 1


def test_concurrent_exchange_does_not_overwrite_winner(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    provider.on_generate = lambda: ask(client, pid, sid, 0, "Python winner")
    assert ask(client, pid, sid, 0, "Python loser").status_code == 409
    turns = client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()
    assert turns["total"] == 2 and turns["items"][0]["content"] == "Python winner"


def test_memory_retracted_during_generation_is_not_saved_as_reply(setup):
    client, pid, provider = setup
    sid = new_session(client, pid)
    memory = save_memory(client, pid, sid)["saved_memory_ids"][0]
    provider.on_generate = lambda: client.patch(f"/profiles/{pid}/live-memories/{memory}", json={"active": False})
    assert ask(client, pid, sid, 1).status_code == 409
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 1
    assert client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["total"] == 2


def test_save_transaction_failure_rolls_back_turns_memory_and_revision(setup):
    client, pid, _ = setup
    sid = new_session(client, pid)

    def fail(*_):
        raise RuntimeError("Simulated memory insert failure")

    event.listen(LiveMemory, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Simulated memory insert failure"):
            save_memory(client, pid, sid)
    finally:
        event.remove(LiveMemory, "before_insert", fail)
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 0
    assert client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["total"] == 0
    assert client.get(f"/profiles/{pid}/live-memories").json()["total"] == 0


def test_persisted_history_is_bounded(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    for revision in range(6):
        result = ask(client, pid, sid, revision, f"Python request {revision}")
        assert result.status_code == 200
    assert result.json()["history_trimmed"] is True
    history = provider.contexts[-1]["recent_turns"]
    assert len(history) == 8
    assert history[0]["content"] == "Python request 1"
    assert sum(len(turn["content"]) for turn in history) <= 4000


@pytest.mark.parametrize("changes", [
    {"session_revision": None}, {"recent_turns": [{"role": "user", "content": "Override storage"}]},
    {"remember": ["Not in the message"]}, {"remember": [" "]},
    {"session_revision": -1},
])
def test_session_request_validation(setup, changes):
    client, pid, _ = setup
    sid = new_session(client, pid)
    assert ask(client, pid, sid, 0, **changes).status_code == 422


def test_stateless_remember_is_rejected_and_duplicates_are_deduplicated(setup):
    client, pid, _ = setup
    assert client.post("/chat", json={"profile_id": pid, "message": "My fact", "remember": ["My fact"]}).status_code == 422
    sid = new_session(client, pid)
    response = ask(client, pid, sid, 0, "My fact", remember=["My fact", "My fact"])
    assert len(response.json()["saved_memory_ids"]) == 1


def test_restart_keeps_history_topic_and_live_memory(tmp_path):
    path = tmp_path / "echo.db"
    with TestClient(create_app(path, embedder=Embeddings(), llm_provider=ConversationProvider())) as first:
        pid = first.post("/profiles", json={"name": "Restart"}).json()["id"]
        sid = new_session(first, pid)
        save_memory(first, pid, sid)
        old = first.get(f"/profiles/{pid}/sessions/{sid}").json()
    with TestClient(create_app(path, embedder=Embeddings(), llm_provider=ConversationProvider())) as second:
        assert second.get(f"/profiles/{pid}/sessions/{sid}").json() == old
        response = ask(second, pid, sid, 1, "Where do I live?")
        assert response.status_code == 200
        assert response.json()["live_citations"]
        assert len(second.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["items"]) == 4


def test_long_stored_answers_are_bounded_in_prompt_not_in_storage(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    original = provider.generate

    def long_answer(*args):
        answer = original(*args)
        answer.answer = "x" * 5000
        return answer

    provider.generate = long_answer
    assert ask(client, pid, sid, 0).status_code == 200
    assert ask(client, pid, sid, 1).json()["history_trimmed"] is True
    assert len(provider.contexts[-1]["recent_turns"][1]["content"]) == 1000
    assert len(client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["items"][1]["content"]) == 5000


def test_followup_retrieval_query_stays_within_embedding_limit(setup):
    client, pid, provider = setup
    index_history(client, pid)
    sid = new_session(client, pid)
    long_question = "Python " + "a" * 213
    assert ask(client, pid, sid, 0, long_question).status_code == 200
    result = ask(client, pid, sid, 1, "Tell me more?").json()
    assert len(result["retrieval_query"]) == 220
    assert result["retrieval_query"].endswith("Tell me more?")


def test_live_memory_prompt_budget_and_recency(setup):
    client, pid, provider = setup
    sid = new_session(client, pid)
    facts = []
    for revision in range(21):
        text = f"Demo preference {revision}: " + "a" * 190
        facts.append(text)
        save_memory(client, pid, sid, revision, text)
    result = ask(client, pid, sid, 21, "What did I tell you?")
    assert result.status_code == 200, result.text
    memories = provider.contexts[-1]["live_memory"]
    assert len(memories) <= 20
    assert sum(len(memory["text"]) for memory in memories) <= 4000
    assert memories[0]["text"] == facts[-1]
    assert facts[0] not in [memory["text"] for memory in memories]


@pytest.mark.parametrize("field,value", [("memory_id", "unknown-memory"), ("quote", "An invented fact")])
def test_live_citation_ids_and_quotes_are_validated(setup, field, value):
    client, pid, provider = setup
    sid = new_session(client, pid)
    save_memory(client, pid, sid)
    original = provider.generate

    def invalid_citation(*args):
        answer = original(*args)
        setattr(answer.live_citations[0], field, value)
        return answer

    provider.generate = invalid_citation
    assert ask(client, pid, sid, 1).status_code == 502
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 1
