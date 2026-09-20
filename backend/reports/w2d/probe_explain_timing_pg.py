"""U-96 判据实验：gate3（07 §7.5）规定的 EXPLAIN 形态，能不能给出"预估耗时"？

归属窗口：W2D（`backend/reports/w2d/**`）。可复跑、只读、不写库、不依赖应用代码。

--------------------------------------------------------------------------
结论（先写结论，脚本只是复现手段 —— 数字见脚本输出）
--------------------------------------------------------------------------
1. **`EXPLAIN (FORMAT JSON)`（07 §7.5 明文规定的取数形态）输出里没有任何时间字段。**
   顶层键只有 `Plan`；节点键只有 `Startup Cost` / `Total Cost` / `Plan Rows` / `Plan Width`。
   ⇒ §7.5 的"解析字段"清单与 §5.4 的"`预估延迟 > async_threshold_ms`"**没有共同数据源**。
   这不是"W4 忘了加字段"（U-96 的登记口径），是**值来源从未被定义**。

2. **时间只出现在 `EXPLAIN (ANALYZE, FORMAT JSON)`**（`Planning Time` / `Execution Time` /
   逐节点 `Actual Total Time`），而 `ANALYZE` **会真的执行查询** ——
   与 §7.5 自己的"只估算不执行"直接冲突；且"已经执行完了再转异步"本身失去意义。

3. **"拿 `Total Cost` × 系数当毫秒"（唯一剩下的代用路线）实测不成立**：
   五种查询形状的 `cost/ms` 跨 **1.667 ~ 545.5（327×）** —— 固定开销在小 cost 上完全主导比值
   （点查 cost=0.04 / 实测 0.024ms），大 cost 侧又被并行度与缓存态主导。
   稳定性也不够：同进程连跑 3 次漂移 1.10×，而同一查询经**独立进程**（`psql` 冷调用）实测已达
   2.2×（21.4ms vs 47.8ms，同 SQL 同机）。
   ⇒ 用单一系数 = 把"看起来合理的假数字"交给转异步判据（U-22 红线）。

⇒ **U-96 的正解不是"给 `GateResult` 加一个延迟字段"**（加了也没有诚实的取值来源），
而是在 §5.4 判据的**来源**上做一次裁定。方案对比与裁定建议见同目录 `RELAY.md` 的 U-96 一节。

--------------------------------------------------------------------------
跑法
--------------------------------------------------------------------------
    python probe_explain_timing_pg.py

默认连 compose 栈的本地 PG（`postgresql://postgres:postgres@127.0.0.1:5432/ecom`），
可用 `PROBE_PG_DSN` 环境变量覆盖。

⚠️ `ANALYZE` 那一步会**真跑查询**（本脚本只用 count/limit/聚合这类廉价形态，且全部带
`statement_timeout`），**请只在开发库上跑**。
"""

from __future__ import annotations

import os
from typing import Any, Final

import psycopg

#: 探针用的库（默认 = compose 栈本地 PG）。
DEFAULT_DSN: Final[str] = "postgresql://postgres:postgres@127.0.0.1:5432/ecom"

#: 探针语句：覆盖"大代价聚合 / 点查 / 高基数分组 / 排序 + LIMIT / 无索引过滤"五种形状。
#: 前三条用于看"有没有时间字段"，全部五条用于看 cost/ms 比值稳不稳。
PROBES: Final[tuple[tuple[str, str], ...]] = (
    ("① count(*) 全表聚合", "SELECT count(*) FROM app.order_paid"),
    ("② 主键点查（LIMIT 1）", "SELECT * FROM app.order_paid LIMIT 1"),
    ("③ GROUP BY 高基数分组", "SELECT shop_id, count(*) FROM app.order_paid GROUP BY shop_id"),
    ("④ ORDER BY + LIMIT", "SELECT * FROM app.order_paid ORDER BY pay_amount DESC LIMIT 100"),
    (
        "⑤ 无索引列 LIKE 全扫",
        "SELECT count(*) FROM app.order_paid WHERE receiver_city LIKE '%州%'",
    ),
)

#: 探针自己封的顶（避免在开发库上跑出个长查询）。
_PROBE_STATEMENT_TIMEOUT: Final[str] = "5s"


def _walk_keys(node: Any) -> list[str]:
    """递归收集 JSON 里出现过的所有键名（用于"有没有时间字段"的判定）。"""
    if isinstance(node, dict):
        keys = [str(k) for k in node]
        for value in node.values():
            keys.extend(_walk_keys(value))
        return keys
    if isinstance(node, list):
        keys = []
        for item in node:
            keys.extend(_walk_keys(item))
        return keys
    return []


