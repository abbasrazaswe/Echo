"""Request references remain useful without putting private source text in logs."""
import asyncio
import io
import json
import logging
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability import (
    RequestFormatter, RequestLoggingMiddleware, RedactServerException,
    configure_request_logging, logger,
)


@pytest.fixture
def records():
    configure_request_logging()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RequestFormatter())
    logger.addHandler(handler)
    yield lambda: [json.loads(line) for line in output.getvalue().splitlines()]
    logger.removeHandler(handler)


def test_request_reference_and_only_allowlisted_fields(tmp_path, records):
    with TestClient(create_app(tmp_path/'echo.db')) as client:
        response = client.get('/health', headers={'X-Request-ID':'private-client-id', 'Authorization':'Bearer private-key'})
    reference = response.headers['X-Request-ID']
    assert re.fullmatch('[a-f0-9]{32}', reference)
    assert response.json() == {'status':'ok'}
    assert records() == [{**records()[0], 'request_id':reference, 'method':'GET', 'route':'/health', 'status':200, 'outcome':'completed'}]
    assert set(records()[0]) == {'timestamp','event','request_id','method','route','status','duration_ms','outcome'}
    assert records()[0]['duration_ms'] >= 0
    assert 'private' not in json.dumps(records())


def test_logs_never_include_profile_ids_queries_bodies_or_missing_paths(tmp_path, records):
    with TestClient(create_app(tmp_path/'echo.db')) as client:
        pid = client.post('/profiles', json={'name':'private-profile-name'}).json()['id']
        client.post(f'/profiles/{pid}/imports', json={'title':'private-title', 'date_order':'day-first', 'transcript':'14/10/2026, 09:01 - Someone: private-transcript'})
        result = client.get(f'/profiles/{pid}/messages', params={'q':'private-query'})
        assert result.status_code == 200
        missing = client.get('/private-missing-path?query=private-search', headers={'Cookie':'private-cookie'})
        assert missing.status_code == 404
        invalid = client.post('/profiles', json={'name':''})
        assert invalid.status_code == 422 and invalid.headers['X-Request-ID']
    payload = json.dumps(records())
    assert 'private' not in payload and pid not in payload
    assert '/profiles/{profile_id}/imports' in payload
    assert records()[-2]['route'] == '<unmatched>'


def test_unhandled_failures_have_safe_json_matching_reference_and_no_exception_text(tmp_path, records):
    app=create_app(tmp_path/'echo.db')
    @app.get('/broken/{source_id}')
    async def broken(source_id: str):
        raise ValueError('private exception with source '+source_id)
    with TestClient(app, raise_server_exceptions=False) as client:
        response=client.get('/broken/private-source-id')
    assert response.status_code==500
    assert 'private' not in response.text
    assert response.headers['X-Request-ID']==records()[0]['request_id']
    assert records()[0]['route']=='/broken/{source_id}'
    assert records()[0]['outcome']=='error' and records()[0]['status']==500
    assert 'private' not in json.dumps(records())


def test_raised_errors_still_propagate_to_the_server(tmp_path, records):
    app=create_app(tmp_path/'echo.db')
    @app.get('/broken')
    async def broken():
        raise RuntimeError('fictional error')
    with TestClient(app) as client, pytest.raises(RuntimeError):
        client.get('/broken')
    assert len(records())==1 and records()[0]['status']==500


def test_logging_configuration_is_idempotent_and_uvicorn_exceptions_are_sanitized():
    configure_request_logging(); configure_request_logging()
    assert sum(bool(getattr(handler,'_echo_request_handler',False)) for handler in logger.handlers)==1
    assert logging.getLogger('uvicorn.access').disabled
    try:
        raise ValueError('private exception')
    except ValueError:
        import sys
        record=logging.LogRecord('uvicorn.error',logging.ERROR,'',1,'private raw request %s',('private-data',),sys.exc_info())
    RedactServerException().filter(record)
    rendered=logging.Formatter().format(record)
    assert 'private' not in rendered and record.exc_info is None


def test_concurrent_requests_keep_separate_references(records):
    async def run():
        async def app(scope, receive, send):
            scope['route']=SimpleNamespace(path='/requests/{id}')
            await asyncio.sleep(0)
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        middleware=RequestLoggingMiddleware(app)
        async def one():
            sent=[]
            async def send(message): sent.append(message)
            async def receive(): return {'type':'http.request','body':b''}
            await middleware({'type':'http','method':'GET','path':'/requests/private'},receive,send)
            return dict(sent[0]['headers'])[b'x-request-id'].decode()
        return await asyncio.gather(one(),one())
    references=asyncio.run(run())
    assert len(set(references))==2
    assert set(references)=={row['request_id'] for row in records()}


def test_non_http_scopes_pass_through_without_request_logs(records):
    observed=[]
    async def app(scope, receive, send): observed.append(scope['type'])
    async def unused(*args): pass
    asyncio.run(RequestLoggingMiddleware(app)({'type':'lifespan'},unused,unused))
    assert observed==['lifespan'] and records()==[]


def test_cancelled_request_is_logged_once_and_not_swallowed(records):
    async def app(scope, receive, send): raise asyncio.CancelledError()
    async def unused(*args): pass
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(RequestLoggingMiddleware(app)({'type':'http','method':'private-invalid'},unused,unused))
    assert len(records())==1
    assert records()[0]['status']==499 and records()[0]['outcome']=='cancelled'
    assert records()[0]['method']=='OTHER'
