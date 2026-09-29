"""复算 W7 提的**零额度不变量**：`terminal − app.audit_log 行数 = 0`（2026-09-29 第十九轮把分母换成 `terminal`）。

为什么这个文件值得存在（不是"再数一遍别人的数"）
------------------------------------------------
W7 报：三格实测差 0（热臂 86 / 冷臂 84 / session-lock 1），而 **修复前同型格差 8 ≡ 8 条
`ValueError`** ⇒ 一条不花 token 的检查就能检出"终态丢失"这类缺陷（`7035db3` = U-129 修的是
"已有终态后再写第二个终态"，同一条形状的另一种破坏）。他们建议进 W6 的门禁表。

⚠️ **我方不在这里改 §17.3 的判据表**（G-1…G-8 的集合是架构的地盘，本窗口无权自加一格）。
本文件做的是**两件我地盘内的事**：
1. **独立复算**他们的读数（两个记录方各自数过、且用的是不同的时间源），产成入库产物；
2. 把这条不变量做成**将来接 PG 执行链时可直接接的判据形状**（`classify()` 是唯一真相），
   并把它作为候选不变量上呈架构（RELAY A15）。

🔴 分母为什么是 `terminal` 而不是 `admitted`（2026-09-29 第十九轮，**读码核过**）
--------------------------------------------------------------------------
`admitted` 的判据只是 HTTP 2xx（`deploy/loadtest/driver.py:332-333`），而 `truncated`
（200、但流断在半途、没读到 `terminal: true`）**也在 2xx 里** ⇒ 那条请求没资格断言"服务端落了
一条终态"。严格式因此是 **`terminal − 审计行 = 0`**，其中
`terminal = Σ outcomes{ok, clarify, refuse, error_frame, async_degraded}`
—— 词表**逐字**取自 `deploy/loadtest/driver.py:327-329` 的 `_TERMINAL_OUTCOMES`，字段表在
`deploy/loadtest/README.md` §三.0.1p（2026-09-29 实测在 `:924`）。

* **今天两个分母同值**：12 格 `healthy_r*.json` 逐格复算 `admitted − terminal = 0`（无断流）
  ⇒ 上一版用 `admitted` 出的差值读数**不改判**；
* 但驱动自己的 `--self-check` 里就有一格 **`admitted=8 / terminal=7`** 的活样本
  （`driver.py:770-774`，注释明写"别把不变量的分母退回 `admitted`"）⇒ 一出现断流/客户端超时，
  `admitted` 会**假报"少落"**，把量具的形状说成被测系统的缺陷。

`admission.terminal` 那个桶是 `d4b4fef` 才加的 ⇒ **盘上 39 份回执里 0 份带它**（本轮实测），
所以这里按上面的词表从 `outcomes` **就地推导**（同一个定义，不是第三份真相）。两份都读得到而**不等**
⇒ 记 `provided_vs_derived_mismatch` 并采用 W7 自己写的 `admission.terminal`，**不静默挑一个**。
`admitted` 只在 `terminal` 两条路都取不到时作**显式标注的代理**
（`denominator_basis = "admitted_proxy:2xx"`）⇒ 代理格的 `invariant_ok` **不等于**严格式成立。

这条不变量是**双向**的，两个方向都要点名：
* 行数 **<** 分母 ⇒ 有请求没落终态（W7 修复前那一格，差 8）；
* 行数 **>** 分母 ⇒ 一个请求落了**多行**（U-129 的双终态形状正是这一侧）；
所以判据不许写成 `rows <= 分母` 这种单边式。

丢行的**机制**（本轮读码核实，进产物引用）：`app.audit_log` 只有**段 1**（`app/obs/audit.py:18`
的表分工；段 2 落 `audit_log_supplement`，不在被数的表里）。
`backend/app/api/runner.py:669-699` 给取消路径做了两段式补偿（且注释明写"反过来做会重复写段 1
⇒ 同一次 run 两行 `audit_log`" —— 那正是"多落"那一侧的防线）；而 `runner.py:482-501` 的
`graph_run_failed` **只补发 error 帧、不写任何审计** ⇒ "崩在图里 = 客户端拿到终态、审计 0 行"
的形态来源。⇒ 断流与崩溃两条路都会让 `terminal` 与行数不等，只是**方向相反**。

六条会让这条数骗人的前置（都在产物里如实落）：
1. **没有可比对象**：分母取不到 ⇒ `not_applicable`；分母 = 0 ⇒ 也 `not_applicable`
   （空格子差 0 是**恒真**，不能作为"成立"的一格计数）。每格带回执的 `target`、汇总带
   `target_counts` ⇒ "整批打在错端口上"这种成因要能被一眼看出来，而不是只剩一个 `0`；
2. **多场景共用一份 receipt 级时间窗** ⇒ 窗口对该场景是 `ambiguous`，不比（比了就会把整批行数
   压到单场景的分母上，恒" violated"）；
3. **时间源不同**：窗口来自 driver 的墙钟，`timestamp` 来自 PG 的钟 ⇒ 落笔前测一次 `now()` 与
   本地 UTC 的偏移，超过阈值就在产物里标 `edge_unreliable`；
4. **窗口两两重叠** ⇒ 一格会把别人的请求也数进来（`overlapping_windows` 点名，读数打折）；
5. **窗口早于表里现存最老的一行** ⇒ 该格 `not_applicable`（`span_void()`）。这张表在**共享实例**上，
   行可以被清理或整表重载 ⇒ 老回执数到 0 行是"表的历史长度"决定的，写成"少落"就是把清理动作报成缺陷。
   跨度读数落进 `pg_guard.table_span`（`min` / `max` / `rows`），不靠假设。
6. **当天的表行数与分母不在同一量级** ⇒ "少落"这条读数指认不出东西。所以每格带
   `rows_that_window_day`（该 UTC 日整表现存行数），汇总里带 `violated_by_window_day`，
   `pg_guard` 里带 `table_day_counts` / `table_outcome_counts`（服务端 `outcome` 的词表与驱动的
   `ok/error_frame/…` **不同名**，现值看产物键 ⇒ `by_outcome` 只读"落了几行"，不许拿去比词表）。

用法（🔴 缺 `COMMERCEQL_PROBE_DSN` 即 exit 2、不出产物 —— 与 `probe_pg_boundary.py` 同形，
不给字面默认 DSN，因为观察对象**就是共享实例**）：

    export COMMERCEQL_PROBE_DSN='<共享库 DSN>'
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w6/probe_audit_invariant.py

产物 = `backend/reports/w6/probe_audit_invariant.json`（逐格 window / target / denominator + basis /
admitted / terminal / stream_break / audit_rows / diff / by_outcome / state + 汇总 +
`pg_guard` 自证 + 时钟偏移）。
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

#: **严格分母的词表** —— 逐字抄 `deploy/loadtest/driver.py:327-329` 的 `_TERMINAL_OUTCOMES`
#: （U-130）。`truncated` / `http_4xx` / `http_5xx` / `timeout` / `conn_error` 都不在列：
#: 它们没有 `terminal: true` 终止帧，没资格断言"服务端落了一条终态行"。
#: ⚠️ 改这里就是改判据 ⇒ 必须与 W7 的驱动同步（同步不了就别比，标代理）。
TERMINAL_OUTCOMES = ("ok", "clarify", "refuse", "error_frame", "async_degraded")

#: 分母来源标签（进产物，让读者看得见这一格是严格式还是代理）。
BASIS_PROVIDED = "admission.terminal"
BASIS_DERIVED = "derived:outcomes"
BASIS_PROXY = "admitted_proxy:2xx"

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
    """取 `admission.admitted`（HTTP 2xx）。**缺字段就是缺字段** —— 回 None，不当 0（不可引用清单同族）。

    ⚠️ 它只是"进了流"的读数，含 `truncated` ⇒ 只能当**代理**，不能当不变量的分母（见文件头）。
    """
    adm = scenario.get("admission")
    if isinstance(adm, dict) and isinstance(adm.get("admitted"), int):
        return int(adm["admitted"])
    return None


def derived_terminal(scenario: dict) -> int | None:
    """`Σ outcomes{词表}` —— 与 `driver.py:363-364` 逐样本的判定**同一个定义**（不是第二份真相）。

    没有 `outcomes` 或值不成整数 ⇒ None；`outcomes` 全是非终态桶（如只有 `http_4xx`）⇒ **真 0**，
    交给 `classify()` 判空格子。
    """
    out = scenario.get("outcomes")
    if not isinstance(out, dict) or not out:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in out.values()):
        return None
    return sum(v for k, v in out.items() if k in TERMINAL_OUTCOMES)


def denominator_of(scenario: dict) -> tuple[int | None, str | None, dict | None]:
    """严格分母 + 来源标签 + 「自报值与推导值不等」的取证。

    优先级：① W7 自己写的 `admission.terminal` → ② 按词表从 `outcomes` 推导 → ③ `admitted` **代理**
    （只在前两条都取不到时；代理格的 `invariant_ok` **不等于**严格式成立）。
    ①②都取得到而不等 ⇒ 采用 ①（写件人的自报值）并把两个数都落进产物，**不静默挑一个**。
    """
    adm = scenario.get("admission")
    provided = int(adm["terminal"]) if isinstance(adm, dict) and isinstance(adm.get("terminal"), int) else None
    derived = derived_terminal(scenario)
    mismatch = ({"provided": provided, "derived": derived}
                if provided is not None and derived is not None and provided != derived else None)
    if provided is not None:
        return provided, BASIS_PROVIDED, mismatch
    if derived is not None:
        return derived, BASIS_DERIVED, mismatch
    proxy = admitted_of(scenario)
    return (proxy, BASIS_PROXY, mismatch) if proxy is not None else (None, None, mismatch)


def window_of(receipt: dict, scenario: dict) -> tuple[datetime | None, datetime | None, str]:
    """返回 (begin, end, kind)，kind ∈ {"scenario", "receipt", "single", "ambiguous", "missing"}。

    多场景回执若只有 receipt 级窗口 ⇒ `ambiguous`：拿整批窗口去比单场景的分母会恒假。
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


