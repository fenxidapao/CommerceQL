"""W79-2：当前门禁复算（零出站；不是官方快照）。

复用 `w78_gate_recompute.py` 的同一套输入组装与判定逻辑，只替换：
* 红队输入 → `eval/results_w79_redteam.json`（W79-1 覆盖口径订正后）；
* 本地 P0 读数 → W79 本轮全量离线测试；
* 输出 → `eval/results_w79_gate_recompute.json`。

集成层仍用 W78 的 `results_w78_integration.json`（124/0/0；未重跑）与 W77-1 τ 证据。
预期：G-3 PASS ⇒ 6 PASS／0 PARTIAL／2 UNVERIFIED（G-6/G-8 仍 UNVERIFIED）。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import w78_gate_recompute as base  # noqa: E402

base.ROUND_LABEL = "W79-2"
base.REDTEAM_LABEL = "W79-1 G-3 覆盖口径订正后的红队刷新"
base.REDTEAM = os.path.join(HERE, "results_w79_redteam.json")
base.OUT = os.path.join(HERE, "results_w79_gate_recompute.json")
base.LOCAL_P0 = {
    "passed": 2736,
    "failed": 0,
    "errors": 0,
    "source": "W79 本轮 pytest backend/tests --ignore=backend/tests/integration -q",
}

if __name__ == "__main__":
    raise SystemExit(base.main())
