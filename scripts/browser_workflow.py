"""Real React UI with controlled API/stream faults; not a live-generation test."""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5182"
root = Path(__file__).resolve().parents[1]


def project(pid, status):
    return dict(
        id=pid,
        title=f"Project {pid}",
        summary=None,
        kind=None,
        status=status,
        slug=None,
        publishedAt=None,
        createdAt="2026-09-30T00:00:00Z",
        updatedAt="2026-09-30T00:00:00Z",
        prompt=f"Prompt {pid}",
        messages=[],
        requirements=[],
        files=[],
        acceptance=None,
        activeRunId=None,
        latestRun=None,
        buildBudgetSeconds=180,
        race=None,
    )


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    external_fonts = []
    # A hanging third-party stylesheet must never be needed to mount the app.
    def hold_external_font(route):
        external_fonts.append(route.request.url)

    page.route("https://fonts.googleapis.com/**", hold_external_font)
    page.route("https://fonts.gstatic.com/**", hold_external_font)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("""window.sources=[]; window.EventSource=class {
      constructor(url){this.url=url;this.events={};window.sources.push(this);setTimeout(()=>this.emit('open',{}),20)}
      addEventListener(name,cb){this.events[name]=cb} close(){this.closed=true}
      emit(name,value){this.events[name]?.(name==='open'?{}:{data:JSON.stringify(value)})}
    };""")
    states = {
        "A": project("A", "draft"),
        "B": project("B", "ready"),
        "C": project("C", "draft"),
    }
    delayed = []
    hold = {"A": True, "B": False}
    posts = []

    def route(r):
        path = r.request.url.split("/api/", 1)[1].split("?")[0]

        def reply(data, status=200):
            r.fulfill(status=status, json=data)

        if path == "auth/me":
            return reply(
                dict(id="u", email="test@example.com", name="Tester", credits=200)
            )
        if path == "settings":
            return reply(dict(models=[{"id": "fast"}, {"id": "slow"}], model="fast"))
        if path == "projects":
            return reply({"projects": list(states.values())})
        parts = path.split("/")
        pid = parts[1]
        if len(parts) == 2:
            if hold.get(pid):
                delayed.append((r, dict(states[pid])))
                return
            return reply({"project": states[pid]})
        if parts[2] == "plan":
            posts.append((pid, r.request.headers.get("idempotency-key")))
            if pid == "C":
                return reply({"detail": "controlled conflict"}, 409)
            states[pid]["status"] = "planning"
            if sum(x[0] == pid for x in posts) == 1:
                return r.abort("failed")
            return reply({"runId": "one-operation"})
        if parts[2] == "race":
            return reply({"race": None})
        raise AssertionError(path)

    page.route("**/api/**", route)
    page.goto(base + "/app/p/A", wait_until="domcontentloaded")
    assert not external_fonts, external_fonts
    page.get_by_role("link", name="Project B").click()
    page.get_by_role("heading", name="Project B", exact=True).wait_for()
    for r, snapshot in delayed:
        r.fulfill(json={"project": snapshot})
    delayed.clear()
    hold["A"] = False
    page.wait_for_timeout(200)
    assert page.get_by_role("heading", name="Project B", exact=True).count() == 1
    assert not posts
    page.get_by_role("link", name="Project A").click()
    page.wait_for_function("document.body.innerText.includes('规划中')")
    assert len(posts) == 2 and posts[0] == posts[1] == ("A", "initial-plan:A"), posts
    page.get_by_role("link", name="Project C").click()
    page.get_by_text("controlled conflict", exact=True).wait_for()
    page.get_by_role("link", name="Project B").click()
    page.get_by_role("heading", name="Project B", exact=True).wait_for()
    assert page.get_by_text("controlled conflict", exact=True).count() == 0
    # Deliver a late event from the closed C stream. It must not advance B's cursor/state.
    page.evaluate(
        "window.sources.find(s=>s.url.includes('/C/')).emit('run',{seq:999,type:'message.delta',role:'alex',payload:{delta:'LATE-C'},at:''})"
    )
    page.wait_for_timeout(100)
    assert "LATE-C" not in page.locator("body").inner_text()
    # Older same-project snapshot must not overwrite the newer request result.
    hold["B"] = True
    page.evaluate(
        "window.sources.at(-1).emit('run',{seq:1,type:'project.updated',payload:{},at:''})"
    )
    page.wait_for_timeout(100)
    hold["B"] = False
    page.evaluate(
        "window.sources.at(-1).emit('run',{seq:2,type:'project.updated',payload:{},at:''})"
    )
    page.wait_for_timeout(150)
    for r, snapshot in delayed:
        snapshot["status"] = "draft"
        r.fulfill(json={"project": snapshot})
    page.wait_for_timeout(200)
    assert all(pid != "B" for pid, _ in posts)
    assert page.get_by_text("已生成", exact=True).count() == 1
    states["B"]["messages"] = [
        dict(
            id="contract-message",
            role="emma",
            content="可读契约摘要",
            runId="contract-run",
            createdAt="2026-09-30T00:00:00Z",
        )
    ]
    page.evaluate(
        "window.sources.at(-1).emit('run',{seq:3,type:'project.updated',payload:{},at:''})"
    )
    page.get_by_text("可读契约摘要", exact=True).wait_for()
    page.evaluate(
        "window.sources.at(-1).emit('run',{seq:4,runId:'contract-run',role:'emma',type:'message.completed',payload:{text:'RAW_CONTRACT_JSON'},at:''})"
    )
    page.wait_for_timeout(100)
    assert page.get_by_text("可读契约摘要", exact=True).count() == 1
    assert "RAW_CONTRACT_JSON" not in page.locator("body").inner_text()
    assert not errors, errors
    page.screenshot(path=str(root / ".logs/workflow002-navigation.png"), full_page=True)
    print(
        json.dumps(
            {
                "crossProjectIsolation": True,
                "lostResponseSameKey": True,
                "lateStreamIgnored": True,
                "staleSnapshotIgnored": True,
                "errors": errors,
            }
        )
    )
    browser.close()
