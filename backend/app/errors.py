from __future__ import annotations


class AtomError(Exception):
    """Base for errors that map onto a specific HTTP status."""

    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RuntimeUnavailable(AtomError):
    status_code = 502


class OutOfCredits(AtomError):
    status_code = 402


class ConflictError(AtomError):
    status_code = 409


class ContractError(AtomError):
    """The squad produced output we could not turn into a usable contract."""

    status_code = 422
