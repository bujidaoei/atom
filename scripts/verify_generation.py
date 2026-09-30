"""Live-provider verification. Writes actual outcomes, never synthetic completion."""

import concurrent.futures
import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
OUTPUT = Path(sys.argv[2] if len(sys.argv) > 2 else ".logs/live-generation.json")
PROMPTS = {
    "calculator": "做一个简洁计算器，支持四则运算、清空和除零提示，可以点击按钮和键盘操作。",
    "lottery": "做一个网页抽签工具，可以输入姓名加入名单，从名单随机抽取一个人，不重复中奖，可以重置。初始名单为空。",
    "snake": "做一个贪吃蛇网页小游戏，可以开始、暂停、重新开始，用方向键控制，显示分数。",
}


def verify(name, prompt):
    with httpx.Client(base_url=BASE, timeout=30) as client:
        email = f"acceptance-{name}-{time.time_ns()}@example.com"
        password = "Acceptance-test-2026"
        client.post(
            "/api/auth/register", json={"email": email, "password": password}
        ).raise_for_status()
        project = client.post("/api/projects", json={"prompt": prompt}).json()[
            "project"
        ]
        pid = project["id"]
        started = time.monotonic()

        def wait():
            while time.monotonic() - started < 700:
                time.sleep(2)
                detail = client.get(f"/api/projects/{pid}").json()["project"]
                if detail["status"] not in {"draft", "planning", "building"}:
                    return detail
            raise TimeoutError("scenario exceeded 700 seconds")

        client.post(f"/api/projects/{pid}/plan").raise_for_status()
        project = wait()
        planned = time.monotonic() - started
        if project["status"] == "awaiting_approval":
            client.post(f"/api/projects/{pid}/approve", json={}).raise_for_status()
            # Start API response precedes task entry: poll past the old state.
            time.sleep(0.5)
            project = wait()
        result = {
            "name": name,
            "project": project,
            "planningSeconds": round(planned, 2),
            "buildSeconds": round(time.monotonic() - started - planned, 2),
            "email": email,
            "password": password,
        }
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in {"project", "password"}},
                ensure_ascii=False,
            ),
            project["status"],
            flush=True,
        )
        return result


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda item: verify(*item), PROMPTS.items()))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
