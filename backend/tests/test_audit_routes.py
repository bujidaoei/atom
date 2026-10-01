import asyncio
import sqlite3
import threading

import pytest

pytestmark = [pytest.mark.parametrize('audit_schema_version', [5, 6, 7, 9, 10]), pytest.mark.usefixtures('audit_schema_version')]

from app.bounded_operations import BoundedOperations
from app.console_auth import DURABLE_COOKIE
from app.main import app
from app.migrations import migrate
from test_durable_auth_routes import durable_client, LOGIN, ORIGIN

PATH = '/api/audit/events'
HEADERS = {'X-Atom-Intent': 'inspect-audit-events'}


@pytest.fixture
def reader(durable_client, monkeypatch, tmp_path, audit_schema_version):
    client, path = durable_client
    migrate(path, tmp_path/'before-v5.db', target_version=audit_schema_version)
    monkeypatch.setattr(app.state, 'audit_reads', BoundedOperations(capacity=1, send_timeout=.05))
    monkeypatch.setattr(app.state, 'content_issuer', BoundedOperations())
    assert client.post('/api/auth/register', json=LOGIN).status_code == 200
    return client, path


def test_real_signed_login_and_stable_page(reader):
    client, path = reader
    assert client.post('/api/auth/login', json=LOGIN).status_code == 200
    first = client.get(PATH, params={'limit': 1}, headers=HEADERS)
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-store'
    assert first.headers['referrer-policy'] == 'no-referrer'
    page = first.json()
    assert len(page['events']) == 1 and page['nextAfter'] is not None
    assert client.post('/api/auth/login', json=LOGIN).status_code == 200
    last = client.get(PATH, params={'after': page['nextAfter'], 'upper': page['upper']}, headers=HEADERS).json()
    assert len(last['events']) == 1 and last['nextAfter'] is None
    assert last['events'][0]['sequence'] <= page['upper']
    assert len(client.get(PATH, headers=HEADERS).json()['events']) == 3
    assert LOGIN['password'] not in first.text and client.cookies.get(DURABLE_COOKIE) not in first.text
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM security_audit_events').fetchone() == (3,)


@pytest.mark.parametrize('query', ['after=1', 'after=-1', 'upper=9223372036854775808',
    'limit=0', 'limit=101', 'limit=01', 'limit=1&limit=2', 'user_id=other',
    'project=', 'project=../x', 'after=2&upper=1', 'upper=1.1', 'x='+'a'*257])
def test_invalid_query(reader, query):
    client, _ = reader
    assert client.get(PATH+'?'+query, headers=HEADERS).status_code == 400
    assert app.state.audit_reads.pending_count == 0


def test_auth_scope_capacity_and_unavailable(reader, monkeypatch):
    client, path = reader
    assert client.get(PATH).status_code == 403
    assert client.get(PATH, headers=HEADERS|{'Origin': 'https://other.example'}).status_code == 403
    assert client.get(PATH, headers=HEADERS|{'Host': 'other.example'}).status_code == 403
    assert client.get(PATH, params={'project': 'foreign'}, headers=HEADERS).status_code == 404
    slot = app.state.audit_reads.acquire()
    try:
        assert client.get(PATH, headers=HEADERS).status_code == 503
        separate = app.state.content_issuer.acquire()
        assert separate is not None
        app.state.content_issuer.release(separate)
    finally:
        app.state.audit_reads.release(slot)
    cookie = client.cookies.get(DURABLE_COOKIE)
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get(PATH, headers=HEADERS|{'Cookie': DURABLE_COOKIE+'='+cookie}).status_code == 401
    assert client.get(PATH, headers=HEADERS).status_code == 401
    assert client.post('/api/auth/login', json=LOGIN).status_code == 200
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX security_audit_scope_sequence')
    assert client.get(PATH, headers=HEADERS).status_code == 503


def test_other_account_sees_only_its_events_and_forgery_fails(reader):
    client, _ = reader
    first = client.get(PATH, headers=HEADERS).json()['events'][0]
    other = client.post('/api/auth/register', json=LOGIN|{'email': 'other@example.org'}).json()['id']
    events = client.get(PATH, headers=HEADERS).json()['events']
    assert len(events) == 1 and events[0]['scope_id'] == other
    assert events[0]['event_id'] != first['event_id']
    cookie = client.cookies.get(DURABLE_COOKIE)
    parts = cookie.split('.')
    parts[2] = ('a' if parts[2][0] != 'a' else 'b')+parts[2][1:]
    assert client.get(PATH, headers=HEADERS|{'Cookie': DURABLE_COOKIE+'='+'.'.join(parts)}).status_code == 401


def test_schema4_is_unavailable_without_automatic_migration(durable_client, monkeypatch):
    client, path = durable_client
    monkeypatch.setattr(app.state, 'audit_reads', BoundedOperations())
    assert client.post('/api/auth/register', json=LOGIN).status_code == 200
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone() == (4,)


def _scope(client):
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'scheme': 'https',
        'method': 'GET', 'path': PATH, 'raw_path': PATH.encode(), 'query_string': b'',
        'root_path': '', 'server': ('console.example.org', 443), 'client': ('127.0.0.1', 1),
        'headers': [(b'host', ORIGIN[8:].encode()), (b'x-atom-intent', b'inspect-audit-events'),
                    (b'cookie', (DURABLE_COOKIE+'='+client.cookies.get(DURABLE_COOKIE)).encode())]}


async def _receive():
    return {'type': 'http.request', 'body': b'', 'more_body': False}


@pytest.mark.parametrize('failure', ['timeout', 'disconnect', 'cancel'])
def test_response_ownership(reader, failure):
    client, _ = reader
    owner = app.state.audit_reads
    async def scenario():
        started = asyncio.Event()
        async def send(event):
            if event['type'] == 'http.response.body':
                assert owner.pending_count == 1 and owner.acquire() is None
                started.set()
                if failure == 'disconnect':
                    raise OSError('closed')
                await asyncio.Event().wait()
        task = asyncio.create_task(app(_scope(client), _receive, send))
        await asyncio.wait_for(started.wait(), 2)
        if failure == 'cancel':
            task.cancel()
        with pytest.raises({'timeout': TimeoutError, 'disconnect': OSError, 'cancel': asyncio.CancelledError}[failure]):
            await task
        assert owner.pending_count == 0
    asyncio.run(scenario())


def test_cancelled_waiter_retains_real_worker(reader, monkeypatch):
    from app.routers import audit
    client, _ = reader
    entered, finish = threading.Event(), threading.Event()
    original = audit._read
    def held(*args):
        entered.set()
        assert finish.wait(3)
        return original(*args)
    monkeypatch.setattr(audit, '_read', held)
    async def scenario():
        async def send(event):
            raise AssertionError('cancelled waiter must not deliver')
        task = asyncio.create_task(app(_scope(client), _receive, send))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert app.state.audit_reads.pending_count == 1
            assert app.state.audit_reads.acquire() is None
        finally:
            finish.set()
        await app.state.audit_reads.drain(2)
        assert app.state.audit_reads.pending_count == 0
    asyncio.run(scenario())
