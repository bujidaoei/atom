"""Real workspace refresh/resume/cancel smoke; uses isolated test accounts."""

import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5181"
source = Path(sys.argv[2]) if len(sys.argv) > 2 else root / ".logs/live-generation-v2.json"
row = json.loads(source.read_text(encoding="utf-8"))[0]
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    response = context.request.post(
        base + "/api/auth/login",
        data={"email": row["email"], "password": row["password"]},
    )
    assert response.ok, response.text()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    pid = row["project"]["id"]
    page.goto(base + f"/app/p/{pid}")
    detail = context.request.get(base + f"/api/projects/{pid}").json()["project"]
    if detail["status"] != "ready":
        page.get_by_role("button", name="继续生成", exact=True).wait_for()
        page.reload()
        page.get_by_role("button", name="继续生成", exact=True).wait_for()
        assert page.get_by_text("Alex 在跑", exact=True).count() == 0
        page.screenshot(path=str(root / ".logs/workspace-timeout.png"), full_page=True)
        page.get_by_role("button", name="继续生成", exact=True).click()
        page.get_by_role("button", name="停止", exact=True).wait_for()
        page.get_by_role("button", name="停止", exact=True).click()
        page.get_by_role("button", name="继续生成", exact=True).wait_for()
        page.reload()
        page.get_by_role("button", name="继续生成", exact=True).wait_for()
        assert page.get_by_text("Alex 在跑", exact=True).count() == 0
        detail = context.request.get(base + f"/api/projects/{pid}").json()["project"]
        assert detail["status"] == "cancelled" and detail["activeRunId"] is None, (
            detail["status"]
        )
        page.screenshot(
            path=str(root / ".logs/workspace-cancelled.png"), full_page=True
        )
        page.get_by_role("button", name="继续生成", exact=True).click()
        deadline = time.monotonic() + 195
        while time.monotonic() < deadline:
            page.wait_for_timeout(1000)
            detail = context.request.get(base + f"/api/projects/{pid}").json()[
                "project"
            ]
            if detail["status"] not in {"building", "cancelled"}:
                break
        assert detail["status"] == "ready", detail["latestRun"]
    page.reload()
    page.get_by_role("tab", name="契约", exact=True).click()
    page.get_by_role("button", name="运行验收", exact=False).click()
    for _ in range(30):
        page.wait_for_timeout(1000)
        detail = context.request.get(base + f"/api/projects/{pid}").json()["project"]
        if detail["acceptance"]:
            break
    assert (
        detail["acceptance"]
        and detail["acceptance"]["passed"] == detail["acceptance"]["total"]
    ), detail["acceptance"]
    page.screenshot(path=str(root / ".logs/workspace-accepted.png"), full_page=True)
    print(
        json.dumps(
            {
                "status": detail["status"],
                "acceptance": detail["acceptance"],
                "errors": errors,
            },
            ensure_ascii=False,
        )
    )
    assert not errors, errors
    browser.close()