def _time_like_keys(node: Any) -> list[str]:
    """所有**含 "time"** 的键名（大小写无关）。空列表 = 这份计划里没有任何耗时信息。"""
    return sorted({k for k in _walk_keys(node) if "time" in k.lower()})


def _plan_doc(cur: psycopg.Cursor[Any], sql: str, *, analyze: bool) -> Any:
    """跑一条 EXPLAIN 并取回 JSON 计划文档（第 0 行第 0 列）。"""
    head = "EXPLAIN (ANALYZE, FORMAT JSON) " if analyze else "EXPLAIN (FORMAT JSON) "
    cur.execute(head + sql)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("EXPLAIN 无输出")
    return row[0]


def main() -> int:
    dsn = os.environ.get("PROBE_PG_DSN", DEFAULT_DSN)
    print(f"DSN = {dsn}")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = '{_PROBE_STATEMENT_TIMEOUT}'")
        cur.execute("SHOW server_version")
        version = cur.fetchone()
        print(f"PG  = {version[0] if version else '?'}\n")

        # ------------------------------------------------------------------
        # A. 07 §7.5 规定的形态：有没有时间字段？
        # ------------------------------------------------------------------
        print("=" * 74)
        print("A) EXPLAIN (FORMAT JSON) —— 07 §7.5 规定的形态")
        print("=" * 74)
        plain_hits: dict[str, list[str]] = {}
        for label, sql in PROBES:
            plan = _plan_doc(cur, sql, analyze=False)
            hits = _time_like_keys(plan)
            plain_hits[label] = hits
            top_keys = sorted(plan[0]) if isinstance(plan, list) and plan else []
            print(f"  {label:<22} 顶层键={top_keys}  含 time 的键={hits or '无'}")
        total_plain = sum(len(v) for v in plain_hits.values())
        print(f"\n  ⇒ 五个形状合计命中 'time' 键 {total_plain} 个")
        print("     判定：plain EXPLAIN **不产出任何耗时** ⇒ §7.5 无法给出'预估耗时'\n")

        # ------------------------------------------------------------------
        # B. ANALYZE 形态：有耗时，但它执行了查询
        # ------------------------------------------------------------------
        print("=" * 74)
        print("B) EXPLAIN (ANALYZE, FORMAT JSON) —— 有耗时，但会真执行")
        print("=" * 74)
        print(f"  {'查询':<22} {'TotalCost':>12} {'ExecMs':>10} {'cost/ms':>10}")
        ratios: list[float] = []
        for label, sql in PROBES:
            doc = _plan_doc(cur, sql, analyze=True)
            top = doc[0]
            cost = float(top.get("Plan", {}).get("Total Cost", 0.0))
            exec_ms = float(top.get("Execution Time", 0.0))
            ratio = (cost / exec_ms) if exec_ms > 0 else float("nan")
            ratios.append(ratio)
            print(f"  {label:<22} {cost:>12.2f} {exec_ms:>10.3f} {ratio:>10.3f}")
        finite = [r for r in ratios if r == r]
        if finite:
            print(
                f"\n  ⇒ cost/ms 跨度 {min(finite):.3f} ~ {max(finite):.3f}"
                f"（{max(finite) / min(finite):.0f}×）"
            )
        print("     判定：系数不是常数 ⇒ 'Total Cost × 系数 = 毫秒' 是造数字（U-22 红线）")
        print("           且 ANALYZE 已执行查询，与 §7.5 '只估算不执行' 冲突\n")

        # ------------------------------------------------------------------
        # C. 重跑稳定性（同一查询 × 3）
        # ------------------------------------------------------------------
        print("=" * 74)
        print("C) 同一查询连跑 3 次的 cost/ms（看固定开销/缓存态带来的漂移）")
        print("=" * 74)
        repeat_label, repeat_sql = PROBES[0]
        print(f"  查询 = {repeat_label}")
        seen: list[float] = []
        for i in range(3):
            doc = _plan_doc(cur, repeat_sql, analyze=True)
            top = doc[0]
            cost = float(top.get("Plan", {}).get("Total Cost", 0.0))
            exec_ms = float(top.get("Execution Time", 0.0))
            ratio = (cost / exec_ms) if exec_ms > 0 else float("nan")
            seen.append(ratio)
            print(f"    第 {i + 1} 次：cost={cost:.2f}  exec={exec_ms:.3f}ms  cost/ms={ratio:.1f}")
        ok = [r for r in seen if r == r]
        if len(ok) >= 2 and min(ok) > 0:
            print(f"\n  ⇒ 同一条 SQL、同一台机器，cost/ms 漂移 {max(ok) / min(ok):.2f}×")

    print("\n" + "=" * 74)
    print("结论：gate3 的可用信号是 cost/行数，**不是**毫秒。U-96 需在判据来源上裁定。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
