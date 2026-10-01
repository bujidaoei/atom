"""One bounded HTTPS audit batch; only a matching explicit receiver ack is success."""
import asyncio
from contextlib import suppress
import hashlib
import json
import math
import re

import h11

from .audit_destination import AuditDestinationError, connect_audit_tls
from .audit_repository import _FIELDS


class AuditSendError(RuntimeError):
    def __init__(self, code, *, retryable=True):
        super().__init__(code)
        self.retryable = retryable


def encode_batch(destination, events):
    if not isinstance(events, (tuple, list)) or not 1 <= len(events) <= 100:
        raise AuditSendError('invalid_audit_batch', retryable=False)
    ids = set()
    for event in events:
        if (type(event) is not dict or set(event) != set(_FIELDS) or
                event['scope_kind'] != destination.scope_kind or event['scope_id'] != destination.scope_id or
                not isinstance(event['event_id'], str) or re.fullmatch(r'[0-9a-f]{32}', event['event_id']) is None or
                event['event_id'] in ids or any(value is not None and not (
                    (type(value) is int and 0 <= value < 2**63) or
                    (type(value) is str and len(value) <= 128 and value.isascii() and
                     all(32 <= ord(char) <= 126 for char in value))) for value in event.values())):
            raise AuditSendError('invalid_audit_batch', retryable=False)
        ids.add(event['event_id'])
    body = json.dumps([{key: event[key] for key in _FIELDS} for event in events],
                      ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(body) > 262144:
        raise AuditSendError('audit_batch_capacity', retryable=False)
    return body


async def send_audit_events(destination, events, *, ca_file=None, timeout=15):
    """Receiver must durably deduplicate/store all events before 204 + payload SHA256 ack.

    No redirects, automatic retries, response bodies, cookies, proxy or protocol logging.
    This function never changes the local delivery ledger.
    """
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not .01 <= timeout <= 30:
        raise AuditSendError('invalid_audit_send_timeout', retryable=False)
    body = encode_batch(destination, events)
    digest = hashlib.sha256(body).hexdigest().encode('ascii')
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await connect_audit_tls(destination, ca_file=ca_file)
            protocol = h11.Connection(h11.CLIENT, max_incomplete_event_size=16384)
            request = h11.Request(method='POST', target=destination.path, headers=[
                ('Host', destination.host), ('Authorization', 'Bearer '+destination.token),
                ('Content-Type', 'application/json'), ('Content-Length', str(len(body))),
                ('X-Atom-Audit-Version', '1'), ('X-Atom-Audit-SHA256', digest), ('Connection', 'close')])
            for event in (request, h11.Data(data=body), h11.EndOfMessage()):
                writer.write(protocol.send(event))
            await writer.drain()
            received = informational = 0
            acknowledged = False
            while True:
                event = protocol.next_event()
                if event is h11.NEED_DATA:
                    data = await reader.read(4096)
                    received += len(data)
                    if received > 16384:
                        raise AuditSendError('audit_response_capacity')
                    protocol.receive_data(data)
                elif isinstance(event, h11.InformationalResponse):
                    informational += 1
                    if event.status_code == 101 or informational > 4:
                        raise AuditSendError('invalid_audit_response')
                elif isinstance(event, h11.Response):
                    if event.status_code != 204:
                        raise AuditSendError('audit_receiver_rejected',
                            retryable=event.status_code in (408, 429) or 500 <= event.status_code <= 599)
                    ack = [value for name, value in event.headers if name == b'x-atom-audit-ack']
                    length = [value for name, value in event.headers if name == b'content-length']
                    if (ack != [digest] or length not in ([], [b'0']) or
                            any(name == b'transfer-encoding' for name, _ in event.headers)):
                        raise AuditSendError('invalid_audit_ack')
                    acknowledged = True
                elif isinstance(event, h11.EndOfMessage) and acknowledged:
                    return
                else:
                    raise AuditSendError('invalid_audit_response')
    except (OSError, TimeoutError, h11.ProtocolError, AuditDestinationError):
        raise AuditSendError('audit_transport_unavailable') from None
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
