import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.errors import ContractError, GatewayError
from app.models import Message, Project, ProjectFile, Requirement, Usage, User, UserSettings, utcnow
from app.services.acceptance import static_failures
from app.services.llm import complete
from app.services.parsing import extract_json, normalize_requirements, parse_build
from app.services.prompts import (
    ALEX_SYSTEM,
    BOB_SYSTEM,
    BUILD_SYSTEM,
    CLASSIFY_SYSTEM,
    IRIS_SYSTEM,
    MIKE_SYSTEM,
    PLAN_SYSTEM,
    REPAIR_HINT,
)

TOOL_TITLES = {
    "read_contract": "读取契约",
    "write_page": "编写代码",
    "check_page": "检查页面",
}


def resolve_gateway(db: Session, user: User) -> tuple[str, str, str]:
    row = db.get(UserSettings, user.id)
    base_url = ((row.base_url if row else "") or settings.llm_base_url).strip()
    api_key = ((row.api_key if row else "") or settings.llm_api_key).strip()
    model = ((row.model if row else "") or settings.llm_model).strip()
    if not base_url.startswith("https://"):
        raise GatewayError("模型地址需要以 https:// 开头。")
    if not api_key:
        raise GatewayError("还没有可用的 API Key。请到设置里填写，或由部署方配置服务器默认密钥。")
    if not model:
        raise GatewayError("还没有选择模型。")
    lowered = model.lower()
    if any(token in lowered for token in ("image", "seedream", "embedding", "nano-banana")):
        raise GatewayError("这个模型不能写页面。请在输入框旁换成 qwen3.7-plus 这类文本模型。")
    return base_url, api_key, model


def assert_quota(db: Session, user: User) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = db.scalar(
        select(func.count()).select_from(Usage).where(Usage.user_id == user.id, Usage.created_at >= since)
    )
    if count is not None and count >= settings.daily_call_limit:
        raise GatewayError("这个账号今天的模型调用已到上限，明天会恢复。")


