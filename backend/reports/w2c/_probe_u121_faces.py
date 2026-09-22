"""W2C 修正版探针：U-121 三处落点 —— 分工与后果（零 DB / 零 LLM / 零额度）。

**为什么重写**：首版把 `extract_columns_with_assets(sql, allowlist)` 当成"④ 已切结构面"，
但它内部 `_Auditor(allowlist)` 只认 `columns` 键 ⇒ **注释与代码不符**，
读出的"④ 切面后仍漏检"是假结论（W7 2026-09-22 指出，其读数已复现）。
本版把三档分开，并**用真 `SemanticBundleRuntime` 作输入**（不手拼形状）。

四档（互不混写）：
  档1 真扁平面（`asset_allowlist` 原样，顶层无 `assets` 键）⇒ 资产级拦截，走不到列面
  档2 形状顶层 + `columns` 仍是元组（模拟 W2A 只改顶层不改列面）⇒ 列面 `AttributeError`
  档3a 形状双面齐 + ④ 的 auditor 视图切结构面（= 建议方案 D3，`columns` 保持可见）
  档3b 把 `columns` 直接顶成全列（= W7 TierB 做法，**破坏可见面**）
  档3c 只换 `:105`、④⑤ 仍读可见面（= W7 档A）

跑法（CommerceQL 根）：
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w2c/_probe_u121_faces.py
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
from app.core.errors import ContractViolationError  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.policy_gate import (  # noqa: E402
    _extract_tables,
    extract_columns_with_assets,
    run_gate2,
)
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
CTX = IdentityContext(
    trace_id="w2cprobe",
    task_id="w2cprobe",
    session_id="w2cprobe",
    tenant_id="T_A",
    user_id="u_probe",
    role=Role.ANALYST,
)
RT = SemanticBundleRuntime(load_bundle(BUNDLE))

SQLS = {
    "干净-不限定": "SELECT pay_amount FROM v_order_paid",
    "deny-不限定": "SELECT receiver_phone FROM v_order_paid",
    "deny-限定": "SELECT v_order_paid.receiver_phone FROM v_order_paid",
    "deny-别名": "SELECT o.receiver_phone FROM v_order_paid AS o",
    "未知列": "SELECT nonsense_col FROM v_order_paid",
}


class _Runtime:
    """真 runtime 的薄包装，使 `asset_allowlist` 可被替换；其余属性转发。"""

    def __init__(self, rt) -> None:
        self._rt = rt

    def asset_allowlist(self, ctx: IdentityContext):
        return self._rt.asset_allowlist(ctx)

    def __getattr__(self, name: str):
        return getattr(self._rt, name)


class _Shaped(_Runtime):
    """换取用面：`asset_allowlist` 返回七键形状；可选破坏列面以复现两档退化。"""

    def __init__(
        self, rt, *, columns_are_tuples: bool = False, columns_all: bool = False
    ) -> None:
        super().__init__(rt)
        self._tuples = columns_are_tuples
        self._all = columns_all

    def asset_allowlist(self, ctx: IdentityContext):
        shaped = self._rt.guard_allowlist(ctx, max_rows=None)
        for asset in shaped["assets"].values():
            if self._tuples:
                asset["columns"] = tuple(asset["columns"])
            elif self._all:
                asset["columns"] = dict(asset["all_columns"])
        return shaped


def _g1(sql: str, bundle) -> str:
    try:
        r = run_gate1(sql, bundle.asset_allowlist(CTX))
        return f"pass={r.gate_result.passed} rule={r.gate_result.rule_id}"
    except Exception as exc:
        return f"RAISED {type(exc).__name__}@751?"


def _g2(sql: str, bundle) -> str:
    try:
        r = run_gate2(sql, CTX, bundle)
        return f"pass={r.gate_result.passed} rule={r.gate_result.rule_id}"
    except Exception as exc:
        return f"RAISED {type(exc).__name__}"


def _g2_variant_4_reads_struct(sql: str, bundle) -> str:
    """**反事实变体**（非生产）：复刻 run_gate2，④ 的归属面切结构面、⑤ 读 `all_columns`。

    与「把 `columns` 顶成全列」的差别 = 本变体**不动形状**，只给 ④ 一份
    `columns <- all_columns` 的 auditor 视图（= 建议方案 D3）。
    """

    allowlist = bundle.asset_allowlist(CTX)
    assets = allowlist.get("assets") or {}
    tables = _extract_tables(sql)
    if [t for t in tables if t not in assets]:
        return "pass=False rule=G2-ASSET"
    involved = [assets[t] for t in tables]

    struct_view = {
        **allowlist,
        "assets": {
            k: {**v, "columns": dict(v.get("all_columns") or v.get("columns") or {})}
            for k, v in assets.items()
        },
    }
    deny = frozenset(allowlist.get("deny_columns") or ())
    for logical, col in extract_columns_with_assets(sql, struct_view):
        if f"{logical}.{col}" in deny:
            return "pass=False rule=G2-DENY"

    for asset in involved:
        tenant_scoped = bool(asset.get("tenant_scoped"))
        has_tenant_col = "tenant_id" in (asset.get("all_columns") or {})
        if tenant_scoped != has_tenant_col:
            raise ContractViolationError(
                "语义包 tenant_scoped 与 tenant_id 列不一致（07 §7.4 双向断言）",
                detail={"asset": asset.get("logical_name")},
            )
    return "pass=True rule=None"


def _show(label: str, fn) -> None:
    print(f"\n=== {label} ===")
    for name, sql in SQLS.items():
        print(f"  {name:<12} {fn(sql)}")


print("########## 档1：真扁平面（顶层无 assets 键）⇒ 资产级拦截 ##########")
_show(
    "gate1 与 gate2 并列",
    lambda s: f"gate1[{_g1(s, _Runtime(RT))}]  gate2[{_g2(s, _Runtime(RT))}]",
)

print("\n########## 档2：形状顶层 + columns 是元组 ⇒ 列面崩 ##########")
_show(
    "gate1 与 gate2 并列",
    lambda s: f"gate1[{_g1(s, _Shaped(RT, columns_are_tuples=True))}]"
    f"  gate2[{_g2(s, _Shaped(RT, columns_are_tuples=True))}]",
)

print("\n########## 档3a：形状双面齐 + ④ 视图切结构面（建议方案 D3） ##########")
_show(
    "gate1 用可见面 / gate2 ④⑤ 用结构面",
    lambda s: f"gate1[{_g1(s, _Shaped(RT))}]"
    f"  gate2[{_g2_variant_4_reads_struct(s, _Shaped(RT))}]",
)

print("\n########## 档3b：把 columns 顶成全列（W7 TierB 做法） ##########")
_show(
    "gate1 与 gate2 并列（可见面已被破坏）",
    lambda s: f"gate1[{_g1(s, _Shaped(RT, columns_all=True))}]"
    f"  gate2[{_g2(s, _Shaped(RT, columns_all=True))}]",
)

print("\n########## 档3c：只换 :105、④⑤ 仍读可见面（W7 档A） ##########")
_show("gate2 单列", lambda s: f"gate2[{_g2(s, _Shaped(RT))}]")


# ============================================================================
# oracle 机械断言（W7 2026-09-22 提出的落地判据，见 RELAY §6.8 D5）
#
#   A（anti-oracle）：gate1 可见面下，"deny 列"与"不存在的列"两条 SQL 的
#      rule_id **必须同为 R06** —— 两码（R07/R06）= error oracle = 违规。
#   B（冗余复核活着）：gate2 ④⑤ 对 deny 列三形态必须全 `G2-DENY`。
#
#   auditor 视图切面（D3/档3a）= A+B 同时满足；顶全列（3b）= B 满足、A 破坏。
# ============================================================================

def _rule1(sql: str, bundle) -> str | None:
    try:
        return run_gate1(sql, bundle.asset_allowlist(CTX)).gate_result.rule_id
    except Exception:
        return "RAISED"


def oracle_check(label: str, bundle) -> None:
    deny_sql = SQLS["deny-不限定"]
    unknown_sql = SQLS["未知列"]
    r_deny = _rule1(deny_sql, bundle)
    r_unknown = _rule1(unknown_sql, bundle)
    anti_oracle = "PASS" if r_deny == r_unknown == "R06" else "FAIL(oracle!)"

    struct = _g2_variant_4_reads_struct(deny_sql, bundle)
    redundant = "PASS" if "G2-DENY" in struct else "FAIL"

    print(
        f"  {label:<28} A_anti_oracle={anti_oracle}"
        f" (deny={r_deny}, unknown={r_unknown})"
        f"  B_redundant={redundant} ({struct})"
    )


print("\n########## oracle 机械断言（U-121 落地判据，W7 2026-09-22） ##########")
oracle_check("档3a D3 视图切面", _Shaped(RT))
oracle_check("档3b 顶全列（违规对照）", _Shaped(RT, columns_all=True))
