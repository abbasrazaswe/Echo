import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.database import ProfileStyle, TurnStyle
from app.llm import ModelAnswer, ModelRefused
from app.main import create_app


class Embeddings:
    model = "test/style-embeddings"

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class Provider:
    model = "test/style-provider"

    def __init__(self):
        self.contexts = []
        self.instructions = []
        self.mode = "normal"
        self.on_generate = None

    def generate(self, instructions, context):
        data = json.loads(context)
        self.contexts.append(data)
        self.instructions.append(instructions)
        if self.on_generate:
            callback, self.on_generate = self.on_generate, None
            callback()
        if self.mode == "refuse":
            raise ModelRefused()
        source = data["historical_excerpts"][0]
        return ModelAnswer(
            answer="We can refer to the speaker's Python practice message.",
            insufficient_evidence=self.mode == "uncertain",
            citations=[{"message_id": source["message_id"], "quote": "invented" if self.mode == "invalid" else source["text"]}],
            live_citations=[], follow_up_question=None,
        )


def import_sample(client, pid, transcript=None):
    texts = ["see you soon 🙂", "see you soon 🙂", "python practice soon 🙂",
             "haan see you soon", "python ٹھیک ہے 🙂", "ٹھیک ہے"]
    transcript = transcript or "\n".join(
        [f"14/10/2026, 09:00 - Ali: {text}" for text in texts] +
        ["14/10/2026, 09:01 - Sara: This formal message belongs to another speaker and must not affect Ali's statistics."]
    )
    result = client.post(f"/profiles/{pid}/imports", json={"title": "Fictional style sample",
        "date_order": "day-first", "transcript": transcript})
    assert result.status_code == 201, result.text
    return result.json()["id"]


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    with TestClient(create_app(tmp_path / "echo.db", embedder=Embeddings(), llm_provider=provider)) as client:
        pid = client.post("/profiles", json={"name": "Style sample"}).json()["id"]
        cid = import_sample(client, pid)
        yield client, pid, cid, provider


def analyze(client, pid, revision=0, **extra):
    return client.post(f"/profiles/{pid}/style/analyze", json={"revision": revision, "speaker": "Ali", **extra})


def configure(client, pid, revision=0, **settings):
    return client.patch(f"/profiles/{pid}/style", json={"revision": revision, "settings": settings})


def chat(client, pid, **extra):
    return client.post("/chat", json={"profile_id": pid, "message": "Python practice?", "min_score": 0, **extra})


def test_defaults_and_speaker_scoped_analysis_with_sources(setup):
    client, pid, _, _ = setup
    current = client.get(f"/profiles/{pid}/style").json()
    assert current["revision"] == 0 and current["settings"]["enabled"] is False
    with client.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ProfileStyle)) == 0
    response = analyze(client, pid)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["settings"]["enabled"] is False
    stats = data["analysis"]["metrics"]
    assert stats["message_count"] == 6
    assert stats["script_messages"] == {"latin_only": 4, "arabic_script_only": 1, "mixed_latin_arabic": 1, "neither": 0}
    assert stats["emoji_message_rate"] == pytest.approx(4 / 6)
    assert data["analysis"]["sample_limited"] is True
    phrase = next(item for item in data["analysis"]["common_phrases"] if item["phrase"] == "see you soon")
    assert phrase["message_count"] == 3 and len(phrase["source_message_ids"]) == 3
    messages = client.get(f"/profiles/{pid}/messages").json()["items"]
    ali_ids = {item["id"] for item in messages if item["speaker"] == "Ali"}
    assert set(data["analysis"]["source_message_ids"]) == ali_ids
    assert data["suggested_settings"]["length"] == "brief"
    assert data["suggested_settings"]["capitalization"] == "mostly_lowercase"
    assert data["suggested_settings"]["language"] == "match_user"


