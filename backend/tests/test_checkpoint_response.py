import asyncio

import pytest

from app.sandbox.service import _SnapshotResponse


@pytest.mark.parametrize('failure', ['none','disconnect','cancel','timeout'])
def test_snapshot_response_keeps_slot_through_delivery_and_releases(failure, monkeypatch):
    if failure == 'timeout':
        monkeypatch.setattr('app.sandbox.service._CHECKPOINT_SEND_SECONDS', 0.02)
    async def scenario():
        lock = asyncio.Lock()
        await lock.acquire()
        response = _SnapshotResponse(b'actual transport bytes', lock=lock, headers={'cache-control':'no-store'})
        messages = []
        async def receive():
            return {'type':'http.disconnect'}
        async def send(message):
            assert lock.locked()
            messages.append(message)
            if message['type'] == 'http.response.body':
                if failure == 'disconnect':
                    raise OSError('test disconnected transport')
                if failure == 'cancel':
                    raise asyncio.CancelledError
                if failure == 'timeout':
                    await asyncio.Event().wait()
        if failure == 'none':
            await response({'type':'http'}, receive, send)
            assert messages[-1]['body'] == b'actual transport bytes'
        else:
            expected = {'disconnect':OSError,'cancel':asyncio.CancelledError,'timeout':TimeoutError}[failure]
            with pytest.raises(expected):
                await response({'type':'http'}, receive, send)
        assert not lock.locked()
        assert messages[0]['status'] == 200
    asyncio.run(scenario())
