"""W2C 独立复核：U-121 双面（可见面 vs 结构面）对 gate1/gate2 的实测影响。

不连库、不发网络请求。**生产读数**取自 `run_gate1` / `run_gate2`；
④⑤ 的"切面后"读数取自**反事实变体**（`_gate2_variant`，明确标注非生产）。

跑法：`CommerceQL/.venv/Scripts/python.exe backend/reports/w2c/_probe_u121_faces.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.policy_gate import run_gate2  # noqa: E402


class _Bundle:
    """最小端口替身：只实现 gate2 需要的两个方法。"""

    def __init__(self, allowlist: dict) -> None:
        self._allowlist = allowlist

    def asset_allowlist(self, ctx: IdentityContext):
        return self._allowlist

    def active_version(self) -> str:
        return "testbundle-v1"


DENY = ("orders.receiver_phone", "orders.tenant_id")
VISIBLE = {"order_id": "bigint", "amount": "numeric", "status": "text"}
ALL_COLS = {**VISIBLE, "receiver_phone": "text", "tenant_id": "bigint"}


def _allowlist(
    *, with_deny_in_visible: bool, with_all_columns: bool, flat_tuple: bool = False
) -> dict:
    """构造 allowlist。

    :param with_deny_in_visible: `columns` 里**保留** deny 列（= 结构面当可见面用 / 扁平全列）
    :param with_all_columns: 是否另立 `all_columns`（结构面）
    :param flat_tuple: `columns` 给**列名元组**（= 真 `asset_allowlist` 的现状形态）
    """

    visible = ALL_COLS if with_deny_in_visible else VISIBLE
    cols = tuple(visible) if flat_tuple else dict(visible)
    asset: dict = {
        "logical_name": "orders",
        "domain": "trade",
        "grain": "order",
        "tenant_scoped": True,
        "columns": cols,
    }
    if with_all_columns:
        asset["all_columns"] = dict(ALL_COLS)
    return {
        "bundle_version": "testbundle-v1",
        "assets": {"orders": asset},
        "joins": [],
        "deny_columns": list(DENY),
        "default_predicates": {},
        "allowed_constants": (),
        "max_rows": None,
    }


def _ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="t1",
        task_id="k1",
        session_id="s1",
        tenant_id="1",
        user_id="u1",
        role=Role.ANALYST,
        scope_claims=("trade",),
        shop_ids=("1",),
    )


SQLS = {
    "干净 SQL": "SELECT order_id, amount FROM orders LIMIT 10",
    "deny列-限定表名": "SELECT orders.receiver_phone FROM orders LIMIT 10",
    "deny列-不限定": "SELECT receiver_phone FROM orders LIMIT 10",
    "未知列": "SELECT nonsense_col FROM orders LIMIT 10",
}


def _one(label: str, allowlist: dict) -> None:
    print(f"\n=== {label} ===")
    for name, sql in SQLS.items():
        try:
            g1 = run_gate1(sql, allowlist)
            g1v = f"pass={g1.gate_result.passed} rule={g1.gate_result.rule_id}"
        except Exception as exc:
            g1v = f"RAISED {type(exc).__name__}"
        try:
            g2 = run_gate2(sql, _ctx(), _Bundle(allowlist))
            g2v = f"pass={g2.gate_result.passed} rule={g2.gate_result.rule_id}"
        except Exception as exc:
            g2v = f"RAISED {type(exc).__name__}"
        print(f"  {name:<16} gate1[{g1v}]  gate2[{g2v}]")


print("########## A. 生产读数（run_gate1 / run_gate2 原样） ##########")

# A1 = 今天生产的实际形态：扁平面（`asset_allowlist` 只给一层，`columns` 已裁 deny、
#      没有 `all_columns`）。gate2 `:105` 直接吃它 ⇒ ⑤ 读 `columns` 找不到 tenant_id。
_one("A1 扁平投影直喂（今天生产：columns=可见、无 all_columns）",
     _allowlist(with_deny_in_visible=False, with_all_columns=False))

# A2 = W2A 形状的形状面（`guard_allowlist` 双面齐）；但 gate2 `:105` 今天还没换方法，
#      为隔离变量这里直接把它喂给 gate2。
_one("A2 形状面双面齐（columns=可见 + all_columns=全列）",
     _allowlist(with_deny_in_visible=False, with_all_columns=True))

# A3 = 反例：`columns` 填全列（= 只给结构面，不裁 deny）
_one("A3 只给结构面（columns=全列、无 all_columns）",
     _allowlist(with_deny_in_visible=True, with_all_columns=False))

# A4 = **真 `asset_allowlist` 的现形态**：`columns` 是**列名元组**（W7 喂的那一档）
_one("A4 真 runtime 扁平面（columns=元组、无 all_columns）",
     _allowlist(with_deny_in_visible=False, with_all_columns=False, flat_tuple=True))


print("\n########## B. 反事实变体（④⑤ 改读 all_columns；非生产实现） ##########")


def _run_gate2_reading_struct_face(sql: str, ctx: IdentityContext, bundle) -> str:
    """把生产 `run_gate2` 的 ④/⑤ 读取面换成 `all_columns` 的等价复刻。

    只用于回答"切了面之后会怎样"，**不是**生产代码；逐行与 `policy_gate.py:139-155` 对齐。
    """

    from app.core.errors import ContractViolationError
    from app.guard.policy_gate import (
        _extract_tables,
        extract_columns_with_assets,
    )

    allowlist = bundle.asset_allowlist(ctx)
    assets = allowlist.get("assets") or {}
    tables = _extract_tables(sql)
    unknown = [t for t in tables if t not in assets]
    if unknown:
        return "rule=G2-ASSET"
    involved = [assets[t] for t in tables]
    if ctx.scope_claims:
        domains = {a.get("domain") for a in involved}
        if not domains <= set(ctx.scope_claims):
            return "refuse=OUT_OF_SCOPE"

    # ④ 切结构面
    deny = frozenset(allowlist.get("deny_columns") or ())
    for logical, col in extract_columns_with_assets(sql, allowlist):
        if f"{logical}.{col}" in deny:
            return "rule=G2-DENY"
    # ⑤ 切结构面
    for asset in involved:
        tenant_scoped = bool(asset.get("tenant_scoped"))
        has_tenant_col = "tenant_id" in (asset.get("all_columns") or {})
        if tenant_scoped != has_tenant_col:
            raise ContractViolationError(
                "语义包 tenant_scoped 与 tenant_id 列不一致（07 §7.4 双向断言）",
                detail={"asset": asset.get("logical_name")},
            )
    return "pass=True"

for label, al in (
    ("B1 双面齐 + ④⑤ 读 all_columns", _allowlist(with_deny_in_visible=False, with_all_columns=True)),
    ("B2 只给可见面 + ④⑤ 读 all_columns（消费方盲改）",
     _allowlist(with_deny_in_visible=False, with_all_columns=False)),
):
    print(f"\n=== {label} ===")
    for name, sql in SQLS.items():
        try:
            out = _run_gate2_reading_struct_face(sql, _ctx(), _Bundle(al))
        except Exception as exc:
            out = f"RAISED {type(exc).__name__}"
        if out == "pass=True":
            out = "pass=True rule=None"
        print(f"  {name:<16} gate2[{out}]")
