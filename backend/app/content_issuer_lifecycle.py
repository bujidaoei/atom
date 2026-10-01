"""Process-local ownership of admitted console content-access operations."""
import asyncio
import math
from threading import Lock


class ContentIssuerLifecycle:
    def __init__(self, capacity=8):
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise ValueError('invalid_issuer_capacity')
        self._capacity = capacity
        self._lock = Lock()
        self._pending = set()
        self._closing = False

    def start(self):
        with self._lock:
            if self._pending:
                raise RuntimeError('content_issuer_operations_pending')
            self._closing = False

    def acquire(self):
        with self._lock:
            if self._closing or len(self._pending) >= self._capacity:
                return None
            token = object()
            self._pending.add(token)
            return token

    def release(self, token):
        with self._lock:
            self._pending.remove(token)

    def close_admission(self):
        with self._lock:
            self._closing = True

    @property
    def pending_count(self):
        with self._lock:
            return len(self._pending)

    async def drain(self, timeout=15):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not .01 <= timeout <= 60:
            raise ValueError('invalid_issuer_drain_timeout')
        self.close_admission()
        try:
            async with asyncio.timeout(timeout):
                while self.pending_count:
                    await asyncio.sleep(.01)
        except TimeoutError as error:
            raise RuntimeError('content_issuer_drain_timeout') from error
