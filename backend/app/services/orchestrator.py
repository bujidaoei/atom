from __future__ import annotations

import asyncio
import json
import time
from contextlib import aclosing
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import storage
from ..config import get_settings
from ..db import session_scope
from ..errors import ConflictError, OutOfCredits
from ..execution_service import ExecutionResources
from ..revision_view import materialized_revision, committed_catalog
from ..events import bus
from ..models import (
    Message,
    Project,
    Race,
    RaceHeat,
    Requirement,
    Run,
    User,
    UserSettings,
    new_id,
)
from . import credits, parsing
from .artifacts import validate_artifacts
from .runtime_client import GatewayConfig, RuntimeClient, runtime_client
from .provider_connection import resolve_provider

# Roles that reason without touching the workspace, in the order Mike's plan
# normally arranges them. Alex always runs last and separately, because the
# user approves the contract before any code is written.
PLANNING_ORDER = ("iris", "emma", "bob")

ROLE_TITLES = {
    "mike": "Team Leader",
    "iris": "Deep Researcher",
    "emma": "Product Manager",
    "bob": "Architect",
    "alex": "Engineer",
}


@dataclass
class TurnOutcome:
    text: str
    input_tokens: int
    output_tokens: int
    failed: bool
    error: str | None = None
    status: str = "done"


