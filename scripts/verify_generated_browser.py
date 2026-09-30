"""Run stored contracts in Chromium against real generated applications."""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
source = Path(sys.argv[2] if len(sys.argv) > 2 else ".logs/live-generation.json")
rows = json.loads(source.read_text(encoding="utf-8"))
out = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for row in rows:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        response = context.request.post(
            base + "/api/auth/login",
            data={"email": row["email"], "password": row["password"]},
        )
        assert response.ok, response.text()
        pid = row["project"]["id"]
        detail = context.request.get(f"{base}/api/projects/{pid}").json()["project"]
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(f"{base}/preview/{pid}/")
        result = {
            "name": row["name"],
            "id": pid,
            "status": detail["status"],
            "http": response.status,
            "errors": errors,
        }
        if response.ok:
            page.add_script_tag(path=str(root / ".logs/acceptance.bundle.js"))
            checks = page.evaluate(
                "(requirements)=>AtomAcceptance.runAcceptance(document,requirements)",
                detail["requirements"],
            )
            result.update(
                checks=checks,
                passed=sum(x["passed"] for x in checks),
                total=len(checks),
            )
            page.screenshot(
                path=str(root / f".logs/{row['name']}-desktop.png"), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            result["mobileOverflow"] = page.evaluate(
                "document.documentElement.scrollWidth>innerWidth"
            )
            page.screenshot(
                path=str(root / f".logs/{row['name']}-mobile.png"), full_page=True
            )
        out.append(result)
        context.close()
    browser.close()
target = source.with_name(source.stem + "-browser.json")
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
