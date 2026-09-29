import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import ContractError, GatewayError
from app.models import Message, Project, ProjectFile, Requirement, Usage, User, UserSettings, utcnow
from app.services.acceptance import static_failures
from app.services.llm import complete
from app.services.parsing import extract_json, normalize_requirements, parse_build
from app.services.prompts import BUILD_SYSTEM, CLASSIFY_SYSTEM, PLAN_SYSTEM, REPAIR_HINT


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


def add_message(db: Session, project: Project, role: str, content: str) -> None:
    text = (content or "").strip()
    if not text:
        return
    db.add(Message(project_id=project.id, role=role, content=text[:4000]))


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


async def _call(db: Session, user: User, project: Project, messages: list[dict], max_tokens: int) -> str:
    assert_quota(db, user)
    base_url, api_key, model = resolve_gateway(db, user)
    text, usage = await complete(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    record_usage(db, user, project, usage)
    return text


def _touch(project: Project, status: str) -> None:
    project.status = status
    project.error_message = ""
    project.updated_at = utcnow()


async def plan_project(db: Session, project: Project, user: User) -> None:
    _touch(project, "planning")
    db.commit()
    text = await _call(
        db,
        user,
        project,
        [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": f"用户想做的产品：\n{project.prompt}"},
        ],
        max_tokens=900,
    )
    try:
        data = extract_json(text)
        requirements = normalize_requirements(data.get("requirements"))
    except ContractError:
        text = await _call(
            db,
            user,
            project,
            [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": f"用户想做的产品：\n{project.prompt}"},
                {"role": "assistant", "content": text[:6000]},
                {"role": "user", "content": "上次的 JSON 不合格。请只返回修正后的 JSON。"},
            ],
            max_tokens=900,
        )
        data = extract_json(text)
        requirements = normalize_requirements(data.get("requirements"))

    project.name = str(data.get("name") or project.name).strip()[:40] or "未命名"
    project.lead_note = str(data.get("lead") or "").strip()[:2000]
    project.research_note = str(data.get("research") or "").strip()[:2000]
    project.architecture_note = str(data.get("architecture") or "").strip()[:2000]
    replace_requirements(db, project, requirements)
    project.contract_locked = False
    project.contract_version = 0
    project.pending_amendment = ""
    add_message(db, project, "mike", project.lead_note)
    add_message(db, project, "iris", project.research_note)
    add_message(db, project, "bob", project.architecture_note)
    add_message(db, project, "emma", _contract_message(requirements))
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
    messages = [
        {"role": "system", "content": BUILD_SYSTEM},
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

    text = await _call(db, user, project, messages, max_tokens=1800)
    built = await _repair_if_needed(db, user, project, text, requirements)
    write_html(db, project, built["html"])
    project.trace_json = json.dumps(built["trace"], ensure_ascii=False)
    project.pending_amendment = ""
    add_message(db, project, "alex", built["notes"] or "页面已经按契约写好，可以预览。")
    _touch(project, "ready")
    db.commit()


async def _repair_if_needed(db: Session, user: User, project: Project, text: str, requirements: list[dict]) -> dict:
    last_error = ""
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
        current = await _call(
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
    verdict_text = await _call(
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
        add_message(db, project, "emma", reason or "这句修改会改掉已锁定的契约，需要你确认修订。")
        project.updated_at = utcnow()
        db.commit()
        return "amend"
    add_message(db, project, "mike", reason or "这处修改还在契约里面，交给工程师。")
    db.commit()
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
