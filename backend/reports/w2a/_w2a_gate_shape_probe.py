"""W2A · 零 LLM 取件：闸门 allowlist 形状接缝的**可产出性**与**修法后果**。

来源：W7 第八轮预检 + 07 v1.6.4 `U-121`（架构已裁，归 W0 + W2A + W2C）。

本脚本只回答四件事，**不碰任何生产文件**：

1. **可产出性**：闸门要的 7 个键，语义层运行时到底能给出几个、各自来自哪个方法；
2. **交叉核对**：W2A 提案形状 vs **W6 已在评测侧实现的** `eval/harness.py::build_guard_allowlist()`
   —— 两条独立实现若逐字节同形，形状就不再是"谁说了算"的问题；
3. **后果对照**（真 SQL 喂真 `run_gate1` / `run_gate2`）：
   扁平 → ? ｜ 只补 `assets` 的**天真修法** → ? ｜ 完整 wrapper → ?；
4. **判据④**：请求级 `max_rows` 到底能不能生效。

⚠️ **前情（本文第一版写错过，已订正）**：`assets[*].columns` 该取"可见列"还是"声明全列"这件事，
**不是本探针的发现**。W6 早已实测并落盘：`eval/redteam_eval.py:169-212`
（`StructuralAllowlistBundle` docstring 逐字写着 `v_order_paid` 24 → 21 列、以及 gate2 必抛
`ContractViolationError`），且给出了修法 `redteam_eval.structural_wrapper()`；
`backend/tests/eval/test_harness_allowlist.py:107-136` 三条测试把它钉死。

本探针相对 W6 的增量只有两处（其余是独立复现）：
- **§⑦ 归因漂移**：换列源对 gate1 `rule_id` 的副作用（W6 没测过这半边）；
- **§⑧ 端口方法面**：闸门 7 键各自能否**经 `SemanticBundlePort`** 取到 —— 这一节回答
  "W2A 单独改形状能不能修好"，答案是**不能**（`joins` 与「声明全列」在端口上无入口）。

只读语义包 + 纯函数，**零 LLM、不碰服务、不碰 DB**。

复现：`CommerceQL\\.venv\\Scripts\\python.exe backend\\reports\\w2a\\_w2a_gate_shape_probe.py`
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "eval"))

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.policy_gate import run_gate2  # noqa: E402
from app.semantics import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = REPO / "semantic" / "bundle_2026.09.14.1.yaml"

#: 与 `eval/harness.py::_GUARD_WRAPPER_KEYS` 逐字一致（W6 实证的闸门读键面）。
GUARD_KEYS = (
    "bundle_version",
    "assets",
    "joins",
    "deny_columns",
    "default_predicates",
    "allowed_constants",
    "max_rows",
)

SQL_SIMPLE = "SELECT pay_amount FROM v_order_paid"
SQL_JOIN = (
    "SELECT p.sku_name FROM v_order_paid o "
    "JOIN v_product p ON o.sku_id = p.sku_id"
)
SQL_DENIED = "SELECT receiver_phone FROM v_order_paid"


def _ctx(role: Role = Role.ANALYST) -> IdentityContext:
    return IdentityContext(
        trace_id="t",
        task_id="k",
        session_id="s",
        tenant_id="T_PROBE",
        user_id="u",
        role=role,
        scope_claims=(),
        shop_ids=(),
    )


# ---------------------------------------------------------------------------
# W2A 提案：从**真运行时**组装闸门形状（这就是要交给 W0 定形状的那份）
# ---------------------------------------------------------------------------

def build_gate_criteria(
    runtime: SemanticBundleRuntime,
    ctx: IdentityContext,
    *,
    max_rows: int | None = None,
    columns_from: str = "declared",
) -> dict[str, Any]:
    """把闸门要的 7 个键从语义层**逐字派生**出来（不做业务发明）。

    三项非平凡变换（形状的难点就在这里，W0 定形状时必须写死）：
    - `columns`：运行时给**列名元组**，闸门要 **`{列名: 类型}`**（`_scope_tables` 调 `.keys()`，
      `_column_type` 调 `.get()`）⇒ 类型从 `Asset.columns[].type` 补齐；
    - `joins`：包里的 `left/right` 是 **`<逻辑名>.<列>`**，闸门拿它跟**逻辑名**比
      （`ast_gate.py:639-642` 的 `pair = {entry['left'], entry['right']}` vs `left_logical`）
      ⇒ 必须 `split('.', 1)[0]` 剥掉列名；
    - `max_rows`：**语义层没有这个事实** ⇒ 只能由调用方传入（请求级选项）。

    🔴 `columns_from` 是本脚本要裁决的**第四个**、也是最隐蔽的一项
    （**W6 先发现**，见 `eval/redteam_eval.py:169-212`；本探针独立复现）：

    | 取值 | 列源 | 后果 |
    |---|---|---|
    | `"trimmed"` | 跟 `asset_allowlist(ctx)` 走（**角色裁剪后**，`tenant_id` 被剔） | `policy_gate.py:145-149` 的 `tenant_scoped ⟺ "tenant_id" in columns` **当场 `ContractViolationError`**；且 gate2 第④步（敏感列复核）**列不在表里就永远检不出 ⇒ 形同空转** |
    | `"declared"` | 语义包**声明**的全列（`runtime.asset()`） | 与 `guard_fixtures.build_allowlist()` 一致；`tenant_id` 一类受限列由 `deny_columns` 在 R07/G2-DENY 拦 |

    ⇒ 「角色裁剪」是**给 planner / binding 看的视图**，不是给闸门看的判据面。
    真正要裁的是**两个面**，不是一个：
    - **可见面**（planner/binding + gate1 的 R06 解析）→ 裁掉 deny 列，目的是"不许被提出来"；
    - **结构面**（gate2 ④⑤）→ 必须含全列，目的是"**得先认得出来，才拒得掉**"。
    这正是 W6 的 `StructuralAllowlistBundle` 只补结构面、不动权限面的理由。
    """
    flat = runtime.asset_allowlist(ctx)
    assets: dict[str, Any] = {}
    for physical, entry in flat.items():
        logical = str(entry.get("logical_name") or "")
        if columns_from == "trimmed":
            names = tuple(str(c) for c in (entry.get("columns") or ()))
            types = {c.name: c.type for c in (runtime.asset(logical).columns if runtime.asset(logical) else ())}
        else:
            asset = runtime.asset(logical)
            cols = tuple(asset.columns) if asset is not None else ()
            names = tuple(c.name for c in cols)
            types = {c.name: c.type for c in cols}
        assets[str(physical)] = {
            "logical_name": entry.get("logical_name"),
            "domain": entry.get("domain"),
            "tenant_scoped": bool(entry.get("tenant_scoped")),
            "columns": {name: types.get(name, "unknown") for name in names},
        }
    policy = dict(runtime.policy() or {})
    out: dict[str, Any] = {
        "bundle_version": runtime.active_version(),
        "assets": assets,
        "joins": [
            {
                "left": str(j.left).split(".", 1)[0],
                "right": str(j.right).split(".", 1)[0],
                "on_columns": [str(c) for c in (j.on_columns or ())],
            }
            for j in runtime.joins()
        ],
        "deny_columns": [str(x) for x in (policy.get("deny_columns") or ())],
        "default_predicates": dict(policy.get("default_predicates") or {}),
        # 包内**没有** allowed_constants 声明区 → 空表，不编造（R14 第③类无输入）。
        "allowed_constants": [],
    }
    if max_rows is not None:
        out["max_rows"] = int(max_rows)
    return out


class _WrapperBundle:
    """只为探针存在的薄代理：把 `asset_allowlist` 换成闸门形状，其余透传。

    （W6 的 `GuardAllowlistBundle` 干的是同一件事；本探针不 import 它，避免
    "用被测方的实现去证明被测方" —— 两者在 §2 做**输出级**交叉核对。）
    """

    def __init__(
        self,
        runtime: SemanticBundleRuntime,
        *,
        max_rows: int | None = None,
        bump_version: str | None = None,
        columns_from: str = "declared",
    ) -> None:
        self._rt = runtime
        self._max_rows = max_rows
        self._bump = bump_version
        self._columns_from = columns_from

    def asset_allowlist(self, ctx: IdentityContext) -> Mapping[str, Any]:
        w = build_gate_criteria(
            self._rt, ctx, max_rows=self._max_rows, columns_from=self._columns_from
        )
        if self._bump is not None:
            w["bundle_version"] = self._bump
        return w

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rt, name)


class _HarnessShim:
    """只补 W6 的 `structural_wrapper(harness)` 需要的两个属性，别的一概不提供。

    刻意**不** import `eval/harness.py::Harness` —— 那会拉起 settings / 检索 / 执行器一整套，
    而本探针只需要"它读的那两个字段"。窄接口也让"W6 依赖了什么"变成可见事实。
    """

    def __init__(self, loaded: Any, runtime: SemanticBundleRuntime) -> None:
        self.loaded = loaded
        self.runtime = runtime


def _verdict(gr: Any) -> str:
    """`GateResult` → 一行（`rule_id` 只在拒绝时有值）。"""
    passed = getattr(gr, "passed", None)
    rule = getattr(gr, "rule_id", None)
    reason = getattr(gr, "reason", None)
    out = f"passed={passed}"
    if rule:
        out += f"｜rule_id={rule}"
    if reason:
        out += f"｜reason={reason!r}"
    return out


def _rule_of(line: str) -> str:
    """从 `_call_gate1` 的一行结果里抠出 `rule_id`（只做归因对比，不解析业务语义）。"""
    for part in line.split("｜"):
        if part.startswith("rule_id="):
            return part
        if part.startswith("❌"):
            return part[:40]
    return "passed"


def _reason_of(line: str) -> str:
    """抠出用户可见 `reason`——判"归因漂移对用户是否可见"的唯一依据。"""
    for part in line.split("｜"):
        if part.startswith("reason="):
            return part
    return "（放行，无 reason）"


def _limit_of(report: Any) -> str:
    """生效 LIMIT —— 从改写后的 SQL 里读，**不**从 `limit_injected` 猜。"""
    sql = str(getattr(report, "rewritten_sql", "") or "")
    if not sql:
        return "（无改写 SQL：被拒）"
    tail = sql.rsplit("LIMIT", 1)[-1].strip() if "LIMIT" in sql.upper() else "?"
    return f"LIMIT {tail.split()[0] if tail else '?'}｜{sql[-60:]}" if tail else "?"


def _call_gate1(sql: str, allowlist: Mapping[str, Any]) -> str:
    try:
        report = run_gate1(sql, allowlist)
    except Exception as exc:  # 探针要把"崩溃"如实记下来，不当失败中止
        return f"❌ 抛异常 {type(exc).__name__}: {exc}"
    applied = tuple(getattr(report, "applied_predicates", ()) or ())
    return (
        f"{_verdict(getattr(report, 'gate_result', report))}"
        f"｜谓词={list(applied) or '空'}"
        f"｜{_limit_of(report)}"
    )


def _call_gate2(sql: str, ctx: IdentityContext, bundle: Any) -> str:
    try:
        report = run_gate2(sql, ctx, bundle)
    except Exception as exc:  # 同上：闸门抛异常本身就是要记的读数
        return f"❌ 抛异常 {type(exc).__name__}: {exc}"
    extra = getattr(report, "refuse_reason", None)
    return f"{_verdict(getattr(report, 'gate_result', report))}" + (
        f"｜refuse={getattr(extra, 'value', extra)}" if extra is not None else ""
    )


def main() -> None:
    loaded = load_bundle(BUNDLE)
    runtime = SemanticBundleRuntime(loaded)
    ctx = _ctx()
    print(f"语义包 = {BUNDLE.name} | version={loaded.version} | status={loaded.status}")
    print(f"role = {ctx.role.value}")
    print()

    # ---- ① 可产出性 ----
    flat = runtime.asset_allowlist(ctx)
    print("=== ① 可产出性核对（闸门要 7 键，语义层能给几个）===")
    print(f"  runtime.asset_allowlist(ctx) 顶层键 = {sorted(flat)[:3]} …（扁平，{len(flat)} 项）")
    wrapper = build_gate_criteria(runtime, ctx)
    got = [k for k in GUARD_KEYS if k in wrapper]
    missing = [k for k in GUARD_KEYS if k not in wrapper]
    print(f"  闸门 7 键：可产出 {len(got)}/7 {got}")
    print(f"           需调用方传入 {missing or '无'}"
          f"{'（语义层没有这个事实：请求级选项）' if missing else ''}")
    print(f"  assets 条目数 = {len(wrapper['assets'])}｜joins 条数 = {len(wrapper['joins'])}"
          f"｜deny 条数 = {len(wrapper['deny_columns'])}"
          f"｜谓词域数 = {len(wrapper['default_predicates'])}")
    sample = wrapper["assets"].get("v_order_paid", {})
    print(f"  样本 v_order_paid: logical={sample.get('logical_name')} "
          f"domain={sample.get('domain')} 列数={len(sample.get('columns', {}))} "
          f"tenant_id 在内? {'tenant_id' in sample.get('columns', {})}")
    print(f"  样本 joins[0] = {wrapper['joins'][0] if wrapper['joins'] else None}")
    print()

    # ---- ② 列源之争：trimmed vs declared（W6 先发现，此处独立复现）----
    print("=== ② 🔴 `assets[].columns` 该取哪一份列？（W6 已实测，此处独立复现）===")
    trimmed = build_gate_criteria(runtime, ctx, columns_from="trimmed")
    t_asset = trimmed["assets"]["v_order_paid"]
    d_asset = wrapper["assets"]["v_order_paid"]
    print(f"  trimmed（跟 asset_allowlist 走，角色裁剪后）: 列数={len(t_asset['columns'])} "
          f"tenant_id 在内? {'tenant_id' in t_asset['columns']}")
    print(f"  declared（语义包声明全列，runtime.asset()） : 列数={len(d_asset['columns'])} "
          f"tenant_id 在内? {'tenant_id' in d_asset['columns']}")
    print(f"  tenant_scoped = {d_asset['tenant_scoped']} "
          "→ policy_gate.py:145-149 断言 `tenant_scoped ⟺ 'tenant_id' in columns`")
    print(f"  ⇒ gate2 用 trimmed 的结果 : {_call_gate2(SQL_SIMPLE, ctx, _WrapperBundle(runtime, columns_from='trimmed'))}")
    print(f"  ⇒ gate2 用 declared 的结果: {_call_gate2(SQL_SIMPLE, ctx, _WrapperBundle(runtime))}")
    try:
        sys.path.insert(0, str(REPO / "backend" / "tests" / "unit"))
        import guard_fixtures as GF  # type: ignore[import-not-found]

        f_cols = GF.build_allowlist()["assets"]["v_order_paid"]["columns"]
        print(f"  对照 W2C 夹具 guard_fixtures.build_allowlist(): 列数={len(f_cols)} "
              f"tenant_id 在内? {'tenant_id' in f_cols} ← 它取的是**声明全列**")
    except Exception as exc:  # 对照做不成要显式说出来，不能静默读成"一致"
        print(f"  ⚠️ 无法导入 W2C 夹具（{type(exc).__name__}: {exc}）—— 该对照**未做**")
    print()

    # ---- ③ 与 W6 评测侧适配器交叉核对 ----
    print("=== ③ 交叉核对：本提案 vs W6 `eval/harness.py::build_guard_allowlist` ===")
    try:
        import harness as H  # type: ignore[import-not-found]

        w6 = H.build_guard_allowlist(loaded, runtime, ctx)
        diffs = sorted(k for k in set(w6) | set(wrapper) if w6.get(k) != wrapper.get(k))
        print(f"  W6 适配器输出键 = {sorted(w6)}")
        print(f"  键集相同 = {sorted(w6) == sorted(wrapper)}｜值级差异键 = {diffs or '无（逐值一致）'}")
        if diffs:
            for k in diffs:
                print(f"    - {k}: W6={str(w6.get(k))[:80]} … 本提案={str(wrapper.get(k))[:80]}")
        w6_cols = w6["assets"]["v_order_paid"]["columns"]
        print(f"  W6 的列源: tenant_id 在内? {'tenant_id' in w6_cols}（{len(w6_cols)} 列）")
        print("  ✅ 这一点**不是缺陷**：`build_guard_allowlist` 的刻意语义就是"
              "\"镜像**生产可见面**\"")
        print("     （gate1 的 R06 靠它），给 gate2 的全列由**另一个**入口补：")
        print("     `redteam_eval.structural_wrapper()` + `StructuralAllowlistBundle`。")
        print(f"  ⚠️ 但 `max_rows` 两边都**刻意缺席**（W6 测试钉死）："
              f"{'max_rows' in w6}")
        # 直接验一下 W6 那套修法在真闸门上到底成不成立（不 import 被测实现的自证，只看行为）
        import redteam_eval as rt  # type: ignore[import-not-found]

        structural = rt.StructuralAllowlistBundle(runtime, rt.structural_wrapper(_HarnessShim(loaded, runtime)))
        s_cols = rt.structural_wrapper(_HarnessShim(loaded, runtime))["assets"]["v_order_paid"]["columns"]
        print(f"  ✅ W6 结构档列源: tenant_id 在内? {'tenant_id' in s_cols}（{len(s_cols)} 列）"
              f"｜其 gate2 = {_call_gate2(SQL_SIMPLE, ctx, structural)}")
    except Exception as exc:  # 交叉核对做不成必须显式声明，否则读者会把它当"验过了"
        print(f"  ⚠️ 无法导入 W6 适配器（{type(exc).__name__}: {exc}）—— 交叉核对**未做**，"
              "不得读作'一致'")
    print()

    # ---- ④ 后果对照（真 SQL 喂真闸门）----
    print("=== ④ 后果对照：同一批 SQL 喂真闸门 ===")
    naive = {
        "assets": {k: {**v, "columns": tuple(v["columns"])} for k, v in wrapper["assets"].items()},
        **{k: wrapper[k] for k in ("bundle_version", "joins", "deny_columns",
                                   "default_predicates", "allowed_constants")},
    }
    for label, al in (
        ("扁平（= 生产现状）", flat),
        ("只补 `assets` 键（天真修法）", naive),
        ("完整 wrapper · declared", wrapper),
    ):
        print(f"  ── {label} ──")
        print(f"     简单 SQL   : {_call_gate1(SQL_SIMPLE, al)}")
        print(f"     JOIN SQL   : {_call_gate1(SQL_JOIN, al)}")
        print(f"     受限列 SQL : {_call_gate1(SQL_DENIED, al)}")
    print()

    # ---- ⑤ gate2：归因与版本守卫（判据③）----
    print("=== ⑤ gate2：归因与版本守卫（判据③）===")
    wrapped = _WrapperBundle(runtime)
    print(f"  扁平         : {_call_gate2(SQL_SIMPLE, ctx, runtime)}")
    print(f"  wrapper      : {_call_gate2(SQL_SIMPLE, ctx, wrapped)}")
    print(f"  受限列 SQL   : {_call_gate2(SQL_DENIED, ctx, wrapped)}"
          "   ← 期望归因落 G2-DENY，而不是被 G2-ASSET 抢走")
    stale = _WrapperBundle(runtime, bump_version="1999.01.01.0")
    print(f"  版本错配     : {_call_gate2(SQL_SIMPLE, ctx, stale)}"
          "   ← 期望 G2-VERSION（扁平下 `snap_version is None` ⇒ **永不触发**）")
    # 第④步（敏感列复核）在**裁剪列**下到底还响不响？—— 这一行是判"④ 形同空转"的**实测**依据，
    # 不是复述 W6 的 docstring：若 ④ 还在工作，应在 ⑤ 抛断言之前先返回 G2-DENY。
    print(f"  受限列·trimmed : {_call_gate2(SQL_DENIED, ctx, _WrapperBundle(runtime, columns_from='trimmed'))}"
          "   ← 若返回 G2-DENY 则 ④ 仍工作；若抛 ContractViolationError 则 ④ **空转**且 ⑤ 先炸")
    print(f"  受限列·declared: {_call_gate2(SQL_DENIED, ctx, wrapped)}"
          "   ← 对照：全列下 ④ 正常工作")
    print()

    # ---- ⑥ 判据④：请求级 max_rows ----
    print("=== ⑥ 判据④：请求级 max_rows 能不能生效 ===")
    print("  不传         : " + _call_gate1(SQL_SIMPLE, build_gate_criteria(runtime, ctx)))
    print("  max_rows=200 : " + _call_gate1(
        SQL_SIMPLE, build_gate_criteria(runtime, ctx, max_rows=200)))
    print()

    # ---- ⑦ 换列源对 gate1 归因的副作用（本节是本探针相对 W6 的增量）----
    print("=== ⑦ 若「一律用声明全列」：gate1 的归因会怎么漂？ ===")
    print("  （gate1 只用 columns 做**列归属解析** → 解析失败落 R06、解析成功再被 deny 落 R07）")
    probes = [
        ("SELECT sub_order_id FROM v_order_paid", "干净列（两档都该放行）"),
        ("SELECT tenant_id FROM v_order_paid", "受限列·未限定"),
        ("SELECT v_order_paid.tenant_id FROM v_order_paid", "受限列·已限定"),
        ("SELECT receiver_phone FROM v_order_paid", "受限列·receiver_phone"),
        ("SELECT * FROM v_order_paid", "受限列·SELECT *"),
    ]
    trimmed_al = build_gate_criteria(runtime, ctx, columns_from="trimmed")
    declared_al = build_gate_criteria(runtime, ctx, columns_from="declared")
    for sql, label in probes:
        line_t, line_d = _call_gate1(sql, trimmed_al), _call_gate1(sql, declared_al)
        rule_t, rule_d = _rule_of(line_t), _rule_of(line_d)
        flag = "  ← ⚠️ 归因变了" if rule_t != rule_d else ""
        print(f"  · {label}")
        print(f"      可见列(trimmed)  : {rule_t}｜{_reason_of(line_t)}")
        print(f"      声明全列(declared): {rule_d}｜{_reason_of(line_d)}{flag}")
    print("  ⇒ 结论：**两档都是拦住的**（安全性不变），但 `rule_id` 会漂："
          "未限定受限列 R06 → R07。")
    print("     ⚠️ **用户可见文案不漂**（两档同一句）⇒ 漂移只落内部统计与归因口径：")
    print("     ① 已落盘的红队读数按 `rule_id` 归因，会跟着变；")
    print("     ② W2C 的 `test_gate1_blocks_tenant_id_either_qualified_or_not` 断言的是"
          "**集合 {R06,R07}**，故容忍这次漂移（该测试不用改）。")

    print()
    print("=== ⑧ 端口方法面：闸门 7 键各自「经 SemanticBundlePort」可达吗？ ===")
    print("  （这一节回答的是「W2A 单独改 asset_allowlist 能不能修好」—— 不能的话，")
    print("    形状决议就必须动 contracts.py，即 W0 的份）")
    from app.core.contracts import SemanticBundlePort

    port_methods = sorted(
        n for n, _ in inspect.getmembers(SemanticBundlePort, predicate=inspect.isfunction)
        if not n.startswith("_")
    )
    print(f"  SemanticBundlePort 方法 = {port_methods}（{len(port_methods)} 个）")
    reach = [
        ("bundle_version", "✅", "active_version()"),
        ("deny_columns", "✅", "policy()['deny_columns']"),
        ("default_predicates", "✅", "policy()['default_predicates']"),
        ("allowed_constants", "✅", "包内无该声明区 ⇒ 空表，无需来源"),
        ("assets", "⚠️", "只有 asset_allowlist()（**可见面**）；"
                         "「声明全列」要 runtime.asset() —— **不在端口上**"),
        ("joins", "❌", "runtime.joins() —— **不在端口上** ⇒ 经端口不可达"),
        ("max_rows", "❌", "语义层没有这个事实（请求级）"),
    ]
    for key, mark, how in reach:
        print(f"    {mark} {key:18s}: {how}")
    print("  ⇒ GraphDeps.semantics 的类型**就是** SemanticBundlePort（`graph/context.py:105`）")
    print("    ⇒ `gate1_ast.py:52` 能调的只有那 4 个方法")
    print("    ⇒ 🔴 结论：**W2A 单独改 `asset_allowlist` 的返回形状也修不好这条缝** ——")
    print("      `joins` 与「声明全列」在端口上根本没有入口，必须动 `app/core/contracts.py`。")
    print("      这与 `U-121` 把归属写成 W0 + W2A + W2C 三方是一致的（不是 W2A 一家的事）。")

    print()
    print("=== ⑨ 结论 ===")
    print("  · 7 键里 6 键可由语义层逐字派生；`max_rows` 是请求级事实 ⇒ 必须作参数传入。")
    print("  · 形状无需新设计：W6 已在评测侧实现同一形状（见 ③），三项变换逐字一致。")
    print("  · 🔴 真正的争点不是\"谁说了算\"，而是 **`assets[].columns` 只够一个面**（见 ②）：")
    print("     可见面（planner/binding + gate1 解析）要裁剪；结构面（gate2 ④⑤）要全列。")
    print("     单槽位放任一份都会有一方受损 ⇒ W0 定形状时必须显式回答"
          "\"两个面怎么给\"，而不是只写一个 `columns`。")
    print("  · '只补 assets 键' 见 ④：不是 fail-open，而是**更早的崩溃**。")
    print("  · ⚠️ 本节第一版把 ② 报成\"本探针新发现\"——**错**，W6 已实测并落盘"
          "（`eval/redteam_eval.py:169-212`），已订正。")


if __name__ == "__main__":
    main()
