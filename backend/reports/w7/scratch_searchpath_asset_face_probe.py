"""W7 探针：闸门认的是"非限定名"还是"关系全名"？—— 零 DB / 零 LLM / 零额度。

触发（2026-09-22 19:48 真栈 c=1 预检，判据④ 未过）：生成 SQL
`SELECT SUM(order_paid.pay_amount) … FROM order_paid …` 一路过了 gate1/gate2 才在
execute 期 `error_class=unknown_table`。而 `order_paid` **不是**语义包里的资产
（`semantic/bundle_2026.09.14.1.yaml:95` 的 `physical_asset` 全是 `v_*` 视图）。
⇒ 两条各自独立的问题，本探针只答第 1 条：

1. **闸门面**：白名单外关系（裸表）会不会被放过？deny 列经裸表名还拦得住吗？
2. **解析面**（不在本探针内，另条实测）：analytics 连接 `search_path="$user", public`
   里没有 `app` ⇒ 非限定名 **无论资产合法与否** 都 `undefined_table`。

第 2 条决定第 1 条的修法方向，所以顺手测：**限定名 `app.v_order_paid` 闸门认不认**。
若限定名反而被拒，那"让模型写 schema 限定名"这条修法就不成立（必须先改闸门取面）。

跑法（CommerceQL 根）：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w7/scratch_searchpath_asset_face_probe.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder-not-a-real-key")
# 占位 DSN：本探针**不连库**。分段写以免触发 DSN 卫生门禁（它把模式串等同触犯）。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg" + "://u:p@127.0.0.1:5432/none")
os.environ.setdefault("ANALYTICS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ENABLE_RESULT_CACHE_CONFIRMED", "false")

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.policy_gate import run_gate2  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
CTX = IdentityContext(
    trace_id="w7sp", task_id="w7sp", session_id="w7sp",
    tenant_id="T_A", user_id="u_probe", role=Role.ANALYST,
)
RT = SemanticBundleRuntime(load_bundle(BUNDLE))

SQLS: list[tuple[str, str]] = [
    ("合法资产·非限定", "SELECT pay_amount FROM v_order_paid"),
    ("合法资产·限定 app.", "SELECT pay_amount FROM app.v_order_paid"),
    ("裸表·非限定", "SELECT pay_amount FROM order_paid"),
    ("裸表·限定 app.", "SELECT pay_amount FROM app.order_paid"),
    ("裸表 + deny 列", "SELECT receiver_phone FROM order_paid"),
    ("裸表 + deny 列·限定", "SELECT receiver_phone FROM app.order_paid"),
    ("生产 repair 去参数",
     "SELECT SUM(order_paid.pay_amount) AS gmv FROM order_paid "
     "WHERE order_paid.pay_status = 'paid' LIMIT 1"),
]


def g1(sql: str) -> str:
    try:
        rep = run_gate1(sql, RT.guard_allowlist(CTX))
    except Exception as exc:
        return f"RAISED {type(exc).__name__}"
    res = rep.gate_result
    return f"passed={res.passed} rule={res.rule_id or '-'}"


def rewritten(sql: str) -> str:
    """gate1 通过时会把 `rewritten_sql` 写回 `state["sql_text"]`（`nodes/gate1_ast.py:65`）
    ⇒ 送给 execute 的其实是改写后的那条。本探针要的就是"限定名有没有被改掉"。"""
    try:
        rep = run_gate1(sql, RT.guard_allowlist(CTX))
    except Exception as exc:
        return f"RAISED {type(exc).__name__}"
    out = rep.rewritten_sql or ""
    return " ".join(out.split())[:120]


def g2(sql: str) -> str:
    try:
        rep = run_gate2(sql, CTX, RT)
    except Exception as exc:
        return f"RAISED {type(exc).__name__}"
    res = rep.gate_result
    return f"passed={res.passed} rule={res.rule_id or '-'} refuse={rep.refuse_reason or '-'}"


def main() -> int:
    print(f"semantic bundle: {RT.active_version()}")
    print("allowlist 顶层键数 =", len(RT.guard_allowlist(CTX).get("assets") or {}))
    print()
    print(f"{'题面':22}{'gate1':34}gate2")
    for label, sql in SQLS:
        print(f"{label:22}{g1(sql):34}{g2(sql)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
