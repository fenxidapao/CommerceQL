"""W80-1：同一 HEAD 门禁复算（零出站；**不是**官方快照）。

与 `w79_gate_recompute.py` 同一套复算逻辑，只替换三处：
* 红队输入 → `eval/results_w80_redteam.json`（W80-1 同一 HEAD 重跑）；
* 集成层文案 → 明写「复用 W78 的 124/0/0」，不再说"本轮一次性 Docker"；
* 本地 P0 → **从本轮离线 pytest 的 JUnit 读计数**（不手抄 2736；少一条或多一条都当场变）。

集成层仍用 W78 的 `results_w78_integration.json`（`backend/app` 与
`backend/tests/integration` 自 `e7fc769` 空 diff），W77-1 τ 证据同源。
产物：`eval/results_w80_gate_recompute.json`
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import w78_gate_recompute as base  # noqa: E402

JUNIT = os.path.join(HERE, "results_w80_offline_pytest.junit.xml")


def _offline_counts() -> dict[str, object]:
    """本轮离线 pytest 的计数（只认 JUnit，不自报、不沿用上一轮）。"""
    if not os.path.isfile(JUNIT):
        raise SystemExit(
            f"缺少离线 JUnit：{os.path.relpath(JUNIT, ROOT)}；"
            "先跑 pytest backend/tests --ignore=backend/tests/integration --junitxml=…"
        )
    root = ET.parse(JUNIT).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals: Counter[str] = Counter()
    failed_tests: list[str] = []
    error_tests: list[str] = []
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.get(key) or 0)
        for case in suite.findall("testcase"):
            node_id = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None:
                failed_tests.append(node_id)
            if case.find("error") is not None:
                error_tests.append(node_id)
    tests = totals["tests"]
    failed = totals["failures"] + totals["errors"]
    return {
        "passed": tests - failed - totals["skipped"],
        "failed": totals["failures"],
        "errors": totals["errors"],
        "skipped": totals["skipped"],
        "tests": tests,
        "failed_tests": failed_tests,
        "error_tests": error_tests,
        "source": "W80 本轮 pytest backend/tests --ignore=backend/tests/integration -q",
        "junit": os.path.relpath(JUNIT, ROOT).replace("\\", "/"),
    }


base.ROUND_LABEL = "W80-1"
base.REDTEAM_LABEL = "W80-1 同一 HEAD 红队重跑"
base.REDTEAM = os.path.join(HERE, "results_w80_redteam.json")
base.OUT = os.path.join(HERE, "results_w80_gate_recompute.json")
base.INTEGRATION_SOURCE = (
    "W78 一次性 Docker 集成层 JUnit（W80 复用：backend/app 与 backend/tests/integration "
    "自 e7fc769 空 diff；端口/库名见 results_w78_integration.json）"
)
base.INTEGRATION_LABEL = "W78 一次性 Docker 集成层（本轮复用）"
base.LOCAL_P0 = _offline_counts()

if __name__ == "__main__":
    raise SystemExit(base.main())
