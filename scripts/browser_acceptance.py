"""Chromium regression of the actual TypeScript acceptance engine."""

import json
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / ".logs/acceptance.bundle.js"
BUNDLE.parent.mkdir(exist_ok=True)
subprocess.run(
    [
        "node",
        "--input-type=module",
        "-e",
        "import {build} from 'esbuild'; await build({entryPoints:['../frontend/src/workspace/acceptance.ts'],bundle:true,format:'iife',globalName:'AtomAcceptance',outfile:'../.logs/acceptance.bundle.js'});",
    ],
    cwd=ROOT / "runtime",
    check=True,
)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content("""<iframe></iframe>""")
    frame = page.frames[1]
    frame.set_content("""<label>Name<input id="name" required></label><button id="add" disabled>Add</button><ul id="list"></ul>
    <button id="locked" disabled>Locked</button><script>nameInput=document.querySelector('#name');
    nameInput.addEventListener('input',()=>document.querySelector('#add').disabled=!nameInput.value);
    document.querySelector('#add').onclick=()=>{const li=document.createElement('li');li.textContent=nameInput.value;document.querySelector('#list').append(li);document.querySelector('#add').disabled=true;setTimeout(()=>document.querySelector('#add').disabled=false,150)};
    nameInput.onkeydown=e=>{if(e.key==='Enter')document.querySelector('#add').click()};</script>""")
    page.add_script_tag(path=str(BUNDLE))
    page.locator('iframe').evaluate("el => el.style.display = 'none'")
    checks = [
        {"type": "flow", "selector": "#add", "expect": "li"},
        {
            "type": "flow",
            "setup": [{"action": "fill", "selector": "#name", "value": "Alice"}],
            "selector": "#add",
            "expect": "li",
        },
        {
            "type": "flow",
            "setup": [
                {"action": "fill", "selector": "#name", "value": "Bob"},
                {"action": "press", "selector": "#name", "key": "Enter"},
            ],
            "selector": "#add",
            "expect": "li:nth-child(3)",
        },
        {"type": "flow", "selector": "#add", "expect": "["},
        {
            "type": "flow",
            "setup": [{"action": "fill", "selector": "#missing", "value": "bad"}],
            "selector": "#add",
            "expect": "li",
        },
        {"type": "text", "selector": "li", "contains": "Alice"},
        {"type": "flow", "setup": [{"action": "click", "selector": "#add"}, {"action": "click", "selector": "#add"}], "selector": "#add", "expect": "li:nth-child(6)"},
        {"type": "flow", "setup": [{"action": "click", "selector": "#locked"}], "selector": "#add", "expect": "li"},
    ]
    results = page.evaluate(
        '(checks)=>AtomAcceptance.runAcceptance(document.querySelector("iframe").contentDocument,[{key:"form",checks}])',
        checks,
    )
    assert [r["passed"] for r in results] == [False, True, True, False, False, True, True, False], (
        results
    )
    print(
        json.dumps({"browser": browser.version, "results": results}, ensure_ascii=False)
    )
    browser.close()
