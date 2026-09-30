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
#:    ／⑭b "先过滤再算 turn"的假绿守卫。
#:    ⚠️ 为什么本窗口要自己接这把尺：架构在 `07 §4.8` 的 `U-130` 上按它加了 **`turn≥2` 限定**（v1.7.12，
#:    基准 `399b786`）—— "0 审计行"不是崩臂独有指纹，不加限定的批级计数会把崩臂**高估约 40 倍**
#:    ⇒ 我方那条"少落 = 缺陷"的读数必须带 turn 维度。
#:    ⚠️ 行号只在**读数那一秒**有效（本轮实测：⑨ `:193`、⑩ `:212`、⑭ `:297`、⑭b `:332`）⇒ 引用请以标签为准。
THREAD_RULER_SOURCE = "deploy/loadtest/r23_thread_from_checkpoints.sql 段 ①⑨⑩⑭⑭b（按标签锚定，行号会漂）"
THREAD_RULER_SECTIONS = ("①", "⑨", "⑩", "⑭", "⑭b")

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
        return {"n": 0, "min": None, "median": None, "max": None}
    vs = sorted(values)
    return {"n": len(vs), "min": vs[0], "median": vs[len(vs) // 2], "max": vs[-1]}


def stamp_has_row(ruler: dict, audit_ts: dict[str, datetime]) -> dict:
    """把"这条 run 在 `app.audit_log` 里有没有行 / 行落在什么时刻"标到尺上（一次算完，全库与单格共用）。"""
    for tk, entry in ruler["by_tk"].items():
        ts = audit_ts.get(tk)
        entry["has_row"] = ts is not None
        entry["audit_ts"] = ts
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
    offsets: list[float] = []
    for entry in runs.values():
        b = _bucket(int(entry["turn"]))
        total[b] += 1
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
        "audit_row_minus_first_seen_s": _spread(offsets),
    }


def cell_thread_position(ruler: dict, window_task_ids: list[str], begin: datetime, end: datetime,
                         terminal: int | None, gap: int | None) -> dict:
    """单格窗口内的 thread 尺读数：先在全历史上赋好号（`thread_turns`），**再由这里按窗口筛**。

    ⚠️ 命名与判据形状照 W7 第二十五轮 ⑭ 的四条措辞纪律（他实测三域：字面式 81 / 16 / 1,330，
    正确式 4 / 8 / 13 ⇒ 两式只在"runs 全是 turn≥2"时才相等）：
    ① **判据分子只许写 `crash_turn2plus`**（窗口内 `turn≥2` 且零审计行的 run 数）；
    ② 架构 `v1.7.12` 那句字面式 `terminal − 审计行(turn≥2)` 的被减数**没有限定** ⇒ 我方照他的做法
       把它算出来并命名成 **`gap_literal_DO_NOT_USE`**，让"错的那列"在产物里**可见且不可引**，
       而不是删掉后没人知道有这个坑；
    ③ `scope_empty` = 窗口内一条 run 都没配上 ⇒ 这一维**不可用**（多半是配窗/边缘偏移，不是"没有崩臂"）；
    ④ turn1 的零行（`crash_turn1`）**结构性不进判据**，只并列给数。
    窗口配的是 `first_seen`（run 起点），与审计行写行时刻的差值分布见全库块
    `audit_row_minus_first_seen_s` ⇒ 边缘会漂那么多。
    """
    runs = ruler["by_tk"]
    hit = {"turn1": 0, "turn2plus": 0}
    crash = {"turn1": 0, "turn2plus": 0}
    matched = 0
    for entry in runs.values():
        seen = entry["first_seen"]
        if not (isinstance(seen, datetime) and begin <= seen < end):
            continue
        matched += 1
        b = _bucket(int(entry["turn"]))
        hit[b] += 1
        if not entry["has_row"]:
            crash[b] += 1
    rows_t2 = 0
    unmapped = 0
    for tk in window_task_ids:
        entry = runs.get(tk)
        if entry is None:
            unmapped += 1
        elif int(entry["turn"]) >= 2:
            rows_t2 += 1
    return {
        "matched_by": "lg.checkpoints 的 first_seen（run 起点），不是审计行时间",
        "window_matched_runs": matched,
        "scope_empty": matched == 0,
        "runs_by_turn_bucket": hit,
        "crash_turn1": crash["turn1"],
        "crash_turn2plus": crash["turn2plus"],
        "rows_turn2plus": rows_t2,
        "audit_rows_unmapped_to_thread": unmapped,
        "gap_for_this_cell": gap,
        "gap_literal_DO_NOT_USE": (terminal - rows_t2) if terminal is not None else None,
        "turn2plus_no_row_ge_gap": bool(gap and gap > 0 and crash["turn2plus"] >= gap),
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
                 "turn2plus_no_row_ge_gap": (r.get("thread_position") or {}).get("turn2plus_no_row_ge_gap")}
                for r in rows
                if r["state"] == INVARIANT_VIOLATED and r.get("thread_position")],
            "id_level_turns": {r["receipt"]: (r.get("task_id_evidence") or {}).get("turn_of_given_id")
                               for r in rows if r.get("task_id_evidence")},
            "naming_note": "判据分子只许写 **`crash_turn2plus`**（窗口内 `turn≥2` 且零审计行的 run 数）。"
                           "产物里同时留着 **`gap_literal_DO_NOT_USE`**（架构 `v1.7.12` 那句字面式 `terminal − "
                           "审计行(turn≥2)` 的算法，被减数没有限定 ⇒ 会被 turn1 的行放大）：这一列**故意公开**"
                           "是为了让'两种式子差多少'可被复算，命名本身即禁用标记（做法照 W7 第二十五轮 ⑭）。"
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
        "window_citation_rule": "引用任何 gap 必须连着该格的 `window_kind` 一起写：`scenario` 与 `single` = "
                                "**单场景（子窗）口径**（`single` = 这份回执只含一个场景，回执窗就等于该场景窗），"
                                "`receipt` = 整批窗口，`ambiguous` 不参与判据。架构 `v1.7.13` 现测：同一批 A 档"
                                "**子窗 99 run / 95 行 = gap 4** 与 **整窗 104 run / 99 行 = gap 5** 两个数都对、"
                                "**不得互换**，也不许取平均 ⇒ 本器件逐格只按单场景窗口数，"
                                "所以我方所有 gap 读数都属于『子窗』口径。"
                                "⚠️ 已知边缘偏差：thread 尺是按 run 起点 `first_seen` 配窗，而审计行的写入时刻"
                                "中位比它晚约十秒量级（见 `thread_channel.db_wide.audit_row_minus_first_seen_s`）"
                                "⇒ 窗口左边缘会多吸进上一条 run，本器件**没有**为此放宽 pad（pad 仍是 1 秒）。",
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
            audit_ts_rows = await (await conn.execute(sql.SQL(
                "select task_id, min({}) from app.{} where task_id is not null group by task_id").format(
                sql.Identifier(time_col), sql.Identifier(table)))).fetchall()
            audit_ts = {str(t): ts for t, ts in audit_ts_rows if t}
            ruler = stamp_has_row(thread_turns(list(run_rows)), audit_ts)
            #: 尺自检（W7 的 ① 段同判据）：一个 tk 落多个 thread ⇒ 整段作废，点名而不静默取第一个。
            ruler["self_check"] = {
                "tk_threads_unique": not ruler["ambiguous_tk_to_threads"],
                "ambiguous_examples": ruler["ambiguous_tk_to_threads"][:5],
            }
            stamp["thread_ruler"] = {"available": True, **thread_position(ruler)}
        except Exception as exc:
            # 尺不可用要让产物显式承担（available = false），但不能让整个探针不出产物。
            ruler = {"by_tk": {}, "ambiguous_tk_to_threads": [], "usable": False}
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
                    row["terminal"], (row["two_numbers"] or {}).get("gap_terminal_minus_audit_rows"))
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
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
