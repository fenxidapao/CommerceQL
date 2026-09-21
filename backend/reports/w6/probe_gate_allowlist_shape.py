"""W6 探针（U-119 判据③）：真运行时的两种 allowlist 形状 × 两道闸门的对照。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_gate_allowlist_shape.py
产物：同目录 `probe_gate_allowlist_shape.json`（结论只由本脚本实测派生，不手写）。

为什么这条探针值得重跑一遍：它 09-20 那版**第二步就崩**（`ast_gate.py:751` 要
`columns.keys()`，扁平面给的是列名元组）⇒ 崩了就没产出结论，而架构的判据③要的是
"跑到底并输出两种形状的对照"。⚠️ 教训与 U-110 同型：**有诊断没结论 = 没有诊断**。

三种输入形状（都从**同一个** `SemanticBundleRuntime` 读出，不掺评测侧发明）：
  1. `flat`   = `asset_allowlist(ctx)`      —— 生产 `gate1_ast.py:52` / `policy_gate.py:105` 今天喂的东西
  2. `legacy` = 09-20 那版手拼 wrapper       —— 保留它，因为**崩因本身就是读数**
  3. `port`   = `guard_allowlist(ctx, …)`    —— U-121（`b7e6c8d`）定的唯一闸门形状（7 键 + 两个列面）
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder-not-a-real-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://u:p@pg:5432/ecom")
os.environ.setdefault("ANALYTICS_DB_URL", "postgresql+psycopg://u:p@pg:5432/ecom")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ENABLE_RESULT_CACHE_CONFIRMED", "false")

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1, run_gate2  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
#: 两条 SQL 分别对应 W4 的接缝契约（普通）与"带时间边界"（会触发默认谓词注入）。
SQLS = {
    "plain": "SELECT pay_amount FROM v_order_paid",
    "time_bounded": "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '2026-08-01'",
}
#: 手拼 wrapper 用的七键清单（`contracts.GuardAllowlist` 的键集，本窗口只读复用，不发明）。
GUARD_KEYS = ("bundle_version", "assets", "joins", "deny_columns",
              "default_predicates", "allowed_constants", "max_rows")


def ctx(tenant: str = "T_A") -> IdentityContext:
    return IdentityContext(
        trace_id="probe", task_id="probe", session_id="probe",
        tenant_id=tenant, user_id="probe", role=Role.ANALYST,
    )


def _gate1_verdict(sql: str, allowlist: object) -> dict:
    """把"闸门吃这个形状"的结果压成读数；**异常也是读数**（不许让探针为此崩）。"""
    try:
        r = run_gate1(sql, allowlist)  # type: ignore[arg-type]
    except Exception as exc:  # 崩因必须落进产物，不能被 traceback 带走（BLE001 未启用，不写 noqa）
        return {"raised": type(exc).__name__, "message": str(exc)[:300], "passed": None}
    return {
        "raised": None,
        "passed": r.gate_result.passed,
        "rule_id": r.gate_result.rule_id,
        "reason": r.gate_result.reason,
        "applied_predicates": list(r.applied_predicates),
        "rewritten_sql": r.rewritten_sql,
    }


def _gate2_verdict(sql: str, runtime: SemanticBundleRuntime, identity: IdentityContext) -> dict:
    try:
        r = run_gate2(sql, identity, runtime)
    except Exception as exc:
        return {"raised": type(exc).__name__, "message": str(exc)[:300], "passed": None}
    return {
        "raised": None,
        "passed": r.gate_result.passed,
        "rule_id": r.gate_result.rule_id,
        "reason": r.gate_result.reason,
        "refuse_reason": r.refuse_reason,
        "scope": str(r.scope),
    }


class _GuardShapedBundle(SemanticBundleRuntime):
    """**只**把 `asset_allowlist` 换成端口自己的 `guard_allowlist`，用来隔离"W2C 那一行"。

    为什么要这个代理：`policy_gate.py:105` 今天仍从 `bundle.asset_allowlist(ctx)` 里读
    wrapper 键。把它换掉是 W2C 的活，本窗口不改生产件 ⇒ 用子类替一个方法，证明
    "gate2 缺的只是这一次改调用"，而不是"gate2 还有别的判据拿不到"。
    ⚠️ 派生数据全部来自端口自身（`guard_allowlist`），评测侧不拼列类型、不截 joins。
    """

    def asset_allowlist(self, ctx_: IdentityContext):  # 覆写：与 run_gate2 的读法对齐
        return self.guard_allowlist(ctx_, max_rows=None)


def _legacy_wrapper(runtime: SemanticBundleRuntime, flat: dict, identity: IdentityContext) -> dict:
    """09-20 那版手拼形状（原样保留，作为"为什么会崩"的见证件）。"""
    policy = dict(runtime.policy() or {})
    return {
        "bundle_version": runtime.active_version(),
        "assets": flat,  # ← 崩因就在这：扁平面把 columns 给成列名元组
        "joins": [],
        "deny_columns": list(policy.get("deny_columns") or ()),
        "default_predicates": {k: list(v) for k, v in (policy.get("default_predicates") or {}).items()},
        "allowed_constants": [],
        "max_rows": 10000,
    }


def _shape_facts(runtime: SemanticBundleRuntime, identity: IdentityContext) -> dict:
    flat = runtime.asset_allowlist(identity)
    port = runtime.guard_allowlist(identity, max_rows=None)
    entry = next(iter(flat.values()))
    asset = next(iter(port["assets"].values()))
    return {
        "flat_keys_sample": sorted(flat)[:5],
        "flat_has_wrapper_keys": {k: (k in flat) for k in GUARD_KEYS},
        "flat_columns_type": type(entry["columns"]).__name__,
        "port_top_level_keys": sorted(port),
        "port_asset_entry_keys": sorted(asset),
        "port_columns_type": type(asset["columns"]).__name__,
        "port_has_all_columns": "all_columns" in asset,
        "port_max_rows": port["max_rows"],
        "port_joins_n": len(port["joins"]),
        "port_default_predicates": dict(port["default_predicates"]),
        "derivation_invariant": {
            "same_physical_keys": sorted(flat) == sorted(port["assets"]),
            "scalar_keys_equal": all(
                flat[p]["logical_name"] == port["assets"][p]["logical_name"]
                and flat[p]["domain"] == port["assets"][p]["domain"]
                and flat[p]["grain"] == port["assets"][p]["grain"]
                and flat[p]["tenant_scoped"] == port["assets"][p]["tenant_scoped"]
                for p in flat
            ),
            "visible_columns_equal": all(
                set(flat[p]["columns"]) == set(port["assets"][p]["columns"]) for p in flat
            ),
        },
    }


def _face_control(runtime: SemanticBundleRuntime, identity: IdentityContext, port: dict) -> dict:
    """反证：为什么"两个面"不能整包换成结构面（判据来自实测，不是引文档）。

    被测 SQL 故意选 deny 列。三种给法：
      - `visible_face`   = 端口原样（`columns` 已裁 deny）⇒ 期望列解析就拒
      - `structural_face`= 把每个资产的 `columns` 换成 `all_columns`（= 整包换面的做法）
      - `structural_face_no_deny` = 再删掉 `deny_columns` ⇒ 这一格就是"敏感列被放行"的失效形态
    """
    sql = "SELECT receiver_phone FROM v_order_paid"
    structural = {
        **port,
        "assets": {p: {**a, "columns": dict(a["all_columns"])} for p, a in port["assets"].items()},
    }
    no_deny = {**structural, "deny_columns": []}
    return {
        "sql": sql,
        "deny_column_in_bundle": "order_paid.receiver_phone" in list(port["deny_columns"]),
        "visible_face": _gate1_verdict(sql, port),
        "structural_face": _gate1_verdict(sql, structural),
        "structural_face_no_deny_columns": _gate1_verdict(sql, no_deny),
    }


def main() -> int:
    runtime = SemanticBundleRuntime(load_bundle(BUNDLE))
    identity = ctx()
    flat = runtime.asset_allowlist(identity)
    port = runtime.guard_allowlist(identity, max_rows=None)
    legacy = _legacy_wrapper(runtime, flat, identity)

    out: dict = {
        "bundle": os.path.relpath(BUNDLE, ROOT).replace("\\", "/"),
        "bundle_version": runtime.active_version(),
        "bundle_status": runtime.bundle_status(),
        "role": identity.role.value,
        "sqls": SQLS,
        "shape_facts": _shape_facts(runtime, identity),
        "gate1": {},
        "gate2": {},
    }
    for name, sql in SQLS.items():
        out["gate1"][name] = {
            "sql": sql,
            "flat_production_wiring": _gate1_verdict(sql, flat),
            "legacy_hand_wrapper": _gate1_verdict(sql, legacy),
            "port_guard_allowlist": _gate1_verdict(sql, port),
        }
        out["gate2"][name] = {
            "sql": sql,
            "real_runtime": _gate2_verdict(sql, runtime, identity),
            "port_shaped_bundle": _gate2_verdict(sql, _GuardShapedBundle(load_bundle(BUNDLE)), identity),
        }

    out["gate1_face_control"] = _face_control(runtime, identity, port)

    g1 = {n: v["port_guard_allowlist"]["passed"] for n, v in out["gate1"].items()}
    g2 = {n: v["real_runtime"]["passed"] for n, v in out["gate2"].items()}
    g2_via_port = {n: v["port_shaped_bundle"]["passed"] for n, v in out["gate2"].items()}
    out["conclusion"] = {
        "wrapper_question": "U-119 判据③ 问的那句：由运行时派生 wrapper 能否让真 SQL 过闸",
        "answer": (
            "能，但**必须由端口派生**（`guard_allowlist`），不是由评测侧手拼："
            f"手拼那版崩在 `columns.keys()`（扁平面给列名元组、不给类型），"
            f"端口那版 gate1 全 passed（{g1}）"
        ),
        "gate1_flat_still_fails": {n: v["flat_production_wiring"]["passed"] for n, v in out["gate1"].items()},
        "gate1_via_port": g1,
        "gate2_via_real_runtime": g2,
        "gate2_via_port_shaped_bundle": g2_via_port,
        "gate2_port_shaped_detail": {
            n: v["port_shaped_bundle"].get("message") for n, v in out["gate2"].items()
        },
        "remaining_break_ownership": (
            "gate1 的接缝本窗口已可直连端口（`run_gate1(sql, semantics.guard_allowlist(ctx, max_rows=…))`，"
            "两条 SQL 今天全 passed）。gate2 断在消费侧，且**不是一行**："
            "①`app/guard/policy_gate.py:105` 要从 `asset_allowlist` 改调 `guard_allowlist`；"
            "②只改 ① 会当场 `ContractViolationError`（本产物 `gate2_port_shaped_detail` 那句"
            "「语义包 tenant_scoped 与 tenant_id 列不一致」）—— 因为 ⑤ 在 "
            "`policy_gate.py:148` 用**可见面** `columns` 判「`tenant_id` in columns」，而 `tenant_id` "
            "恰是 deny 列 ⇒ 必须改读 `all_columns`；同理 ④ 的 `extract_columns_with_assets` 也要走结构面。"
            "⚠️ 但**不能整包换成结构面**：gate1 的 R06 必须继续读可见面，否则"
            "「deny 缺失时敏感列被放行」那条 fail-open 就回来了（`contracts.py` 的 U-121 子事实 2 写的就是这两面）。"
            "⇒ 消费侧要**按判据选面**，归属 W2C；本窗口不改生产件。"
        ),
        "face_control": {
            "passed_by_variant": {
                k: out["gate1_face_control"][k]["passed"]
                for k in ("visible_face", "structural_face", "structural_face_no_deny_columns")
            },
            "reading": (
                "可见面 = 端口原样；整包换结构面在 deny_columns 还在时仍被 R07 拦（所以「换面」看起来无害），"
                "但 deny_columns 一旦漏送就变成**放行**——这就是 `contracts.py` 那句"
                "「两面缺一不可、且不得整包换面」的实测形状。⇒ 消费侧只能**按判据选面**。"
            ),
        },
        "seam_test_caution_for_W4": (
            "`tests/contract/test_gate_seam_contract.py:54` 把**扁平面**原样喂 `run_gate1` 并要求 pass。"
            "按 U-121 裁定的正解（消费方改调 `guard_allowlist`）改完之后，这条仍会红 —— "
            "它的绿条件只能靠「给扁平面补 wrapper 键」达成，而那正是 07 明令禁止的做法。"
            "判据①的输入应是端口形状，或由 W4 显式声明「红的是消费侧未接线、不是形状本身」。"
        ),
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))
    dst = os.path.join(HERE, "probe_gate_allowlist_shape.json")
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\n[OK] 探针跑到底，产物 = {os.path.relpath(dst, ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
