from app.services.acceptance import evaluate_static, merge_acceptance, static_failures
from app.services.parsing import normalize_requirements, parse_build


HTML = """<!DOCTYPE html>
<html><head><title>今日烘焙</title></head>
<body>
  <h1 id="page-title">今日烘焙</h1>
  <input id="item-title" />
  <button id="add-item">记下</button>
  <script>const hidden = "不要把脚本里的字当成页面文字";</script>
</body></html>
"""

REQUIREMENTS = [
    {
        "key": "R1",
        "title": "记下一项",
        "detail": "输入后出现在列表",
        "priority": "must",
        "checks": [
            {"op": "exists", "selector": "#item-title"},
            {
                "op": "flow",
                "steps": [
                    {"do": "fill", "selector": "#item-title", "value": "可颂"},
                    {"do": "click", "selector": "#add-item"},
                    {"do": "see", "contains": "可颂"},
                ],
            },
        ],
    },
    {
        "key": "R2",
        "title": "看到标题",
        "priority": "must",
        "checks": [{"op": "text", "contains": "今日烘焙"}, {"op": "exists", "selector": "#page-title"}],
    },
    {
        "key": "R3",
        "title": "有按钮",
        "priority": "must",
        "checks": [{"op": "exists", "selector": "#missing-button"}],
    },
]


def test_static_check_ignores_script_text_and_reports_missing_id():
    failures = static_failures(HTML, REQUIREMENTS)
    assert failures == ["R3 页面里没有 #missing-button"]
    items = evaluate_static(HTML, REQUIREMENTS)
    assert items[1]["checks"][0]["ok"] is True


def test_merge_uses_browser_only_for_flow():
    static_items = evaluate_static(HTML, REQUIREMENTS[:2])
    merged = merge_acceptance(
        static_items,
        [{"key": "R1", "index": 1, "ok": True, "detail": "看到了可颂"}],
        REQUIREMENTS[:2],
    )
    assert merged["passed"] == 2
    assert merged["total"] == 2


def test_parse_build_keeps_raw_html():
    text = """NOTES
做了一个看板。

TRACE
R1 | #item-title

HTML
<!DOCTYPE html><html><body><h1>今日烘焙</h1></body></html>
"""
    built = parse_build(text)
    assert built["notes"].startswith("做了")
    assert built["trace"][0]["key"] == "R1"
    assert built["html"].startswith("<!DOCTYPE html>")


def test_normalize_rejects_class_selectors_and_too_few_items():
    cleaned = normalize_requirements(
        [
            {
                "key": "R1",
                "title": "甲",
                "priority": "must",
                "checks": [{"op": "exists", "selector": ".nope"}, {"op": "text", "contains": "甲"}],
            },
            {"key": "R2", "title": "乙", "priority": "later", "checks": [{"op": "exists", "selector": "#ok-id"}]},
            {"key": "R3", "title": "丙", "checks": []},
        ]
    )
    assert cleaned[0]["checks"] == [{"op": "text", "contains": "甲"}]
    assert cleaned[1]["priority"] == "must"
    assert cleaned[1]["checks"][0]["selector"] == "#ok-id"
    assert cleaned[2]["checks"][0]["op"] == "text"
