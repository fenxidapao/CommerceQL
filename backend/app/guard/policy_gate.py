"""闸门二：策略校验 + scope 计算（07 §7.4）。

归属窗口：W2C（docs/08 §4.1）。**纯函数，禁依赖 LLM**（N-01 / N-03 / R-DEP-2）。

与 gate1 的**故意冗余**（07 §7.4）：gate1 守"生成的 SQL 是否合法"（只看 AST），
gate2 守"这次请求在当前策略快照下是否允许"（看策略快照 + 身份）。两道都是 0.1s 级纯计算。

**`scope.level` 四分支算法（07 §7.4，确定性，禁用 LLM）**：

    1. platform_admin                                  → unrestricted, applied=false
    2. shop_ids 非空                                    → role_limited,  applied=true, notice=固定文案, disclosable=true
    3. 涉及资产启用租户级 RLS（tenant_scoped=true）      → tenant_isolated, applied=true, notice=null, disclosable=false
    4. else                                            → unrestricted, applied=false

⚠️ 分支 3 的判据是"**该资产启用了租户级 RLS**"（对本租户所有用户一视同仁），
**不是**"该用户有额外限制" —— 写反 = 把跨租户不可见当成角色限制下发提示 =
违反 A.1.5 红线 3（跨租户响应必须与"真无数据"不可区分，N-07）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.contracts import GateResult, IdentityContext, ScopeInfo
from app.core.enums import (
    GateDecision,
    GateNo,
    RefuseReason,
    Role,
    ScopeLevel,
)
from app.core.errors import ContractViolationError
from app.guard.ast_gate import strip_comments

if TYPE_CHECKING:
    from app.core.contracts import SemanticBundlePort

__all__ = ["Gate2Report", "run_gate2", "SHOP_LIMITED_NOTICE"]

#: 分支 2 的固定披露文案（附录 A §A.1.5 `meta.scope.notice`）。
#: ⚠️ 07 只规定"固定文案"，未给内容 —— 精确措辞归 06 UI/UX 复核（见 reports/w2c/RELAY.md）。
SHOP_LIMITED_NOTICE: Final[str] = "结果已按你负责的店铺范围过滤"


@dataclass(frozen=True, slots=True)
class Gate2Report:
    """gate2 完整出参。``refuse_reason`` 非 None 时由节点发 `refuse`（07 §7.6.1），
    其余拒绝走 `error(GATE_POLICY_REJECTED)`。"""

    gate_result: GateResult
    scope: ScopeInfo
    #: 数据域越界（out_of_scope）时置值 —— 这是产品结论（refuse），不是工程故障。
    refuse_reason: RefuseReason | None = None


def _pass(scope: ScopeInfo) -> Gate2Report:
    return Gate2Report(
        gate_result=GateResult(
            gate_no=GateNo.POLICY,
            passed=True,
            decision=GateDecision.PASS,
        ),
        scope=scope,
    )


def _reject(rule_id: str, reason: str, scope: ScopeInfo) -> Gate2Report:
    return Gate2Report(
        gate_result=GateResult(
            gate_no=GateNo.POLICY,
            passed=False,
            decision=GateDecision.REJECT,
            rule_id=rule_id,
            reason=reason,
        ),
        scope=scope,
    )


def _refuse(reason: RefuseReason, scope: ScopeInfo) -> Gate2Report:
    return Gate2Report(
        gate_result=GateResult(
            gate_no=GateNo.POLICY,
            passed=False,
            decision=GateDecision.REJECT,
            rule_id="G2-DOMAIN",
            reason="查询涉及的数据范围超出你的权限",
        ),
        scope=scope,
        refuse_reason=reason,
    )


def run_gate2(
    sql: str, ctx: IdentityContext, bundle: SemanticBundlePort
) -> Gate2Report:
    """执行 gate2。入参形状与 ``GuardPort.gate2`` 一致。

    取用面 = ``bundle.guard_allowlist(ctx)``（U-121 第三步；七键形状，
    唯一真相 ``app/core/contracts.py::GuardAllowlist``）。gate1 与 gate2
    **各自取一次是刻意的**（``gate1_ast.py`` docstring）——不要合并。
    """

    allowlist: Mapping[str, Any] = bundle.guard_allowlist(ctx)
    assets: Mapping[str, Any] = allowlist.get("assets") or {}

    # ---- ① 版本一致性（请求固定版本 vs 当前激活版本）----
    snap_version = allowlist.get("bundle_version")
    if snap_version is not None and snap_version != bundle.active_version():
        # 策略快照过期 = 请求锚定的口径已不在服务（07 §5.7 版本固定的反面）。
        unrestricted = ScopeInfo(ScopeLevel.UNRESTRICTED, False, None, True)
        return _reject(
            "G2-VERSION",
            "口径版本已更新，请重新发起提问",
            unrestricted,
        )

    # ---- ② 资产白名单二次复核（只认最终 SQL 的对象引用）----
    tables = _extract_tables(sql)
    unknown = [t for t in tables if t not in assets]
    if unknown:
        unrestricted = ScopeInfo(ScopeLevel.UNRESTRICTED, False, None, True)
        return _reject(
            "G2-ASSET",
            "查询涉及的数据范围超出你的权限",
            unrestricted,
        )

    involved = [assets[t] for t in tables]

    # ---- ③ 数据域覆盖（涉及数据域 ⊆ JWT.scope → 否则 refuse(out_of_scope)）----
    scope_now = _compute_scope(ctx, involved)
    if ctx.scope_claims:
        domains = {a.get("domain") for a in involved}
        if not domains <= set(ctx.scope_claims):
            return _refuse(RefuseReason.OUT_OF_SCOPE, scope_now)

    # ---- ④ 敏感列二次复核（与 gate1 R07 冗余，07 §7.4 原文）----
    # 归属面切**结构面**（U-121 判据⑤的落点约束：结构面只对 gate2 ④ 开；
    # gate1 的列解析必须留在可见面）。可见面已裁 deny 列 ⇒ 直接喂会让
    # 无表别名的 deny 列归属失败 ⇒ ④ 遍历体不执行 = 静默漏检。
    deny: frozenset[str] = frozenset(allowlist.get("deny_columns") or ())
    for logical, col in extract_columns_with_assets(sql, _struct_view(allowlist)):
        if f"{logical}.{col}" in deny:
            return _reject("G2-DENY", "查询包含受保护字段", scope_now)

    # ---- ⑤ tenant_scoped 双向断言（07 §7.4 ⚠️：写反 = N-07 失效）----
    # 读**结构面**（all_columns）：可见面已裁 tenant_id（deny 列），读可见面
    # 会让 tenant_scoped=true 的资产在干净 SQL 上误抛 ContractViolationError。
    for asset in involved:
        tenant_scoped = bool(asset.get("tenant_scoped"))
        has_tenant_col = "tenant_id" in (asset.get("all_columns") or {})
        if tenant_scoped != has_tenant_col:
            raise ContractViolationError(
                "语义包 tenant_scoped 与 tenant_id 列不一致（07 §7.4 双向断言）",
                detail={"asset": asset.get("logical_name")},
            )

    return _pass(scope_now)


def _compute_scope(
    ctx: IdentityContext, involved: list[Mapping[str, Any]]
) -> ScopeInfo:
    """07 §7.4 四分支。顺序即优先级，不可换。"""

    # 分支 1：platform_admin → unrestricted（⚠️ 业务表仍受 DB 层 RLS 约束，见 enums.Role）
    if ctx.role == Role.PLATFORM_ADMIN:
        return ScopeInfo(ScopeLevel.UNRESTRICTED, False, None, True)
    # 分支 2：shop_ids 非空 → role_limited（唯一会向用户披露"行级范围"的情形）
    if ctx.shop_ids:
        return ScopeInfo(ScopeLevel.ROLE_LIMITED, True, SHOP_LIMITED_NOTICE, True)
    # 分支 3：涉及资产任一启用租户级 RLS → tenant_isolated（不提示 —— 防存在性泄露）
    if any(bool(a.get("tenant_scoped")) for a in involved):
        return ScopeInfo(ScopeLevel.TENANT_ISOLATED, True, None, False)
    # 分支 4
    return ScopeInfo(ScopeLevel.UNRESTRICTED, False, None, True)


def _struct_view(allowlist: Mapping[str, Any]) -> Mapping[str, Any]:
    """把 ``assets[].columns`` 顶成结构面（``all_columns``）的**一次性视图**。

    仅供 gate2 ④ 的列归属使用（U-121 判据⑥落点约束：结构面只对 gate2 ④ 开）——
    **不得**传给 gate1：graph 的 gate1 列解析留在可见面（可见面裁剪让**列白名单**
    有效；顶全列会让任意真实列都过 R06）。形状不含 ``all_columns`` 时退回原
    ``columns``（fail-closed 由调用侧 ``deny_columns`` 比对兜底）。
    """

    assets = allowlist.get("assets") or {}
    return {
        **allowlist,
        "assets": {
            key: {
                **asset,
                "columns": dict(asset.get("all_columns") or asset.get("columns") or {}),
            }
            for key, asset in assets.items()
        },
    }


def _extract_tables(sql: str) -> list[str]:
    """从最终 SQL 提取物理表名（供资产二次复核）。

    解析失败时返回空表清单 —— 闸门二不做语法审计（那是 gate1 的职责；
    能到 gate2 的 SQL 必然已过 gate1 —— 若被测直接调 gate2 则语义失真，测试须守此序）。
    """

    try:
        statements = sqlglot.parse(strip_comments(sql), dialect="postgres")
    except ParseError:
        return []
    if len(statements) != 1 or statements[0] is None:
        return []
    root = statements[0]
    cte_names = {c.alias for c in root.find_all(exp.CTE)}
    tables: list[str] = []
    for t in root.find_all(exp.Table):
        if t.name and t.name not in cte_names and t.name not in tables:
            tables.append(t.name)
    return tables


def extract_columns_with_assets(
    sql: str, allowlist: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """提取 ``(逻辑资产名, 列名)`` 对（deny 二次复核用）。

    独立函数而非内联：``allowlist`` 由 bundle 在调用点给出（端口签名无此参数）。
    """

    from app.guard.ast_gate import _Auditor  # 局部 import：避免包内导入环

    try:
        statements = sqlglot.parse(strip_comments(sql), dialect="postgres")
    except ParseError:
        return []
    if len(statements) != 1 or statements[0] is None:
        return []
    root = statements[0]
    auditor = _Auditor(allowlist, frozenset())
    cte_names = {c.alias for c in root.find_all(exp.CTE)}
    pairs: list[tuple[str, str]] = []
    for col in root.find_all(exp.Column):
        resolved = auditor._resolve_column(col, cte_names)
        if resolved is not None:
            (kind, logical, _cols), colname = resolved
            if kind == "asset":
                pairs.append((logical, colname))
    return pairs
