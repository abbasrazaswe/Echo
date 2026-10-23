"""Fictional undated transcripts, legacy migration, and downstream provenance."""
import json
import re
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateTable, CreateIndex

from app.database import Base, Database
from app.main import create_app
from app.parser.labelled import parse_labelled
from app.parser.whatsapp import ParseError
from app.llm import LLMSettings, OpenAIProvider
from test_chat import TestEmbeddings, completed

TEXT = 'Sara:\nStudy Python tonight.\nA checklist:\n1. Practice functions\n\nAli:\nGood idea 🙂\n'


def test_explicit_labels_preserve_content_source_lines_and_unknown_dates():
    rows = parse_labelled(TEXT, speakers=['Sara', 'Ali'])
    assert len(rows) == 2
    assert rows[0].text == 'Study Python tonight.\nA checklist:\n1. Practice functions\n'
    assert rows[0].raw_record == '\n'.join(TEXT.splitlines()[:5])
    assert (rows[0].source_line_start, rows[0].source_line_end) == (1, 5)
    assert rows[1].source_line_start == 6
    assert all(row.timestamp is None and row.raw_timestamp is None and row.source_type == 'speaker_labelled' for row in rows)


@pytest.mark.parametrize('text,speakers', [('', ['Sara']), ('Hello\nSara:\nHello', ['Sara']), ('Sara:\nHi', []), ('Sara:\nHi', ['Sara:'])])
def test_rejects_missing_labels_and_preamble(text, speakers):
    with pytest.raises(ParseError):
        parse_labelled(text, speakers=speakers)


def test_unicode_bom_crlf_and_inline_colons_are_preserved():
    rows = parse_labelled('\ufeffعلی:\r\nسلام: hello\r\nSara:\r\nHello', speakers=['علی', 'Sara'])
    assert rows[0].speaker == 'علی' and rows[0].text == 'سلام: hello'
    assert rows[0].raw_record.startswith('\ufeff')


def test_undated_import_export_index_artifacts_style_and_mocked_chat(tmp_path):
    requests = []
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        source = json.loads(payload['input'][0]['content'])['historical_excerpts'][0]
        assert source['timestamp'] is None
        return httpx.Response(200, json=completed({'answer': 'Python was suggested; the date is unknown.', 'insufficient_evidence': False,
            'citations': [{'message_id': source['message_id'], 'quote': source['text']}], 'live_citations': [], 'follow_up_question': None}))
    provider = OpenAIProvider(LLMSettings(api_key='fictional-key', model='fictional-model'), transport=httpx.MockTransport(handle))
    path = tmp_path / 'undated.db'
    with TestClient(create_app(path, embedder=TestEmbeddings(), llm_provider=provider)) as client:
        pid = client.post('/profiles', json={'name':'Fictional undated'}).json()['id']
        base = f'/profiles/{pid}'
        body = {'title':'Fictional notes', 'transcript_format':'speaker-labelled', 'speakers':['Sara','Ali'], 'transcript':TEXT}
        imported = client.post(base+'/imports', json=body)
        assert imported.status_code == 201, imported.text
        data = imported.json()
        assert data['date_order'] is None and data['transcript_format'] == 'speaker-labelled'
        cid = data['id']
        messages = client.get(base+f'/conversations/{cid}/export').json()
        assert messages[0]['timestamp'] is None and messages[0]['raw_timestamp'] is None
        assert messages[0]['text'] == parse_labelled(TEXT, speakers=['Sara','Ali'])[0].text
        assert client.post(base+'/imports', json=body).status_code == 409
        assert client.post(base+'/memories/index').status_code == 200
        hits = client.get(base+'/memories/search', params={'q':'Python','min_score':0}).json()['items']
        assert hits[0]['messages'][0]['timestamp'] is None
        assert client.post(base+'/artifacts/generate').status_code == 200
        assert client.get(base+'/artifacts').json()['total'] > 0
        assert client.post(base+'/style/analyze', json={'revision':0,'speaker':'Sara'}).status_code == 200
        result = client.post('/chat', json={'profile_id':pid,'message':'What about Python?','min_score':0})
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'answered' and len(requests) == 1
        assert 'null source timestamp' in requests[0]['instructions']
    with TestClient(create_app(path)) as client:
        assert client.get(base+'/messages').json()['total'] == 2
        other = client.post('/profiles', json={'name':'Other'}).json()['id']
        assert client.get(f'/profiles/{other}/conversations/{cid}/export').status_code == 404


