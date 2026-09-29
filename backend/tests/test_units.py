from __future__ import annotations

from pathlib import Path

import pytest

from app.masking import mask_secret
from app.services.orchestrator import _render_contract, _render_plan
from app.services.parsing import (
    extract_json_object,
    fallback_title,
    normalize_plan,
    normalize_requirements,
)
from app.storage import resolve_within


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        ("", ""),
        ("a", "*"),
        ("abcd", "****"),
        ("abcde", "ab*de"),
        ("sk-cWbrmSA3klFP6DieuBLIGg", "sk" + "*" * 21 + "Gg"),
    ],
)
def test_mask_secret(secret: str, expected: str) -> None:
    assert mask_secret(secret) == expected


def test_mask_preserves_length_so_users_can_spot_a_wrong_key() -> None:
    for secret in ("sk-short99", "sk-" + "x" * 60):
        assert len(mask_secret(secret)) == len(secret)


def test_mask_never_leaks_short_secrets() -> None:
    assert set(mask_secret("abcd")) == {"*"}


def test_extract_json_from_fenced_and_prose_responses() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('好的：\n```json\n{"a": 2}\n```\n以上。') == {"a": 2}
    assert extract_json_object('前言 {"a": {"b": 3}} 后记') == {"a": {"b": 3}}
    # A brace inside a string must not end the object early.
    assert extract_json_object('{"a": "}"}') == {"a": "}"}
    assert extract_json_object("完全没有 JSON") is None


def test_normalize_plan_keeps_only_known_roles() -> None:
    plan = normalize_plan(
        '{"title":"记账本","summary":"一个小工具","kind":"tool",'
        '"steps":[{"role":"iris","goal":"调研"},{"role":"sarah","goal":"SEO"},'
        '{"role":"alex","goal":"实现"}],"clarification":null}',
        fallback_title="备用标题",
    )
    assert plan["title"] == "记账本"
    assert [step["role"] for step in plan["steps"]] == ["iris", "alex"]
    assert plan["clarification"] is None


def test_normalize_plan_falls_back_when_model_returns_junk() -> None:
    plan = normalize_plan("模型今天不想说话", fallback_title="备用标题")
    assert plan["title"] == "备用标题"
    assert plan["steps"] == []


def test_normalize_requirements_drops_unusable_checks() -> None:
    requirements = normalize_requirements(
        """{"requirements":[
          {"key":"Add Entry","title":"新增记录","detail":"",
           "checks":[
             {"type":"exists","selector":"[data-testid=add]"},
             {"type":"text","selector":"h1"},
             {"type":"flow","selector":"[data-testid=add]","expect":"[data-testid=row]"},
             {"type":"screenshot","selector":"body"}
           ]},
          {"title":"","checks":[]}
        ]}"""
    )
    assert len(requirements) == 1
    requirement = requirements[0]
    # The key is slugified from "Add Entry".
    assert requirement["key"] == "add-entry"
    # The text check had no `contains` and screenshot is not a real type.
    assert [check["type"] for check in requirement["checks"]] == ["exists", "flow"]


def test_normalize_requirements_deduplicates_keys() -> None:
    requirements = normalize_requirements(
        """{"requirements":[
          {"key":"same","title":"A","checks":[{"type":"exists","selector":"a"}]},
          {"key":"same","title":"B","checks":[{"type":"exists","selector":"b"}]}
        ]}"""
    )
    assert len({r["key"] for r in requirements}) == 2


def test_fallback_title_condenses_whitespace() -> None:
    assert fallback_title("  做一个   待办  ") == "做一个 待办"
    assert fallback_title("") == "未命名项目"
    assert fallback_title("x" * 50).endswith("…")


PLAN_JSON = """{
  "title": "本地记账小工具",
  "summary": "一个纯前端的记账小工具",
  "kind": "tool",
  "steps": [
    {"role": "iris", "goal": "看同类产品怎么做"},
    {"role": "alex", "goal": "写成可运行的页面"}
  ],
  "clarification": null
}"""

CONTRACT_JSON = """{
  "scope": ["新增一笔收支", "按分类筛选"],
  "outOfScope": ["多账本"],
  "requirements": [
    {"key": "add-entry", "title": "新增一笔", "detail": "点按钮能加一行",
     "checks": [
       {"type": "exists", "selector": "[data-testid='add']"},
       {"type": "flow", "selector": "[data-testid='add']", "expect": "[data-testid='row']"}
     ]}
  ]
}"""


def test_plan_is_rendered_for_humans_not_as_json() -> None:
    rendered = _render_plan(PLAN_JSON)
    assert "{" not in rendered
    assert rendered.startswith("一个纯前端的记账小工具")
    assert "Deep Researcher" in rendered
    assert "看同类产品怎么做" in rendered


def test_plan_renderer_passes_through_unparseable_text() -> None:
    assert _render_plan("模型没有返回 JSON") == "模型没有返回 JSON"


def test_contract_is_rendered_as_a_summary() -> None:
    rendered = _render_contract(CONTRACT_JSON)
    assert "{" not in rendered
    assert "这一版包含：新增一笔收支、按分类筛选" in rendered
    assert "这一版不做：多账本" in rendered
    # One requirement carrying two checks.
    assert "写了 1 条需求，共 2 个可机检的验收点" in rendered
    assert "· 新增一笔" in rendered


def test_contract_renderer_passes_through_unparseable_text() -> None:
    assert _render_contract("没有需求") == "没有需求"


def test_resolve_within_blocks_escapes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("hi", encoding="utf-8")
    assert resolve_within(tmp_path, "index.html") is not None
    assert resolve_within(tmp_path, "../secret") is None
    assert resolve_within(tmp_path, "/etc/passwd") is None
    assert resolve_within(tmp_path, "") is None
    assert resolve_within(tmp_path, ".git/config") is None
    assert resolve_within(tmp_path, "node_modules/x/y.js") is None
