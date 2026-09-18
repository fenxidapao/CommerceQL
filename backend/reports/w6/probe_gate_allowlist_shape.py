"""W6 探针：在线 `guard` 与真实 `SemanticBundleRuntime` 的 allowlist 形状是否对齐。

结论用途：评测执行器必须 import 在线闸门（ADR-18），而 `run_gate1/run_gate2` 的入参形状
写在 `app/guard/ast_gate.py` 模块 docstring（`{"assets":…, "default_predicates":…, …}`），
`SemanticBundleRuntime.asset_allowlist(ctx)` 实测回的是**扁平** `{物理名: {...}}`。
本探针把两边的实际形状打出来，并验证"由运行时派生 wrapper"是否能让真 SQL 过闸。

跑法：CommerceQL 根目录下
    .venv/Scripts/python.exe backend/reports/w6/probe_gate_allowlist_shape.py
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
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

SQL = "SELECT SUM(pay_amount) FROM v_order_paid WHERE pay_time >= '2026-08-01'"


def ctx(tenant: str = "T_A") -> IdentityContext:
    return IdentityContext(
        trace_id="probe", task_id="probe", session_id="probe",
        tenant_id=tenant, user_id="probe", role=Role.ANALYST,
    )


def main() -> int:
    rt = SemanticBundleRuntime(load_bundle(os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")))
    flat = rt.asset_allowlist(ctx())
    print("== runtime.asset_allowlist keys ==")
    print(sorted(flat.keys()))
    print("has 'assets' wrapper?", "assets" in flat, "| has 'default_predicates'?", "default_predicates" in flat)
    first_key, first_val = next(iter(flat.items()))
    print("entry sample:", first_key, "->", json.dumps({k: str(v)[:200] for k, v in first_val.items()}, ensure_ascii=False))
    print("policy keys:", sorted(rt.policy().keys()))

    print("\n== gate1 with FLAT allowlist (production wiring) ==")
    r1 = run_gate1(SQL, flat)
    print("passed:", r1.gate_result.passed, "| applied_predicates:", r1.applied_predicates)
    print("rewritten:", r1.rewritten_sql[:200])

    print("\n== gate2 with FLAT allowlist (production wiring) ==")
    r2 = run_gate2(SQL, ctx(), rt)
    print("passed:", r2.gate_result.passed, "| rule_id:", r2.gate_result.rule_id, "| reason:", r2.gate_result.reason)

    wrapper = {
        "bundle_version": rt.active_version(),
        "assets": flat,
        "joins": [],
        "deny_columns": list(rt.policy()["deny_columns"]),
        "default_predicates": {k: list(v) for k, v in rt.policy()["default_predicates"].items()},
        "allowed_constants": [],
        "max_rows": 10000,
    }
    print("\n== gate1 with WRAPPER derived from runtime ==")
    w1 = run_gate1(SQL, wrapper)
    print("passed:", w1.gate_result.passed, "| applied_predicates:", w1.applied_predicates)
    print("rewritten:", w1.rewritten_sql[:300])
    print("\n== gate2 with WRAPPER derived from runtime ==")
    w2 = run_gate2(w1.rewritten_sql, ctx(), _WrapperSemantics(rt, wrapper))
    print("passed:", w2.gate_result.passed, "| rule_id:", w2.gate_result.rule_id,
          "| reason:", w2.gate_result.reason, "| refuse:", w2.refuse_reason, "| scope:", w2.scope)
    return 0


class _WrapperSemantics:
    """把 wrapper 塞进 `SemanticBundlePort` 面（只为验证 gate2 消费路径，不改生产件）。"""

    def __init__(self, inner: SemanticBundleRuntime, wrapper: dict) -> None:
        self._inner, self._wrapper = inner, wrapper

    def active_version(self) -> str:
        return self._inner.active_version()

    def asset_allowlist(self, ctx_: IdentityContext) -> dict:
        return self._wrapper

    def time_semantics(self):
        return self._inner.time_semantics()

    def policy(self) -> dict:
        return self._inner.policy()


if __name__ == "__main__":
    raise SystemExit(main())
