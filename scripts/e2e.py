"""End-to-end smoke test against a running dev stack.

Drives the real product loop with real model calls: register, create a
project, plan with the squad, approve the contract, let Alex build, then
check that the preview actually serves the generated app.

Usage:  python scripts/e2e.py [base_url]
"""

from __future__ import annotations

import json
import sys
import threading
import time
from queue import Empty, Queue

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
EMAIL = f"e2e-{int(time.time())}@example.com"
PASSWORD = "e2e-passw0rd"
PROMPT = "做一个极简的每日习惯打卡工具，可以添加习惯、勾选今天完成、看到连续天数"

PLAN_TIMEOUT = 600
BUILD_TIMEOUT = 900


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=True)

    health = client.get("/api/health").json()
    step("health", health)
    if not health.get("runtime"):
        return fail("agent runtime sidecar is not reachable")

    user = client.post(
        "/api/auth/register", json={"email": EMAIL, "password": PASSWORD}
    ).json()
    step("registered", {"email": user["email"], "credits": user["credits"]})

    project = client.post("/api/projects", json={"prompt": PROMPT}).json()["project"]
    project_id = project["id"]
    step("project created", {"id": project_id, "status": project["status"]})

    events = EventTap(client, project_id)
    events.start()

    client.post(f"/api/projects/{project_id}/plan").raise_for_status()
    step("plan started", {})
    status = events.wait_for_status({"awaiting_approval", "error", "draft"}, PLAN_TIMEOUT)
    if status != "awaiting_approval":
        return fail(f"planning ended in {status!r}", events)

    detail = client.get(f"/api/projects/{project_id}").json()["project"]
    step(
        "contract ready",
        {
            "title": detail["title"],
            "kind": detail["kind"],
            "roles": sorted({m["role"] for m in detail["messages"]}),
            "requirements": [r["key"] for r in detail["requirements"]],
            "checks": sum(len(r["checks"]) for r in detail["requirements"]),
        },
    )
    if not detail["requirements"]:
        return fail("Emma produced no requirements", events)
    if not any(
        c["type"] == "flow" for r in detail["requirements"] for c in r["checks"]
    ):
        print("  ! warning: contract has no flow check")

    client.post(f"/api/projects/{project_id}/approve", json={}).raise_for_status()
    step("build started", {})
    status = events.wait_for_status({"ready", "error"}, BUILD_TIMEOUT)
    if status != "ready":
        return fail(f"build ended in {status!r}", events)

    detail = client.get(f"/api/projects/{project_id}").json()["project"]
    files = detail["files"]
    step("built", {"files": [f["path"] for f in files]})
    if not any(f["path"] == "index.html" for f in files):
        return fail("no index.html in the workspace", events)

    preview = client.get(f"/preview/{project_id}/")
    step("preview", {"status": preview.status_code, "bytes": len(preview.content)})
    if preview.status_code != 200 or b"<" not in preview.content[:2000]:
        return fail("preview did not serve HTML", events)

    published = client.post(f"/api/projects/{project_id}/publish").json()
    step("published", published)
    live = httpx.get(f"{BASE}{published['url']}/", timeout=30.0)
    step("public url", {"status": live.status_code, "bytes": len(live.content)})
    if live.status_code != 200:
        return fail("published url is not reachable", events)

    usage = client.get("/api/usage").json()
    step(
        "usage",
        {
            "credits": usage["credits"],
            "runs": usage["runs"],
            "inputTokens": usage["inputTokens"],
            "outputTokens": usage["outputTokens"],
        },
    )
    if usage["runs"] < 5:
        return fail(f"expected at least 5 agent turns, saw {usage['runs']}", events)

    events.stop()
    print("\nPASS  full loop works end to end")
    print(f"      project  {BASE}/app/p/{project_id}")
    print(f"      live app {BASE}{published['url']}/")
    return 0


class EventTap:
    """Consumes the SSE stream in a thread and tracks project status."""

    def __init__(self, client: httpx.Client, project_id: str) -> None:
        self._client = client
        self._project_id = project_id
        self._status: Queue[str] = Queue()
        self._log: list[tuple[str, str]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        url = f"{BASE}/api/projects/{self._project_id}/events?after=0"
        try:
            with httpx.stream(
                "GET", url, cookies=self._client.cookies, timeout=httpx.Timeout(None)
            ) as response:
                for line in response.iter_lines():
                    if self._stop.is_set():
                        return
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    self._note(event)
        except httpx.HTTPError:
            return

    def _note(self, event: dict) -> None:
        kind = event["type"]
        role = event.get("role") or ""
        if kind == "squad.role_started":
            print(f"    -> {event['payload'].get('role')} started")
        elif kind == "tool.started":
            print(f"       tool {event['payload'].get('toolName')}")
        elif kind == "run.failed":
            print(f"    !! {role} failed: {event['payload'].get('message')}")
        elif kind == "project.updated":
            new_status = event["payload"].get("status")
            if new_status:
                self._status.put(new_status)
        self._log.append((kind, json.dumps(event["payload"], ensure_ascii=False)[:160]))

    def wait_for_status(self, wanted: set[str], timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = self._status.get(timeout=2.0)
            except Empty:
                continue
            if status in wanted:
                return status
        return "timeout"

    def tail(self, count: int = 25) -> list[tuple[str, str]]:
        return self._log[-count:]


def step(label: str, data: object) -> None:
    print(f"  {label}: {json.dumps(data, ensure_ascii=False)}")


def fail(message: str, events: EventTap | None = None) -> int:
    print(f"\nFAIL  {message}")
    if events:
        print("  last events:")
        for kind, payload in events.tail():
            print(f"    {kind}  {payload}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
