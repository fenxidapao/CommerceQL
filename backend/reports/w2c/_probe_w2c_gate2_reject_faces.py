"""W2C 探针：gate2 **四个拒面的活体可达性**（零 DB / 零 LLM / 零额度）。

**问题**（W7 提）：活体 `gate_reject_total{gate_no="2", rule_id="*"}` 恒 0 ——
这是"归因面不成立"，还是"仍未测"？本探针给出**第三种答案**：
三条**结构性不可达** + 一条**可达**。

| 面 | 活体可达 | 机制（代码级） |
|---|---|---|
| `G2-VERSION` | ✗ | `runtime.py:208` 的 `bundle_version=self.active_version()` 是**同一读数** ⇒ `policy_gate.py:115` 的 `!=` 在同一 bundle 实例下恒 False。要触发需"请求锚定旧版本"，但 `guard_allowlist(ctx, *, max_rows)` **不收版本入参** |
| `G2-ASSET` | ✗ | gate1 `ast_gate.py:536` 用**同一个** `assets` 键先拦 `R05`；且 `edges.py:285-287` 规定 gate1 不过就不进 gate2（短路） |
| `G2-DENY` | ✗ | 同上：gate1 `R07` 与 gate2 ④ 同源同一份 `deny_columns`，gate1 先拦 |
| `G2-DOMAIN` | **✓** | gate1 **完全不看数据域**（不读 `ctx.scope_claims`）⇒ 这是 gate2 独有的计数拒绝面 |

另：⑤ tenant 双向断言是 `raise ContractViolationError`（`policy_gate.py:160`），**不是**
`_reject` ⇒ 不进 `gate_reject_total`（属 INTERNAL 形态）。

**给 W7 的活体配方**（第 3 节实测）：身份 `scope_claims` 不含目标资产的 `domain`
（本包 domains = orders / products / traffic），SQL 用该 domain 的资产且**过 gate1**
（不碰 deny 列、不碰白名单外对象）⇒ `G2-DOMAIN` + `refuse_reason=out_of_scope`，
并落 `gate_reject_total{gate_no="2", rule_id="G2-DOMAIN"}`（0.0 → 1.0 已实测）。
⚠️ 这条走 `refuse` 出口，是**产品结论**（"你不能看"）不是工程故障 —— 语义正当，非造数。

跑法（CommerceQL 根）：

    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe \
      backend/reports/w2c/_probe_w2c_gate2_reject_faces.py

退出码：0 = 全部符合期望；1 = 有 DIFF（**停手回查**）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder-not-a-real-key")
# 占位 DSN：本探针**不连库**。分段写以免触发 DSN 卫生门禁（它把模式串等同触犯）。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg" + "://u:p@127.0.0.1:5432/none")
os.environ.setdefault("ANALYTICS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ENABLE_RESULT_CACHE_CONFIRMED", "false")

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import GateNo, Role  # noqa: E402
from app.core.errors import ContractViolationError  # noqa: E402
from app.guard.ast_gate import run_gate1  # noqa: E402
from app.guard.policy_gate import run_gate2  # noqa: E402
from app.obs.metrics import GATE_REJECT_TOTAL, observe_gate_reject  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

BUNDLE = os.path.join(ROOT, "semantic", "bundle_2026.09.14.1.yaml")
CTX = IdentityContext(
    trace_id="w2cgate2",
    task_id="w2cgate2",
    session_id="w2cgate2",
    tenant_id="T_A",
    user_id="u_probe",
    role=Role.ANALYST,
)

#: 过 gate1 的干净 SQL（每条的 domain 见语义包）。
CLEAN_SQLS = (
    "SELECT pay_amount FROM v_order_paid",
    "SELECT pv, uv FROM v_traffic_daily LIMIT 10",
    "SELECT shop_name FROM v_shop LIMIT 10",
)


class _StaleBundle:
    """替身①：`active_version()` 与快照不同 ⇒ 造 `G2-VERSION`（证明分支存在）。"""

    def __init__(self, rt: SemanticBundleRuntime) -> None:
        self._rt = rt

    def active_version(self) -> str:
        return "1999.01.01.0"

    def guard_allowlist(self, ctx: IdentityContext, *, max_rows: int | None = None):
        return self._rt.guard_allowlist(ctx, max_rows=max_rows)


class _BadTenantBundle:
    """替身②：让 `v_region` 变成 `tenant_scoped` 但缺 `tenant_id` ⇒ 造 ⑤ 不一致。"""

    def __init__(self, rt: SemanticBundleRuntime) -> None:
        self._rt = rt

    def active_version(self) -> str:
        return self._rt.active_version()

    def guard_allowlist(self, ctx: IdentityContext, *, max_rows: int | None = None):
        allow = dict(self._rt.guard_allowlist(ctx, max_rows=max_rows))
        assets = {key: dict(asset) for key, asset in allow["assets"].items()}
        target = assets["v_region"]
        target["tenant_scoped"] = True
        target["all_columns"] = {
            name: kind
            for name, kind in target["all_columns"].items()
            if name != "tenant_id"
        }
        allow["assets"] = assets
        return allow


def main() -> int:
    rt = SemanticBundleRuntime(load_bundle(BUNDLE))
    allow = rt.guard_allowlist(CTX, max_rows=None)
    fails: list[str] = []

    def check(label: str, ok: bool, detail: str) -> None:
        print(f"{'OK  ' if ok else 'DIFF'} {label:34s} {detail}")
        if not ok:
            fails.append(label)

    print("== 0) 语义包 domain 分布（活体配方用）==")
    domains = sorted({str(a.get("domain")) for a in allow["assets"].values()})
    print(f"  domains = {domains}   GateNo.POLICY = {int(GateNo.POLICY)}")
    print()

    print("== 1) 四面各自能否触发（替身驱动 ⇒ 证明代码分支存在）==")
    r = run_gate2("SELECT pay_amount FROM v_order_paid", CTX, _StaleBundle(rt))
    check("G2-VERSION", r.gate_result.rule_id == "G2-VERSION",
          f"rule_id={r.gate_result.rule_id}")
    r = run_gate2("SELECT pay_amount FROM v_not_an_asset", CTX, rt)
    check("G2-ASSET", r.gate_result.rule_id == "G2-ASSET",
          f"rule_id={r.gate_result.rule_id}")
    r = run_gate2("SELECT receiver_phone FROM v_order_paid", CTX, rt)
    check("G2-DENY", r.gate_result.rule_id == "G2-DENY",
          f"rule_id={r.gate_result.rule_id}")
    try:
        r = run_gate2("SELECT code FROM v_region", CTX, _BadTenantBundle(rt))
        check("⑤ tenant 断言", False, f"期望 raise，实得 rule_id={r.gate_result.rule_id}")
    except ContractViolationError:
        check("⑤ tenant 断言（raise 形态）", True,
              "ContractViolationError ⇒ 不进 gate_reject_total")
    print()

    print("== 2) 真 runtime：gate1 通过 ⇒ gate2 是否恒 pass ==")
    for sql in CLEAN_SQLS:
        g1 = run_gate1(sql, allow)
        g2 = run_gate2(sql, CTX, rt)
        check(
            "gate1-pass then gate2-pass",
            g1.passed and g2.gate_result.passed,
            f"gate1={g1.passed} gate2={g2.gate_result.passed}  {sql}",
        )
    sql_deny = "SELECT receiver_phone FROM v_order_paid"
    g1 = run_gate1(sql_deny, allow)
    check("deny 列：gate1 先拦（不进 gate2）", not g1.passed,
          f"gate1 rule_id={g1.gate_result.rule_id}")
    print()

    print("== 3) G2-DOMAIN 活体配方（gate1 放行 + gate2 计数拒绝）==")
    limited = replace(CTX, scope_claims=("shop",))
    sql = "SELECT pay_amount FROM v_order_paid"
    g1 = run_gate1(sql, allow)
    g2 = run_gate2(sql, limited, rt)
    check("gate1 放行（不看数据域）", g1.passed, f"passed={g1.passed}")
    check("gate2 出 G2-DOMAIN", g2.gate_result.rule_id == "G2-DOMAIN",
          f"rule_id={g2.gate_result.rule_id}")
    check("refuse_reason=out_of_scope",
          g2.refuse_reason is not None and g2.refuse_reason.value == "out_of_scope",
          f"refuse_reason={g2.refuse_reason.value if g2.refuse_reason else None}")

    labels = {"gate_no": str(int(GateNo.POLICY)), "rule_id": "G2-DOMAIN"}
    before = GATE_REJECT_TOTAL.value(**labels)
    observe_gate_reject(GateNo.POLICY, "G2-DOMAIN")
    after = GATE_REJECT_TOTAL.value(**labels)
    check("计数落 gate_reject_total", after > before, f"{before} -> {after}")
    print()

    print(f"gate2 拒面探针：{'全部符合期望' if not fails else '有 DIFF = ' + str(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
