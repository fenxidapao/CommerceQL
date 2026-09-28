"""架构自证探针（只读、零 LLM、零 DB、不落盘）：`U-121` 的四条判据在**生产端口直连闸门**上到底通了几条。

W2C `c76f701` 落了第三格的最后半边（`policy_gate.py` 换 `guard_allowlist` + ④⑤ 切结构面）⇒
`U-121` 的**四个取用点**据报已全部换调。本探针不采信 commit message，按 `07 §4.8` 的判据逐条实测：

| 判据 | 断言 |
|---|---|
| ① | 真运行时 `guard_allowlist(ctx)` 直喂 `run_gate1` ⇒ 普通 SQL `passed=True`（历史上恒 `R05`） |
| ② | 默认谓词**真被注入**（`applied_predicates` 非空且含 `pay_status = 'paid'`）—— 缺它是 **fail-open**（口径静默失真） |
| ③ | `G2-VERSION` **真能触发**（快照版本 ≠ 激活版本 ⇒ `_reject`）—— 缺它是 **fail-open**（违反 §5.7） |
| ④ | 请求级 `max_rows=200` **真生效**（生效 LIMIT = 200，不是 10000） |

判据⑤（`rule_id` 不得成为列存在性 oracle）由同目录 `probe_gate1_column_oracle.py` 单独量，本件不重复。

⚠️ ③ 需要"快照版本 ≠ 激活版本"这一输入：生产侧由 `SemanticBundleRuntime.active_version()` 给，
   探针**不改任何源码**，只在进程内包一层壳（`_SnapStale`）把激活版本换成另一个字符串。

跑法：cd CommerceQL/backend && ../.venv/Scripts/python.exe reports/arch/probe_u121_final.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.guard import run_gate1, run_gate2
from app.semantics.loader import load_bundle
from app.semantics.runtime import SemanticBundleRuntime

BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"
PLAIN_SQL = "SELECT pay_amount FROM v_order_paid"
DENY_SQL = "SELECT receiver_phone FROM v_order_paid"


def ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="t", task_id="t", session_id="t",
        tenant_id="T_A", user_id="u", role=Role.ANALYST,
    )


class _SnapStale:
    """只把 `active_version()` 换一个值；`guard_allowlist` 原样透传（进程内壳，不改源码）。"""

    def __init__(self, inner: Any, stale: str) -> None:
        self._inner, self._stale = inner, stale

    def active_version(self) -> str:
        return self._stale

    def guard_allowlist(self, c: IdentityContext, *, max_rows: int | None = None) -> Any:
        return self._inner.guard_allowlist(c, max_rows=max_rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def main() -> int:
    rt = SemanticBundleRuntime(load_bundle(str(BUNDLE)))
    c = ctx()
    res: list[tuple[str, bool, str]] = []

    print("=" * 78)
    print("U-121 四条判据 · 生产端口直连闸门（离线，零 LLM / 零 DB）")
    print("=" * 78)

    # ---- ① 普通 SQL 必须过 gate1 ----
    al = rt.guard_allowlist(c, max_rows=1000)
    g1 = run_gate1(PLAIN_SQL, al).gate_result
    print(f"① gate1({PLAIN_SQL!r})\n   -> passed={g1.passed} rule={g1.rule_id} decision={g1.decision}")
    res.append(("①", bool(g1.passed), f"rule={g1.rule_id}"))

    # ---- ② 默认谓词真被注入 ----
    applied = run_gate1(PLAIN_SQL, al).applied_predicates
    has_paid = any("pay_status" in p and "paid" in p for p in applied)
    print(f"② applied_predicates = {list(applied)}\n   -> 含 pay_status='paid' = {has_paid}")
    res.append(("②", bool(applied) and has_paid, f"n={len(applied)}"))

    # ---- ③ G2-VERSION 真能触发（快照 ≠ 激活）----
    stale = _SnapStale(rt, "2099.01.01")
    g2v = run_gate2(PLAIN_SQL, c, stale)  # type: ignore[arg-type]
    print(f"③ gate2(快照 {al.get('bundle_version')} vs 激活 {stale.active_version()})\n"
          f"   -> passed={g2v.gate_result.passed} rule={g2v.gate_result.rule_id} "
          f"decision={g2v.gate_result.decision} reason={g2v.gate_result.reason}")
    hit = g2v.gate_result.rule_id == "G2-VERSION"
    res.append(("③", hit, f"rule={g2v.gate_result.rule_id}"))

    # ---- ④ 请求级 max_rows 生效 ----
    al200 = rt.guard_allowlist(c, max_rows=200)
    r200 = run_gate1(PLAIN_SQL, al200)
    r_def = run_gate1(PLAIN_SQL, rt.guard_allowlist(c, max_rows=None))
    lim200 = "LIMIT 200" in r200.rewritten_sql.upper()
    print(f"④ max_rows=200 -> limit_injected={dict(r200.limit_injected or {})} sql = {r200.rewritten_sql}\n"
          f"   max_rows=None -> limit_injected={dict(r_def.limit_injected or {})} sql = {r_def.rewritten_sql}")
    res.append(("④", lim200 and "LIMIT 10000" in r_def.rewritten_sql.upper(), "200 生效 / 缺省回硬上限"))

    # ---- 附带：deny 列仍被拒（回归护栏，不是新判据）----
    gd = run_gate1(DENY_SQL, al).gate_result
    print(f"＋ deny 列 gate1 -> passed={gd.passed} rule={gd.rule_id}（判据⑤ 要求与'不存在列'同码）")

    print("=" * 78)
    for name, ok, detail in res:
        print(f"  {name} {'PASS' if ok else 'FAIL'}  {detail}")
    n = sum(1 for _, ok, _ in res if ok)
    print(f"\n  ⇒ {n}/4 条判据实测成立 @HEAD 见 git log（架构只读探针，未改任何源码）")
    if n < 4:
        print("  ⇒ 未成立的那几条**不得记作已落地**；请核对上方读数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
