import pytest

from app.sandbox.file_helper import FileError, validate


@pytest.mark.parametrize("operation", [
    {}, {"op": "exec", "command": "pwd"}, {"op": "read_bytes", "path": "../secret"},
    {"op": "read_bytes", "path": "/etc/passwd"}, {"op": "read_bytes", "path": ".env"},
    {"op": "read_bytes", "path": "src/.git/config"}, {"op": "read_bytes", "path": "CON.txt"},
    {"op": "read_bytes", "path": "a\\b"}, {"op": "read_bytes", "path": "a//b"},
    {"op": "read_bytes", "path": "x", "command": "cat"},
    {"op": "read_lines", "path": "x", "start": True, "limit": 1},
    {"op": "glob", "pattern": "**/*", "limit": 501},
    {"op": "write", "path": "x", "content": False},
    {"op": "write", "path": "x", "content": "a", "expected_sha256": "invalid"},
    {"op": "read_bytes", "path": "COM¹.txt"}, {"op": "read_bytes", "path": "a\u200bb"},
    {"op": "read_bytes", "path": "\ud800"},
])
def test_rejects_untrusted_file_operation_shapes(operation):
    with pytest.raises(FileError):
        validate(operation)


def test_schema_accepts_explicit_operations():
    for request in (
        {"op": "read_bytes", "path": "src/a.txt"},
        {"op": "read_lines", "path": "a", "start": 1, "limit": 2000},
        {"op": "glob", "pattern": "src/**/*.ts", "limit": 200},
        {"op": "grep", "pattern": "x+", "path": ".", "glob": "**/*.txt", "case_sensitive": False, "limit": 200},
        {"op": "write", "path": "a", "content": "hello", "expected_sha256": "a" * 64},
    ):
        assert validate(request) == request