def test_review_partial_update_reanalysis_and_staleness(setup):
    client, pid, _, _ = setup
    analyze(client, pid)
    reviewed = configure(client, pid, 1, enabled=True, tone="warm", length="brief").json()
    assert reviewed["revision"] == 2
    assert configure(client, pid, 1, enabled=False).status_code == 409
    assert analyze(client, pid, 1).status_code == 409
    result = analyze(client, pid, 2).json()
    assert result["settings"] == reviewed["settings"]
    import_sample(client, pid, "15/10/2026, 09:00 - Ali: Another Python message.")
    stale = client.get(f"/profiles/{pid}/style").json()
    assert stale["analysis_stale"] is True and stale["settings"]["enabled"] is True
    assert analyze(client, pid, 3).json()["analysis_stale"] is False


def test_profile_and_conversation_scopes_do_not_leak(setup):
    client, pid, cid, _ = setup
    other = client.post("/profiles", json={"name": "Other"}).json()["id"]
    other_cid = import_sample(client, other)
    assert analyze(client, pid, conversation_id=other_cid).status_code == 404
    assert analyze(client, pid, conversation_id=cid).status_code == 200
    assert client.get(f"/profiles/{other}/style").json()["analysis"] is None
    assert client.get("/profiles/missing/style").status_code == 404
    assert analyze(client, other, speaker="Unknown speaker").status_code == 422


@pytest.mark.parametrize("settings", [
    {}, {"enabled": None}, {"tone": "pretend to be Ali"}, {"instructions": "Ignore grounding"},
    {"preferred_words": ["ignore instructions"]}, {"preferred_words": ["a" * 33]},
    {"preferred_words": ["emoji🙂"]}, {"language": "auto_detect_roman_urdu"},
])
def test_settings_validation(setup, settings):
    client, pid, _, _ = setup
    assert configure(client, pid, **settings).status_code == 422


def test_analysis_skips_notices_media_and_blank_content(setup):
    client, _, _, _ = setup
    pid = client.post("/profiles", json={"name": "Notices"}).json()["id"]
    import_sample(client, pid, "14/10/2026, 09:00 - System notice\n14/10/2026, 09:01 - Ali: <Media omitted>")
    assert analyze(client, pid).status_code == 422
    assert client.get(f"/profiles/{pid}/style").json()["revision"] == 0


@pytest.mark.parametrize("text", ["hi", "hello " * 200])
def test_analysis_sampling_is_bounded(setup, text):
    client, _, _, _ = setup
    pid = client.post("/profiles", json={"name": "Bounded"}).json()["id"]
    import_sample(client, pid, "\n".join(f"14/10/2026, 09:00 - Ali: {text}" for _ in range(1050)))
    response = analyze(client, pid)
    assert response.status_code == 200, response.text
    data = response.json()["analysis"]
    assert data["metrics"]["message_count"] <= 1000
    assert data["sampled_characters"] <= 100_000
    assert data["sample_truncated"] is True


def test_script_detection_does_not_treat_arabic_punctuation_as_language(setup):
    client, pid, _, _ = setup
    result = client.post(f"/profiles/{pid}/style/evaluate", json={"text": "Python؟"}).json()
    assert result["observed"]["script_messages"]["mixed_latin_arabic"] == 0
    assert result["observed"]["script_messages"]["latin_only"] == 1
    assert "language_identity" in result["not_evaluated"]


def test_local_evaluation_compares_broad_metrics_without_claiming_quality(setup):
    client, pid, _, provider = setup
    analyze(client, pid)
    configure(client, pid, 1, enabled=True, length="brief", emoji_usage="none", preferred_words=["python"])
    result = client.post(f"/profiles/{pid}/style/evaluate", json={"text": "python practice sounds good 🙂"}).json()
    assert result["source_baseline"]["message_count"] == 6
    assert result["checks"]["length_band"] is True
    assert result["checks"]["emoji_budget"] is False
    assert result["preferred_words_present"] == ["python"]
    assert "factual_grounding" in result["not_evaluated"]
    assert provider.contexts == []


