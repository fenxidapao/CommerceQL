"""复算 W7 提的**零额度不变量**：`admitted − app.audit_log 行数 = 0`（2026-09-28 第十八轮 ①）。

为什么这个文件值得存在（不是"再数一遍别人的数"）
------------------------------------------------
W7 报：三格实测差 0（热臂 86 / 冷臂 84 / session-lock 1），而 **修复前同型格差 8 ≡ 8 条
`ValueError`** ⇒ 一条不花 token 的检查就能检出"终态丢失"这类缺陷（`7035db3` = U-129 修的是
"已有终态后再写第二个终态"，同一条形状的另一种破坏）。他们建议进 W6 的门禁表。

⚠️ **我方不在这里改 §17.3 的判据表**（G-1…G-8 的集合是架构的地盘，本窗口无权自加一格）。
本文件做的是**两件我地盘内的事**：
1. **独立复算**他们的三个读数（两个记录方各自数过、且用的是不同的时间源），产成入库产物；
2. 把这条不变量做成**将来接 PG 执行链时可直接接的判据形状**（`classify()` 是唯一真相），
   并把它作为候选不变量上呈架构（RELAY A15）。

这条不变量是**双向**的，两个方向都要点名：
* 行数 **<** `admitted` ⇒ 有请求没落终态（W7 修复前那一格，差 8）；
* 行数 **>** `admitted` ⇒ 一个请求落了**多行**（U-129 的双终态形状正是这一侧）；
所以判据不许写成 `rows <= admitted` 这种单边式。

三条会让这条数骗人的前置（都在产物里如实落）：
1. **老回执没有 `admission` 字段** ⇒ 一律 `not_applicable`，**绝不当成"差 0"**（与不可引用清单同族）；
2. **多场景共用一份 receipt 级时间窗** ⇒ 窗口对该场景是 `ambiguous`，不比（比了就会把整批行数
   压到单场景的 `admitted` 上，恒" violated"）；
3. **时间源不同**：窗口来自 driver 的墙钟，`created_at` 来自 PG 的钟 ⇒ 落笔前测一次 `now()` 与
   本地 UTC 的偏移，超过阈值就在产物里标 `edge_unreliable`。

用法（🔴 缺 `COMMERCEQL_PROBE_DSN` 即 exit 2、不出产物 —— 与 `probe_pg_boundary.py` 同形，
不给字面默认 DSN，因为观察对象**就是共享实例**）：

    export COMMERCEQL_PROBE_DSN='<共享库 DSN>'
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w6/probe_audit_invariant.py

产物 = `backend/reports/w6/probe_audit_invariant.json`（逐格 window / admitted / audit_rows /
diff / by_outcome / applicability + 汇总 + `pg_guard` 自证 + 时钟偏移）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "eval"))

from pg_guard import force_readonly, open_readonly, redact_dsn, target_stamp  # noqa: E402

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: 🔴 不留字面默认 DSN（对齐 U-114 防线①与 `probe_pg_boundary.py`）。
DSN = force_readonly(os.environ.get("COMMERCEQL_PROBE_DSN", "")) if os.environ.get(
    "COMMERCEQL_PROBE_DSN") else ""

RECEIPTS_GLOB_DEFAULT = "deploy/loadtest/*.json"
DEFAULT_OUT = HERE / "probe_audit_invariant.json"

#: 窗口右端点**含**该秒（回执时间戳是秒级，批次最后一条落在 `finished_at` 那一秒内）。
#: 这是判据的一部分，写进产物，不许读者以为我用的是开区间。
WINDOW_PAD = timedelta(seconds=1)
#: 时钟偏移超过它 ⇒ 窗口边缘不可信，读数照写但打标记。
SKEW_LIMIT_S = 2.0

#: `app.audit_log` 里可能被当时间轴的列，按优先级点名；找不到就报错，**不猜**。
#: ⚠️ 09-28 实测该表的列名是 **`timestamp`（timestamptz）**，**没有** `created_at` ⇒ 把它排第一是
#: 读数写下来的结果，不是"我猜这个更常见"。留其余候选作 fallback（列被改名时宁可红也不要静默数错）。
TIME_COLUMN_CANDIDATES = ("timestamp", "created_at", "ts", "event_time", "occurred_at")

#: 结论词表（唯一真相在 `classify()`，测试吃它）。
NOT_APPLICABLE = "not_applicable"
AMBIGUOUS_WINDOW = "ambiguous_window"
INVARIANT_OK = "invariant_ok"
INVARIANT_VIOLATED = "invariant_violated"
NO_DB = "no_measurement"


def _ts(value: Any) -> datetime | None:
    """把回执里的时间戳解析成带时区的 datetime；解析不了就回 None（让调用方标不适用）。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def admitted_of(scenario: dict) -> int | None:
    """取 `admission.admitted`。**缺字段就是缺字段** —— 回 None，不当 0（不可引用清单同族）。"""
    adm = scenario.get("admission")
    if isinstance(adm, dict) and isinstance(adm.get("admitted"), int):
        return int(adm["admitted"])
    return None