class Orchestrator:
    """Drives the squad. One project runs at most one job at a time."""

    def __init__(self, client: RuntimeClient | None = None) -> None:
        self._client = client or runtime_client
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._stopping: set[str] = set()
        self.execution: ExecutionResources | None = None

    # ---------------------------------------------------------------- public

    def active(self, project_id: str) -> bool:
        task = self._jobs.get(project_id)
        return project_id in self._stopping or task is not None and not task.done()

    async def start_plan(self, project_id: str, user_id: str) -> str:
        return self._spawn(
            project_id, self._plan(project_id, user_id), status="planning"
        )

    async def start_build(self, project_id: str, user_id: str, note: str | None) -> str:
        return self._spawn(
            project_id, self._build(project_id, user_id, note, phase="build")
        )

    async def start_revise(self, project_id: str, user_id: str, message: str) -> str:
        return self._spawn(
            project_id, self._build(project_id, user_id, message, phase="revise")
        )

    def create_race(self, project_id: str, models: list[str]) -> str:
        """Persist the race and its heats before the job starts.

        The caller needs the heat ids in its response, so the rows cannot be
        created inside the background task.
        """
        if self.active(project_id):
            raise ConflictError("该项目已有任务在运行")
        with session_scope() as session:
            race = Race(project_id=project_id, status="running")
            session.add(race)
            session.flush()
            for position, model in enumerate(models):
                session.add(
                    RaceHeat(
                        race_id=race.id, model=model, position=position, status="queued"
                    )
                )
            return race.id

    async def start_race(
        self,
        project_id: str,
        user_id: str,
        race_id: str,
        budget_seconds: int | None = None,
        only_heat: str | None = None,
    ) -> str:
        return self._spawn(
            project_id,
            self._race(project_id, user_id, race_id, budget_seconds, only_heat),
        )

    async def cancel(self, project_id: str) -> None:
        task = self._jobs.get(project_id)
        if task is None or task.done():
            return
        if project_id in self._stopping:
            await asyncio.gather(task, return_exceptions=True)
            return
        self._stopping.add(project_id)
        try:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # Covers cancellation before _guard has entered its try block.
            await self._terminate(project_id, "cancelled", "任务已取消，已有文件已保留")
        finally:
            self._stopping.discard(project_id)
            if self._jobs.get(project_id) is task:
                self._jobs.pop(project_id, None)

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.cancel(key) for key in list(self._jobs)))

    async def _cancel_remote(self, run_id: str) -> None:
        try:
            async with asyncio.timeout(5):
                await self._client.cancel(run_id)
        except Exception:
            pass  # Closing the stream also cancels the sidecar.

    async def reconcile(self) -> None:
        """Single-worker startup: previous process cannot still own these jobs."""
        with session_scope() as session:
            ids = set(
                session.scalars(
                    select(Project.id).where(
                        Project.status.in_(("planning", "building"))
                    )
                )
            )
            ids.update(
                session.scalars(select(Run.project_id).where(Run.status == "running"))
            )
            ids.update(
                session.scalars(select(Race.project_id).where(Race.status == "running"))
            )
        for project_id in ids:
            await self._terminate(
                project_id,
                "interrupted",
                "服务重启中断了任务，已有文件已保留，请继续生成",
            )

    async def _terminate(self, project_id: str, status: str, note: str) -> None:
        with session_scope() as session:
            runs = list(
                session.scalars(
                    select(Run).where(
                        Run.project_id == project_id, Run.status == "running"
                    )
                )
            )
            pending = [(run.id, run.role, run.heat_id) for run in runs]
            for run in runs:
                run.status, run.error = (
                    ("failed" if status == "error" else status),
                    note,
                )
                run.finished_at = datetime.now(timezone.utc)
                project = session.get(Project, project_id)
                if project and (run.input_tokens or run.output_tokens):
                    credits.charge(
                        session,
                        project.user_id,
                        reason=run.phase,
                        run_id=run.id,
                        input_tokens=run.input_tokens,
                        output_tokens=run.output_tokens,
                    )
            for race in session.scalars(
                select(Race).where(
                    Race.project_id == project_id, Race.status == "running"
                )
            ):
                race.status = status
                for heat in race.heats:
                    if heat.status in {"queued", "running"}:
                        heat.status, heat.error = status, note
        await asyncio.gather(*(self._cancel_remote(run_id) for run_id, _, _ in pending))
        for run_id, role, heat_id in pending:
            await bus.publish(
                project_id,
                f"run.{status}",
                {"message": note, **({"heatId": heat_id} if heat_id else {})},
                run_id=run_id,
                role=role,
            )
        await self._finish(project_id, status=status, note=note)

    # --------------------------------------------------------------- private

    def _spawn(self, project_id: str, coro, *, status: str = "building") -> str:
        if self.active(project_id):
            coro.close()
            raise ConflictError("该项目已有任务在运行")
        job_id = new_id()
        try:
            with session_scope() as session:
                project = session.get(Project, project_id)
                if project:
                    project.status = status
        except Exception:
            coro.close()
            raise
        task = asyncio.create_task(
            self._guard(project_id, coro), name=f"squad:{project_id}"
        )
        task.add_done_callback(lambda _: coro.close())
        self._jobs[project_id] = task
        return job_id

    async def _guard(self, project_id: str, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            await self._terminate(project_id, "cancelled", "任务已取消，已有文件已保留")
            raise
        except OutOfCredits as error:
            await self._fail(project_id, str(error))
        except Exception as error:  # noqa: BLE001 - surface anything to the UI
            await self._fail(project_id, f"{type(error).__name__}: {error}")
        finally:
            self._jobs.pop(project_id, None)

    async def _fail(self, project_id: str, detail: str) -> None:
        await self._terminate(project_id, "error", detail)

    async def _finish_turn_failure(self, project_id: str, outcome: TurnOutcome, fallback: str) -> None:
        await self._finish(project_id,
            status=outcome.status if outcome.status in ('cancelled','timed_out') else 'error',
            note=outcome.error or fallback)

    async def _finish(
        self, project_id: str, *, status: str, note: str | None = None
    ) -> None:
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project:
                project.status = status
                project.active_run_id = None
        payload: dict[str, Any] = {"status": status}
        if note:
            payload["note"] = note
        await bus.publish(project_id, "project.updated", payload)

    # ------------------------------------------------------------- pipelines

    async def _plan(self, project_id: str, user_id: str) -> None:
        gateway = _gateway_for(user_id, planning=True)
        prompt, title = _project_prompt(project_id)

        await self._set_status(project_id, "planning")

        mike = await self._turn(
            project_id,
            user_id,
            role="mike",
            phase="plan",
            gateway=gateway,
            prompt=prompt,
            render=_render_plan,
        )
        if mike.failed:
            await self._finish_turn_failure(project_id, mike, "规划失败")
            return
        plan = parsing.normalize_plan(mike.text, fallback_title=title)
        _apply_plan(project_id, plan)
        await bus.publish(
            project_id, "project.updated", {"status": "planning", "plan": plan}
        )

        if plan["clarification"]:
            _add_message(project_id, "mike", plan["clarification"])
            await self._finish(project_id, status="draft")
            return

        planned = [
            step["role"] for step in plan["steps"] if step["role"] in PLANNING_ORDER
        ]
        order = [role for role in PLANNING_ORDER if role in planned] or list(
            PLANNING_ORDER
        )

        transcript: list[tuple[str, str]] = [("Mike 的计划", mike.text)]
        for role in order:
            outcome = await self._turn(
                project_id,
                user_id,
                role=role,
                phase="plan",
                gateway=gateway,
                prompt=prompt,
                context=_context_block(transcript),
                render=_render_contract if role == "emma" else None,
            )
            if outcome.failed:
                await self._finish_turn_failure(project_id, outcome, f"{role} 执行失败")
                return
            transcript.append((f"{role.capitalize()} 的产出", outcome.text))
            if role == "emma":
                _apply_requirements(project_id, outcome.text)

        await self._finish(project_id, status="awaiting_approval")

    async def _build(
        self, project_id: str, user_id: str, note: str | None, *, phase: str
    ) -> None:
        gateway = _gateway_for(user_id)
        prompt, _ = _project_prompt(project_id)

        await self._set_status(project_id, "building")
        if phase == "revise" and note:
            _add_message(project_id, "user", note)

        outcome = await self._turn(
            project_id,
            user_id,
            role="alex",
            phase=phase,
            gateway=gateway,
            prompt=_build_prompt(project_id, prompt, note, phase=phase),
            context=_squad_context(project_id),
        )
        if outcome.failed:
            await self._finish_turn_failure(project_id, outcome, '生成失败')
            return

        await self._publish_files(project_id)
        await self._finish(project_id, status="ready")

    async def _race(
        self,
        project_id: str,
        user_id: str,
        race_id: str,
        budget_seconds: int | None = None,
        only_heat: str | None = None,
    ) -> None:
        """Run Alex on several models at once, each in its own workspace.

        Atoms calls this Race Mode. The heats are fully independent so one
        model failing or timing out does not spoil the comparison.
        """
        gateway = _gateway_for(user_id)
        prompt, _ = _project_prompt(project_id)
        context = _squad_context(project_id)
        build_prompt = _build_prompt(project_id, prompt, None, phase="build")

        with session_scope() as session:
            heats = [
                (heat.id, heat.model)
                for heat in session.scalars(
                    select(RaceHeat)
                    .where(RaceHeat.race_id == race_id)
                    .order_by(RaceHeat.position)
                )
                if only_heat is None or heat.id == only_heat
            ]

        await self._set_status(project_id, "building")
        await bus.publish(
            project_id,
            "race.started",
            {"raceId": race_id, "models": [model for _, model in heats]},
        )

        results = await asyncio.gather(
            *(
                self._run_heat(
                    project_id,
                    user_id,
                    heat_id,
                    model,
                    gateway,
                    (
                        build_prompt
                        + "\n继续已有工作区，先检查现有文件，只补齐未完成内容。"
                        if only_heat
                        else build_prompt
                    ),
                    context,
                    budget_seconds,
                )
                for heat_id, model in heats
            ),
            return_exceptions=True,
        )

        with session_scope() as session:
            race = session.get(Race, race_id)
            if race:
                for (heat_id, _), result in zip(heats, results):
                    heat = session.get(RaceHeat, heat_id)
                    if heat.status in {"queued", "running"}:
                        heat.status = "failed"
                        heat.error = (
                            str(result)
                            if isinstance(result, BaseException)
                            else "赛道未返回完成结果"
                        )
                succeeded = any(heat.status == "done" for heat in race.heats)
                race.status = "done" if succeeded else "failed"
                adopted = bool(race.winner_heat_id)
        await bus.publish(project_id, "race.completed", {"raceId": race_id})
        await self._finish(
            project_id,
            status="ready"
            if adopted
            else "awaiting_approval"
            if succeeded
            else "error",
        )

    async def _run_heat(
        self,
        project_id: str,
        user_id: str,
        heat_id: str,
        model: str,
        gateway: GatewayConfig,
        prompt: str,
        context: str,
        budget_seconds: int | None = None,
    ) -> None:
        started = time.monotonic()
        with session_scope() as session:
            heat = session.get(RaceHeat, heat_id)
            previous = (heat.elapsed_ms or 0, heat.input_tokens, heat.output_tokens)
        _set_heat(heat_id, status="running")
        await bus.publish(
            project_id, "race.heat_started", {"heatId": heat_id, "model": model}
        )

        try:
            outcome = await self._turn(
                project_id,
                user_id,
                role="alex",
                phase="race",
                gateway=GatewayConfig(gateway.base_url, gateway.api_key, model),
                prompt=prompt,
                context=context,
                heat_id=heat_id,
                record_message=False,
                budget_seconds=budget_seconds,
            )
        except asyncio.CancelledError:
            count, size = await self._workspace_stats(project_id, user_id, heat_id)
            with session_scope() as session:
                heat = session.get(RaceHeat, heat_id)
                run = session.get(Run, heat.run_id) if heat.run_id else None
                heat.elapsed_ms = previous[0] + int((time.monotonic() - started) * 1000)
                heat.input_tokens = previous[1] + (run.input_tokens if run else 0)
                heat.output_tokens = previous[2] + (run.output_tokens if run else 0)
                heat.file_count, heat.bytes = count, size
            raise

        workspace = storage.workspace_dir(project_id, heat_id)
        file_count, total_bytes = await self._workspace_stats(project_id, user_id, heat_id)
        _set_heat(
            heat_id,
            status=outcome.status,
            elapsed_ms=previous[0] + int((time.monotonic() - started) * 1000),
            input_tokens=previous[1] + outcome.input_tokens,
            output_tokens=previous[2] + outcome.output_tokens,
            file_count=file_count,
            bytes=total_bytes,
            error=outcome.error,
        )
        await bus.publish(
            project_id,
            "race.heat_completed",
            {
                "heatId": heat_id,
                "model": model,
                "failed": outcome.failed,
                "fileCount": file_count,
                "bytes": total_bytes,
            },
        )

    # ------------------------------------------------------------- one turn

    async def _turn(
        self,
        project_id: str,
        user_id: str,
        *,
        role: str,
        phase: str,
        gateway: GatewayConfig,
        prompt: str,
        context: str | None = None,
        heat_id: str | None = None,
        record_message: bool = True,
        render: Callable[[str], str] | None = None,
        budget_seconds: int | None = None,
    ) -> TurnOutcome:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise OutOfCredits("用户不存在")
            credits.ensure_affordable(session, user)
            run = Run(
                project_id=project_id,
                role=role,
                model=gateway.model,
                phase=phase,
                heat_id=heat_id,
                status="running",
            )
            session.add(run)
            session.flush()
            run_id = run.id
            if heat_id:
                heat = session.get(RaceHeat, heat_id)
                if heat:
                    heat.run_id = run_id
            project = session.get(Project, project_id)
            if project and heat_id is None:
                project.active_run_id = run_id

        await bus.publish(
            project_id,
            "squad.role_started",
            {
                "role": role,
                "title": ROLE_TITLES.get(role, ""),
                "model": gateway.model,
                **({"heatId": heat_id} if heat_id else {}),
            },
            run_id=run_id,
            role=role,
        )

        workspace = storage.workspace_dir(project_id, heat_id)
        sessions = storage.sessions_dir(project_id)
        workspace.mkdir(parents=True, exist_ok=True)
        sessions.mkdir(parents=True, exist_ok=True)

        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        failed = False
        error: str | None = None
        budget = (
            (
                budget_seconds
                if budget_seconds is not None
                else get_settings().build_budget_seconds
            )
            if role == "alex"
            else get_settings().run_timeout_seconds
        )
        terminal = False
        status = "done"
        cancelled = False
        lease = None
        completed_revision = None
        execution_args = {}
        try:
            async with asyncio.timeout(budget):
                if get_settings().sandbox_mode == 'broker':
                    if self.execution is None:
                        raise RuntimeError('执行服务尚未就绪')
                    lease = await self.execution.prepare_run(owner=user_id, project_id=project_id,
                        run_id=run_id, heat_id=heat_id, source=workspace, budget=budget)
                    execution_args = {'execution_lease':lease, 'execution_repository':self.execution.repository,
                                      'execution_owner':user_id}
                async with aclosing(
                    self._client.run(
                        run_id=run_id,
                        role=role,
                        prompt=prompt,
                        workspace_path=workspace,
                        session_path=sessions / f"{run_id}.jsonl",
                        agent_dir=storage.agent_dir(project_id),
                        gateway=gateway,
                        context=context,
                        budget_seconds=budget,
                        **execution_args,
                    )
                ) as stream:
                    async for line in stream:
                        if line.kind == "event":
                            # The orchestrator alone commits authoritative terminal events.
                            if line.type in {
                                "run.completed",
                                "run.failed",
                                "run.cancelled",
                            }:
                                continue
                            payload = dict(line.payload)
                            if heat_id:
                                payload["heatId"] = heat_id
                            if line.type == "usage.updated":
                                usage = payload.get("usage") or payload
                                seen_in = int(usage.get("inputTokens") or 0)
                                seen_out = int(usage.get("outputTokens") or 0)
                                payload["inputTokens"] = max(0, seen_in - input_tokens)
                                payload["outputTokens"] = max(
                                    0, seen_out - output_tokens
                                )
                                input_tokens, output_tokens = seen_in, seen_out
                                with session_scope() as session:
                                    persisted = session.get(Run, run_id)
                                    if persisted:
                                        persisted.input_tokens = input_tokens
                                        persisted.output_tokens = output_tokens
                            elif line.type == "message.delta":
                                text_parts.append(str(payload.get("delta") or ""))
                            await bus.publish(
                                project_id,
                                line.type or "",
                                payload,
                                run_id=run_id,
                                role=role,
                            )
                        elif line.kind in {"result", "error"}:
                            terminal = True
                            usage = line.payload.get("usage") or {}
                            input_tokens = int(usage.get("inputTokens") or input_tokens)
                            output_tokens = int(
                                usage.get("outputTokens") or output_tokens
                            )
                            if line.kind == "error":
                                reported = line.payload.get('status')
                                status = reported if reported in ('cancelled','timed_out') else 'failed'
                                error = str(line.payload.get("message") or "运行时错误")
                            else:
                                text_parts = [str(line.payload.get("resultText") or "")]
                                if lease is not None:
                                    completed_revision = line.payload['revisionReceipt']['revision_id']
                            break
                if not terminal:
                    raise RuntimeError("运行时未返回完成结果，已有文件已保留")
                if status == "done" and role == "alex":
                    if lease is None:
                        await validate_artifacts(workspace)
                    else:
                        with materialized_revision(self.execution.repository, self.execution.store,
                                owner=user_id, workspace_id=lease.workspace_id,
                                expected_revision_id=completed_revision) as view:
                            await validate_artifacts(view.path)
        except TimeoutError:
            status, error = (
                "timed_out",
                f"已达到 {budget:g} 秒生成上限，已有文件已保留，可继续生成",
            )
        except asyncio.CancelledError:
            status, error, cancelled = "cancelled", "任务已取消，已有文件已保留", True
        except Exception as exc:
            status, error = "failed", str(exc) or type(exc).__name__
        if status != "done":
            await self._cancel_remote(run_id)
            if lease is not None:
                try:
                    await self.execution.coordinator.interrupt(user_id, lease.execution_id, status)
                except Exception:
                    error = (error or '执行失败') + '；沙箱终止尚未确认，占用已保留'
        failed = status != "done"
        text = "".join(text_parts).strip()
        rendered = text
        if record_message and text and render and not failed:
            try:
                rendered = render(text)
            except (ValueError, TypeError) as exc:
                failed, status, error = True, "failed", f"契约格式无效：{exc}"

        with session_scope() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = status
                run.error = error
                run.input_tokens = input_tokens
                run.output_tokens = output_tokens
                run.finished_at = datetime.now(timezone.utc)
            project = session.get(Project, project_id)
            if project and project.active_run_id == run_id:
                project.active_run_id = None
            credits.charge(
                session,
                user_id,
                reason=phase,
                run_id=run_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            if record_message and text:
                # Mike and Emma answer in JSON because the pipeline parses it.
                # The chat log is for the user, so store a readable version.
                session.add(
                    Message(
                        project_id=project_id,
                        role=role,
                        content=rendered,
                        run_id=run_id,
                    )
                )

        await bus.publish(
            project_id,
            f"run.{status}" if failed else "run.completed",
            {
                **({"message": error} if failed else {"resultText": text}),
                **({"heatId": heat_id} if heat_id else {}),
            },
            run_id=run_id,
            role=role,
        )
        if cancelled:
            raise asyncio.CancelledError
        return TurnOutcome(text, input_tokens, output_tokens, failed, error, status)

    async def _set_status(self, project_id: str, status: str) -> None:
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project:
                project.status = status
        await bus.publish(project_id, "project.updated", {"status": status})

    async def _catalog(self, project_id: str, user_id: str, heat_id=None):
        if get_settings().sandbox_mode != 'broker':
            return {'revisionId':None, 'files':storage.list_files(storage.workspace_dir(project_id, heat_id))}
        if self.execution is None:
            raise RuntimeError('执行服务尚未就绪')
        return await asyncio.to_thread(committed_catalog, self.execution.repository, self.execution.store,
                                       owner=user_id, project_id=project_id, heat_id=heat_id)

    async def _workspace_stats(self, project_id, user_id, heat_id):
        listing = await self._catalog(project_id, user_id, heat_id)
        return len(listing['files']), sum(item['bytes'] for item in listing['files'])

    async def _publish_files(self, project_id: str) -> None:
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is None:
                return
            owner = project.user_id
        listing = await self._catalog(project_id, owner)
        files = listing['files']
        await bus.publish(
            project_id, "project.updated", {"status": "ready", "files": files, "revisionId":listing["revisionId"]}
        )


# ----------------------------------------------------------------- helpers


def _gateway_for(user_id: str, *, planning: bool = False) -> GatewayConfig:
    """Resolve the gateway for a turn.

    A user-chosen model always wins. Otherwise planning turns use the fast
    tier and build turns use the strong one.
    """
    settings = get_settings()
    with session_scope() as session:
        overrides = session.get(UserSettings, user_id)
        connection = resolve_provider(settings, overrides)
        chosen = overrides.model if overrides else None
        default = settings.llm_planning_model if planning else settings.llm_model
    return GatewayConfig(connection.base_url, connection.api_key, chosen or default)


def _project_prompt(project_id: str) -> tuple[str, str]:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ConflictError("项目不存在")
        return project.prompt, parsing.fallback_title(project.prompt)


def _apply_plan(project_id: str, plan: dict[str, Any]) -> None:
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            return
        project.title = plan["title"]
        project.summary = plan["summary"]
        project.kind = plan["kind"]


def _apply_requirements(project_id: str, text: str) -> None:
    requirements = parsing.normalize_requirements(text)
    if not requirements or any(not item["checks"] for item in requirements):
        raise ValueError("契约没有有效验收检查，请重新规划")
    with session_scope() as session:
        for existing in session.scalars(
            select(Requirement).where(Requirement.project_id == project_id)
        ):
            session.delete(existing)
        session.flush()
        for position, item in enumerate(requirements):
            session.add(
                Requirement(
                    project_id=project_id,
                    key=item["key"],
                    title=item["title"],
                    detail=item["detail"],
                    checks_json=json.dumps(item["checks"], ensure_ascii=False),
                    position=position,
                )
            )


def _context_block(parts: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"### {label}\n{text.strip()}" for label, text in parts if text.strip()
    )


def _squad_context(project_id: str) -> str:
    """Everything Alex needs: the squad's notes plus the acceptance contract."""
    with session_scope() as session:
        messages = session.scalars(
            select(Message)
            .where(
                Message.project_id == project_id,
                Message.role.in_(("iris", "emma", "bob")),
            )
            .order_by(Message.created_at)
        ).all()
        requirements = session.scalars(
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.position)
        ).all()

        parts = [
            (f"{ROLE_TITLES.get(m.role, m.role)} ({m.role.capitalize()})", m.content)
            for m in messages
        ]
        if requirements:
            lines = []
            for requirement in requirements:
                checks = json.loads(requirement.checks_json)
                lines.append(
                    f"- [{requirement.key}] {requirement.title}: {requirement.detail}"
                )
                for check in checks:
                    lines.append(f"    check: {json.dumps(check, ensure_ascii=False)}")
            parts.append(
                (
                    "验收契约（必须逐条满足，选择器要一字不差）",
                    "\n".join(lines),
                )
            )
    return _context_block(parts)


def _build_prompt(project_id: str, prompt: str, note: str | None, *, phase: str) -> str:
    if phase == "revise":
        return (
            f"这是一个已经构建好的项目，原始需求是：{prompt}\n\n"
            f"用户现在要求修改：{note}\n\n"
            "先用 read_file / glob 看清现有文件，再做最小必要改动。不要重写无关的文件。"
        )
    extra = f"\n\n用户在批准契约时补充了一句：{note}" if note else ""
    return (
        f"按照团队的契约把这个应用构建出来。原始需求：{prompt}{extra}\n\n"
        "工作区现在可能是空的，也可能已有文件；先确认再动手。"
    )


def _render_plan(text: str) -> str:
    if parsing.extract_json_object(text) is None:
        return text
    plan = parsing.normalize_plan(text, fallback_title="这一轮")
    lines = [plan["summary"] or plan["title"]]
    if plan["steps"]:
        lines.append("")
        lines.extend(
            f"{index}. {ROLE_TITLES.get(step['role'], step['role'])}（{step['role'].capitalize()}）"
            f"{'：' + step['goal'] if step['goal'] else ''}"
            for index, step in enumerate(plan["steps"], start=1)
        )
    return "\n".join(lines).strip() or text


def _render_contract(text: str) -> str:
    requirements = parsing.normalize_requirements(text)
    if not requirements:
        return text
    scope, out_of_scope = parsing.normalize_scope(text)
    lines: list[str] = []
    if scope:
        lines.append("这一版包含：" + "、".join(scope))
    if out_of_scope:
        lines.append("这一版不做：" + "、".join(out_of_scope))
    if lines:
        lines.append("")
    total = sum(len(item["checks"]) for item in requirements)
    lines.append(f"写了 {len(requirements)} 条需求，共 {total} 个可机检的验收点：")
    lines.extend(f"· {item['title']}" for item in requirements)
    lines.append("")
    lines.append("详细选择器在「契约」标签页里。确认后 Alex 才会动手。")
    return "\n".join(lines)


def _add_message(project_id: str, role: str, content: str) -> None:
    with session_scope() as session:
        session.add(Message(project_id=project_id, role=role, content=content))


def _set_heat(heat_id: str, **fields: Any) -> None:
    with session_scope() as session:
        heat = session.get(RaceHeat, heat_id)
        if heat is None:
            return
        for key, value in fields.items():
            if value is not None or key == "error":
                setattr(heat, key, value)


orchestrator = Orchestrator()
