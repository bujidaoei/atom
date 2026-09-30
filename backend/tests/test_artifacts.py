import asyncio
import pytest
from app.services.artifacts import validate_artifacts


def test_actual_javascript_and_asset_gate(tmp_path):
    with pytest.raises(ValueError, match="index.html"):
        asyncio.run(validate_artifacts(tmp_path))
    (tmp_path / "index.html").write_text(
        '<script src="app.js"></script>', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="资源不存在"):
        asyncio.run(validate_artifacts(tmp_path))
    (tmp_path / "app.js").write_text("const bad = ;", encoding="utf-8")
    with pytest.raises(ValueError, match="语法校验失败"):
        asyncio.run(validate_artifacts(tmp_path))
    (tmp_path / "app.js").write_text("const good = 1;", encoding="utf-8")
    asyncio.run(validate_artifacts(tmp_path))
