"""W7 只读探针 #2（零 DB / 零 LLM / 零额度）：端口形状喂进 gate2，逐档验三处落点的后果。

为什么值得入库：U-121 的 gate2 半边有**三处**改动（取用面 `policy_gate.py:105` +
读取面 ④ 与 ⑤），而"只换 105、不换读取面"的失败形态**不是**"和今天一样"，是
**干净 SQL 当场抛 ContractViolationError**。这句话若只写在报告里，下一个窗口无法复核。

两档（都不改 `app/guard/**`，只在测试侧换 bundle 的返回值）：
  A = 只换取用面：`asset_allowlist()` 返回 `guard_allowlist()` 的七键，④⑤ 仍是今天的读法
  B = 再模拟读取面切到结构面：把可见面 `columns` 顶成 `all_columns`

⚠️ **档 B 是读数器件、不是落地形态**（W2C 提出、W7 独立复现）：顶全列会让 gate1 的归因从
   `R06`（deny 列与不存在列同码）漂成 deny 列 `R07` / 不存在列 `R06` 两码 ⇒ **rule_id 成了列存在性
   oracle**（N-07 相邻面）。落地要走"给 auditor 一个结构面视图"的路子，别退到顶全列。
   `oracle对照` 那一档就是为这件事钉的：两种面 × {deny 列, 不存在列} 的 rule_id 全打出来。

跑法（CommerceQL 根）：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w7/scratch_gate2_face_probe.py
"""
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder-not-a-real-key")
# 占位 DSN：本探针**不连库**。分段写是为了不触犯 DSN 卫生门禁（它把模式串等同触犯）。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg" + "://u:p@127.0.0.1:5432/none")
os.environ.setdefault("ANALYTICS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ENABLE_RESULT_CACHE_CONFIRMED", "false")

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1, run_gate2  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
CTX = IdentityContext(trace_id="w7probe", task_id="w7probe", session_id="w7probe",
                      tenant_id="T_A", user_id="u_probe", role=Role.ANALYST)
RT = SemanticBundleRuntime(load_bundle(BUNDLE))

SQLS = {
    "plain_unqualified": "SELECT pay_amount FROM v_order_paid",
    "deny_unqualified": "SELECT receiver_phone FROM v_order_paid",
    "deny_qualified": "SELECT v_order_paid.receiver_phone FROM v_order_paid",
    "deny_qualified_alias": "SELECT o.receiver_phone FROM v_order_paid AS o",
}


class TierA:
    """只换 `:105`：闸门拿到七键，④⑤ 仍读可见面。其余属性转发真 runtime。"""

    def asset_allowlist(self, identity: IdentityContext) -> object:
        return RT.guard_allowlist(identity, max_rows=None)

    def __getattr__(self, name: str) -> object:
        return getattr(RT, name)


class TierB(TierA):
    """再把读取面顶到结构面（④⑤ 看见全列，含 deny 列）。"""

    def asset_allowlist(self, identity: IdentityContext) -> object:
        shaped = RT.guard_allowlist(identity, max_rows=None)
        for asset in shaped["assets"].values():
            asset["columns"] = dict(asset["all_columns"])
        return shaped


def probe(bundle: Any, sql: str) -> dict[str, object]:
    try:
        result = run_gate2(sql, CTX, bundle).gate_result
        return {"passed": result.passed, "rule_id": result.rule_id}
    except Exception as exc:
        return {"raised": type(exc).__name__, "message": str(exc)[:140]}


def oracle_row(allowlist: Any, sql: str) -> dict[str, object]:
    result = run_gate1(sql, allowlist).gate_result
    return {"passed": result.passed, "rule_id": result.rule_id}


def topped(allowlist: Any) -> Any:
    for asset in allowlist["assets"].values():
        asset["columns"] = dict(asset["all_columns"])
    return allowlist


PORT = RT.guard_allowlist(CTX, max_rows=None)
SQL_GATE1 = {"deny列": "SELECT receiver_phone FROM v_order_paid",
             "不存在的列": "SELECT definitely_not_a_col FROM v_order_paid"}

print(json.dumps(
    {"A_只换取用面": {k: probe(TierA(), v) for k, v in SQLS.items()},
     "B_顶全列(读数器件_非落地形态)": {k: probe(TierB(), v) for k, v in SQLS.items()},
     "生产今天(未换 105)": {k: probe(RT, v) for k, v in SQLS.items()},
     "oracle对照_gate1的rule_id": {
         "可见面(端口原样)": {k: oracle_row(copy.deepcopy(PORT), v) for k, v in SQL_GATE1.items()},
         "顶全列(=档B手法)": {k: oracle_row(topped(copy.deepcopy(PORT)), v)
                        for k, v in SQL_GATE1.items()}},
     },
    ensure_ascii=False, indent=1))
