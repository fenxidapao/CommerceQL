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

🔴 **两个差值不许并成一个数**（2026-09-29 第二十轮，W7 明确要求"两数请分写别并"）
------------------------------------------------------------------------
同一段路的两半各有归属，合成一个数就同时丢掉两件事：

| 差值 | 说的是 | 归属 |
|---|---|---|
| `admitted − terminal` | **有没有断流**（2xx 但没读到终止帧）⇒ 是**量具/客户端侧**的形状 | U-129 家族（终态形状），**与审计行无关** |
| `terminal − app.audit_log 行数` | **进了图的终态有没有落段 1 审计行** ⇒ 是**服务端侧**的缺失 | **U-130** |

⇒ 本产物**逐格同时落两个具名键**（`gap_admitted_minus_terminal` / `gap_terminal_minus_audit_rows`，
包在 `two_numbers` 里各自带 `attribution`），并**刻意不输出** `admitted − 审计行` 这个合并值 ——
代数上它等于两半之和，但报出来会把"4 条断流"和"4 条没落审计"混成同一个缺陷。
本轮盘上的活样本 = `healthy_r20_aprime_c12n108.json`：`admitted 99 / terminal 99 / 审计行 95`
⇒ 前一半 **0**（没断流）、后一半 **+4**（四条没落段 1）—— 两个数分别是"无事"和"有缺陷"，
并成一个 `99 − 95 = 4` 就看不出前一半了。

🔑 **task_id 级取证通道（W7 第二十轮新增字段 `codes_task_ids`，第二十三轮起盘上首次非空）**：回执里带
`codes_task_ids`（`错误码 → ≤12 条 task_id`，见 `driver.py:542`）⇒ 本器件**自动**逐 id 点名哪些在
`app.audit_log` 有段 1 行、哪些没有，**不再靠时间窗猜**。覆盖面按**三态**数（`absent` / `empty` / `present`，
见 `codes_task_ids_presence()`）⇒ "0 格带 id"这句话永远要连着"其中几格是压根没键、几格是有键但无 id 可给"。

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

⚠️ **从 `deploy/.env` 抄 `DATABASE_URL` 时有两个坑**（2026-09-29 各实测一次，都是"探针拒绝出产物"而不是"连上了"）：
① 它写的是 SQLAlchemy 式 `postgresql+psycopg://` ⇒ psycopg 不认（且不报在明显的地方：连接池会一路重试到
   `PoolTimeout`，把排查方向带去"库挂了/密码错了"）。**scheme 契约不在本窗口重写**：`pg_guard.force_readonly()`
   自第十二轮起直接调 W1B 的 `app/repo/dsn.py:153 to_libpq_conninfo()`（库里唯一的那件，`build.py:186` 等 5 处生产
   调用也走它）；它对未知 scheme 直接抛、不静默透传，但**报错文案会回显 `url[:24]`** ⇒ 本窗口这层掐掉原异常、不回显，
   所有异常文案统一过 `pg_guard.safe_error_text()`（`type(exc).__name__` + 过 `scrub_secrets` 的摘要）。
② 它的 host 是 compose **内部**名 `pg` ⇒ 宿主机解析不了（`failed to resolve host 'pg'`），
   compose 把 `5432:5432` 映射到宿主 ⇒ 本机跑要自己换成 `localhost`。**这条不做自动改写**：
   悄悄换主机等于换靶子，宁可红一次让操作方看见。

产物 = `backend/reports/w6/probe_audit_invariant.json`（逐格 window / target / denominator + basis /
admitted / terminal / **`two_numbers`（两个差值分写，各带归属）** / audit_rows / diff / by_outcome /
**`codes_task_ids` 与 `task_id_evidence`（含 `turn_of_given_id`）** / **`thread_position`（turn 维度）** /
state + 汇总（含 `two_number_block` / `task_id_channel` / **`thread_channel`** / `proxy_only_cells`）
+ `pg_guard` 自证（含 **`thread_ruler`** 全库面）+ 时钟偏移。
⚠️ `thread_channel` 与 `client_side_crosscheck` 同性质：**进产物、不进判据**（`classify()` 不读它们）——
   架构 `07 §4.8` 的 `U-130 v1.7.12` 只加了"崩臂必须限定 `turn≥2`"这一句口径，**没改严格式本身**。
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

from pg_guard import (  # noqa: E402
    force_readonly,
    open_readonly,
    redact_dsn,
    safe_error_text,
    target_stamp,
)

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

#: 🔴 写行延迟的分桶阈值（秒）—— 用来回答"pad 只 1 秒会放过多少"，**不**用来放宽 pad。
#:    `188` 不是凑数：它是本轮实测 max lag（187.623s）向上取整，W7 第二十六轮 ② 给的同一个量级 ⇒
#:    我方把它做成"若真按 max lag 放宽 pad，窗口会多吸进多少条 run"的**对照读数**（`edge_control`）。
LAG_BUCKETS_S = (1, 10, 60, 188)
#: 吸边对照用的宽 pad（秒）；与 `LAG_BUCKETS_S` 的最后一档同值，改一处就要改另一处。
WIDE_PAD_S = 188.0

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


def codes_task_ids_presence(scenario: dict) -> str:
    """`codes_task_ids` 这一格的**三态**：`absent`（键没有）/ `empty`（键在但是 `{}`）/ `present`（有 id）。

    存在的理由（W7 第二十二轮 ④ + 我方实测）：两态读法会把"字段没落地"与"字段落地但这条错误码**根本没有
    `task_id` 可给**"混成同一个 0 ⇒ 冤枉字段。盘上就有活例：`r22_lock_c8n8.json` 的
    `codes = {SESSION_CONFLICT: 7}` 而 `codes_task_ids = {}`（409 没有 ack 帧 ⇒ 无 id 可记，不是坏）。
    """
    raw = scenario.get("codes_task_ids")
    if not isinstance(raw, dict):
        return "absent"
    return "present" if codes_task_ids_of(scenario) else "empty"


def terminal_of(scenario: dict) -> int | None:
    """`terminal` 本身（与"分母走哪条路"无关）：① W7 自报 `admission.terminal` → ② 按词表推导。

    ⚠️ 不能用 `denominator_of()` 的返回值代替：那条路可能落到 `admitted` **代理**，
    而代理值当 `terminal` 用就等于把两个差值并成一个（W7 第二十轮禁的那件事）。
    """
    adm = scenario.get("admission")
    if isinstance(adm, dict) and isinstance(adm.get("terminal"), int):
        return int(adm["terminal"])
    return derived_terminal(scenario)


def codes_task_ids_of(scenario: dict) -> dict[str, list[str]] | None:
    """取 W7 第二十轮新增的 `codes_task_ids`（`错误码 → ≤12 条 task_id`，`driver.py:542`）。

    形状不对（不是 dict、值不是字符串列表、全空）⇒ **None**，不做"半解析"：
    有半个键就照没键处理，免得拿一个残缺的 id 集去宣布"逐 id 点名过了"。
    """
    raw = scenario.get("codes_task_ids")
    if not isinstance(raw, dict) or not raw:
        return None
    out = {str(code): list(ids) for code, ids in raw.items()
           if isinstance(ids, list) and ids and all(isinstance(x, str) for x in ids)}
    return out or None


def client_side_evidence_of(scenario: dict) -> dict | None:
    """W7 第二十一轮那两条**客户端侧探测器**在盘上回执里唯一可离线复算的那一条：`stage=none` 计数。

    来源 = `scenario.terminal_provenance`（`{终态词: {"stage=X|reason=Y": n}}`），W7 的
    `probe_session_owner_context.py` 用同一个面判 `terminal_without_any_stage`。
    🔴 **诊断件、不参与判据**：`classify()` 不读它，本函数的任何数都不进严格式 —— 因为实测两者**不同阶**
    （r20 那格 `stage=none` 的 error_frame = 11、全体 = 22，而我方那一格的差 = **4**），
    把它当"缺的那几条"来对齐 = 造一条解释力过头的假绿灯。另一条 `terminal_digest_same_as_turn1`
    需要**同一会话的两轮 SSE 原文**，盘上回执结构性不含 ⇒ 本批 UNVERIFIED，不在这里冒充。
    """
    raw = scenario.get("terminal_provenance")
    if not isinstance(raw, dict) or not raw:
        return None
    by_outcome: dict[str, int] = {}
    for outcome, buckets in raw.items():
        if not isinstance(buckets, dict):
            continue
        n = sum(v for k, v in buckets.items() if isinstance(k, str) and k.startswith("stage=none")
                and isinstance(v, int))
        if n:
            by_outcome[str(outcome)] = n
    if not by_outcome:
        return {"by_outcome": {}, "total": 0}
    return {"by_outcome": by_outcome, "total": sum(by_outcome.values())}


def two_numbers_of(admitted: int | None, terminal: int | None, audit_rows: int | None) -> dict:
    """**两个差值分写**的落盘形状（不许合并 ⇒ 本函数不返回 `admitted − audit_rows`）。"""
    return {
        "admitted": admitted,
        "terminal": terminal,
        "audit_rows": audit_rows,
        "gap_admitted_minus_terminal": (admitted - terminal) if (admitted is not None and terminal is not None) else None,
        "gap_terminal_minus_audit_rows": (terminal - audit_rows) if (terminal is not None and audit_rows is not None) else None,
        "attribution": {
            "gap_admitted_minus_terminal": "非 0 = 有 2xx 没读到终止帧（断流/客户端超时）⇒ 量具与客户端侧的形状，"
                                           "归 U-129 家族；**与 app.audit_log 行数无关**",
            "gap_terminal_minus_audit_rows": "严格式的差：> 0 = 进了图的终态没落段 1 审计行（U-130），"
                                             "< 0 = 一个请求落了多行（双终态）",
        },
        "merge_forbidden": "admitted − 审计行数 在代数上等于上面两半之和，但本产物**不输出它** —— "
                           "合成一个数会把'N 条断流'与'M 条没落审计'报成同一个缺陷。",
    }


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