def window_of(receipt: dict, scenario: dict) -> tuple[datetime | None, datetime | None, str]:
    """返回 (begin, end, kind)，kind ∈ {"scenario", "receipt", "single", "ambiguous", "missing"}。

    多场景回执若只有 receipt 级窗口 ⇒ `ambiguous`：拿整批窗口去比单场景 `admitted` 会恒假。
    """
    b, e = _ts(scenario.get("started_at")), _ts(scenario.get("finished_at"))
    if b and e:
        return b, e, "scenario"
    scenarios = receipt.get("scenarios")
    b, e = _ts(receipt.get("started_at")), _ts(receipt.get("finished_at"))
    if not (b and e):
        return None, None, "missing"
    if not isinstance(scenarios, list) or len(scenarios) == 1:
        return b, e, ("single" if isinstance(scenarios, list) and len(scenarios) == 1 else "receipt")
    return None, None, "ambiguous"


def classify(admitted: int | None, audit_rows: int | None) -> tuple[str, int | None]:
    """判据唯一形状：缺准入数 / 没测到 ⇒ 不适用；差为 0 ⇒ 成立；否则**双向**都算违反。"""
    if admitted is None or audit_rows is None:
        return NOT_APPLICABLE, None
    diff = admitted - audit_rows
    return (INVARIANT_OK, 0) if diff == 0 else (INVARIANT_VIOLATED, diff)


def overlap_pairs(rows: list[dict]) -> list[tuple[str, str]]:
    """窗口两两重叠 ⇒ 点名。重叠时单格的 `audit_rows` 会把别人的请求也算进来，读数必须打折。"""
    out: list[tuple[str, str]] = []
    measured = [r for r in rows if r.get("begin") and r.get("end")]
    for i in range(len(measured)):
        for j in range(i + 1, len(measured)):
            a, b = measured[i], measured[j]
            if a["begin"] <= b["end"] and b["begin"] <= a["end"]:
                out.append((a["receipt"], b["receipt"]))
    return out


def summarize(rows: list[dict], skew_s: float | None) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    violated = [
        {"receipt": r["receipt"], "admitted": r["admitted"], "audit_rows": r["audit_rows"], "diff": r["diff"]}
        for r in rows if r["state"] == INVARIANT_VIOLATED
    ]
    return {
        "n_receipts_scanned": len({r["receipt"] for r in rows}),
        "n_scenario_cells": len(rows),
        "state_counts": counts,
        "invariant_ok_cells": counts.get(INVARIANT_OK, 0),
        "violated_cells": violated,
        "undercount_side": sum(1 for v in violated if (v["diff"] or 0) > 0),
        "overcount_side": sum(1 for v in violated if (v["diff"] or 0) < 0),
        "clock_skew_s": skew_s,
        "edge_unreliable": skew_s is None or abs(skew_s) > SKEW_LIMIT_S,
        "window_rule": f"created_at >= begin AND created_at < finished_at + {WINDOW_PAD.total_seconds():.0f}s"
                       "（右端含该秒；回执时间戳为秒级）",
        "note": "admitted − 审计行数 = 0 是**双向**判据：差 > 0 = 有请求没落终态（W7 修复前那一格），"
                "差 < 0 = 一个请求落了多行（U-129 的双终态形状）。缺 admission 的格子一律 not_applicable，"
                "**不许**当成差 0。",
    }


def pick_time_column(cols: list[str]) -> str | None:
    for cand in TIME_COLUMN_CANDIDATES:
        if cand in cols:
            return cand
    return None


