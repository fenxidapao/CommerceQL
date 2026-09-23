"""W2C 判据⑥ 形态矩阵探针：gate1 对 deny 列的归因覆盖面（零 DB / 零 LLM / 零额度）。

**为什么需要**：判据⑥（07 v1.7.1）只写了一句"deny 列无论带不带表限定符都必须 R07"。
但 gate1 的 `_check_columns` 会遍历**全部** `exp.Column`，裸列名可以出现在 6 个语法
位置（投影 / WHERE / ORDER BY / 子查询 / CTE 内 / 表别名带裸列）；且 `_resolve_column`
在 **JOIN 多义**时同样返回 `None`（"多义" ≠ "不存在"）。⇒ 判据⑥的落点必须证明：
① 上述形态全归 `R07`；② anti-oracle 的反面仍成立（多义非 deny 列 / 不存在列 /
CTE 输出列名回避 ⇒ 仍 `R06`，不因新分支被顺手改成 `R07`）。

零 DB / 零 LLM / 零额度。跑法（CommerceQL 根）：

    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w2c/_probe_u121_judge6_shapes.py

退出码：0 = 全部符合期望；1 = 有 DIFF（**停手回查**，不是调断言）。
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
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
CTX = IdentityContext(
    trace_id="w2cjudge6",
    task_id="w2cjudge6",
    session_id="w2cjudge6",
    tenant_id="T_A",
    user_id="u_probe",
    role=Role.ANALYST,
)

# 本语义包的 deny_columns：order_paid.receiver_phone / .receiver_address / product.cost_price
# 以及 order_paid/order_refund/product/shop/traffic_daily/campaign 六张表的 tenant_id。
# R06 = 列白名单（列不存在或不可归属）；R07 = deny 列。
CASES: list[tuple[str, str, str]] = [
    ("1 单表裸写", "SELECT receiver_phone FROM v_order_paid", "R07"),
    ("2 表别名+裸写", "SELECT o.pay_amount, receiver_phone FROM v_order_paid AS o", "R07"),
    (
        "3 WHERE 裸写",
        "SELECT pay_amount FROM v_order_paid WHERE receiver_phone IS NOT NULL",
        "R07",
    ),
    ("4 ORDER BY 裸写", "SELECT pay_amount FROM v_order_paid ORDER BY receiver_phone", "R07"),
    (
        "5 子查询内裸写",
        "SELECT pay_amount FROM v_order_paid WHERE pay_amount >"
        " (SELECT AVG(cost_price) FROM v_product)",
        "R07",
    ),
    (
        "6 CTE 内裸写",
        "WITH t AS (SELECT receiver_phone AS rp FROM v_order_paid) SELECT rp FROM t",
        "R07",
    ),
    (
        "7 JOIN 多义(双表皆 deny)",
        "SELECT tenant_id FROM v_order_paid JOIN v_product"
        " ON v_order_paid.sku_id = v_product.sku_id",
        "R07",
    ),
    (
        "8 JOIN 单表 deny 裸写",
        "SELECT receiver_phone FROM v_order_paid JOIN v_product"
        " ON v_order_paid.sku_id = v_product.sku_id",
        "R07",
    ),
    (
        "9 JOIN 多义非 deny 列",
        "SELECT refund_status FROM v_order_paid JOIN v_order_refund"
        " ON v_order_paid.sub_order_id = v_order_refund.sub_order_id",
        "R06",
    ),
    (
        "10 CTE 输出列名回避",
        "WITH t AS (SELECT pay_amount FROM v_order_paid) SELECT receiver_phone FROM t",
        "R06",
    ),
    ("11 不存在列（anti-oracle）", "SELECT not_a_col FROM v_order_paid", "R06"),
]


def main() -> int:
    allowlist = SemanticBundleRuntime(load_bundle(BUNDLE)).guard_allowlist(
        CTX, max_rows=None
    )
    diff = 0
    for label, sql, expect in CASES:
        report = run_gate1(sql, allowlist)
        got = report.gate_result.rule_id if report.gate_result is not None else None
        good = got == expect
        diff += 0 if good else 1
        mark = "OK  " if good else "DIFF"
        print(
            f"{mark} {label:24s} expect={expect:5s} got={got!s:5s}"
            f" passed={report.passed}"
        )
    total = len(CASES)
    print(f"\n判据⑥ 形态矩阵：{total - diff}/{total} 符合期望（DIFF={diff}）")
    return 1 if diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
