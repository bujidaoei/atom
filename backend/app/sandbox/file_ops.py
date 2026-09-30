"""Trusted adapter for fixed helper execution; lifecycle owns authorization/locking."""
import json
from pathlib import Path
import time

from .docker_driver import DockerDriver, DriverError, run_bounded
from .file_helper import FileError, validate
from .registry import Attempt

_SOURCE = Path(__file__).with_name("file_helper.py").read_text(encoding="utf-8")


class FileOperations:
    def __init__(self, driver: DockerDriver):
        self.driver = driver

    def execute(self, attempt: Attempt, request: dict, *, timeout_seconds: int = 10) -> dict:
        try:
            validate(request)
            payload = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        except (ValueError, TypeError, RecursionError):
            raise FileError("invalid_operation") from None
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 10:
            raise FileError("invalid_timeout")
        if attempt.state != "ready" or attempt.deadline <= time.time():
            raise FileError("attempt_not_ready")
        state = self.driver.inspect(attempt)
        if state is None or not state.running or state.paused:
            raise FileError("container_not_running")
        status, out, _err = run_bounded(
            [self.driver.executable, "container", "exec", "--interactive", state.id,
             "/usr/local/bin/python3", "-I", "-c", _SOURCE, str(timeout_seconds)],
            input_data=payload, timeout=timeout_seconds + 5, output_limit=12 * 1024 * 1024)
        if status != 0:
            raise DriverError("file_execution_unknown")
        try:
            response = json.loads(out)
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise ValueError
            if response["ok"] and set(response) == {"ok", "result"} and isinstance(response["result"], dict):
                return response["result"]
            if set(response) == {"ok", "error"} and isinstance(response["error"], str) and response["error"] in {
                "invalid_operation", "invalid_path", "file_too_large", "unsafe_file", "file_conflict", "entry_limit",
                "output_limit", "unsupported_platform", "operation_timeout", "input_limit", "file_operation_failed",
            }:
                raise FileError(response["error"])
            raise ValueError
        except (ValueError, TypeError) as error:
            if isinstance(error, FileError):
                raise
            raise DriverError("invalid_file_response") from None