async def measure(rows: list[dict], table: str = "audit_log") -> tuple[list[dict], float | None, dict]:
    """逐格数 `app.audit_log` 的行数（参数化查询 + 只读闸门）。返回 (带读数的行, 时钟偏移秒, 闸门自证)。"""
    conn = await open_readonly(DSN, purpose="probe_audit_invariant")
    try:
        stamp = await target_stamp(conn)
        t0 = datetime.now(UTC)
        pg_now = (await (await conn.execute("select now()")).fetchone())[0]
        skew = round((pg_now - t0).total_seconds(), 3)
        cols = [r[0] for r in await (await conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema='app' and table_name=%s order by ordinal_position", (table,)
        )).fetchall()]
        stamp["columns"] = cols
        time_col = pick_time_column(cols)
        if time_col is None:
            raise LookupError(
                f"app.{table} 里没有我认识的时间列（候选 {list(TIME_COLUMN_CANDIDATES)}，实际列 {cols}）"
                " ⇒ 不猜，终止且不出产物"
            )
        stamp["time_column"] = time_col
        rls = await (await conn.execute(
            "select c.relrowsecurity, c.relforcerowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'app' and c.relname = %s", (table,)
        )).fetchone()
        stamp["row_security"] = {"relrowsecurity": bool(rls[0]), "relforcerowsecurity": bool(rls[1])} if rls else None
        #: 本探针的连接**不设租户 GUC** ⇒ 一旦这张表被纳入 RLS，计数会静默变 0（交付 §5.24 那个坑）。
        #: 所以把可见性条件写进产物，而不是让读者假设"数得到"。
        stamp["count_visible_without_tenant_guc"] = not (rls and (rls[0] or rls[1]))
        for row in rows:
            if row["state"] != NO_DB or not row["begin"]:
                continue
            q = sql.SQL("select outcome, count(*) from app.{} where {} >= %s and {} < %s group by outcome").format(
                sql.Identifier(table), sql.Identifier(time_col), sql.Identifier(time_col)
            )
            pairs = await (await conn.execute(q, (row["begin"], row["end"] + WINDOW_PAD))).fetchall()
            by_outcome = {str(o): int(c) for o, c in pairs}
            row["audit_rows"] = sum(by_outcome.values())
            row["by_outcome"] = by_outcome
            row["state"], row["diff"] = classify(row["admitted"], row["audit_rows"])
        return rows, skew, stamp
    finally:
        await conn.close()


def collect(receipt_dir: Path, pattern: str) -> list[dict]:
    """把回执展开成"场景格"清单；没跑库时先给状态占位。"""
    rows: list[dict] = []
    for path in sorted(receipt_dir.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "scenarios" not in data:
            continue
        scenarios = data.get("scenarios") if isinstance(data.get("scenarios"), list) else [{}]
        for idx, sc in enumerate(scenarios, 1):
            if not isinstance(sc, dict):
                continue
            begin, end, kind = window_of(data, sc)
            adm = admitted_of(sc)
            state = NO_DB
            if adm is None:
                state = NOT_APPLICABLE
            elif kind in ("ambiguous", "missing"):
                state = AMBIGUOUS_WINDOW
            rows.append({
                "receipt": path.name,
                "scenario_index": idx,
                "schema": data.get("schema"),
                "window_kind": kind,
                "begin": begin,
                "end": end,
                "admitted": adm,
                "audit_rows": None,
                "diff": None,
                "by_outcome": None,
                "state": state,
                "g6_caveat_present": sc.get("g6_caveat") is not None,
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", default=RECEIPTS_GLOB_DEFAULT,
                    help="相对仓库根的回执 glob（默认 deploy/loadtest/*.json）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--table", default="audit_log")
    args = ap.parse_args()
    if psycopg is None:
        print("psycopg 不在位 ⇒ 不探测（不猜结论）")
        return 2
    if not DSN:
        print("🔴 未设 COMMERCEQL_PROBE_DSN ⇒ 不探测。本探针数的是**共享实例**的 `app.audit_log`，"
              "连它必须是显式动作（不给字面默认 DSN，理由见文件头）；缺 env 不出产物。")
        return 2

    rows = collect(REPO / Path(args.receipts).parent, Path(args.receipts).name)
    if not rows:
        print(f"🔴 回执扫描面为空（{args.receipts}）⇒ 不出产物（空扫描面不能写成「没违反」）")
        return 2
    try:
        rows, skew, stamp = asyncio.run(measure(rows, table=args.table))
    except (LookupError, RuntimeError, psycopg.Error) as exc:  # RuntimeError 含 PgReadOnlyGuardError
        print(f"🔴 探测未跑成：{type(exc).__name__}: {str(exc)[:300]}")
        return 2

    out = Path(args.out)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "dsn_redacted": redact_dsn(DSN),
        "pg_guard": stamp,
        "receipts_pattern": args.receipts,
        "cells": [{**r, "begin": r["begin"].isoformat() if r["begin"] else None,
                   "end": r["end"].isoformat() if r["end"] else None} for r in rows],
        "overlapping_windows": overlap_pairs(rows),
        "summary": summarize(rows, skew),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = payload["summary"]
    print(f"闸门自证：{ {k: stamp[k] for k in ('database', 'role', 'read_only_enforced', 'write_attempt_rejected')} }")
    print(f"时钟偏移 = {s['clock_skew_s']}s（阈值 {SKEW_LIMIT_S}s，edge_unreliable = {s['edge_unreliable']}）")
    print(f"场景格 {s['n_scenario_cells']} 格：状态分布 {s['state_counts']}；"
          f"违反 {len(s['violated_cells'])}（少落 {s['undercount_side']} / 多落 {s['overcount_side']}）")
    for v in s["violated_cells"]:
        print(f"   ⚠️ {v['receipt']} admitted={v['admitted']} 审计行={v['audit_rows']} 差={v['diff']}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
