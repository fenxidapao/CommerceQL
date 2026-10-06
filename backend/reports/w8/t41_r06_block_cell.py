"""T-41 D 的现读尺：演示那句在 **HEAD 闸门**上到底被哪一格拦下（`rule_id` ＋ `reason`）。

🔴 零出站：SQL 只读自 `app.audit_log.final_executed_sql`（外层 `begin; … rollback;`，复用第 13 轮那件
离线器件的取数面 `probe_r13_gate_rejections._sql_of`，含 base64 折行拼接逻辑）；闸门是纯静态件。

为什么要单独一把尺（`t39_u137_before_after.py` 给的是 `user_message`，不是 `reason`）：
QA 第 20 轮 17.5 要的是 `gate_result.reason` 现读 ⇒ 对外那句"拦在 R06 列面"必须能自己跑出来。
依 `U-125` 判据④：按 `rule_id` 的归因属**离线器件**，不得写成生产可观测。

复算（cwd = 仓库根）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t41_r06_block_cell.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
for _p in (str(ROOT / "eval"), str(ROOT / "backend"), str(ROOT / "backend" / "reports" / "w8")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import probe_r13_gate_rejections as p13  # noqa: E402

from app.auth.context import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.rules import RULE_BY_ID  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

#: 演示那句的 `task_id`（`deploy/loadtest/t38_c3n30_main.json` 的 `codes_task_ids.GATE_AST_REJECTED` 之一）。
DEMO_TASK = "tk_ca342fa63c0044d98461f6184ebbd994"
OUT = ROOT / "backend" / "reports" / "w8" / "evidence" / "t41" / "r06_block_cell.json"


def main() -> int:
    print(f"[ROOT] {ROOT}")
    rec = p13._sql_of(DEMO_TASK)
    if not rec.get("sql"):
        raise SystemExit(f"尺坏：审计面没给到 {DEMO_TASK} 的 SQL（先确认取数条件在场，别读成'缺这行'）")

    runtime = SemanticBundleRuntime(load_bundle(_bootstrap.BUNDLE_PATH))
    identity = IdentityContext(
        trace_id="tr-t41", task_id=DEMO_TASK, session_id="se-t41",
        tenant_id=rec["tenant_id"], user_id=rec["user_id"],
        role=Role.ANALYST if rec["role"] == "analyst" else Role.PLATFORM_ADMIN,
        scope_claims=(), shop_ids=())
    allowlist = runtime.guard_allowlist(identity, max_rows=None)
    gate = run_gate1(rec["sql"], allowlist).gate_result

    payload = {
        "artifact": "commerceql.w8.t41_r06_block_cell/1",
        "zero_egress": True,
        "task_id": DEMO_TASK,
        "raw_question": rec["raw_question"],
        "sql_chars": len(rec["sql"]),
        "sql_len_matches_declared": len(rec["sql"]) == rec["declared_len"],
        "surface": "HEAD 工作树的 app/guard（第 16 轮 U-137 落地之后）",
        "gate_result": {
            "passed": gate.passed,
            "rule_id": gate.rule_id,
            "reason": gate.reason,
            "user_message": RULE_BY_ID[gate.rule_id].user_message if gate.rule_id else None,
        },
        "读法": (
            "拦点 = R06（列面／受保护字段），与 JOIN 路径无关 ⇒ `U-137` 的结案不覆盖'这句能不能出数'；"
            "要让它出数得动语义包／列权限面（另一件主单）。"),
        "边界": "依 U-125 判据④，本件的 rule_id/reason 归因 = 离线器件读数，不是生产可观测。",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(payload["gate_result"] | {"raw_question": payload["raw_question"],
                                               "passed": payload["gate_result"]["passed"]},
                     ensure_ascii=False))
    print(f"落盘 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