def record_usage(db: Session, user: User, project: Project, usage: dict) -> None:
    db.add(
        Usage(
            user_id=user.id,
            project_id=project.id,
            model=str(usage.get("model") or ""),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
    )


def add_message(db: Session, project: Project, role: str, content: str, activity: list | None = None) -> Message | None:
    text = (content or "").strip()
    if not text:
        return None
    row = Message(
        project_id=project.id,
        role=role,
        content=text[:4000],
        activity_json=json.dumps(activity or [], ensure_ascii=False),
    )
    db.add(row)
    return row


def _load_steps(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def begin_turn(db: Session, project: Project, role: str, opening: str, title: str) -> Message:
    row = Message(
        project_id=project.id,
        role=role,
        content=opening[:4000],
        activity_json=json.dumps(
            [{"kind": "narration", "title": title, "detail": "", "status": "run"}],
            ensure_ascii=False,
        ),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_turn(db: Session, row: Message, content: str, extra: list | None = None) -> None:
    db.refresh(row)
    steps = _load_steps(row.activity_json)
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "run":
            step["status"] = "done"
    steps.extend(extra or [])
    row.content = (content or row.content or "").strip()[:4000]
    row.activity_json = json.dumps(steps, ensure_ascii=False)
    db.commit()


def watch_turn(message_id: str, *, show_text: bool = True):
    state = {"at": 0.0}

    def on_event(event: dict) -> None:
        kind = event.get("event")
        now = time.monotonic()
        if kind in {"text", "thinking"} and now - state["at"] < 0.35:
            return
        state["at"] = now
        with SessionLocal() as side:
            row = side.get(Message, message_id)
            if row is None:
                return
            steps = _load_steps(row.activity_json)
            if kind == "text" and show_text:
                row.content = str(event.get("text") or "")[:4000]
            elif kind == "thinking":
                thought = str(event.get("text") or "")[:500]
                if steps and steps[-1].get("kind") == "thinking":
                    steps[-1]["detail"] = thought
                else:
                    steps.append({"kind": "thinking", "title": "推理", "detail": thought, "status": "run"})
                row.activity_json = json.dumps(steps, ensure_ascii=False)
            elif kind == "tool":
                name = str(event.get("name") or "tool")
                steps.append(
                    {
                        "kind": "tool",
                        "title": TOOL_TITLES.get(name, name),
                        "detail": str(event.get("detail") or "")[:240],
                        "status": "done" if event.get("status") != "start" else "run",
                    }
                )
                row.activity_json = json.dumps(steps, ensure_ascii=False)
            side.commit()

    return on_event


def replace_requirements(db: Session, project: Project, requirements: list[dict]) -> None:
    db.execute(delete(Requirement).where(Requirement.project_id == project.id))
    db.flush()
    for index, item in enumerate(requirements):
        db.add(
            Requirement(
                project_id=project.id,
                position=index,
                key=item["key"],
                title=item["title"],
                detail=item["detail"],
                priority=item["priority"],
                checks_json=json.dumps(item["checks"], ensure_ascii=False),
            )
        )


def requirement_payload(db: Session, project: Project) -> list[dict]:
    rows = db.scalars(
        select(Requirement).where(Requirement.project_id == project.id).order_by(Requirement.position)
    ).all()
    return [
        {
            "key": row.key,
            "title": row.title,
            "detail": row.detail,
            "priority": row.priority,
            "checks": row.checks,
        }
        for row in rows
    ]


def write_html(db: Session, project: Project, html: str) -> None:
    current = db.scalar(
        select(ProjectFile).where(ProjectFile.project_id == project.id, ProjectFile.path == "index.html")
    )
    if current is None:
        db.add(ProjectFile(project_id=project.id, path="index.html", content=html, updated_at=utcnow()))
    else:
        current.content = html
        current.updated_at = utcnow()


def read_html(db: Session, project: Project) -> str:
    current = db.scalar(
        select(ProjectFile).where(ProjectFile.project_id == project.id, ProjectFile.path == "index.html")
    )
    return current.content if current else ""


async def _call(
    db: Session,
    user: User,
    project: Project,
    messages: list[dict],
    max_tokens: int,
    on_event=None,
    extra: dict | None = None,
    timeout: int = 58,
) -> tuple[str, dict]:
    assert_quota(db, user)
    base_url, api_key, model = resolve_gateway(db, user)
    text, usage = await complete(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        on_event=on_event,
        extra=extra,
        timeout=timeout,
    )
    record_usage(db, user, project, usage)
    return text, usage


def _touch(project: Project, status: str) -> None:
    project.status = status
    project.error_message = ""
    project.updated_at = utcnow()


async def _speak(db: Session, user: User, project: Project, role: str, system: str, user_text: str, title: str, handoff: str) -> str:
    row = begin_turn(db, project, role, "正在接过上一手。", title)
    text, _usage = await _call(
        db,
        user,
        project,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        max_tokens=500,
        on_event=watch_turn(row.id),
    )
    finish_turn(
        db,
        row,
        text,
        [{"kind": "narration", "title": handoff, "detail": "", "status": "done"}],
    )
    return text


async def plan_project(db: Session, project: Project, user: User) -> None:
    _touch(project, "planning")
    add_message(db, project, "system", "Pi agent 0.87.1 开始这一轮。下面每一步都会单独出现。")
    db.commit()
    idea = project.prompt
    mike = await _speak(
        db,
        user,
        project,
        "mike",
        MIKE_SYSTEM,
        f"用户想做的产品：\n{idea}",
        "读取这条需求",
        "把简报交给 @Iris、@Bob、@Emma",
    )
    iris = await _speak(
        db,
        user,
        project,
        "iris",
        IRIS_SYSTEM,
        f"用户想做的产品：\n{idea}\n\nMike 的简报：\n{mike}",
        "根据简报判断使用者和风险",
        "把研究交给 @Bob",
    )
    bob = await _speak(
        db,
        user,
        project,
        "bob",
        BOB_SYSTEM,
        f"用户想做的产品：\n{idea}\n\nIris 的研究：\n{iris}",
        "确定要记住的数据",
        "把结构交给 @Emma，并通知 @Alex 等批准",
    )
    emma = begin_turn(db, project, "emma", "正在把需求写成可检查的契约。", "对照前面的交接写检查项")
    text, _usage = await _call(
        db,
        user,
        project,
        [
            {"role": "system", "content": PLAN_SYSTEM},
            {
                "role": "user",
                "content": f"用户想做的产品：\n{idea}\n\nMike：\n{mike}\n\nIris：\n{iris}\n\nBob：\n{bob}",
            },
        ],
        max_tokens=900,
        on_event=watch_turn(emma.id, show_text=False),
    )
    try:
        data = extract_json(text)
        requirements = normalize_requirements(data.get("requirements"))
    except ContractError:
        text, _usage = await _call(
            db,
            user,
            project,
            [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": f"用户想做的产品：\n{idea}"},
                {"role": "assistant", "content": text[:6000]},
                {"role": "user", "content": "上次的 JSON 不合格。请只返回修正后的 JSON。"},
            ],
            max_tokens=900,
        )
        data = extract_json(text)
        requirements = normalize_requirements(data.get("requirements"))

    project.name = str(data.get("name") or project.name).strip()[:40] or "未命名"
    project.lead_note = mike.strip()[:2000]
    project.research_note = iris.strip()[:2000]
    project.architecture_note = bob.strip()[:2000]
    replace_requirements(db, project, requirements)
    project.contract_locked = False
    project.contract_version = 0
    project.pending_amendment = ""
    finish_turn(
        db,
        emma,
        _contract_message(requirements) + "\n@Alex 等用户批准后再写页面。",
        [{"kind": "narration", "title": "契约已摆出来，等你批准", "detail": "", "status": "done"}],
    )
    _touch(project, "awaiting_approval")
    db.commit()


def _contract_message(requirements: list[dict]) -> str:
    lines = ["第一版契约："]
    for item in requirements:
        mark = "必须" if item["priority"] == "must" else "可以稍后"
        lines.append(f"{item['key']} {item['title']}（{mark}）")
    lines.append("确认后我会锁定它，工程师再按这个写页面。")
    return "\n".join(lines)


async def build_project(db: Session, project: Project, user: User, instruction: str = "") -> None:
    requirements = requirement_payload(db, project)
    if len(requirements) < 3:
        raise ContractError("还没有可构建的契约。")
    _touch(project, "building")
    project.contract_locked = True
    if project.contract_version < 1:
        project.contract_version = 1
    db.commit()

    brief = {
        "idea": project.prompt,
        "architecture": project.architecture_note,
        "requirements": requirements,
    }
    alex = begin_turn(db, project, "alex", "我接过交接，先读契约。", "读取契约")
    messages = [
        {"role": "system", "content": ALEX_SYSTEM},
        {"role": "user", "content": json.dumps(brief, ensure_ascii=False)},
    ]
    if instruction.strip():
        messages.append(
            {
                "role": "user",
                "content": "在不推翻契约的前提下，按这句修改现有页面：\n"
                + instruction.strip()
                + "\n\n当前 HTML：\n"
                + read_html(db, project)[:120000],
            }
        )

    text, usage = await _call(
        db,
        user,
        project,
        messages,
        max_tokens=1800,
        on_event=watch_turn(alex.id),
        extra={"mode": "build", "requirements": requirements},
        timeout=120,
    )
    built = _built_from_tools(text, usage) 
    if built is None or static_failures(built["html"], requirements):
        problem = "" if built is None else "；".join(static_failures(built["html"], requirements))
        seed = text if built is None else _as_build_text(built)
        if problem:
            finish_turn(
                db,
                alex,
                alex.content,
                [{"kind": "narration", "title": "检查没过，再写一版", "detail": problem[:240], "status": "run"}],
            )
            db.refresh(alex)
        built = await _repair_if_needed(db, user, project, seed, requirements, problem)
    write_html(db, project, built["html"])
    project.trace_json = json.dumps(built["trace"], ensure_ascii=False)
    project.pending_amendment = ""
    finish_turn(
        db,
        alex,
        built["notes"] or "页面已经按契约写好，可以预览。",
        [{"kind": "narration", "title": f"版本 {project.contract_version}：{project.name}", "detail": "可以预览", "status": "done"}],
    )
    _touch(project, "ready")
    db.commit()


def _built_from_tools(text: str, usage: dict) -> dict | None:
    html = str(usage.get("html") or "").strip()
    if "<html" not in html.lower() or "</html>" not in html.lower():
        return None
    trace = []
    for line in str(usage.get("trace") or "").splitlines():
        if "|" not in line:
            continue
        key, evidence = line.split("|", 1)
        if key.strip():
            trace.append({"key": key.strip()[:16], "evidence": evidence.strip()[:240]})
    notes = str(usage.get("notes") or text or "页面已经按契约写好，可以预览。").strip()
    return {"html": html, "notes": notes[:2000], "trace": trace[:12]}


def _as_build_text(built: dict) -> str:
    lines = ["NOTES", built.get("notes") or "", "", "TRACE"]
    for item in built.get("trace") or []:
        lines.append(f"{item.get('key', '')} | {item.get('evidence', '')}")
    lines.extend(["", "HTML", built.get("html") or ""])
    return "\n".join(lines)


async def _repair_if_needed(
    db: Session,
    user: User,
    project: Project,
    text: str,
    requirements: list[dict],
    known_error: str = "",
) -> dict:
    last_error = known_error
    current = text
    for attempt in range(2):
        try:
            built = parse_build(current)
        except ContractError as exc:
            last_error = str(exc)
            built = None
        else:
            failures = static_failures(built["html"], requirements)
            if not failures:
                return built
            last_error = "；".join(failures)
        if attempt == 1:
            break
        current, _usage = await _call(
            db,
            user,
            project,
            [
                {"role": "system", "content": BUILD_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({"requirements": requirements, "problem": last_error}, ensure_ascii=False),
                },
                {"role": "assistant", "content": current[:20000]},
                {"role": "user", "content": REPAIR_HINT},
            ],
            max_tokens=1800,
        )
    if built is None:
        raise ContractError(last_error or "页面没有生成完整")
    return built


async def revise_project(db: Session, project: Project, user: User, instruction: str) -> str:
    text = instruction.strip()
    if not text:
        raise ContractError("请先写想改的地方。")
    add_message(db, project, "user", text)
    if not project.contract_locked:
        raise ContractError("契约还没锁定。先确认契约，再提修改。")
    requirements = requirement_payload(db, project)
    reviewer = begin_turn(db, project, "mike", "正在看这句修改还在不在契约里。", "判断修改范围")
    verdict_text, _usage = await _call(
        db,
        user,
        project,
        [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {"requirements": requirements, "instruction": text},
                    ensure_ascii=False,
                ),
            },
        ],
        max_tokens=900,
    )
    verdict = extract_json(verdict_text)
    kind = verdict.get("kind")
    reason = str(verdict.get("reason") or "").strip()[:500]
    if kind == "amend":
        proposed = normalize_requirements(verdict.get("requirements"))
        project.pending_amendment = json.dumps(
            {"reason": reason, "requirements": proposed},
            ensure_ascii=False,
        )
        finish_turn(db, reviewer, reason or "这句修改会改掉已锁定的契约。", [{"kind": "narration", "title": "交给 @Emma 确认修订", "detail": "", "status": "done"}])
        add_message(db, project, "emma", reason or "这句修改会改掉已锁定的契约，需要你确认修订。")
        project.updated_at = utcnow()
        db.commit()
        return "amend"
    finish_turn(
        db,
        reviewer,
        reason or "这处修改还在契约里面，交给工程师。",
        [{"kind": "narration", "title": "交给 @Alex", "detail": "", "status": "done"}],
    )
    await build_project(db, project, user, instruction=text)
    return "built"


async def apply_amendment(db: Session, project: Project, user: User) -> None:
    if not project.pending_amendment:
        raise ContractError("没有待确认的契约修订。")
    payload = json.loads(project.pending_amendment)
    requirements = normalize_requirements(payload.get("requirements"))
    replace_requirements(db, project, requirements)
    project.contract_version += 1
    project.pending_amendment = ""
    add_message(db, project, "emma", f"契约已修订为 v{project.contract_version}。")
    db.commit()
    db.refresh(project)
    await build_project(db, project, user)
