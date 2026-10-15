from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.database import Conversation, Message
from app.main import create_app
from app.parser.whatsapp import parse_whatsapp


SAMPLE = (Path(__file__).parent / "fixtures/whatsapp_sample.txt").read_text()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "echo.db")) as client:
        yield client


def new_profile(client, name="Learning profile"):
    response = client.post("/profiles", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def import_sample(client, profile_id, transcript=SAMPLE):
    return client.post(f"/profiles/{profile_id}/imports", json={
        "title": "Python discussion", "transcript": transcript, "date_order": "day-first",
    })


def test_import_browse_search_and_export_round_trip(client):
    profile = new_profile(client)
    assert client.get("/profiles").json()[0]["name"] == "Learning profile"
    result = import_sample(client, profile)
    assert result.status_code == 201, result.text
    conversation = result.json()["id"]
    assert result.json()["message_count"] == 4
    assert len(client.get(f"/profiles/{profile}/conversations").json()) == 1
    page = client.get(f"/profiles/{profile}/messages?limit=2&offset=1").json()
    assert page["total"] == 4
    assert [message["sequence_number"] for message in page["items"]] == [2, 3]
    search = client.get(f"/profiles/{profile}/messages", params={"q": "FUNCTIONS"}).json()
    assert search["total"] == 1
    assert search["items"][0]["speaker"] == "Sara"
    exported = client.get(f"/profiles/{profile}/conversations/{conversation}/export").json()
    parsed = parse_whatsapp(SAMPLE, date_order="day-first")
    for record, original in zip(exported, parsed, strict=True):
        assert {key: record[key] for key in type(original).model_fields} == original.model_dump(mode="json")
        assert record["conversation_id"] == conversation
        assert record["id"]
    listed = client.get(f"/profiles/{profile}/messages").json()["items"]
    assert [item["id"] for item in exported] == [item["id"] for item in listed]


def test_duplicate_import_ignores_line_ending_and_bom_differences(client):
    profile = new_profile(client)
    assert import_sample(client, profile).status_code == 201
    duplicate = import_sample(client, profile, "\ufeff" + SAMPLE.replace("\n", "\r\n"))
    assert duplicate.status_code == 409
    assert client.get(f"/profiles/{profile}/messages").json()["total"] == 4


def test_profiles_and_conversation_filters_are_isolated(client):
    first, second = new_profile(client), new_profile(client)
    conversation = import_sample(client, first).json()["id"]
    assert client.get(f"/profiles/{second}/messages").json()["total"] == 0
    assert client.get(f"/profiles/{second}/conversations/{conversation}/export").status_code == 404
    assert client.get(f"/profiles/{second}/messages", params={"conversation_id": conversation}).status_code == 404
    assert import_sample(client, second).status_code == 201
    another = import_sample(client, first, SAMPLE.replace("Python", "Databases")).json()["id"]
    filtered = client.get(f"/profiles/{first}/messages", params={"conversation_id": another}).json()
    assert filtered["total"] == 4
    assert {item["conversation_id"] for item in filtered["items"]} == {another}


def test_invalid_import_saves_nothing(client):
    profile = new_profile(client)
    assert import_sample(client, profile, SAMPLE + "31/02/2026, 09:00 - Ali: Bad date").status_code == 422
    assert client.get(f"/profiles/{profile}/conversations").json() == []
    assert client.get(f"/profiles/{profile}/messages").json()["total"] == 0


def test_database_failure_rolls_back_conversation_and_messages(client):
    profile = new_profile(client)

    def fail_insert(*_):
        raise RuntimeError("Simulated storage failure")

    event.listen(Message, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="Simulated storage failure"):
            import_sample(client, profile)
    finally:
        event.remove(Message, "before_insert", fail_insert)
    with client.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    assert import_sample(client, profile).status_code == 201


def test_data_survives_application_restart(tmp_path):
    path = tmp_path / "echo.db"
    with TestClient(create_app(path)) as first:
        profile = new_profile(first)
        import_sample(first, profile)
        ids = [item["id"] for item in first.get(f"/profiles/{profile}/messages").json()["items"]]
    with TestClient(create_app(path)) as restarted:
        assert restarted.get("/health").json() == {"status": "ok"}
        assert [item["id"] for item in restarted.get(f"/profiles/{profile}/messages").json()["items"]] == ids


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": ""}])
def test_pagination_and_query_validation(client, params):
    profile = new_profile(client)
    assert client.get(f"/profiles/{profile}/messages", params=params).status_code == 422


def test_missing_profiles_and_empty_names(client):
    assert client.post("/profiles", json={"name": "  "}).status_code == 422
    assert client.get("/profiles/missing/messages").status_code == 404
    assert import_sample(client, "missing").status_code == 404


def test_search_treats_percent_and_underscore_literally(client):
    profile = new_profile(client)
    import_sample(client, profile)
    for query in ("%", "_", "' OR 1=1 --"):
        assert client.get(f"/profiles/{profile}/messages", params={"q": query}).json()["total"] == 0
