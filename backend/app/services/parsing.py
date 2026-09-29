from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_VALID_CHECK_TYPES = {"exists", "text", "flow"}
_KEY_SAFE = re.compile(r"[^a-z0-9-]+")


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or fences often enough that trusting the raw
    string is not worth it. Tries the whole string, then fenced blocks, then
    the widest brace-balanced span.
    """
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _json_candidates(text: str):
    stripped = text.strip()
    if stripped:
        yield stripped
    for match in _FENCE.finditer(text):
        yield match.group(1).strip()
    start = text.find("{")
    if start == -1:
        return
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                yield text[start : index + 1]
                return


def normalize_plan(text: str, *, fallback_title: str) -> dict[str, Any]:
    data = extract_json_object(text) or {}
    title = str(data.get("title") or "").strip() or fallback_title
    steps: list[dict[str, str]] = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        role = str(step.get("role") or "").strip().lower()
        if role in {"iris", "emma", "bob", "alex"}:
            steps.append({"role": role, "goal": str(step.get("goal") or "").strip()})
    clarification = data.get("clarification")
    return {
        "title": title[:200],
        "summary": str(data.get("summary") or "").strip()[:500] or None,
        "kind": (str(data.get("kind") or "").strip().lower() or None),
        "steps": steps,
        "clarification": (
            str(clarification).strip() if isinstance(clarification, str) and clarification.strip() else None
        ),
    }


def normalize_requirements(text: str) -> list[dict[str, Any]]:
    """Turn Emma's JSON into requirement rows, dropping anything unusable.

    Checks drive the acceptance runner, so a malformed selector is worse than
    a missing requirement; invalid entries are discarded rather than repaired.
    """
    data = extract_json_object(text) or {}
    raw = data.get("requirements")
    if not isinstance(raw, list):
        return []

    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        key = _KEY_SAFE.sub("-", str(item.get("key") or title).strip().lower()).strip("-")
        key = (key or f"req-{index + 1}")[:80]
        if key in seen:
            key = f"{key}-{index + 1}"[:80]
        seen.add(key)

        checks = [c for c in (_normalize_check(c) for c in item.get("checks") or []) if c]
        requirements.append(
            {
                "key": key,
                "title": title[:200],
                "detail": str(item.get("detail") or "").strip()[:1000],
                "checks": checks,
            }
        )
    return requirements[:8]


def _normalize_check(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip().lower()
    if kind not in _VALID_CHECK_TYPES:
        return None
    selector = str(raw.get("selector") or "").strip()
    if not selector:
        return None
    if kind == "exists":
        return {"type": "exists", "selector": selector}
    if kind == "text":
        contains = str(raw.get("contains") or "").strip()
        return {"type": "text", "selector": selector, "contains": contains} if contains else None
    expect = str(raw.get("expect") or "").strip()
    return {"type": "flow", "selector": selector, "expect": expect} if expect else None


def normalize_scope(text: str) -> tuple[list[str], list[str]]:
    data = extract_json_object(text) or {}
    scope = [str(s).strip() for s in (data.get("scope") or []) if str(s).strip()]
    out_of_scope = [str(s).strip() for s in (data.get("outOfScope") or []) if str(s).strip()]
    return scope[:6], out_of_scope[:3]


def fallback_title(prompt: str) -> str:
    condensed = " ".join(prompt.split())
    return (condensed[:28] + "…") if len(condensed) > 29 else (condensed or "未命名项目")