@pytest.mark.parametrize('overrides', [{'speakers':[]}, {'date_order':'day-first'}, {'speakers':['Sara:']}, {'speakers':['']}, {'transcript_format':'unsupported'}])
def test_format_and_label_validation_is_transactional(tmp_path, overrides):
    with TestClient(create_app(tmp_path/'echo.db')) as client:
        pid=client.post('/profiles',json={'name':'Test'}).json()['id']
        body={'title':'Test','transcript_format':'speaker-labelled','speakers':['Sara'],'transcript':'Sara:\nHello',**overrides}
        assert client.post(f'/profiles/{pid}/imports',json=body).status_code == 422
        assert client.get(f'/profiles/{pid}/conversations').json() == []


def legacy_database(path, *, invalid=False):
    db = sqlite3.connect(path)
    nullable={'conversations': ['date_order','started_at','ended_at'], 'messages':['timestamp','raw_timestamp']}
    for table in Base.metadata.sorted_tables:
        sql=str(CreateTable(table).compile(dialect=dialect()))
        if table.name == 'conversations':
            sql=re.sub(r'^\s*transcript_format[^\n]*\n', '', sql, flags=re.M)
        for column in nullable.get(table.name,[]):
            sql=re.sub(r'(?m)^(\s*'+column+r'\s+\w+)(\s*[,\n])', r'\1 NOT NULL\2', sql)
        db.execute(sql)
        for index in table.indexes:
            db.execute(str(CreateIndex(index).compile(dialect=dialect())))
    db.execute("INSERT INTO profiles VALUES ('p','Legacy','2026-10-14')")
    db.execute("INSERT INTO conversations VALUES ('c','p','Legacy','hash','day-first',1,'2026-10-14','2026-10-14')")
    db.execute("INSERT INTO messages VALUES ('m',?,1,'Sara','Hello','2026-10-14','14/10/2026','message','whatsapp_export',1,1,'raw')", ('missing' if invalid else 'c',))
    db.execute("INSERT INTO derived_artifacts VALUES ('a','c','summary','key','Hello','[\"m\"]','Hello','[\"m\"]','test',0,'confirmed',2)")
    db.execute("CREATE INDEX legacy_extra_index ON messages(speaker)")
    db.execute("CREATE TRIGGER legacy_trigger AFTER UPDATE ON messages BEGIN SELECT 1; END")
    db.commit(); db.close()


def test_legacy_upgrade_preserves_rows_constraints_indexes_and_is_idempotent(tmp_path):
    path=tmp_path/'legacy.db'; legacy_database(path)
    database=Database(path); database.initialize(); database.initialize()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT transcript_format,date_order FROM conversations').fetchone() == ('whatsapp','day-first')
        assert db.execute('SELECT text,timestamp FROM messages').fetchone() == ('Hello','2026-10-14')
        assert db.execute('SELECT status,revision FROM derived_artifacts').fetchone() == ('confirmed',2)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('legacy_extra_index','legacy_trigger')").fetchone()[0] == 2
        assert next(row for row in db.execute('PRAGMA table_info(messages)') if row[1]=='timestamp')[3] == 0
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO messages SELECT * FROM messages")
    backups=list(tmp_path.glob('legacy.pre-undated-*.db'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:
        assert next(row for row in db.execute('PRAGMA table_info(messages)') if row[1]=='timestamp')[3] == 1
    database.engine.dispose()


def test_migration_failure_rolls_back_the_entire_upgrade(tmp_path):
    path=tmp_path/'legacy.db'; legacy_database(path, invalid=True)
    database=Database(path)
    with pytest.raises(RuntimeError,match='Foreign key check'):
        database.initialize()
    with sqlite3.connect(path) as db:
        assert 'transcript_format' not in {row[1] for row in db.execute('PRAGMA table_info(conversations)')}
        assert next(row for row in db.execute('PRAGMA table_info(messages)') if row[1]=='timestamp')[3] == 1
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==1
    database.engine.dispose()


def test_empty_source_messages_are_preserved_without_inventing_content():
    rows=parse_labelled('Sara:\n\nAli:\nHello', speakers=['Sara','Ali'])
    assert len(rows)==2 and rows[0].text==''
    assert rows[0].raw_record=='Sara:\n' and rows[0].source_line_end==2


def test_unused_participant_label_is_rejected():
    with pytest.raises(ParseError, match='not found'):
        parse_labelled('Sara:\nHello', speakers=['Sara','Typo'])


def test_undated_cli_export_preserves_null_dates_and_refuses_overwrite(tmp_path, monkeypatch):
    import sys
    from app.parser.__main__ import main
    source=tmp_path/'input.txt'; source.write_text(TEXT)
    output=tmp_path/'output.json'
    monkeypatch.setattr(sys,'argv',['parser',str(source),'--format','speaker-labelled','--speaker','Sara','--speaker','Ali','--output',str(output)])
    main()
    assert json.loads(output.read_text())[0]['timestamp'] is None
    with pytest.raises(SystemExit):
        main()
