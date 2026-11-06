"""`docs/10_未决问题台账.md` 的机器门（取号 / 关闭 / 跳过 / WIP 闸）。

判定逻辑**只有一份**，在 `tools/open_issues.py`；本文件只做两件事：
① 现读台账必须 0 违规，且条目数不低于下界（防误删 —— 删条目等于把未决重新丢回人脑）；
② 反向对照：塞一行伪造的 `CLOSED` 必须被判红（证明这道门不是恒绿摆设）。

台账坏了 = 「遇到问题一点一点遗忘、直接跳过」会重新发生，所以它必须在 CI 里有一条断言。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = REPO_ROOT / "tools" / "open_issues.py"
MIN_ROWS = 13

FAKE_HEADER = (
    "| ID | 现象 | 首次登记 | 状态 | 关闭判据（可复算） | 证据路径 | 阻塞付费批 | 责任人 | 复审触发 |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def _load_tool() -> ModuleType:
    assert TOOL_PATH.is_file(), f"missing tool: {TOOL_PATH}"
    spec = importlib.util.spec_from_file_location("open_issues_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ledger_passes_all_gates() -> None:
    rows, violations = _load_tool().validate()
    assert violations == [], violations
    assert len(rows) >= MIN_ROWS, f"台账条目 {len(rows)} < 下界 {MIN_ROWS}（疑似误删）"


def test_fabricated_closed_row_is_rejected() -> None:
    fake = FAKE_HEADER + (
        "| T-99 | 伪造示例 | 2026-11-05 | CLOSED | — | `docs/does-not-exist.md` "
        "| 否 | lead | — |\n"
    )
    _, violations = _load_tool().validate(fake)
    messages = "\n".join(violations)
    assert "T-99" in messages, violations
    assert "关闭门" in messages, violations
    assert "取号门" in messages, violations
