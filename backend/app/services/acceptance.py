import json
import re
from html.parser import HTMLParser


class _Dom(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.text_parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        for key, value in attrs:
            if key == "id" and value:
                self.ids.add(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts))


def parse_dom(html: str) -> _Dom:
    dom = _Dom()
    dom.feed(html or "")
    return dom


def _static_check(dom: _Dom, check: dict) -> dict | None:
    op = check.get("op")
    if op == "exists":
        selector = str(check.get("selector") or "")
        ok = selector.startswith("#") and selector[1:] in dom.ids
        return {
            "op": "exists",
            "ok": ok,
            "detail": f"{selector} 在页面里" if ok else f"页面里没有 {selector}",
        }
    if op == "text":
        needle = str(check.get("contains") or "")
        ok = bool(needle) and needle in dom.text
        return {
            "op": "text",
            "ok": ok,
            "detail": f"页面写了「{needle}」" if ok else f"页面上没有「{needle}」",
        }
    return None


def evaluate_static(html: str, requirements: list[dict]) -> list[dict]:
    """Check selectors and visible text. Flow checks are left for the browser."""
    dom = parse_dom(html)
    items = []
    for requirement in requirements:
        checks = []
        for index, check in enumerate(requirement.get("checks") or []):
            result = _static_check(dom, check)
            if result is None:
                continue
            result["index"] = index
            checks.append(result)
        items.append(
            {
                "key": requirement["key"],
                "title": requirement["title"],
                "priority": requirement.get("priority", "must"),
                "checks": checks,
            }
        )
    return items


def static_failures(html: str, requirements: list[dict]) -> list[str]:
    lines = []
    for item in evaluate_static(html, requirements):
        if item["priority"] != "must":
            continue
        for check in item["checks"]:
            if not check["ok"]:
                lines.append(f"{item['key']} {check['detail']}")
    return lines


def merge_acceptance(static_items: list[dict], runtime: list[dict], requirements: list[dict]) -> dict:
    runtime_map = {}
    for row in runtime:
        if not isinstance(row, dict):
            continue
        runtime_map[(str(row.get("key")), int(row.get("index", -1)))] = row

    items = []
    for requirement, static_item in zip(requirements, static_items, strict=True):
        checks = list(static_item["checks"])
        for index, check in enumerate(requirement.get("checks") or []):
            if check.get("op") != "flow":
                continue
            reported = runtime_map.get((requirement["key"], index))
            if reported is None:
                checks.append(
                    {
                        "index": index,
                        "op": "flow",
                        "ok": False,
                        "detail": "浏览器没有返回这次操作的结果",
                    }
                )
            else:
                checks.append(
                    {
                        "index": index,
                        "op": "flow",
                        "ok": bool(reported.get("ok")),
                        "detail": str(reported.get("detail") or "")[:200],
                    }
                )
        ok = all(check["ok"] for check in checks) if checks else False
        items.append(
            {
                "key": requirement["key"],
                "title": requirement["title"],
                "priority": requirement.get("priority", "must"),
                "ok": ok,
                "checks": checks,
            }
        )
    counted = [item for item in items if item["priority"] == "must"] or items
    passed = sum(1 for item in counted if item["ok"])
    return {"passed": passed, "total": len(counted), "items": items}


def loads_json(raw: str, fallback):
    try:
        return json.loads(raw) if raw else fallback
    except json.JSONDecodeError:
        return fallback