#: 🔑 **thread 尺的出处**（借别人字段的语义 = 先读他的码并记下锚点；**不复制他的 SQL** —— 复制 = 第二份真相，
#:    所以测试里做**同源守卫**：他改尺 ⇒ 我方测试当场红）。
#:    文件 = `deploy/loadtest/r23_thread_from_checkpoints.sql`，语义逐字对应四段（**按语句标签锚定，不按行号** ——
#:    W7 第二十五轮 ③ 明说"我下一轮可能要动 ⑥⑦，行号会漂"）：
#:    ① 尺自检（`tk → thread` 必须 1:1，不成立整段作废）／⑨ 崩臂在 thread 尺上的位置
#:    ／⑩ 「0 审计行 = 崩臂」必须限定 `turn>=2`／⑭ 四条措辞纪律 + `gap_literal_DO_NOT_USE` 的命名
#:    ／⑭b "先过滤再算 turn"的假绿守卫（W7 第二十八轮升级成三态：`NULL / t / f`，列名列数未动）
#:    ／⑭c "读得太早"的假红守卫／**⑮ = 判据② 的两臂配对（臂1 零行 / 臂2 行数 > 1，分母 = run，空作用域 NULL）**
#:    ／**⑯ = 写面(`lg.checkpoint_writes`)能否落到 run 的可行性 + `branch:to:%` 路由集**
#:    ／**⑯b = 全库侧：terminal 写按 run 归属落在第几轮 + 这些 run 里有几条零审计行**
#:    ／**⑰ = U-129 验收「三格并报」的格2／格3（格2 = `t2` 被路由进 `audit_supp` ∧ 本轮没写 terminal ⇒ 期望 0，
#:      pre-fix 基线 5；格3 = `t2` 本轮自己有 terminal 写 ⇒ 期望 ≥1，pre-fix 基线 0，窗内无 turn≥2 样本记 `n/a`）**
#:    ／**⑰b = 路由行的覆盖面形状（建线期行 vs 真覆盖损失的拆分，不受窗口限定）**
#:    —— ⑮ 是 W7 按架构 `v1.7.14` 新起的**独立语句**（他明说"不给 ⑭ 加列"）⇒ 我方把配对断言的**外部对应件**
#:    锚在这里：他删/改名 ⇒ 我方红（借语义不锚 = 第十四轮那条纪律的反面）。
#:    ⚠️ 为什么本窗口要自己接这把尺：架构在 `07 §4.8` 的 `U-130` 上按它加了 **`turn≥2` 限定**（v1.7.12，
#:    基准 `399b786`）—— "0 审计行"不是崩臂独有指纹，不加限定的批级计数会把崩臂**高估约 40 倍**
#:    ⇒ 我方那条"少落 = 缺陷"的读数必须带 turn 维度。
#:    ⚠️ 行号只在**读数那一秒**有效 ⇒ 引用以标签为准。第十九轮实测（树 `beac8c6`，尺件在 W7 `810aa25`；
#:    工作树 == HEAD，`git diff --stat` 对该文件为空）：⑭b `:346`、⑮ `:418`、⑯ `:450`、⑯b `:512` **未漂**，
#:    新 ⑰ `:535`、⑰b `:594`；件规模 = **23 个标签 / 带圈标签行 24（⑯ 内部有一行 `-- ②` 子注释）/
#:    按 `;` 切非空 26 条 / 616 行（`splitlines()` 与 `wc -l` 两口径同值）/ 43,876 字节**；
#:    字节面 = **LF**（CRLF 行数 0）⇒ `md5(raw) = md5(LF) = b5a1bd546688…`、`md5(CRLF) = e86f72f56330…`。
#:    🔻 第十八轮录的 21/24/533 与 `3ec339227dbd…` 作废于 W7 第三十轮追加 ⑰⑰b（第三次同类过期，交付 §5.54）。
#:    ⚠️ 报这类数一律「数 + 方法名 + 当时 tree」三件同写，且**下一轮必须重新现测**。
THREAD_RULER_SOURCE = "deploy/loadtest/r23_thread_from_checkpoints.sql 段 ①⑨⑩⑫b⑭⑭b⑭c⑮⑯⑯b⑰⑰b（按标签锚定，行号会漂）"
THREAD_RULER_SECTIONS = ("①", "⑨", "⑩", "⑫b", "⑭", "⑭b", "⑭c", "⑮", "⑯", "⑯b", "⑰", "⑰b")

#: 只取全库的 `(thread, tk, 首次出现时间)`；**分桶与赋 turn 号都在 Python 里做**
#: ⇒ 不经过任何展开/聚合，避开交付 §5.40 那一族（"经过展开的行数就不是行数"）。
#: 🔴 这条 SQL **不带窗口条件**是纪律而不是偷懒：turn 必须在 thread **全历史**上算完，再由调用方按窗口筛
#:    （W7 的 ⑭b 守卫）。反过来"先按窗口过滤再算 turn"会把窗口里的第 2 轮读成 turn1 ⇒ `crash_turn2plus`
#:    静默变 0 ⇒ **假绿**。
CHECKPOINT_RUNS_SQL = """
select thread_id,
       checkpoint->'channel_values'->>'task_id' as tk,
       min((checkpoint->>'ts')::timestamptz) as first_seen
from lg.checkpoints
where checkpoint->'channel_values'->>'task_id' like 'tk_%'
group by 1, 2
"""

#: 🔴 「1,322」这类数**必须连谓词一起报**（W7 第二十六轮 ⑤ = 我方 P23 ⑥ 的诉求，他已落成 ⑫b）。
#:    上一版我方只在**文档里**写了"1,322 / 1,317 / 5"三个数 ⇒ 它们不在任何产物里，引用者无从复算；
#:    本轮把它做成常驻读数（**一条语句里四个谓词各自直接数**）。⚠️ 两处 NULL 陷阱都是**本轮实测踩到的**：
#:    ① 不用 `task_id is null` 那种几乎恒真的谓词（W7 第一稿由此得到过 1,322，他已在 ⑫b 用 `not in` 复核出 5）；
#:    ② 也**不能**裸写 `bool_or(tk like 'tk_%')` —— `NULL like …` 出 NULL，而 `bool_or` **忽略 NULL**，
#:      一个"全部行都没有 tk"的 thread 会聚合出 NULL 而非 false ⇒ `filter (where not has_tk)` **恒 0**
#:      （我方第一版就是这么错的，被自己的产物测试逮到：`1322 == 1317 + 0`）。⇒ 必须 `coalesce(..., false)`。
#:    第四个读数 `threads_multi_tk` 是给"轮次编号"做算术自证用的：`tk_runs − threads_with_tk` 必须
#:    **恰等于** `runs_by_turn_bucket.turn2plus`（每条 thread 从 1 连续编号才成立）。
THREAD_SCOPE_SQL = """
with t as (
    select thread_id,
           bool_or(coalesce(checkpoint->'channel_values'->>'task_id' like 'tk_%', false)) as has_tk,
           count(distinct case when checkpoint->'channel_values'->>'task_id' like 'tk_%'
                               then checkpoint->'channel_values'->>'task_id' end) as n_tk
    from lg.checkpoints
    group by thread_id
)
select count(*) as threads_all,
       count(*) filter (where has_tk) as threads_with_tk,
       count(*) filter (where not has_tk) as threads_without_tk,
       count(*) filter (where n_tk > 1) as threads_multi_tk
from t
"""

#: 🔴 台账**第 8 面** `lg.checkpoint_writes`（架构 `07 §16.5` v1.7.15 = `b62e011`，§38 ④ 点名给 W6 做对照）。
#:    它数的是**「哪一轮真的往 `terminal` 通道写过」** ⇒ 与我方判据② 的"多落"臂**同向**、但**不同量纲**
#:    （那臂数 `app.audit_log` 的行数/每 run，这里数 channel 写行/每 thread）⇒ 只许**对照**、不许代。
#:    一条语句把两侧的对撞都数完（`ck_only_threads` / `writes_only_threads` 是**集合差**，
#:    不是 `thread_id is null` 那种谓词 —— 交付 §5.43 的"没有 X 用集合差"）。
CHECKPOINT_WRITES_SHAPE_SQL = """
select (select count(*) from lg.checkpoint_writes) as rows_all,
       (select count(distinct thread_id) from lg.checkpoint_writes) as threads_all,
       (select count(distinct thread_id) from lg.checkpoints) as ck_threads_all,
       (select count(*) from (select distinct thread_id from lg.checkpoints
                              except select distinct thread_id from lg.checkpoint_writes) x) as ck_only_threads,
       (select count(*) from (select distinct thread_id from lg.checkpoint_writes
                              except select distinct thread_id from lg.checkpoints) y) as writes_only_threads,
       (select count(*) from lg.checkpoint_writes where channel = 'terminal') as terminal_rows,
       (select count(distinct thread_id) from lg.checkpoint_writes
         where channel = 'terminal') as terminal_threads,
       (select coalesce(max(c), 0) from (select count(*) as c from lg.checkpoint_writes
          where channel = 'terminal' group by thread_id) z) as max_terminal_writes_per_thread
"""

#: 对撞要按**集合**比，不是按数比 ⇒ 取回带终态写的 thread 清单（今天 813 条，逐行取回）。
TERMINAL_WRITE_THREADS_SQL = """
select distinct thread_id from lg.checkpoint_writes where channel = 'terminal'
"""

#: 🔴 第十八轮新增：**写面能不能落到 run**（W7 `⑯/⑯b` 提的那条路，我方自己走一遍、**不复制他的 SQL**）。
#:    连法 = 写行的 `checkpoint_id` 回连 `lg.checkpoints` 里**带 `tk_` 的那一行** ⇒ 得到 run。
#:    ⚠️ 两件必须同时报，否则这句话会被读成"归属免费"：
#:    ① **覆盖面**（`*_unmatched` = 连不到任何 `tk_` 检查点的写行）——今天 terminal = **0**、
#:      `branch:to:%` = **非 0** ⇒ 终态写可全量归属，**路由集不是**（用 distinct thread 把"每 thread 一条"这形状钉住，
#:      机制仍 UNVERIFIED）；
#:    ② 归属完的 run 上**turn 由我方尺在全历史上数**（⑭b 那条假绿纪律在这里同样成立：先编号、后归属）。
#:    出口列名规矩：`rows` 只数行、`runs` 只数 run、`channels` 只数通道种数。
WRITES_ATTRIBUTION_SQL = """
with c as (
  select distinct checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), w as (
  select checkpoint_id, thread_id, channel from lg.checkpoint_writes
  where channel = 'terminal' or channel like 'branch:to:%'
)
select count(*) filter (where w.channel = 'terminal') as terminal_rows_via_join,
       count(*) filter (where w.channel = 'terminal' and c.tk is not null) as terminal_matched_rows,
       count(*) filter (where w.channel = 'terminal' and c.tk is null) as terminal_unmatched_rows,
       count(*) filter (where w.channel like 'branch:to:%') as route_rows,
       count(distinct w.channel) filter (where w.channel like 'branch:to:%') as route_channels,
       count(*) filter (where w.channel like 'branch:to:%' and c.tk is null) as route_unmatched_rows,
       count(distinct w.thread_id) filter (where w.channel like 'branch:to:%' and c.tk is null)
           as route_unmatched_threads,
       count(distinct c.tk) as tk_runs_touched
from w left join c on c.checkpoint_id = w.checkpoint_id
"""

#: 两条 tk 清单（逐行取回后在 Python 里配我方尺数 turn ⇒ 不在库里 `row_number()`，避免第三份真相）。
#: 🔴 W8 接手（2026-10-02，@ `f485ffe`，验收窗 T-12 的覆盖面延伸）：`TERMINAL_RUN_TKS_SQL` 是**"本轮自己写了终态"的 run 级证据**
#:    ⇒ 必须排除 `task_path` 第二段 = `__start__` 的入口复位写行（W4 修法 `RUN_SCOPED_STATE_FIELDS` 含 `terminal`，任何 run 走到入口都留一行）。
#:    同件里 465–474 / 485–503 那几处是**行级与 thread 级普查**，不是 run 级"自写终态"证据 ⇒ **本轮未动**（不动的理由也写在这里，防下一轮误读成"漏改"）。
#:    现测（全库，2026-10-02）：`channel='terminal'` 825 行／`__start__` 6 行／3 个 thread，ts 全部在 2026-10-01T12:55:28Z 之后
#:    ⇒ W6 历史批次的 run 级读数作用域内该形状 = 0，**加排除不推翻已登记的数**；换式与不改读数的 A/B 对照见 `backend/reports/w8/RELAY.md` §一。
TERMINAL_RUN_TKS_SQL = """
select distinct c.tk from lg.checkpoint_writes w
  join (select distinct checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk
        from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%') c
    on c.checkpoint_id = w.checkpoint_id
  where w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__'
"""

#: `branch:to:audit_supp` = N-08 那条出口的**路由集**（判据② 的候选生产读点）。
#: ⚠️ 只取 `tk` 清单 ⇒ thread 数由**我方尺**从 tk 反推（交付 §5.54 的"粒度"形状：同一批里 run 数 ≠ thread 数，
#:    两个都要报，不能只报一个 —— W7 ⑯ 那句"70 条全在 turn1"就是这么来的）。
AUDIT_SUPP_RUN_TKS_SQL = """
select distinct c.tk from lg.checkpoint_writes w
  join (select distinct checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk
        from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%') c
    on c.checkpoint_id = w.checkpoint_id
  where w.channel = 'branch:to:audit_supp'
"""

