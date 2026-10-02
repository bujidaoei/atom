"""Internal verifier transport validation; real service/browser path is integration-tested."""
import asyncio

import httpx
import pytest

from app.verifier_client import VerifierClient, VerifierClientError, VerifierObservation


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        pass


def test_requires_literal_loopback_or_exact_private_service_and_distinct_sized_token():
    private = VerifierClient('http://atom-verifier:8765', 'x' * 48)
    assert private._origin == 'http://atom-verifier:8765'
    asyncio.run(private.close())
    for origin in ('http://localhost:8123', 'http://0.0.0.0:8123',
                   'http://127.0.0.1', 'https://127.0.0.1:8123',
                   'http://127.0.0.1:8123/path',
                   'http://user@127.0.0.1:8123', 'http://127.0.0.1:8123/?x=1',
                   'http://atom-verifier:8766', 'http://atom-verifier.evil:8765',
                   'http://user@atom-verifier:8765',
                   'http://atom-verifier:8765/path',
                   'https://atom-verifier:8765'):
        with pytest.raises(VerifierClientError, match='invalid_verifier_client_configuration'):
            VerifierClient(origin, 'x' * 48)
    with pytest.raises(VerifierClientError, match='invalid_verifier_client_configuration'):
        VerifierClient('http://127.0.0.1:8123', 'short')


@pytest.mark.parametrize('status,body,expected', [
    (200, b'{"requestId":"wrong","revisionId":"rev","outcome":"passed","total":1,"passed":1}',
     'invalid_verifier_response'),
    (200, b'{"requestId":"req","revisionId":"rev","outcome":"passed","total":1,"passed":true}',
     'invalid_verifier_response'),
    (200, b'{"requestId":"req","revisionId":"rev","outcome":"passed","total":1,"passed":0}',
     'invalid_verifier_response'),
    (200, b'{"requestId":"req","requestId":"req","revisionId":"rev","outcome":"passed","total":1,"passed":1}',
     'invalid_verifier_response'),
    (307, b'{"error":"verifier_busy"}', 'verifier_http_error'),
    (503, b'{"error":"verifier_busy"}', 'verifier_busy'),
    (409, b'{"error":"verifier_already_dispatched"}', 'verifier_already_dispatched'),
])
def test_exact_response_classification(status, body, expected):
    async def exercise():
        async with VerifierClient('http://127.0.0.1:8123', 'x' * 48) as client:
            await client._http.aclose()
            client._http = httpx.AsyncClient(base_url='http://127.0.0.1:8123',
                transport=httpx.MockTransport(lambda _request: httpx.Response(status,
                    stream=_Chunks(body), headers={'content-type':'application/json'})),
                trust_env=False, follow_redirects=False)
            with pytest.raises(VerifierClientError, match=expected):
                await client.verify(owner='user', request_id='req')
    asyncio.run(exercise())


def test_valid_envelope_and_transport_loss_is_not_retried():
    calls = []

    async def exercise():
        async with VerifierClient('http://127.0.0.1:8123', 'x' * 48) as client:
            await client._http.aclose()
            def transport(request):
                calls.append(request)
                if len(calls) == 1:
                    return httpx.Response(200, stream=_Chunks(
                        b'{"requestId":"req","revisionId":"rev","outcome":"passed",'
                        b'"total":1,"passed":1}'),
                        headers={'content-type':'application/json'})
                raise httpx.ConnectError('connection lost')
            client._http = httpx.AsyncClient(base_url='http://127.0.0.1:8123',
                transport=httpx.MockTransport(transport), trust_env=False)
            assert await client.verify(owner='user', request_id='req') == VerifierObservation(
                'req','rev','passed',1,1)
            with pytest.raises(VerifierClientError, match='verifier_outcome_unknown'):
                await client.verify(owner='user', request_id='req')
            assert len(calls) == 2
            assert calls[0].headers['authorization'] == 'Bearer ' + 'x' * 48
    asyncio.run(exercise())
