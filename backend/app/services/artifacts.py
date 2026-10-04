"""Deterministic generation gate. This is not browser acceptance."""

from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class ArtifactValidationError(ValueError):
    """Deterministic generated-file defect eligible for bounded model repair."""


def syntax_diagnostic(path: Path, root: Path, stderr: bytes) -> str:
    output = stderr.decode('utf-8', 'replace')
    location = re.search(re.escape(str(path)) + r':(\d+)', output)
    reason = re.search(r'^SyntaxError:\s*(.+)$', output, re.MULTILINE)
    line = ':' + location[1] if location else ''
    detail = reason[0][:240] if reason else 'JavaScript 语法不完整或无效'
    return f'{path.relative_to(root).as_posix()}{line} 语法校验失败：{detail}'


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "img"} and values.get("src"):
            self.paths.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.paths.append(values["href"])


async def validate_artifacts(workspace: Path) -> None:
    root = workspace.resolve()
    entry = root / "index.html"
    if not entry.is_file() or not entry.stat().st_size:
        raise ArtifactValidationError("生成缺少有效 index.html，不能标记完成")
    parser = Assets()
    parser.feed(entry.read_text("utf-8"))
    for reference in parser.paths:
        url = urlsplit(reference)
        if url.scheme or url.netloc or not url.path:
            continue
        target = (root / unquote(url.path).lstrip("/")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ArtifactValidationError(f"生成引用的本地资源不存在：{reference[:240]}")
    for path in root.rglob("*"):
        if path.suffix not in {".js", ".mjs"} or not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError("JavaScript 文件越出工作区")
        process = await asyncio.create_subprocess_exec(
            "node",
            "--check",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await process.communicate()
            if process.returncode:
                if b'SyntaxError:' not in stderr:
                    raise RuntimeError('JavaScript 校验服务未能完成，请稍后重试')
                raise ArtifactValidationError(syntax_diagnostic(path, root, stderr))
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