#: 被路由行触到的 run（判"这一面切不切得出**第 2 轮**"要用它，不是用 terminal）。
ROUTE_RUN_TKS_SQL = """
select distinct c.tk from lg.checkpoint_writes w
  join (select distinct checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk
        from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%') c
    on c.checkpoint_id = w.checkpoint_id
  where w.channel like 'branch:to:%'
"""

#: 🔴 第十八轮我方报的"1,318 行连不到 `tk_` 检查点、机制未查"⇒ 第十九轮**自己把它拆开**。
#:    三分类之和必须 = `route_unmatched_rows`（**闭合**才算解释成立；不闭合就还是"机制未查"）：
#:    ① 该写行自己的 `ts` **早于**本 thread 第一个带 `tk_` 的检查点 ⇒「建线期路由行」（不属于任何 run、不是覆盖损失）；
#:    ② 不早于 ⇒ 真·覆盖损失（本轮要盯的就是这一类**该为 0**）；
#:    ③ 该 thread **完全没有**带 `tk_` 的检查点 ⇒ 连"第一个"都无从谈起（`tk → thread` 之外那一小撮）。
#:    ⚠️ 出口列名规矩：`rows` 只数行、`threads` 只数 thread、`runs` 只数 run。
ROUTE_UNMATCHED_SHAPE_SQL = """
with all_ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints
), tk_ck as (
  select distinct thread_id, checkpoint_id from all_ck where tk like 'tk_%'
), first_tk as (
  select thread_id, min(ts) as first_tk_ts from all_ck where tk like 'tk_%' group by thread_id
), routed as (
  select thread_id, checkpoint_id from lg.checkpoint_writes where channel like 'branch:to:%'
), unmatched as (
  select r.thread_id, r.checkpoint_id, a.ts
  from routed r
  left join tk_ck t on t.checkpoint_id = r.checkpoint_id and t.thread_id = r.thread_id
  left join all_ck a on a.checkpoint_id = r.checkpoint_id and a.thread_id = r.thread_id
  where t.checkpoint_id is null
)
select (select count(*) from routed) as route_rows,
       (select count(*) from unmatched) as route_unmatched_rows,
       (select count(distinct thread_id) from unmatched) as route_unmatched_threads,
       count(*) filter (where u.ts < f.first_tk_ts) as unmatched_before_first_tk,
       count(*) filter (where u.ts >= f.first_tk_ts) as unmatched_at_or_after_first_tk,
       count(*) filter (where f.thread_id is null) as unmatched_on_threads_without_tk,
       count(distinct u.thread_id) filter (where u.ts >= f.first_tk_ts) as threads_with_real_loss_rows
from unmatched u left join first_tk f on f.thread_id = u.thread_id
"""


def thread_turns(run_rows: list[tuple]) -> dict:
    """`(thread_id, tk, first_seen)` 行 → `{by_tk: {tk: {thread_id, turn, first_seen, has_row}}, ambiguous_…: [...]}`。

    `turn` = 同一 thread 内按 `first_seen` 升序的序号（与库里 `row_number() over (partition by thread_id
    order by first_seen)` 同义，但在 Python 里数）。⚠️ 两条与 W7 的尺同判据：
    ① 一个 tk 落在**多个** thread 上 ⇒ 不静默取第一个，读数以 `usable = false` 作废（他的 ① 段）；
    ② **这里不看窗口** —— 全历史赋完号才交给调用方按窗口筛（他的 ⑭b：先过滤再编号会把第 2 轮读成 turn1 ⇒ 假绿）。
    """
    by_tk: dict[str, dict] = {}
    tk_threads: dict[str, set[str]] = {}
    per_thread: dict[str, list[tuple]] = {}
    for thread_id, tk, first_seen in run_rows:
        tk_threads.setdefault(str(tk), set()).add(str(thread_id))
        per_thread.setdefault(str(thread_id), []).append((first_seen, str(tk)))
    for thread_id, items in per_thread.items():
        ordered = sorted(items, key=lambda p: (p[0] is None, p[0]))
        for idx, (seen, tk) in enumerate(ordered, start=1):
            by_tk.setdefault(tk, {"thread_id": thread_id, "turn": idx, "first_seen": seen})
    return {"by_tk": by_tk, "ambiguous_tk_to_threads": sorted(t for t, s in tk_threads.items() if len(s) > 1)}


def _bucket(turn: int) -> str:
    return "turn1" if turn == 1 else "turn2plus"


