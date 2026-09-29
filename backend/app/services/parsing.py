import json
import re

from app.errors import ContractError


def extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ContractError("模型没有返回可解析的 JSON")
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ContractError("模型返回的 JSON 不完整") from exc
    if not isinstance(data, dict):
        raise ContractError("模型返回的不是一个 JSON 对象")
    return data


def parse_build(text: str) -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```[a-z]*\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    notes_at = re.search(r"(?m)^NOTES\s*$", raw)
    trace_at = re.search(r"(?m)^TRACE\s*$", raw)
    html_at = re.search(r"(?m)^HTML\s*$", raw)
    if not (notes_at and trace_at and html_at):
        raise ContractError("构建结果缺少 NOTES、TRACE 或 HTML 段")
    if not (notes_at.start() < trace_at.start() < html_at.start()):
        raise ContractError("构建结果的三段顺序不对")
    notes = raw[notes_at.end() : trace_at.start()].strip()
    trace_block = raw[trace_at.end() : html_at.start()].strip()
    html = raw[html_at.end() :].strip()
    trace = []
    for line in trace_block.splitlines():
        if "|" not in line:
            continue
        key, evidence = line.split("|", 1)
        key = key.strip()
        evidence = evidence.strip()
        if key:
            trace.append({"key": key[:16], "evidence": evidence[:240]})
    if "<html" not in html.lower() or "</html>" not in html.lower():
        raise ContractError("构建结果里没有完整的 HTML 文档")
    if len(html) > 200_000:
        raise ContractError("生成的页面超过了体积上限")
    return {"notes": notes[:2000], "trace": trace[:12], "html": html}


def normalize_requirements(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ContractError("契约不是列表")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        key = re.sub(r"[^A-Za-z0-9]", "", str(item.get("key") or f"R{len(cleaned) + 1}"))[:8] or f"R{len(cleaned) + 1}"
        base = key
        suffix = 2
        while key in seen:
            key = f"{base[:6]}{suffix}"
            suffix += 1
        seen.add(key)
        priority = item.get("priority") if item.get("priority") in {"must", "should"} else "must"
        checks = _normalize_checks(item.get("checks"))
        if not checks:
            checks = [{"op": "text", "contains": title[:40]}]
        cleaned.append(
            {
                "key": key,
                "title": title[:80],
                "detail": str(item.get("detail") or "").strip()[:400],
                "priority": priority,
                "checks": checks[:6],
            }
        )
        if len(cleaned) == 6:
            break
    if len(cleaned) < 3:
        raise ContractError("契约至少需要 3 条可检查的需求")
    return cleaned


def _normalize_checks(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    checks = []
    for check in raw:
        if not isinstance(check, dict):
            continue
        op = check.get("op")
        if op == "exists":
            selector = str(check.get("selector") or "").strip()
            if re.fullmatch(r"#[A-Za-z][\w-]{0,40}", selector):
                checks.append({"op": "exists", "selector": selector})
        elif op == "text":
            contains = str(check.get("contains") or "").strip()
            if contains:
                checks.append({"op": "text", "contains": contains[:80]})
        elif op == "flow":
            steps = _normalize_steps(check.get("steps"))
            if steps:
                checks.append({"op": "flow", "steps": steps})
    return checks


def _normalize_steps(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    steps = []
    for step in raw:
        if not isinstance(step, dict) or len(steps) >= 6:
            continue
        action = step.get("do")
        if action in {"fill", "click"}:
            selector = str(step.get("selector") or "").strip()
            if not re.fullmatch(r"#[A-Za-z][\w-]{0,40}", selector):
                continue
            entry = {"do": action, "selector": selector}
            if action == "fill":
                entry["value"] = str(step.get("value") or "样本").strip()[:40] or "样本"
            steps.append(entry)
        elif action == "see":
            contains = str(step.get("contains") or "").strip()
            if contains:
                steps.append({"do": "see", "contains": contains[:80]})
    return steps
