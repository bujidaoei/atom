"""Live model/UI workflow check. Uses isolated accounts, no seeded generated files."""

import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5182"
output = Path(sys.argv[2] if len(sys.argv) > 2 else ".logs/workflow002-live.json")
email = f"workflow-{time.time_ns()}@example.com"
password = "Workflow-test-2026"
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    resume = "--resume" in sys.argv
    saved = json.loads(output.read_text(encoding="utf-8")) if resume else []
    if saved:
        email, password = saved[0]["email"], saved[0]["password"]
    response = context.request.post(
        base + ("/api/auth/login" if saved else "/api/auth/register"),
        data={"email": email, "password": password},
    )
    assert response.ok, response.text()
    rows = []
    pages = []
    for name, prompt in [
        (
            "minesweeper",
            "帮我开发一个扫雷小游戏，支持开始、重新开始和插旗，首次点击安全，手机可用。",
        ),
        (
            "match3",
            "帮我开发一个消消乐游戏，支持相邻交换、三消、分数和重开，手机可用。",
        ),
    ]:
        project = (
            next(row["project"] for row in saved if row["name"] == name)
            if saved
            else context.request.post(
                base + "/api/projects", data={"prompt": prompt}
            ).json()["project"]
        )
        page = context.new_page()
        page.goto(base + "/app/p/" + project["id"], wait_until="domcontentloaded")
        pages.append(page)
        rows.append(
            {"name": name, "project": project, "email": email, "password": password}
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # Two real tabs issue the same automatic start command.
    duplicate = context.new_page()
    duplicate.goto(
        base + "/app/p/" + rows[0]["project"]["id"], wait_until="domcontentloaded"
    )

    def detail(i):
        return context.request.get(
            base + "/api/projects/" + rows[i]["project"]["id"], max_retries=2
        ).json()["project"]

    def wait(predicate, seconds=650):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            pages[0].wait_for_timeout(1000)
        raise TimeoutError("live workflow deadline exceeded")

    wait(
        lambda: all(detail(i)["status"] not in ("draft", "planning") for i in range(2))
    )
    for i in range(2):
        d = detail(i)
        assert d["status"] == "awaiting_approval", d["latestRun"]
        assert sum(m["role"] == "mike" for m in d["messages"]) == 1
        assert pages[i].get_by_text("该项目已有任务在运行", exact=True).count() == 0
    duplicate.close()
    print(
        "Two projects planned; duplicate-tab start produced one Mike run.", flush=True
    )
    pages[0].get_by_role("tab", name="契约", exact=True).click()
    pages[0].get_by_role("button", name="开始构建", exact=True).click()
    racepage = pages[1]
    racepage.get_by_role("tab", name="竞速", exact=True).click()
    settings = context.request.get(base + "/api/settings").json()
    models = [m["id"] for m in settings["models"]]
    chosen = [m for m in models if m in ("deepseek-v4.1-flash", "dashscope/qwen3-max")]
    if len(chosen) < 2:
        chosen = models[:2]
    for model in models:
        button = racepage.get_by_role("button", name=model, exact=True)
        if (button.get_attribute("aria-pressed") == "true") != (model in chosen):
            button.click()
    racepage.get_by_label("每个模型时间上限").select_option("360")
    racepage.get_by_role("button", name="开始竞速", exact=True).click()
    print(
        "Minesweeper building; match-three race started with 360-second budget.",
        flush=True,
    )
    pid = rows[1]["project"]["id"]
    wait(lambda: detail(1)["race"] is not None, 30)
    race = detail(1)["race"]
    target = race["heats"][0]

    def has_entry():
        return (
            context.request.get(base + f"/preview/{pid}/race/{target['id']}/").status
            == 200
        )

    wait(has_entry, 150)
    racepage.get_by_role("button", name="停止", exact=True).click()
    wait(lambda: detail(1)["status"] == "cancelled", 20)
    cancelled = detail(1)["race"]
    assert all(h["status"] not in ("running", "queued") for h in cancelled["heats"])
    target = next(h for h in cancelled["heats"] if h["id"] == target["id"])
    if target["status"] == "done":
        target = next(h for h in cancelled["heats"] if h["status"] == "cancelled")
    siblings = [h for h in cancelled["heats"] if h["id"] != target["id"]]
    racepage.reload(wait_until="domcontentloaded")
    racepage.get_by_role("tab", name="竞速", exact=True).click()
    racepage.get_by_label("每个模型时间上限").select_option("360")
    card = racepage.locator("article").filter(
        has=racepage.get_by_text(target["model"], exact=True)
    )
    card.get_by_role("button", name="继续此赛道", exact=True).click()
    print("Race cancelled; continuing only " + target["model"], flush=True)
    wait(lambda: detail(1)["race"]["status"] == "running", 20)
    wait(lambda: detail(1)["race"]["status"] != "running", 380)
    final = detail(1)
    heat = next(h for h in final["race"]["heats"] if h["id"] == target["id"])
    assert heat["status"] == "done", heat
    assert [h for h in final["race"]["heats"] if h["id"] != target["id"]] == siblings
    card.get_by_role("button", name="采用", exact=True).click()
    wait(lambda: detail(1)["status"] == "ready", 20)
    wait(lambda: detail(0)["status"] != "building", 200)
    for i, row in enumerate(rows):
        row["project"] = detail(i)
        assert pages[i].get_by_text("该项目已有任务在运行", exact=True).count() == 0
        pages[i].screenshot(
            path=str(output.with_name(f"{output.stem}-{row['name']}.png")),
            full_page=True,
        )
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "statuses": [r["project"]["status"] for r in rows],
                "duplicatePlanRuns": False,
                "retryHeat": heat["id"],
                "siblingUnchanged": True,
            }
        )
    )
    browser.close()