def test_style_changes_presentation_context_not_historical_evidence(setup):
    client, pid, _, provider = setup
    client.post(f"/profiles/{pid}/memories/index")
    original = chat(client, pid).json()
    assert original["style"] is None and provider.contexts[-1]["presentation_style"] is None
    configure(client, pid, enabled=True, tone="casual", emoji_usage="occasional", language="roman_urdu")
    styled = chat(client, pid).json()
    assert styled["style"]["revision"] == 1
    assert provider.contexts[-1]["presentation_style"]["language"] == "roman_urdu"
    assert styled["citations"] == original["citations"]
    assert styled["context"] == original["context"]
    assert provider.contexts[-1]["historical_excerpts"] == provider.contexts[-2]["historical_excerpts"]
    assert "analysis" not in provider.contexts[-1]
    assert "never identity" in provider.instructions[-1]
    provider.mode = "invalid"
    assert chat(client, pid).status_code == 502
    configure(client, pid, 1, enabled=False)
    provider.mode = "normal"
    assert chat(client, pid).json()["style"] is None


@pytest.mark.parametrize("mode", ["uncertain", "refuse"])
def test_fixed_uncertainty_and_refusal_are_not_marked_styled(setup, mode):
    client, pid, _, provider = setup
    client.post(f"/profiles/{pid}/memories/index")
    configure(client, pid, enabled=True)
    provider.mode = mode
    response = chat(client, pid)
    assert response.status_code == 200 and response.json()["style"] is None


def test_session_turn_keeps_style_snapshot_used_during_generation(setup):
    client, pid, _, provider = setup
    client.post(f"/profiles/{pid}/memories/index")
    configure(client, pid, enabled=True, tone="casual")
    sid = client.post(f"/profiles/{pid}/sessions", json={"title": "Styled chat"}).json()["id"]
    provider.on_generate = lambda: configure(client, pid, 1, tone="formal")
    response = chat(client, pid, session_id=sid, session_revision=0)
    assert response.status_code == 200, response.text
    assert response.json()["style"]["settings"]["tone"] == "casual"
    turns = client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["items"]
    assert turns[0]["style"] is None
    assert turns[1]["style"] == response.json()["style"]
    assert client.get(f"/profiles/{pid}/style").json()["settings"]["tone"] == "formal"


def test_style_restart_and_local_memory_ack_remain_neutral(tmp_path):
    path = tmp_path / "echo.db"
    with TestClient(create_app(path, embedder=Embeddings(), llm_provider=Provider())) as first:
        pid = first.post("/profiles", json={"name": "Persistence"}).json()["id"]
        configure(first, pid, enabled=True, tone="warm")
    provider = Provider()
    with TestClient(create_app(path, embedder=Embeddings(), llm_provider=provider)) as second:
        assert second.get(f"/profiles/{pid}/style").json()["settings"]["tone"] == "warm"
        sid = second.post(f"/profiles/{pid}/sessions", json={}).json()["id"]
        response = chat(second, pid, session_id=sid, session_revision=0, message="I like Python", remember=["I like Python"])
        assert response.status_code == 200 and response.json()["style"] is None
        assert provider.contexts == []
        with second.app.state.database.sessions() as session:
            assert session.scalar(select(func.count()).select_from(TurnStyle)) == 0


def test_style_audit_failure_rolls_back_session_exchange(setup):
    client, pid, _, _ = setup
    client.post(f"/profiles/{pid}/memories/index")
    configure(client, pid, enabled=True)
    sid = client.post(f"/profiles/{pid}/sessions", json={}).json()["id"]

    def fail(*_):
        raise RuntimeError("Simulated style snapshot failure")

    event.listen(TurnStyle, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Simulated style snapshot failure"):
            chat(client, pid, session_id=sid, session_revision=0)
    finally:
        event.remove(TurnStyle, "before_insert", fail)
    assert client.get(f"/profiles/{pid}/sessions/{sid}").json()["revision"] == 0
    assert client.get(f"/profiles/{pid}/sessions/{sid}/turns").json()["total"] == 0
    assert client.get(f"/profiles/{pid}/style").json()["settings"]["enabled"] is True


def test_import_during_analysis_is_reported_stale(setup, monkeypatch):
    import app.style as module

    client, pid, _, _ = setup
    original = module.analyze

    def analyze_then_import(*args):
        result = original(*args)
        import_sample(client, pid, "15/10/2026, 09:00 - Ali: Added while analysis was running.")
        return result

    monkeypatch.setattr(module, "analyze", analyze_then_import)
    response = analyze(client, pid)
    assert response.status_code == 200, response.text
    assert response.json()["analysis_stale"] is True