def _spread(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None,
                "negative": 0, "gt_s": {str(s): 0 for s in LAG_BUCKETS_S}}
    vs = sorted(values)
    return {"n": len(vs), "min": vs[0], "median": vs[len(vs) // 2], "max": vs[-1],
            #: 🔴 `negative > 0` 意味着"审计行比 run 起点还早"⇒ `first_seen` 不是那条 run 的起点，
            #:    尺的配窗方向就不该再用了（本轮实测 = 0，W7 第二十六轮 ② 亦为 0 ⇒ 两家同测）。
            "negative": sum(1 for v in vs if v < 0),
            #: 超过各阈值的条数 ⇒ "pad 1 秒放过几成"是**读数**，不是谁转述的一句"约九成"。
            "gt_s": {str(s): sum(1 for v in vs if v > s) for s in LAG_BUCKETS_S}}


def stamp_has_row(ruler: dict, audit_ts: dict[str, datetime], rows_by_tk: dict[str, int]) -> dict:
    """把"这条 run 在 `app.audit_log` 里落了几行 / 行落在什么时刻"标到尺上（全库与单格共用）。

    🔴 `rows_by_tk` 是**必传**的：只给"有没有行"就把判据② 的第二臂（一个 run 落多行 = **多落**）
    永久丢掉了 —— 架构 `v1.7.14` 把判据② 裁成**两条**断言，正是这一臂（直读式对多落是盲的）。
    行数由调用方**逐行取回后在 Python 里数**，不在库里 `count(*)`（交付 §5.40：数出来的"行数"
    一旦经过展开/聚合就不是行数了）。
    """
    for tk, entry in ruler["by_tk"].items():
        ts = audit_ts.get(tk)
        entry["has_row"] = ts is not None
        entry["audit_ts"] = ts
        entry["audit_rows"] = int(rows_by_tk.get(tk, 0))
    ruler["usable"] = not ruler["ambiguous_tk_to_threads"]
    return ruler


def thread_position(ruler: dict) -> dict:
    """按 **`turn` 桶**数"有审计行 / 零审计行"的 run 数（全库面），并落两条前置读数。

    ⚠️ 两条必须一起看，否则这把尺会被读过：
    ① `first_seen` 是 run 的**起点**（checkpoints 里最早那条 ts），而 `app.audit_log` 的时间是**写行时刻**
       ⇒ 两者差值分布落在 `audit_row_minus_first_seen_s`；拿它配"回执窗口"时，窗口边缘会漂这么多；
    ② 零行 run 的**成因不在本函数里**（turn1 那一桶今天仍 `UNVERIFIED`，W7 第二十四轮 ⑦ 也标了未查）
       ⇒ 本函数只给**位置**，不给因果，也不给"谁接在谁后面"（那要 prev-outcome 面，我方今天不产）。
    """
    buckets = ("turn1", "turn2plus")
    runs = ruler["by_tk"]
    total = dict.fromkeys(buckets, 0)
    with_row = dict.fromkeys(buckets, 0)
    rows_in = dict.fromkeys(buckets, 0)
    multi = dict.fromkeys(buckets, 0)
    offsets: list[float] = []
    for entry in runs.values():
        b = _bucket(int(entry["turn"]))
        total[b] += 1
        n_rows = int(entry.get("audit_rows", 0))
        rows_in[b] += n_rows
        if n_rows > 1:
            multi[b] += 1
        if entry["has_row"]:
            with_row[b] += 1
            if isinstance(entry["first_seen"], datetime) and isinstance(entry["audit_ts"], datetime):
                offsets.append(round((entry["audit_ts"] - entry["first_seen"]).total_seconds(), 3))
    return {
        "source": THREAD_RULER_SOURCE,
        "usable": ruler["usable"],
        "ambiguous_tk_to_threads": len(ruler["ambiguous_tk_to_threads"]),
        "tk_runs": len(runs),
        "threads": len({e["thread_id"] for e in runs.values()}),
        "runs_by_turn_bucket": total,
        "runs_with_audit_row": with_row,
        "runs_without_audit_row": {b: total[b] - with_row[b] for b in buckets},
        #: 🔴 **判据② 两条断言的"另一臂"在全库面上**（架构 v1.7.14）：
        #:    `audit_rows_by_turn_bucket` = 各桶的**真行数**（不是"有行的 run 数"，两者只在"一格一行"时相等）；
        #:    `multi_row_turn2plus_runs` = `turn≥2` 且落 **> 1 行**的 run 数 ⇒ 判据② 的第二条断言要求它 = 0；
        #:    `second_form_turn2plus` = `runs(turn≥2) − 行(turn≥2)` = 架构登记的**第二形**（两侧同限定）
        #:      ⇒ 今天应与直读式（`runs_without_audit_row.turn2plus`）逐域相等；**为负就是多落**。
        "audit_rows_by_turn_bucket": rows_in,
        "multi_row_turn2plus_runs": multi["turn2plus"],
        "second_form_turn2plus": total["turn2plus"] - rows_in["turn2plus"],
        "direct_vs_second_form_agree": (total["turn2plus"] - with_row["turn2plus"])
                                       == (total["turn2plus"] - rows_in["turn2plus"]),
        "audit_row_minus_first_seen_s": _spread(offsets),
        #: 🔴 `too_soon_to_read` 的阈值来源：观测到的**最大**写行延迟（W7 ⑭c 同判据："阈值自己算，不写死常数"）。
        #:    没有任何观测样本 ⇒ None ⇒ 各格的 `too_soon_to_read` 一律落 `null`（**未知**，不是 **false**）。
        "max_lag_s": max(offsets) if offsets else None,
        #: **thread 数的谓词口径**（W7 ⑫b 同判据）+ 两条闭合自证。
        #:    `threads_all == threads_with_tk + threads_without_tk` 是集合闭合；
        #:    `tk_runs − threads_with_tk == runs_by_turn_bucket.turn2plus` 是"每条 thread 从 1 连续编号"
        #:    的算术自证（编号若错成"每窗重新起号"，这一条不可能相等）。
        "thread_scope": _scope_block(ruler.get("scope"), len(runs), total["turn2plus"]),
        #: 台账第 8 面的对撞结果（取不到 = `None` = **没测**，不是"测了且没有"）。
        "checkpoint_writes": ruler.get("writes"),
    }


def _scope_block(scope: dict | None, tk_runs: int, turn2plus: int) -> dict | None:
    if not scope or not scope.get("available", True):
        return scope if scope else None
    all_n = int(scope["threads_all"])
    with_n = int(scope["threads_with_tk"])
    without_n = int(scope["threads_without_tk"])
    return {
        **scope,
        "closure_threads_add_up": all_n == with_n + without_n,
        "turn_numbering_closes": tk_runs - with_n == turn2plus,
        "tk_runs_minus_threads_with_tk": tk_runs - with_n,
    }


#: 🔴 第十八轮**改掉**了上一版的一条限制句（自账见交付 §5.53），第十九轮又**补量**了它留下的那一格
#:    （「1,318 行连不到、机制未查」⇒ 本轮三分类拆开、见 `unmatched_route_rows_shape`，交付 §5.54）。
WRITES_FACE_LIMITS = (
    "归属**按通道集分别成立**：`channel='terminal'` 经 `checkpoint_id` 回连 ⇒ 本轮实测 `unmatched_rows = 0`（全可归）；"
    "`branch:to:%` 有一批不可归的行，第十九轮拆开后 = 建线期路由行 + 无 `tk_` 的 thread（两类都**不是** run "
    "覆盖损失，真损失列 `unmatched_at_or_after_first_tk` 应为 0）⇒ 引用「写面能落到 run」必须带是哪个通道集 + 这一格"
    "（条数只看本产物 `unmatched_route_rows_shape`，别抄文案里的数字）",
    "`max_terminal_writes_per_thread` 仍是 **thread 级上界**，与 run 级归属是两件事 ⇒ 它 = 1 只说"
    "「没有任何 thread 写过两次终态」，**不能代** `multi_row_turn2plus_runs`（那臂数的是审计行）",
    "两侧各按各的谓词、面、窗口与前缀，且**粒度不同**（rows / runs / threads 三个数常常不等，见 `granularity`）"
    "⇒ **同向、不互认、不可相加**；相等只是巧合（W7 ⑯⑰ 的连法与我方相同，但他算他的窗、我方算全库）",
)


def _runs_by_turn(tk_set: set[str], by_tk: dict, rows_by_tk: dict[str, int]) -> dict:
    """把一串 run（`tk_`）按**我方尺的 turn** 分桶，并顺带数其中"零审计行"的 run。

    ⚠️ 尺里没有的 tk ⇒ 单列 `unknown_runs`，**不静默丢**（丢了就等于把覆盖面算没）。
    """
    out = {"runs": len(tk_set), "turn1": 0, "turn2plus": 0, "unknown_runs": 0,
           "zero_audit_row_runs": 0, "crash_turn2plus_runs": 0}
    for tk in tk_set:
        entry = by_tk.get(tk)
        if entry is None:
            out["unknown_runs"] += 1
            continue
        turn = int(entry["turn"])
        out[_bucket(turn)] += 1
        if int(rows_by_tk.get(tk, 0)) == 0:
            out["zero_audit_row_runs"] += 1
            if turn >= 2:
                out["crash_turn2plus_runs"] += 1
    return out


def writes_attribution(join: dict, terminal_runs: set[str], audit_supp_runs: set[str],
                       route_runs: set[str], unmatched_shape: dict,
                       ruler: dict, rows_by_tk: dict[str, int]) -> dict:
    """纯函数：写面 → run 的归属结果（输入由调用方逐行取回，turn 用我方尺数）。

    🔴 三个粒度各数各的（W7 ⑯ 那句「70 条全在 turn1」的根因 = 把 **thread 数当 run 数**报）⇒
       每一集 `rows` / `runs` / `threads` **成对报**，不相等时用 `runs_vs_threads_differ` 点名。
    """
    by_tk = ruler.get("by_tk") or {}
    t = _runs_by_turn(terminal_runs, by_tk, rows_by_tk)
    s = _runs_by_turn(audit_supp_runs, by_tk, rows_by_tk)
    rt = _runs_by_turn(route_runs, by_tk, rows_by_tk)

    def _threads(tks: set[str]) -> int:
        return len({str(by_tk[k]["thread_id"]) for k in tks if k in by_tk})

    counts = {"terminal": {"runs": t["runs"], "threads": _threads(terminal_runs)},
              "audit_supp": {"runs": s["runs"], "threads": _threads(audit_supp_runs)},
              "route": {"runs": rt["runs"], "threads": _threads(route_runs)}}
    unmatched = int(join["terminal_unmatched_rows"])
    before = int(unmatched_shape["unmatched_before_first_tk"])
    after = int(unmatched_shape["unmatched_at_or_after_first_tk"])
    no_tk = int(unmatched_shape["unmatched_on_threads_without_tk"])
    total_un = int(unmatched_shape["route_unmatched_rows"])
    return {
        "method": "写行的 `checkpoint_id` 回连 `lg.checkpoints` 里带 `tk_` 的行 ⇒ run；"
                  "turn 由我方尺在**全历史**上数（先编号、后归属，与 W7 ⑭b 同判据）",
        "coverage": {**join, "join_covers_terminal_rows": unmatched == 0},
        "terminal_writes_on_runs": t,
        "audit_supp_routes_on_runs": s,
        #: 🔑 这一格回答「该面切不切得出**第 2 轮**」：路由行按 run 归属后 turn≥2 有没有行（不看 terminal）。
        "route_rows_on_runs": rt,
        "granularity": {**counts,
                        "runs_vs_threads_differ": [k for k, v in counts.items()
                                                   if v["runs"] != v["threads"]],
                        "note": "报数五件 = 数 + 面 + 谓词 + 分母 + **粒度**（本项目第四种混淆形状）"},
        "unmatched_route_rows_shape": {
            **unmatched_shape,
            #: 三分类之和必须恰等于总数 ⇒ **闭合**才可以说"机制已查"。
            "closure_adds_up": before + after + no_tk == total_un,
            #: 🔴 两条 join 形状必须给出同一个 `route_unmatched_rows`：归属语句只按 `checkpoint_id` 连，
            #:    本语句多绑了一个 `thread_id` ⇒ 不等就说明写行的 thread 与检查点的 thread 有对不上的（第三种形状）。
            "agrees_with_attribution_join": bool(
                total_un == int(join["route_unmatched_rows"])
                and int(unmatched_shape["route_rows"]) == int(join["route_rows"])),
            "real_coverage_loss_rows": after,
            "reads": "早于本 thread 第一个带 `tk_` 检查点的路由行（建线期）与「该 thread 完全没有 `tk_` 检查点」"
                     "两类都**不是** run 覆盖损失 ⇒ 只有 `unmatched_at_or_after_first_tk` 那一类才是，本轮应为 0；"
                     "若非 0 ⇒ 「路由集可归属」这句要重开。",
        },
        #: 🔑 判别条（判据② 生产面读点的形状，本轮同时有 terminal 与路由两维）：
        #:    · terminal 写全落 turn1、且不落零审计行 run；
        #:    · 同面上 turn≥2 的 run **有路由行** ⇒ 该面切得出第 2 轮 ⇒ 黏性解释被**现测排除**。
        "discriminator": {
            "terminal_on_crash_turn2plus_runs": t["crash_turn2plus_runs"],
            "terminal_writes_at_turn2plus": t["turn2plus"],
            "route_rows_at_turn2plus": rt["turn2plus"],
            "audit_supp_at_turn2plus": s["turn2plus"],
            "audit_supp_on_crash_turn2plus_runs": s["crash_turn2plus_runs"],
            "face_can_split_turn2plus": bool(rt["turn2plus"] > 0 and t["turn2plus"] == 0),
            "reads": "路由行在 turn≥2 有行而 terminal 写没有 ⇒ 排除「黏在第一轮」；修复后若 "
                     "`terminal_writes_at_turn2plus > 0` ⇒ 判据② 拿到 run 级落库面读点，若仍 = 0 ⇒ 该维判不了 "
                     "⇒ **两种结果都有信息量，0 不许读成「通过」**（pre-fix 它本就 = 0 ⇒ 单独当验收位会恒真）。",
        },
        "attribution_closes": bool(unmatched == 0 and not t["unknown_runs"] and not t["turn2plus"]),
    }


def writes_crosscheck(ruler: dict, shape: dict, terminal_threads: set[str],
                      attrib: dict | None = None) -> dict:
    """把台账第 8 面与我方 thread 尺做**集合对撞**（纯函数，输入由调用方从库里取回）。

    ⚠️ 这一臂今天多半不报任何东西（两侧都等于 813）。它防的是**将来**：`terminal` 若在某个 run 上双写，
       我方审计面的配对臂与这里的 `max_terminal_writes_per_thread` 必须**一起**红，只红一侧就是漏。
    """
    by_tk = ruler.get("by_tk") or {}
    a1 = {str(e["thread_id"]) for e in by_tk.values()
          if int(e["turn"]) == 1 and int(e.get("audit_rows", 0)) > 0}
    a2p = {str(e["thread_id"]) for e in by_tk.values()
           if int(e["turn"]) >= 2 and int(e.get("audit_rows", 0)) > 0}
    any_tk = {str(e["thread_id"]) for e in by_tk.values()}
    ck_n = int(shape["ck_threads_all"])
    w_n = int(shape["threads_all"])
    return {
        "source": "07 §16.5 台账第 8 面 `lg.checkpoint_writes`（`07` v1.7.15；`07` 不在 git ⇒ "
                  "指针用 RELAY §38 = 架构 `b62e011`，不写 `07` 行号）",
        "available": True,
        "shape": {**shape, "thread_sets_equal_across_faces": w_n == ck_n},
        "terminal_writes": {
            "rows": int(shape["terminal_rows"]),
            "threads": int(shape["terminal_threads"]),
            "max_writes_per_thread": int(shape["max_terminal_writes_per_thread"]),
            #: thread 级"双写终态"的上界读数：**> 1 就说明有 thread 被写过两次**（判据② 第二臂的同向对照）。
            "any_double_terminal_write": int(shape["max_terminal_writes_per_thread"]) > 1,
        },
        "set_equality_with_my_turn1_face": {
            "a_turn1_threads_with_audit_row": len(a1),
            "b_terminal_write_threads": len(terminal_threads),
            "a_minus_b": len(a1 - terminal_threads),
            "b_minus_a": len(terminal_threads - a1),
            "equal": a1 == terminal_threads,
            "b_threads_without_any_tk": len(terminal_threads - any_tk),
        },
        "turn2plus_overlap": {
            "a_turn2plus_threads_with_audit_row": len(a2p),
            "a_turn2plus_intersect_b": len(a2p & terminal_threads),
            #: 🔴 第十七轮这里**写死 False**（"归不出轮次"是他转述的设计问题、我方未复算）；
            #:    第十八轮改成**测量值**：terminal 写归属后全落 turn1 且覆盖面闭合 ⇒ `attribution_closes`。
            #:    取不到归属数据 ⇒ `None`（= **没测**），既不写 True 也不写 False。
            "attributable_to_a_specific_turn": None if attrib is None else attrib["attribution_closes"],
        },
        "run_attribution": attrib,
        "limits": WRITES_FACE_LIMITS,
        "verdict_role": "**对照面，不是判据**：`classify()` 不读本块，判据② 的两条断言仍以"
                        "`crash_turn2plus` / `multi_row_turn2plus_runs` 为准（交付 §4.26）。",
    }


def cell_thread_position(ruler: dict, window_task_ids: list[str], begin: datetime, end: datetime,
                         terminal: int | None, gap: int | None, *,
                         audit_rows: int | None = None, max_lag_s: float | None = None,
                         now: datetime | None = None) -> dict:
    """单格窗口内的 thread 尺读数：先在全历史上赋好号（`thread_turns`），**再由这里按窗口筛**。

    ⚠️ 命名与判据形状照 W7 第二十五轮 ⑭ 的四条措辞纪律（他实测三域：字面式 81 / 16 / 1,330，
    正确式 4 / 8 / 13 ⇒ 两式只在"runs 全是 turn≥2"时才相等）：
    ① **判据分子只许写 `crash_turn2plus`**（窗口内 `turn≥2` 且零审计行的 run 数）—— 架构 `v1.7.14` 已把
       这一句裁成判据② 的**主式（直读式）**，并要求配一条**第二臂**：窗口内 `turn≥2` 且行数 > 1 的 run 数 = 0
       ⇒ 本函数同时落 `multi_row_turn2plus_runs` 与 `second_form_turn2plus`，**直读式对"多落"盲**这件事
       从此有读数、不靠注释；

    ② 架构 `v1.7.12` 那句字面式 `terminal − 审计行(turn≥2)` 的被减数**没有限定** ⇒ 我方照他的做法
       把它算出来并命名成 **`gap_literal_DO_NOT_USE`**，让"错的那列"在产物里**可见且不可引**，
       而不是删掉后没人知道有这个坑；
    ③ `scope_empty` = 窗口内一条 run 都没配上 ⇒ 这一维**不可用**（多半是配窗/边缘偏移，不是"没有崩臂"）；
    ④ turn1 的零行（`crash_turn1`）**结构性不进判据**，只并列给数。
    窗口配的是 `first_seen`（run 起点），与审计行写行时刻的差值分布见全库块
    `audit_row_minus_first_seen_s` ⇒ 边缘会漂那么多。

    🔴 参数 `end` 传进来时**已经含 `WINDOW_PAD`**（判据那一侧的窗口形状），所以这里的窗口与严格式
       用的是同一条边；宽 pad 的三把对照只在 `edge_control` 里并列，**不进任何判据**。
    """
    runs = ruler["by_tk"]
    hit = {"turn1": 0, "turn2plus": 0}
    crash = {"turn1": 0, "turn2plus": 0}
    rows_in = {"turn1": 0, "turn2plus": 0}
    multi = {"turn1": 0, "turn2plus": 0}
    extra = timedelta(seconds=WIDE_PAD_S)
    matched = 0
    wide_right = 0
    wide_left = 0
    last_seen: datetime | None = None
    for entry in runs.values():
        seen = entry["first_seen"]
        if not isinstance(seen, datetime):
            continue
        if begin <= seen < end:
            matched += 1
            if last_seen is None or seen > last_seen:
                last_seen = seen
            b = _bucket(int(entry["turn"]))
            hit[b] += 1
            if not entry["has_row"]:
                crash[b] += 1
            #: 🔴 逐 run 的**真行数**（`stamp_has_row` 从取回的行里数的）：判据② 的第二臂要用它，
            #:    而"有行的 run 数"看不见一个 run 落两行（架构 v1.7.14 §37 ① 那条"直读式对多落盲"）。
            rows_in[b] += int(entry.get("audit_rows", 0))
            if int(entry.get("audit_rows", 0)) > 1:
                multi[b] += 1
        #: 吸边对照：只把**右**边再推 188 秒（= 本轮实测 max lag）会多配进多少条 run。
        if end <= seen < end + extra:
            wide_right += 1
        #: 只把**左**边往前推 188 秒（上一条 run 被吸进来的那一族）会多配进多少条。
        if begin - extra <= seen < begin:
            wide_left += 1
    rows_t2 = 0
    unmapped = 0
    for tk in window_task_ids:
        entry = runs.get(tk)
        if entry is None:
            unmapped += 1
        elif int(entry["turn"]) >= 2:
            rows_t2 += 1
    #: 🔴 "还没写" ≠ "不会有"（W7 第二十六轮 ④，他那面的 ⑭c）：窗口右端最后一条 run 距今还不足**观测 max lag**
    #:    ⇒ 这一格的零行里可能混着**在途 run** ⇒ `crash_turn2plus` 是**假红**方向，不许引。
    #:    阈值来自 `thread_position().max_lag_s`（**自算**，不写死常数）；缺样本 ⇒ `None`（未知 ≠ 可以引）。
    read_age_s = round((now - last_seen).total_seconds(), 3) if (now and last_seen) else None
    too_soon = None if (max_lag_s is None or read_age_s is None) else bool(read_age_s < max_lag_s)
    #: 🔴 **读数前置**（架构 `v1.7.14` 同轮补记连带④）：引用"零行"这类读数必须**两条都过** ——
    #:    ① 作用域非空（窗口里至少配上一条 run）；② 该域最后一条 run 的**年龄 > 已观测最大写入延迟**。
    #:    **缺任一条记 UNVERIFIED、不得记 0**（"还没写"与"永远不会有"在只读面上同形）。
    #:    ⚠️ 年龄**引比值不引秒数**（秒数随读数时刻漂移，见架构 `HANDOVER §7.1` 第 21 条）。
    precondition = {
        "scope_non_empty": matched > 0,
        "aged_beyond_max_lag": too_soon,
        "both_pass": bool(matched) and too_soon is False,
        "read_age_over_max_lag": round(read_age_s / max_lag_s, 3)
                                 if (read_age_s is not None and max_lag_s) else None,
    }

    return {
        "matched_by": "lg.checkpoints 的 first_seen（run 起点），不是审计行时间",
        "window_matched_runs": matched,
        "scope_empty": matched == 0,
        "runs_by_turn_bucket": hit,
        "crash_turn1": crash["turn1"],
        "crash_turn2plus": crash["turn2plus"],
        #: 🔻 **这一列本轮改名**：旧名 `rows_turn2plus` 读起来像"行数"，但它数的是**回执侧 turn≥2 的
        #:    task_id 个数**（一个 run 落两行仍计 1）⇒ 正是交付 §5.40 那一族"键数冒充行数"。
        #:    真·行数在下面 `rows_by_turn2plus_runs`，两列**同时在场**、不许互相代。
        "receipt_tk_turn2plus": rows_t2,
        "rows_by_turn2plus_runs": rows_in["turn2plus"],
        #: 判据② 的**第二臂**（架构 v1.7.14 新增那条）：窗口内 `turn≥2` 且段 1 行数 > 1 的 run 数 = 0。
        "multi_row_turn2plus_runs": multi["turn2plus"],
        #: **第二形**（两侧同限定的差值式，架构登记为允许的第二形）：= 0 是主式的等价形；
        #:    **负** ⇒ 该域有 run 落了多行（多落），这正是直读式看不见的那一支。
        "second_form_turn2plus": hit["turn2plus"] - rows_in["turn2plus"],
        "audit_rows_unmapped_to_thread": unmapped,
        "gap_for_this_cell": gap,
        "gap_literal_DO_NOT_USE": (terminal - rows_t2) if terminal is not None else None,
        "turn2plus_no_row_ge_gap": bool(gap and gap > 0 and crash["turn2plus"] >= gap),
        #: 🔴 下面五个键回答的是同一个问题：**gap 与 crash 合不上的那部分，到底是谁的锅**。
        #:    W7 第二十六轮 ① 猜"pad 作用在审计行侧"，而我方逐格实测差值全落在 `terminal − matched`
        #:    （见 `identity_holds`）⇒ 两边说的不是同一件事：他的分母是 **run 数**，我方的分母是
        #:    **回执自报的 terminal 数**，所以差值结构性地来自"回执终态 ≠ 尺配上的 run"。
        "runs_with_row_in_window": matched - crash["turn1"] - crash["turn2plus"],
        "audit_rows_in_window": audit_rows,
        #: 一格一行的见证：窗口内有行的 run 数 == 窗口内行数 ⇒ 两套归属（时间窗 / task_id）同数。
        "row_run_agreement": (audit_rows == matched - crash["turn1"] - crash["turn2plus"])
                             if audit_rows is not None else None,
        "terminal_minus_matched_runs": (terminal - matched) if terminal is not None else None,
        "gap_minus_crash_total": (gap - crash["turn1"] - crash["turn2plus"]) if gap is not None else None,
        "identity_holds": (gap is not None and terminal is not None
                           and gap - crash["turn1"] - crash["turn2plus"] == terminal - matched),
        #: ⚠️ **假红方向**（W7 ⑭c 那条"还没写 ≠ 不会有"）：读数年龄不足观测 max lag ⇒ 这一格的零行里
        #:    可能混着在途 run ⇒ `crash_turn2plus_citable = false` 时**不许**引该格的崩臂数。
        #:    `null` = 没有延迟样本或本格窗口内没配上 run ⇒ 同样是"未知"，**不等于**可以引。
        "read_age_s": read_age_s,
        "too_soon_to_read": too_soon,
        "reading_precondition": precondition,
        #: 与 `reading_precondition.both_pass` **同一个算式**（判据未动 ⇒ 本轮之前/之后的引用不翻面）。
        "crash_turn2plus_citable": precondition["both_pass"],

        #: 宽 pad 对照（**只并列、不进判据**）：把窗口单边推到本轮实测 max lag 会多配进多少条 run。
        #:    这一列就是"抬 pad"的代价读数：它改的是**分母**，所以属判据变更（要走 A17 / 架构），
        #:    而不是"顺手把常量调大一点"。
        "edge_control": {
            "pad_s": WIDE_PAD_S,
            "extra_runs_if_right_pad_widened": wide_right,
            "extra_runs_if_left_pad_widened": wide_left,
            "matched_at_current_pad": matched,
        },
    }


def summarize(rows: list[dict], skew_s: float | None, ruler: dict | None = None) -> dict:
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
    #: 🔴 窗口口径的**分布**必须自己落盘（第十五轮）：上一轮我方把"45 格全为 `single`"写进了文档与回执，
    #:    而产物里只有逐格的 `window_kind`、没有任何一处给出分布 ⇒ 那句过宽的话**没有一件东西会反对它**。
    #:    现查真值 = `single` 41 + `ambiguous` 4（那 4 格是多场景的 `receipt.json`，本来就不参与判据）。
    window_kind_counts: dict[str, int] = {}
    for r in rows:
        key = str(r.get("window_kind") or "none")
        window_kind_counts[key] = window_kind_counts.get(key, 0) + 1
    violated = [
        {"receipt": r["receipt"], "window_kind": r.get("window_kind"),
         "denominator": r["denominator"], "denominator_basis": r["denominator_basis"],
         "admitted": r["admitted"], "terminal": r["terminal"], "audit_rows": r["audit_rows"], "diff": r["diff"],
         "gap_admitted_minus_terminal": (r.get("two_numbers") or {}).get("gap_admitted_minus_terminal"),
         "gap_terminal_minus_audit_rows": (r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows"),
         "task_id_evidence": r.get("task_id_evidence"),
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
        "window_kind_counts": window_kind_counts,
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
        #: 🔴 **两数分写**（W7 第二十轮）：两侧各自点名，产物里**没有**合并值。
        "two_number_block": {
            "admitted_minus_terminal": {
                "cells_nonzero": [{"receipt": r["receipt"], "admitted": r["admitted"], "terminal": r["terminal"],
                                   "gap": (r.get("two_numbers") or {}).get("gap_admitted_minus_terminal")}
                                  for r in rows
                                  if (r.get("two_numbers") or {}).get("gap_admitted_minus_terminal")],
                "attribution": "断流 / 客户端超时（2xx 无终止帧）⇒ U-129 家族，与审计行数无关",
            },
            "terminal_minus_audit_rows": {
                "cells_nonzero": [{"receipt": r["receipt"], "terminal": r["terminal"],
                                   "audit_rows": r["audit_rows"],
                                   "gap": (r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows")}
                                  for r in rows
                                  if (r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows")
                                  and r["state"] == INVARIANT_VIOLATED],
                "sum": sum((r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows") or 0
                           for r in rows if r["state"] == INVARIANT_VIOLATED),
                "attribution": "进了图的终态 vs 段 1 审计行 ⇒ U-130（> 0 少落，< 0 多落）",
            },
            "merged_admitted_minus_audit_rows_emitted": False,
            "why": "两半各自成立才有意义：`admitted − terminal = 0` 与 `terminal − 审计行 = 4` 并成 "
                   "`admitted − 审计行 = 4` 之后，'没断流'这件事就从读数里消失了。",
        },
        #: 🔑 task_id 级取证的**三态覆盖面**（没带 id 就不许说"逐 id 点名过了"；空 dict 也不算坏字段）。
        "task_id_channel": {
            "n_receipts_scanned": len({r["receipt"] for r in rows}),
            "n_cells": len(rows),
            "cells_with_codes_task_ids": sum(1 for r in rows if r.get("codes_task_ids")),
            "presence_counts": {
                state: sum(1 for r in rows if r.get("codes_task_ids_presence") == state)
                for state in ("absent", "empty", "present")},
            "cells_with_id_evidence": sum(1 for r in rows if r.get("task_id_evidence")),
            "status": "三态分开数：**absent** = 回执根本没有 `codes_task_ids` 这个键（老件）；"
                      "**empty** = 键在但值是空字典 ⇒ **不是字段坏了**，是那批错误码没有 ack 帧可取 id"
                      "（W7 第二十二轮 ④ + 我方实测：`r22_lock_c8n8.json` 的 `codes = {SESSION_CONFLICT: 7}` "
                      "而 `codes_task_ids = {}`）；**present** = 有 id ⇒ 本器件自动走逐行 join（`task_id_evidence`）。"
                      "引用这条不变量时**只许**引 present 那一格；absent/empty 的批次一律不许写成'task_id 级复算过'。",
            "present_cells": [r["receipt"] for r in rows if r.get("codes_task_ids")],
        },
        "proxy_only_cells": [{"receipt": r["receipt"], "admitted": r["admitted"]}
                             for r in rows if r.get("denominator_basis") == BASIS_PROXY],
        #: 🔑 W7 第二十一轮"要不要把客户端探测器并进 U-130 判据面"的**答复依据**（对照，不是判据）：
        #: 逐格把 `stage=none` 计数与我方的差摆在同一行里看，不同阶这件事必须由读数说话、不由措辞说话。
        "client_side_crosscheck": {
            "role": "只作对照列 —— `classify()` 不读 `client_side_evidence`，严格式两边都不引它",
            "cells_with_provenance": sum(1 for r in rows if r.get("client_side_evidence")),
            "n_cells": len(rows),
            "violated_cells_compared": [
                {"receipt": r["receipt"],
                 "gap_terminal_minus_audit_rows": (r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows"),
                 "stage_none_by_outcome": (r.get("client_side_evidence") or {}).get("by_outcome"),
                 "stage_none_total": (r.get("client_side_evidence") or {}).get("total")}
                for r in rows
                if r["state"] == INVARIANT_VIOLATED and r.get("client_side_evidence")],
            "verdict_note": "本块不设「同不同阶」的结论位：引用这条对照的人自己把两个数并排写出来"
                            "（`violated_cells_compared` 每格都给 gap 与 `stage_none_*` 两组数）。",
            "not_computable_offline": "terminal_digest_same_as_turn1（同会话第 2 轮终止帧指纹 == 第 1 轮）"
                                      "需要**逐会话的两轮 SSE 原文**，盘上回执结构性不含 ⇒ 本批 UNVERIFIED，"
                                      "不在本产物里冒充成已测。",
        },
        #: 🔑 **thread 尺那一维的汇总出口**（架构 `07 §4.8` 的 `U-130 v1.7.12` 要 `turn≥2` 限定 ⇒ 本轮起产物有这一维）。
        #:    ⚠️ 三条自我约束写进产物而不是只留在注释里：① 它**不进判据**（`classify()` 不读它）；
        #:    ② 尺不可用时 `available = false` 且各格不带这一维 ⇒ "崩臂面"是**未测**，不是"没有崩臂"；
        #:    ③ 只给**位置**，不给"谁接在谁后面"（prev-outcome 面今天不产 —— W7 第二十四轮 ⑥ 正是栽在那种推法上）。
        "thread_channel": {
            "role": "对照 + 崩臂面标定，不是判据（classify() 不读这一块）",
            "source": THREAD_RULER_SOURCE,
            "available": bool(ruler and ruler.get("by_tk")),
            "db_wide": thread_position(ruler) if (ruler and ruler.get("by_tk")) else None,
            "cells_with_this_dimension": sum(1 for r in rows if r.get("thread_position")),
            "scope_empty_cells": sum(1 for r in rows
                                     if r.get("thread_position") and r["thread_position"]["scope_empty"]),
            "violated_cells_turn_split": [
                {"receipt": r["receipt"], "window_kind": r.get("window_kind"),
                 "gap_terminal_minus_audit_rows": (r.get("two_numbers") or {}).get("gap_terminal_minus_audit_rows"),
                 "crash_turn1": (r.get("thread_position") or {}).get("crash_turn1"),
                 "crash_turn2plus": (r.get("thread_position") or {}).get("crash_turn2plus"),
                 "window_matched_runs": (r.get("thread_position") or {}).get("window_matched_runs"),
                 #: 🔴 本轮起每个违反格**连差值归属一起给**（W7 第二十六轮 ① 的归因就是靠这三列判掉的）。
                 "terminal_minus_matched_runs": (r.get("thread_position") or {}).get("terminal_minus_matched_runs"),
                 "row_run_agreement": (r.get("thread_position") or {}).get("row_run_agreement"),
                 "identity_holds": (r.get("thread_position") or {}).get("identity_holds"),
                 "too_soon_to_read": (r.get("thread_position") or {}).get("too_soon_to_read"),
                 "crash_turn2plus_citable": (r.get("thread_position") or {}).get("crash_turn2plus_citable"),
                 "reading_precondition": (r.get("thread_position") or {}).get("reading_precondition"),
                 "multi_row_turn2plus_runs": (r.get("thread_position") or {}).get("multi_row_turn2plus_runs"),
                 "second_form_turn2plus": (r.get("thread_position") or {}).get("second_form_turn2plus"),
                 "turn2plus_no_row_ge_gap": (r.get("thread_position") or {}).get("turn2plus_no_row_ge_gap")}
                for r in rows
                if r["state"] == INVARIANT_VIOLATED and r.get("thread_position")],
            #: 🔑 **判据② 现在是两条断言**（架构 `v1.7.14` 裁直读式时补的那一臂）：主式数"零行的 run"、
            #:    配对式数"落 > 1 行的 run"。⇒ 这块的存在理由 = **直读式对"多落"是盲的**，而我方旧出口
            #:    只有 `runs_with_row_in_window`（有行的 run 数）与格级 `gap`：同一格里"少一行 + 多一行"
            #:    会让 gap = 0 而**两臂都不为 0** ⇒ 只有 run 级行数看得见。全库那一份见 `db_wide`。
            "overcount_pairing": {
                "primary_form": "窗口内 turn≥2 且零段 1 审计行的 run 数 = 0（直读式，量纲 = run）",
                "pair_form": "窗口内 turn≥2 且段 1 行数 > 1 的 run 数 = 0（架构 v1.7.14 新增的第二条）",
                "second_form": "run(turn≥2) − 审计行(turn≥2) = 0（允许的第二形，**两侧同限定**；负 = 多落）",
                #: 🔑 判据② 配对臂现在**五面并存**、各按各的窗与分母 ⇒ 同向不等于互认（W7 廿八轮 ③ 的口径我方接受）：
                #:    W4 = 夹具图结构锁（`d73a201`，契约 7 → 14 条）｜`07 §4.8 U-130 v1.7.14` = 契约文本｜
                #:    我方 = 落库面读数（本块）｜W7 = **同一张库上的独立语句 ⑮**（分母 = run、臂2 = `n_audit_rows > 1`、
                #:    空作用域给 NULL）｜第十七轮新增 = **checkpoint 写面**（架构 §38 ④ 的零成本对照动作，
                #:    量纲 = thread 级上界）⇒ 引用任何一方都不构成对另四方的确认；我方锚点已把 ⑮ 纳进去（他删/改名 ⇒ 我方红）。
                "external_counterpart": "W7 `r23_thread_from_checkpoints.sql` 段 ⑮（A17 两臂，分母 = run）"
                                        " ⇒ 同向、不互认：两数各按各的前缀与窗口，相同只是巧合",
                "pairing_faces": ("W4 夹具图结构锁 = tests/contract/test_audit_terminal_pairing_contract.py"
                                  "（`d73a201`，7 → 14 条）",
                                  "契约文本 = 07 §4.8 U-130 v1.7.14（架构 `44b6783`）",
                                  "落库面读数 = 本产物 thread_channel.overcount_pairing",
                                  "W7 落库面独立语句 = r23_thread_from_checkpoints.sql 段 ⑮",
                                  "checkpoint 写面（台账第 8 面）= 本产物 db_wide.checkpoint_writes"
                                  " ⇒ thread 级上界看 `max_terminal_writes_per_thread`、run 级归属看"
                                  " `run_attribution`（覆盖面按通道集分列，路由集不全可归）"),
                "cells_measured": sum(1 for r in rows if r.get("thread_position")),
                "cells_with_multi_row_turn2plus": sum(1 for r in rows
                                                      if (r.get("thread_position") or {}).get("multi_row_turn2plus_runs")),
                "multi_row_turn2plus_total": sum((r.get("thread_position") or {}).get("multi_row_turn2plus_runs", 0)
                                                 for r in rows if r.get("thread_position")),
                "cells_with_negative_second_form": sum(1 for r in rows
                                                       if ((r.get("thread_position") or {}).get("second_form_turn2plus")
                                                           or 0) < 0),
                "db_wide_agreement": (thread_position(ruler).get("direct_vs_second_form_agree")
                                      if (ruler and ruler.get("by_tk")) else None),
                "status": "两式**同值当且仅当每个 run 至多 1 行** ⇒ 读这一点只看 "
                          "`db_wide.direct_vs_second_form_agree`，不看本句：这一臂今天多半不报任何东西，"
                          "它防的是**将来出现双写（U-129 那一族）时恒绿**。",

            },

            #: 🔑 **差值归属**（本轮的核心读数）：`gap − (crash_turn1 + crash_turn2plus)` 恒等于
            #:    `terminal − window_matched_runs` ⟺ "窗口内行数 == 窗口内有行的 run 数"（一格一行）。
            #:    ⇒ 若 10/10 成立，"gap 与 crash 对不上"就**不是**审计侧 pad 的锅，而是"回执自报的终态数
            #:    比尺在窗口里配上的 run 数多"。两种成因（那些终态在 checkpoints 里根本没有行 /
            #:    行的 `first_seen` 落在窗外）我方**分不开** —— 分不开需要回执自带 task_id 清单
            #:    （`task_id_channel` 的 present 面今天只有 1 格）⇒ 只登记，不猜。
            "gap_attribution": {
                "identity": "gap_for_this_cell − crash_turn1 − crash_turn2plus == terminal − window_matched_runs",
                "checked_cells": sum(1 for r in rows if (r.get("thread_position") or {}).get("identity_holds")
                                      is not None),
                "identity_holds_all": all(bool((r.get("thread_position") or {}).get("identity_holds"))
                                          for r in rows if r.get("thread_position")),
                "cells_where_rows_equal_runs_with_row": sum(
                    1 for r in rows if (r.get("thread_position") or {}).get("row_run_agreement") is True),
                "cells_where_rows_differ_from_runs_with_row": [
                    {"receipt": r["receipt"],
                     "audit_rows": r.get("audit_rows"),
                     "runs_with_row_in_window": (r.get("thread_position") or {}).get("runs_with_row_in_window"),
                     "terminal_minus_matched_runs": (r.get("thread_position") or {}).get("terminal_minus_matched_runs")}
                    for r in rows
                    if (r.get("thread_position") or {}).get("row_run_agreement") is False],
                "cells_with_terminal_minus_matched_nonzero": sum(
                    1 for r in rows
                    if (r.get("thread_position") or {}).get("terminal_minus_matched_runs")),
            },
            #: 🔴 **假红方向的守卫**（W7 第二十六轮 ④ 交给我方做的对照）：只读面上"审计行还没写"与
            #:    "永远不会有"长得一模一样 ⇒ 读数年龄 < 观测 max lag 的格子，其 `crash_turn2plus` **不可引**。
            #:    阈值 = `db_wide.max_lag_s`（本批延迟分布自己算出来的，不是常数）；`now` 取 **PG 的钟**。
            "read_horizon": {
                "rule": "too_soon_to_read = (PG now − 本格窗口内最晚一条 run 的 first_seen) < 观测 max lag"
                        " ⇒ true 时该格 crash_turn2plus 不可引；null = 无延迟样本或窗口内没配上 run（同样不可引）",
                #: 🔴 架构 `v1.7.14` 同轮补记连带④：这两条是**读数前置**（不是新判据）——
                #:    引用零行读数要**同时**给「作用域非空」与「年龄 > 已观测最大写行延迟」，
                #:    **缺任一条记 UNVERIFIED、不得记 0**。逐格的合并旗标 = `reading_precondition.both_pass`。
                "preconditions": ("① 作用域非空（`window_matched_runs > 0`）"
                                  "② 该域最后一条 run 的年龄 > 已观测 max lag（`too_soon_to_read is false`；"
                                  "年龄**引比值** `read_age_over_max_lag`，秒数随读数时刻漂移）"),
                "max_lag_s": (thread_position(ruler) if ruler and ruler.get("by_tk") else {}).get("max_lag_s"),
                "cells_too_soon": sum(1 for r in rows
                                      if (r.get("thread_position") or {}).get("too_soon_to_read") is True),
                "cells_horizon_unknown": sum(1 for r in rows
                                             if (r.get("thread_position") or {}).get("too_soon_to_read") is None
                                             and r.get("thread_position")),
                "cells_scope_empty": sum(1 for r in rows
                                         if (r.get("thread_position") or {}).get("scope_empty")),
                "cells_precondition_fail": sum(1 for r in rows if r.get("thread_position")
                                               and not ((r.get("thread_position") or {})
                                                        .get("reading_precondition") or {}).get("both_pass")),
                "cells_citable": sum(1 for r in rows
                                     if (r.get("thread_position") or {}).get("crash_turn2plus_citable")),
            },

            #: **抬 pad 的代价**（只并列，不进判据）：把窗口单边推到观测 max lag 会多配进多少条 run。
            #: ⇒ "把 pad 改成 ≥188s"不是免费的：它改的是**分母**，属判据变更（走 A17 / 架构），
            #:   而 W7 第 3 条给的另一条路（审计侧不带时间谓词）我方实测**已经同数**（见 `gap_attribution`）。
            "edge_control": {
                "pad_s": WIDE_PAD_S,
                "cells_measured": sum(1 for r in rows if r.get("thread_position")),
                "extra_runs_right_total": sum((r.get("thread_position") or {}).get("edge_control", {})
                                              .get("extra_runs_if_right_pad_widened", 0) for r in rows),
                "extra_runs_left_total": sum((r.get("thread_position") or {}).get("edge_control", {})
                                             .get("extra_runs_if_left_pad_widened", 0) for r in rows),
            },
            "id_level_turns": {r["receipt"]: (r.get("task_id_evidence") or {}).get("turn_of_given_id")
                               for r in rows if r.get("task_id_evidence")},
            "naming_note": "架构 `07 §4.8 U-130 v1.7.14` 已把判据② 裁成**两条断言** ⇒ 本产物的三个'数 run'的列"
                           "各管一条，**不许互相代**：① **`crash_turn2plus`** = 主式（窗口内 `turn≥2` 且**零**段 1 行的"
                           " run 数，量纲 = run）；② **`multi_row_turn2plus_runs`** = 配对式（窗口内 `turn≥2` 且"
                           "行数 **> 1** 的 run 数，直读式对这一支是盲的）；③ **`second_form_turn2plus`** = 允许的"
                           "**第二形** `run(turn≥2) − 审计行(turn≥2)`（**两侧同限定**才与主式等价；**为负 = 多落**）。"
                           "🔻 **本轮一处改名**：旧列 `rows_turn2plus` 读起来像'行数'，实际数的是**回执侧 `turn≥2` 的"
                           " task_id 个数**（一个 run 两行仍计 1）⇒ 现名 **`receipt_tk_turn2plus`**，真行数 = "
                           "`rows_by_turn2plus_runs`（逐行取回后在 Python 里数，交付 §5.40）。"
                           "**`gap_literal_DO_NOT_USE`** 仍保留 = 架构 `v1.7.12` 那句**字面式**（被减数 `terminal` "
                           "未限定 ⇒ 被 turn1 放大，三域实测 20×/2×/102×）的算法，命名即禁用标记、**故意公开**"
                           "是为了让'两种式子差多少'可被复算（做法已被架构抄进契约写法）。"
                           "turn1 的零行（`crash_turn1` / 全库 `runs_without_audit_row.turn1`）结构性不进判据。",

            "why_not_a_verdict": "`turn2plus_no_row_ge_gap` 只是「本格 gap ≤ 窗口内 turn≥2 零行数」这条算术；"
                                 "它不等于「这些 gap 就是那几条崩臂」。要把因果坐实需要**回执自己带 task_id**"
                                 "（即 `task_id_channel` 的 present 面），而窗口配的是 run 起点、边缘会漂"
                                 "（必须配 `db_wide.audit_row_minus_first_seen_s` 一起读）。",
        },
        "window_rule": "时间列见 pg_guard.time_column（本轮实测 = `timestamp`，盘上**没有** `created_at`）："
        f"<时间列> >= begin AND <时间列> < finished_at + {WINDOW_PAD.total_seconds():.0f}s"
                       "（右端含该秒；回执时间戳为秒级）",
        #: 🔴 引用纪律（架构 `07 §4.8 U-130 v1.7.13` 的"gap 双口径"）：**两个数都对、不得互换** ——
        #:    子窗（`window_kind = scenario`）与整窗（`receipt` / `single`）读出来的 run 数与 gap 可以不同
        #:    （架构现测：A 档子窗 99/95 = 4，整窗 104/99 = 5，第 5 条落在子窗之外）。
        "window_citation_rule": "引用任何 gap 必须**三件一起写**：① 用的是**哪一个式子**（直读式 = 数满足条件的 "
                                "run，主式；第二形 = `run(turn≥2) − 审计行(turn≥2)`，两侧同限定；字面式 = "
                                "`terminal − 审计行(turn≥2)`，**禁用**，只以 `gap_literal_DO_NOT_USE` 出现）；"
                                "② **分母口径**（我方的 gap 分母是**回执自报的 terminal 请求数**，W7 那把尺的分母是"
                                "**run 数** ⇒ 两家的同名'gap'**不可互认、不可相加**）；③ 该格的 `window_kind`："
                                "`scenario` 与 `single` = **单场景（子窗）口径**（`single` = 这份回执只含一个场景，"
                                "回执窗就等于该场景窗），`receipt` = 整批窗口，`ambiguous` 不参与判据。架构 "
                                "`v1.7.13` 现测：同一批 A 档**子窗 99 run / 95 行 = gap 4** 与 **整窗 104 run / "
                                "99 行 = gap 5** 两个数都对、**不得互换**、也不许取平均 ⇒ 本器件逐格只按单场景窗口"
                                "数，所以我方所有 gap 读数都属于『子窗』口径（分布本身是字段 = "
                                "`summary.window_kind_counts`）。🔴 **读数前置两条**（架构 `v1.7.14` 同轮补记连带④）："
                                "引用零行读数要同时满足「作用域非空」与「该域最后一条 run 的年龄 > 已观测最大写行"
                                "延迟」，**缺任一条记 UNVERIFIED、不得记 0**（逐格 = `reading_precondition`）。"
                                "⚠️ 边缘偏差的**归属已实测改过两次**，此处写当前结论：thread 尺按 run 起点 "
                                "`first_seen` 配窗，而审计行写入时刻中位比它晚约十秒量级（见 `db_wide."
                                "audit_row_minus_first_seen_s`，含分桶 `gt_s`）。但第十五轮逐格核对后，"
                                "`gap` 与 `crash` 对不上的那部分**不在审计侧 pad**：带尺的格子里「窗口内行数 == "
                                "窗口内有行的 run 数」全部成立 ⇒ 差值恒等于 `terminal − window_matched_runs`"
                                "（见 `gap_attribution`）。⇒ 本器件**没有**为此放宽 pad（pad 仍是 1 秒，架构 "
                                "`v1.7.14` 亦判'两条出路都不采'）：抬到观测 max lag 会把邻近 run 吸进窗口 = 改分母，"
                                "代价见 `edge_control`，且属判据变更（走 A17 / 架构）。",

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


async def measure(rows: list[dict], table: str = "audit_log") -> tuple[list[dict], float | None, dict, dict]:
    """逐格数 `app.audit_log` 的行数（参数化查询 + 只读闸门）。

    返回 `(带读数的行, 时钟偏移秒, 闸门自证, thread 尺)` —— 尺单独返回给 `summarize()` 用，
    因为它是**对象形态**（`by_tk`），不进产物（产物里进的是 `thread_position()` 的汇总）。
    """
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
        #: 🔑 **thread 尺**（架构 `U-130 v1.7.12` 的 `turn≥2` 限定要用的那一把）：借 W7 的语义、自己数。
        #: ⚠️ 这把尺**不可用时不假装可用**：读不到 `lg.checkpoints` ⇒ 落 `{"available": false, "error": …}`，
        #:    各格 `thread_position` 也随之缺席 ⇒ 产物里"崩臂面"这一栏变成"未测"，而不是悄悄等于"没有崩臂"。
        try:
            run_rows = await (await conn.execute(CHECKPOINT_RUNS_SQL)).fetchall()
            #: thread 数的**谓词口径**（W7 ⑫b 同判据）：取不到就当没测，**不猜**、也不静默缺项。
            try:
                scope_row = await (await conn.execute(THREAD_SCOPE_SQL)).fetchone()
                ruler_scope = {"available": True,
                               "threads_all": int(scope_row[0]), "threads_with_tk": int(scope_row[1]),
                               "threads_without_tk": int(scope_row[2]), "threads_multi_tk": int(scope_row[3])}
            except Exception as scope_exc:
                ruler_scope = {"available": False, "error": safe_error_text(scope_exc)}
            #: 🔑 **逐行取回、行数在 Python 里数**（交付 §5.40 的规矩：不在库里 `count(*)` 后再当"行数"引）。
            #:    旧版这里写的是 `select task_id, min(ts) … group by task_id` ⇒ 只留得下"有没有行"，
            #:    一个 run 落两行会被压成 1 ⇒ 判据② 的第二臂（多落）在**取证阶段**就丢了。
            audit_row_pairs = await (await conn.execute(sql.SQL(
                "select task_id, {} from app.{} where task_id is not null").format(
                sql.Identifier(time_col), sql.Identifier(table)))).fetchall()
            audit_ts: dict[str, datetime] = {}
            rows_by_tk: dict[str, int] = {}
            for tk, ts in audit_row_pairs:
                if not tk:
                    continue
                key = str(tk)
                rows_by_tk[key] = rows_by_tk.get(key, 0) + 1
                if isinstance(ts, datetime) and (key not in audit_ts or ts < audit_ts[key]):
                    audit_ts[key] = ts
            ruler = stamp_has_row(thread_turns(list(run_rows)), audit_ts, rows_by_tk)
            #: 谓词口径跟着尺走（`thread_position()` 会把它连同**闭合判据**一起落进产物）。
            ruler["scope"] = ruler_scope
            #: 尺自检（W7 的 ① 段同判据）：一个 tk 落多个 thread ⇒ 整段作废，点名而不静默取第一个。
            ruler["self_check"] = {
                "tk_threads_unique": not ruler["ambiguous_tk_to_threads"],
                "ambiguous_examples": ruler["ambiguous_tk_to_threads"][:5],
            }
            #: 🔴 台账第 8 面对撞（架构 §38 ④ 的零成本动作）：取不到就**显式记 unavailable**，
            #:    不让它把整把尺带崩 —— 这张表归 W7/W4 的迁移面，我有读权限是现状、不是保证。
            try:
                shape_row = await (await conn.execute(CHECKPOINT_WRITES_SHAPE_SQL)).fetchone()
                keys = ("rows_all", "threads_all", "ck_threads_all", "ck_only_threads",
                        "writes_only_threads", "terminal_rows", "terminal_threads",
                        "max_terminal_writes_per_thread")
                tset = {str(r[0]) for r in await (await conn.execute(TERMINAL_WRITE_THREADS_SQL)).fetchall()}
                join_keys = ("terminal_rows_via_join", "terminal_matched_rows", "terminal_unmatched_rows",
                             "route_rows", "route_channels", "route_unmatched_rows",
                             "route_unmatched_threads", "tk_runs_touched")
                join = dict(zip(join_keys, await (await conn.execute(WRITES_ATTRIBUTION_SQL)).fetchone(),
                                strict=True))
                t_runs = {str(r[0]) for r in await (await conn.execute(TERMINAL_RUN_TKS_SQL)).fetchall()}
                s_runs = {str(r[0]) for r in await (await conn.execute(AUDIT_SUPP_RUN_TKS_SQL)).fetchall()}
                rt_runs = {str(r[0]) for r in await (await conn.execute(ROUTE_RUN_TKS_SQL)).fetchall()}
                un_keys = ("route_rows", "route_unmatched_rows", "route_unmatched_threads",
                           "unmatched_before_first_tk", "unmatched_at_or_after_first_tk",
                           "unmatched_on_threads_without_tk", "threads_with_real_loss_rows")
                un_shape = dict(zip(un_keys, await (await conn.execute(ROUTE_UNMATCHED_SHAPE_SQL)).fetchone(),
                                    strict=True))
                attrib = writes_attribution(join, t_runs, s_runs, rt_runs, un_shape, ruler, rows_by_tk)
                ruler["writes"] = writes_crosscheck(ruler, dict(zip(keys, shape_row, strict=True)), tset,
                                                    attrib=attrib)
            except Exception as writes_exc:
                ruler["writes"] = {"available": False, "error": safe_error_text(writes_exc)}
            #: 全库那一维**算一次**存下来（`max_lag_s` 要给逐格的 `too_soon_to_read` 当阈值，
            #: 而逐格重算会把 1,378 条 run 的偏移分布扫 45 遍）。
            db_wide = thread_position(ruler)
            stamp["thread_ruler"] = {"available": True, **db_wide}
        except Exception as exc:
            # 尺不可用要让产物显式承担（available = false），但不能让整个探针不出产物。
            ruler = {"by_tk": {}, "ambiguous_tk_to_threads": [], "usable": False}
            db_wide = thread_position(ruler)
            stamp["thread_ruler"] = {"available": False, "error": safe_error_text(exc)}
        for row in rows:
            if row["state"] != NO_DB or not row["begin"]:
                continue
            q = sql.SQL("select task_id, {} from app.{} where {} >= %s and {} < %s").format(
                sql.Identifier("outcome"), sql.Identifier(table), sql.Identifier(time_col), sql.Identifier(time_col)
            )
            #: 🔴 本轮起**逐行取回**、`audit_rows` 与 `by_outcome` 都在 Python 里数（原来是 `group by outcome` 的
            #:    服务端聚合）：① 与交付 §5.40 同一条纪律（能在本地数就不在库里聚合）；
            #:    ② thread 尺**必须配到 task_id 级**才拿得到 turn ⇒ 聚合面根本配不出这一维。
            #:    两个数（`audit_rows` / `by_outcome`）与上一把逐格相同 ⇒ 这是出口形状变更、不是判据变更。
            window_rows = await (await conn.execute(q, (row["begin"], row["end"] + WINDOW_PAD))).fetchall()
            by_outcome: dict[str, int] = {}
            for _tid, outcome in window_rows:
                key = str(outcome)
                by_outcome[key] = by_outcome.get(key, 0) + 1
            row["audit_rows"] = len(window_rows)
            row["by_outcome"] = by_outcome
            row["rows_that_window_day"] = days_map.get(str(row["begin"].astimezone(UTC).date()))
            #: 🔑 task_id 级取证（W7 第二十轮新增字段，**第二十三轮起盘上首次非空**）：有键就逐 id 点名，不靠时间窗猜。
            if row.get("codes_task_ids"):
                ids = sorted({t for group in row["codes_task_ids"].values() for t in group})
                #: ⚠️ **行数在 Python 里数**，不用 `count(*) … join lateral jsonb_object_keys(latency_ms)`：
                #: 那样每行会**按 latency 键数被乘开**（临时件实测：两个 GATE id 各数成 `rows = 6`、
                #: 两个 INTERNAL id 各 `rows = 2`，而 6 / 2 恰好等于它们各自的键数、真行数**都是 1**
                #: ⇒ 差点把"一格一行"报成"一请求落六行"，那是 U-129 双终态的形状；交付 §5.40）。
                detail = await (await conn.execute(
                    sql.SQL("select task_id, outcome, latency_ms from app.{} where task_id = any(%s)").format(
                        sql.Identifier(table)),
                    (ids,))).fetchall()
                by_id: dict[str, dict] = {}
                for tid, outcome, latency in detail:
                    entry = by_id.setdefault(str(tid), {"seg1_rows": 0, "outcomes": [], "latency_key_counts": []})
                    entry["seg1_rows"] += 1
                    label = str(outcome) if outcome is not None else "<null>"
                    if label not in entry["outcomes"]:
                        entry["outcomes"].append(label)
                    if isinstance(latency, dict):
                        entry["latency_key_counts"].append(len(latency))
                row["task_id_evidence"] = {
                    "method": f"逐行取 app.{table} 的 (task_id, outcome, latency_ms)（参数化、只读闸门内）"
                              "⇒ 行数在 Python 里数（见源码注释：lateral 展开会把行按键数乘开）",
                    "n_ids": len(ids),
                    "n_with_row": sum(1 for t in ids if by_id.get(t, {}).get("seg1_rows")),
                    #: 🔑 **每个 given id 在 thread 尺上的位置**（含没落行的那些 ⇒ 这正是架构要的 `turn≥2` 面）。
                    #:    `null` = 这条 tk 在 `lg.checkpoints` 里映射不到 thread ⇒ 位置未知，不猜。
                    "turn_of_given_id": {t: (ruler["by_tk"].get(t) or {}).get("turn") for t in ids},
                    "by_id": {t: {"seg1_rows": e["seg1_rows"], "outcomes": e["outcomes"],
                                  "turn": (ruler["by_tk"].get(t) or {}).get("turn"),
                                  "thread_id": (ruler["by_tk"].get(t) or {}).get("thread_id"),
                                  "latency_keys": {"min": min(e["latency_key_counts"]),
                                                   "max": max(e["latency_key_counts"])}
                                  if e["latency_key_counts"] else None}
                              for t, e in sorted(by_id.items())},
                    "by_code": {
                        code: {"given": len(group),
                               "with_row": sum(1 for t in group if by_id.get(t, {}).get("seg1_rows")),
                               "missing_task_ids": [t for t in group if not by_id.get(t, {}).get("seg1_rows")]}
                        for code, group in row["codes_task_ids"].items()
                    },
                }
            row["two_numbers"] = two_numbers_of(row["admitted"], row["terminal"], row["audit_rows"])
            if span_void(row["end"], WINDOW_PAD, table_min):
                row["state"], row["diff"] = NOT_APPLICABLE, None
                row["inapplicability_reason"] = "window_before_table_span"
                row["strict_equation_evaluated"] = False
                #: 窗口作废 ⇒ 严格式那一半不许留数（留着会被读者当成差值引用），断流那一半与被数的表无关，保留。
                row["two_numbers"]["gap_terminal_minus_audit_rows"] = None
                row["two_numbers"]["audit_rows"] = None
                continue
            row["state"], row["diff"] = classify(row["denominator"], row["audit_rows"])
            row["strict_equation_evaluated"] = row["diff"] is not None
            #: 🔑 **thread 尺那一维**（架构 `U-130 v1.7.12` 要 `turn≥2` 限定的那一维）：只给位置与并排算术，
            #:    **不参与 `classify()`** ⇒ 判据形状与上一把可比，本轮改的是出口而不是尺。
            #:    ⚠️ 只给**窗口没作废**的格子（窗口作废时严格式那一半已置空，配一个尺读数会拼出差值）。
            if ruler["by_tk"]:
                row["thread_position"] = cell_thread_position(
                    ruler,
                    [str(tid) if tid is not None else "<null>" for tid, _o in window_rows],
                    row["begin"], row["end"] + WINDOW_PAD,
                    row["terminal"], (row["two_numbers"] or {}).get("gap_terminal_minus_audit_rows"),
                    audit_rows=row["audit_rows"],
                    #: 阈值与"现在"都取自 **PG 那一侧**：延迟样本是 PG 写的行时间减 checkpoint 的 ts，
                    #: 而 `now()` 也是 PG 的钟 ⇒ 拿本机墙钟比会再叠一层时钟偏移（本轮实测 skew 见 `clock_skew_s`）。
                    max_lag_s=(thread_position(ruler) or {}).get("max_lag_s"), now=pg_now)
        return rows, skew, stamp, ruler
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
            terminal = terminal_of(sc)
            task_ids = codes_task_ids_of(sc)
            prov = client_side_evidence_of(sc)
            state = NO_DB
            reason = None
            if denominator is None:
                state, reason = NOT_APPLICABLE, "denominator_unavailable"
            elif denominator == 0:
                state, reason = NOT_APPLICABLE, "zero_denominator_vacuous"
            elif basis == BASIS_PROXY:
                #: 只有 `admitted` 可用 ⇒ 拿它去比审计行数**就是那个被禁的合并值** ⇒ 不比、不判。
                state, reason = NOT_APPLICABLE, "denominator_proxy_only"
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
                "two_numbers": two_numbers_of(adm, terminal, None),
                "codes_task_ids": task_ids,
                #: 三态覆盖面（absent / empty / present）—— 两态会把"没带字段"与"无可给的 id"混成一个 0
                "codes_task_ids_presence": codes_task_ids_presence(sc),
                #: 🔴 诊断列，**不参与判据**（`classify()` 不读它）：W7 的 `stage=none` 那面在盘上可离线复算的部分
                "client_side_evidence": prov,
                "task_id_evidence": None,
                "stream_break_gap": (adm - terminal) if (adm is not None and terminal is not None) else None,
                "mismatch": mismatch,
                "inapplicability_reason": reason,
                "audit_rows": None,
                "rows_that_window_day": None,
                "diff": None,
                "by_outcome": None,
                "state": state,
                "strict_equation_evaluated": state == NO_DB,
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
        rows, skew, stamp, ruler = asyncio.run(measure(rows, table=args.table))
    except (LookupError, RuntimeError, psycopg.Error) as exc:  # RuntimeError 含 PgReadOnlyGuardError
        #: 🔴 驱动层的异常消息**会把整条连接串（含口令）打进来**（2026-09-29 实测：
        #: `invalid connection option "<scheme>://<user>:<口令>@<host>:<port>/<db>?options…"`）
        #: ⇒ "我不打印 DSN"管不住别人的文案，出口统一 `pg_guard.safe_error_text()`（W7 第二十一轮规程）。
        print(f"🔴 探测未跑成：{safe_error_text(exc)}")
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
        "summary": summarize(rows, skew, ruler),
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
    #: 🔴 归属块**崩过一次的症状**是"exit 0 + 产物里那一格整块消失"（本轮实测：一句 SQL 列名写错 ⇒
    #:    `checkpoint_writes` 退化成 `{available: false}`，上一轮的归属读数跟着没了，而 stdout 一句没报）。
    #:    ⇒ 判据没红不等于器件在跑 ⇒ 不可用必须喊出来。
    cw = ((s.get("thread_channel") or {}).get("db_wide") or {}).get("checkpoint_writes") or {}
    if cw.get("available") is False:
        print(f"🔴 台账第 8 面不可用 ⇒ 本轮**没有**写面归属读数（不是「归属为 0」）：{cw.get('error')}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
