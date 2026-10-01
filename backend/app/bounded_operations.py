"""Process-local bounded ownership through worker completion and response delivery."""
import asyncio
import math
from threading import Lock
from starlette.responses import JSONResponse


class BoundedOperations:
    def __init__(self, capacity=8, send_timeout=10):
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise ValueError('invalid_operation_capacity')
        if type(send_timeout) not in (int, float) or not math.isfinite(send_timeout) or not .01 <= send_timeout <= 60:
            raise ValueError('invalid_operation_send_timeout')
        self.send_timeout = send_timeout
        self._capacity = capacity
        self._lock = Lock()
        self._pending = set()
        self._closing = False

    def start(self):
        with self._lock:
            if self._pending:
                raise RuntimeError('bounded_operations_pending')
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
            raise ValueError('invalid_operation_drain_timeout')
        self.close_admission()
        try:
            async with asyncio.timeout(timeout):
                while self.pending_count:
                    await asyncio.sleep(.01)
        except TimeoutError as error:
            raise RuntimeError('bounded_drain_timeout') from error


class OwnedJSONResponse(JSONResponse):
    def __init__(self, content, lifecycle, token, status_code=200, headers=None):
        super().__init__(content, status_code=status_code, headers=headers)
        self._lifecycle = lifecycle
        self._token = token

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(self._lifecycle.send_timeout):
                await super().__call__(scope, receive, send)
        finally:
            self._lifecycle.release(self._token)
