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

⚠️ **09-23 判据翻转（架构 v1.7.1：撤销 07 v1.6.8 的判据⑤、换判据⑥）** —— 本件的**读数不变、解释翻转**：
- 判据⑤ 当年要求"deny 列与不存在的列在 gate1 **同为 `R06`**"，把 `R07`/`R06` 分裂读成列存在性 oracle；
- 判据⑥ 反过来要求"deny 列**裸写与带表限定符都必须 `R07`**"，但仍**禁止 gate1 读 `all_columns`**。
- 两者不矛盾的在于**出处不同**：`R07` 由 `deny_columns` + 本 scope 表的**逻辑名反查**得出（W2C `_is_unqualified_deny()`），
  不是"该列在结构面里存在" ⇒ 攻击者能分出"被 deny"与"不存在"（这是判据⑥ 要的归因精度），
  但**分不出"哪些非 deny 列存在"**（这才是判据⑤ 要堵的那道 oracle）。
⇒ 所以本件第 8–11 题的正确读法是：deny 三形态全 `R07`、不存在列仍 `R06`。**任何一格变成 `R06`/`R07` 互换都说明判据⑥ 退步了。**

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
    # ↓ 09-23 补：判据⑥ 的目标形态（前 7 题全打在**表级**，R05/R16 先响 ⇒ 探不到列级判定）
    ("合法资产 + deny 裸写", "SELECT receiver_phone FROM v_order_paid"),
    ("合法资产 + deny 限定", "SELECT v_order_paid.receiver_phone FROM v_order_paid"),
    ("合法资产 + deny 在 WHERE", "SELECT pay_amount FROM v_order_paid WHERE receiver_phone IS NOT NULL"),
    ("合法资产 + 不存在的列", "SELECT not_a_real_column FROM v_order_paid"),
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