def classify(denominator: int | None, audit_rows: int | None) -> tuple[str, int | None]:
    """判据唯一形状：分母没测到 / 空格子恒真 / 没数到行 ⇒ 不适用；差为 0 ⇒ 成立；否则**双向**都算违反。

    `denominator == 0` ⇒ `not_applicable`：这一格一条终态请求都没进图，等式**恒真**，
    把它算进"成立"就是给一个不检验任何东西的格子发绿灯（盘上唯一的全 0 格 = `healthy_r19_wrong_target_404`，
    靶子本来就该 0 行审计）。
    """
    if denominator is None or audit_rows is None:
        return NOT_APPLICABLE, None
    if denominator == 0:
        return NOT_APPLICABLE, None
    diff = denominator - audit_rows
    return (INVARIANT_OK, 0) if diff == 0 else (INVARIANT_VIOLATED, diff)


def span_void(end: datetime | None, window_pad: timedelta, table_min: datetime | None) -> bool:
    """窗口右端**早于**表里最老的一行 ⇒ 这条格作废（`not_applicable`），不是"少落"。

    为什么需要：本探针数的是**共享实例**上现存的行为差，而 `app.audit_log` 的行可以被清理或整表重载
    （09-22 / 09-28 就在同一实例上实测到 `app.embed_doc` 的统计量被清零）。老回执的窗口若落在
    "现存最老一行"之前，数到 0 行是**表的历史长度**决定的，与被测系统有没有落终态无关 ——
    把它写成"差 = 分母"就是把清理动作报成缺陷（与不可引用清单同族）。
    """
    return bool(end and table_min and (end + window_pad) < table_min)


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
    basis_counts: dict[str, int] = {}
    for r in rows:
        key = str(r.get("denominator_basis") or "none")
        basis_counts[key] = basis_counts.get(key, 0) + 1
    reason_counts: dict[str, int] = {}
    for r in rows:
        why = r.get("inapplicability_reason")
        if why:
            reason_counts[str(why)] = reason_counts.get(str(why), 0) + 1
    target_counts: dict[str, int] = {}
    for r in rows:
        key = str(r.get("target"))
        target_counts[key] = target_counts.get(key, 0) + 1
    violated = [
        {"receipt": r["receipt"], "denominator": r["denominator"], "denominator_basis": r["denominator_basis"],
         "admitted": r["admitted"], "terminal": r["terminal"], "audit_rows": r["audit_rows"], "diff": r["diff"],
         "rows_that_window_day": r.get("rows_that_window_day")}
        for r in rows if r["state"] == INVARIANT_VIOLATED
    ]
    by_day: dict[str, int] = {}
    for r in rows:
        if r["state"] != INVARIANT_VIOLATED:
            continue
        b = r.get("begin")
        day = b.astimezone(UTC).date().isoformat() if isinstance(b, datetime) else "unknown"
        by_day[day] = by_day.get(day, 0) + 1
    return {
        "n_receipts_scanned": len({r["receipt"] for r in rows}),
        "n_scenario_cells": len(rows),
        "state_counts": counts,
        "invariant_ok_cells": counts.get(INVARIANT_OK, 0),
        "violated_cells": violated,
        "undercount_side": sum(1 for v in violated if (v["diff"] or 0) > 0),
        "overcount_side": sum(1 for v in violated if (v["diff"] or 0) < 0),
        "violated_by_window_day": by_day,
        "attribution_note": "「少落」不等于「被测系统没落终态」——先对照每格的 rows_that_window_day 与 "
                            "pg_guard.table_day_counts：共享实例上这张表**现存**的历史可能短于回执，"
                            "当天整表只剩的行数小于本格分母时，差值说的是表、不是服务。"
                            "「当时没写」与「写了又被清理」本探针分不开 ⇒ 只有当日行数与分母同量级的格子，"
                            "才指认得出东西（具体的读数进产物与交付报告，不写死在这里）。",
        "denominator_basis_counts": basis_counts,
        "inapplicability_reason_counts": reason_counts,
        "strict_denominator_cells": basis_counts.get(BASIS_PROVIDED, 0) + basis_counts.get(BASIS_DERIVED, 0),
        "proxy_denominator_cells": basis_counts.get(BASIS_PROXY, 0),
        #: `admitted > terminal` 的格子 = 本性格子里有断流/超时 ⇒ **老分母会假报"少落"** 的那些格。
        "stream_break_cells": [{"receipt": r["receipt"], "admitted": r["admitted"], "terminal": r["terminal"],
                                "gap": (r["admitted"] - r["terminal"])
                                if (r["admitted"] is not None and r["terminal"] is not None) else None}
                               for r in rows
                               if r.get("admitted") is not None and r.get("terminal") is not None
                               and r["admitted"] > r["terminal"]],
        "zero_denominator_cells": [{"receipt": r["receipt"], "target": r.get("target")}
                                   for r in rows
                                   if r.get("denominator") == 0 and r["state"] == NOT_APPLICABLE],
        #: 靶子面：`terminal = 0` 的常见成因是"整批打在错端口上"（驱动 `--target` 有默认值，
        #: 见 `deploy/loadtest/driver.py:832`；compose 映射的端口是另一个）⇒ 靶子必须落盘，
        #: 让读者一眼看出这批格打在哪，而不是只看到"0 条终态"。
        "target_counts": target_counts,
        "provided_vs_derived_mismatch": [{"receipt": r["receipt"], **r["mismatch"]} for r in rows
                                         if r.get("mismatch")],
        "clock_skew_s": skew_s,
        "edge_unreliable": skew_s is None or abs(skew_s) > SKEW_LIMIT_S,
        "window_rule": "时间列见 pg_guard.time_column（本轮实测 = `timestamp`，盘上**没有** `created_at`）："
                       f"<时间列> >= begin AND <时间列> < finished_at + {WINDOW_PAD.total_seconds():.0f}s"
                       "（右端含该秒；回执时间戳为秒级）",
        "note": "严格式 = **terminal − 审计行数 = 0**（`terminal = Σ outcomes{ok,clarify,refuse,error_frame,"
                "async_degraded}`，词表逐字来自 `deploy/loadtest/driver.py:327-329`；U-130）。`admitted` 只是 "
                "HTTP 2xx、含 `truncated`（200 但流断在半途）⇒ 只在 terminal 两条取法都落空时作**显式标注的代理**，"
                "代理格的 ok 不等于严格式成立。差值是**双向**的：差 > 0 = 有请求没落终态（W7 修复前那一格），"
                "差 < 0 = 一个请求落了多行（U-129 的双终态形状）。分母取不到、或分母为 0（等式恒真）的格子一律 "
                "not_applicable，**不许**当成差 0。",
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
        #: 表里**现存**行的时间跨度：判"窗口是否早于表的历史"要用它，不能假设数得到。
        span = await (await conn.execute(sql.SQL("select min({}), max({}), count(*) from app.{}").format(
            sql.Identifier(time_col), sql.Identifier(time_col), sql.Identifier(table)
        ))).fetchone()
        table_min = span[0] if isinstance(span[0], datetime) else None
        stamp["table_span"] = {
            "min": table_min.isoformat() if table_min else None,
            "max": span[1].isoformat() if isinstance(span[1], datetime) else str(span[1]),
            "rows": int(span[2]),
        }
        #: 现存行的**成分**：这是"少落"读数的对照面。某天整表只剩 70 行，而那天 8 份回执的终态请求
        #: 合计 ≈ 561 ⇒ 差额不能归因给被测系统（也可能是清理）。服务端 `outcome` 的词表与驱动
        #: **不同**（`success` ≠ `ok`），所以这里的 `by_outcome` 只能读"落了几行"，不许拿去比词表。
        comp = await (await conn.execute(sql.SQL(
            "select outcome, count(*), min({}), max({}) from app.{} group by outcome").format(
            sql.Identifier(time_col), sql.Identifier(time_col), sql.Identifier(table)))).fetchall()
        stamp["table_outcome_counts"] = {
            str(o): {"rows": int(n),
                     "first": lo.isoformat() if isinstance(lo, datetime) else str(lo),
                     "last": hi.isoformat() if isinstance(hi, datetime) else str(hi)}
            for o, n, lo, hi in comp
        }
        days = await (await conn.execute(sql.SQL(
            "select ({} at time zone 'UTC')::date, count(*) from app.{} group by 1 order by 1").format(
            sql.Identifier(time_col), sql.Identifier(table)))).fetchall()
        #: ⚠️ 按 **UTC** 切日：回执窗口是 UTC，用服务端 `TimeZone` GUC 切会把格子的对照日切错一天。
        days_map = {str(d): int(n) for d, n in days}
        stamp["table_day_counts"] = days_map
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
            row["rows_that_window_day"] = days_map.get(str(row["begin"].astimezone(UTC).date()))
            if span_void(row["end"], WINDOW_PAD, table_min):
                row["state"], row["diff"] = NOT_APPLICABLE, None
                row["inapplicability_reason"] = "window_before_table_span"
                continue
            row["state"], row["diff"] = classify(row["denominator"], row["audit_rows"])
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
            denominator, basis, mismatch = denominator_of(sc)
            adm = admitted_of(sc)
            terminal = denominator if basis in (BASIS_PROVIDED, BASIS_DERIVED) else None
            state = NO_DB
            reason = None
            if denominator is None:
                state, reason = NOT_APPLICABLE, "denominator_unavailable"
            elif denominator == 0:
                state, reason = NOT_APPLICABLE, "zero_denominator_vacuous"
            elif kind in ("ambiguous", "missing"):
                state, reason = AMBIGUOUS_WINDOW, f"window_{kind}"
            rows.append({
                "receipt": path.name,
                "scenario_index": idx,
                "schema": data.get("schema"),
                "target": data.get("target"),
                "window_kind": kind,
                "begin": begin,
                "end": end,
                "denominator": denominator,
                "denominator_basis": basis,
                "admitted": adm,
                "terminal": terminal,
                "stream_break_gap": (adm - terminal) if (adm is not None and terminal is not None) else None,
                "mismatch": mismatch,
                "inapplicability_reason": reason,
                "audit_rows": None,
                "rows_that_window_day": None,
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
        "strict_denominator": "terminal − app.audit_log 行数 = 0",
        "denominator_definition": {
            "terminal_outcomes": list(TERMINAL_OUTCOMES),
            "vocabulary_source": "deploy/loadtest/driver.py:327-329 (_TERMINAL_OUTCOMES, U-130)",
            "field_table_source": "deploy/loadtest/README.md §三.0.1p",
            "proxy": f"{BASIS_PROXY} 仅在 admission.terminal 与 outcomes 都取不到时使用，且逐格标注",
        },
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
    print(f"表跨度（现存行）：{stamp['table_span']}（时间列 = {stamp['time_column']}）")
    print(f"时钟偏移 = {s['clock_skew_s']}s（阈值 {SKEW_LIMIT_S}s，edge_unreliable = {s['edge_unreliable']}）")
    print(f"分母来源分布：{s['denominator_basis_counts']}（严格 {s['strict_denominator_cells']} / "
          f"代理 {s['proxy_denominator_cells']}）")
    print(f"场景格 {s['n_scenario_cells']} 格：状态分布 {s['state_counts']}；"
          f"违反 {len(s['violated_cells'])}（少落 {s['undercount_side']} / 多落 {s['overcount_side']}）")
    if s["inapplicability_reason_counts"]:
        print(f"不作数的原因分布：{s['inapplicability_reason_counts']}")
    if s["stream_break_cells"]:
        print(f"🔴 断流格 {len(s['stream_break_cells'])} 处（这些格里老分母 `admitted` 会假报「少落」）："
              + "；".join(f"{c['receipt']} admitted={c['admitted']}/terminal={c['terminal']}"
                          f"（差 {c['gap']}）" for c in s["stream_break_cells"]))
    else:
        print("断流格 0 处 ⇒ 今天的两分母同值（`admitted − terminal = 0` 逐格成立）")
    if s["zero_denominator_cells"]:
        print("恒真空格子（分母 0，不计入成立）："
              + "；".join(f"{c['receipt']} ← target={c['target']}" for c in s["zero_denominator_cells"]))
    print(f"靶子面（回执 target 分布）：{s['target_counts']}")
    for v in s["violated_cells"]:
        print(f"   ⚠️ {v['receipt']} 分母={v['denominator']}({v['denominator_basis']}) "
              f"审计行={v['audit_rows']} 差={v['diff']}｜对照：该 UTC 日整表现存 {v['rows_that_window_day']} 行")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
