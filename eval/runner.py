"""W6 批量执行器 —— 冻结集 → 在线全链路 run → §C.4.1 等价判定 → §C.7 归因 → 结果集 JSON。

归属窗口：W6（08 §3.8 产出①的执行侧；判定/归因分别复用 `equivalence.py` / `attribution.py`）。

--------------------------------------------------------------------------
一、三条跑批纪律（§C.6.1 原文要求，本文件是**唯一**执行入口）
--------------------------------------------------------------------------
| 纪律 | 落地 |
|---|---|
| **串行**，不并发 | 默认单线程逐条；**整批共用一个 event loop**（`run_batch_sync` 是唯一 `asyncio.run` 落点，`Harness` 在循环内构造、`await aclose()` 收口）；`Harness` 的 `deps` 每用例新建（`PlannerEngine._pending` 跨请求会串降级事件），并发既省不了时间也会污染审计 |
| **先报告再跑批** | 不带 `--yes` 时**只打印执行计划**（条数、模式、匣带、预估 token/成本）后退出 0；真跑必须显式 `--yes` |
| **重跑前 mv 备份** | 出参文件已存在时先改名 `*.bak-<UTC时间戳>`，绝不覆盖上一次 run（bad case 复盘要能对照两轮） |

--------------------------------------------------------------------------
二、N-13：验真不过 ⇒ 根本不启动
--------------------------------------------------------------------------
`_bootstrap.verify_frozen_inputs()` 校验冻结集 `content_hash` 与 `sandbox_db_sha256`。
不过就退出 —— 因为哈希不符时继续跑，产出的是一份**没有对应数据集版本**的评测报告，
而报告本身看起来完全合法（这类错误只会在使用时暴露，不会在生产时暴露）。

--------------------------------------------------------------------------
三、哈希只有一处实现（不做第二份真相）
--------------------------------------------------------------------------
判定要两个哈希：**金标哈希复算**与**被测结果哈希**。两者的载荷口径都属于 W1A
（`build_frozen_set.result_hash`，它把列名也算进载荷）。本文件**不复制**那段公式，
而是用 `_ParamCursor` 把"带命名参数的 SQL"接进 W1A 的实现 —— 因为
`result_hash(cur, sql, tenant)` 内部只调 `cur.execute(sql)`，签名不匹配是**形状**问题，
不是口径问题。自己重写 payload = 制造第二份哈希口径。

--------------------------------------------------------------------------
四、租户边界的两侧（§17.6 一致性测试① 的实物）
--------------------------------------------------------------------------
* **被测侧** = `views=True`：TEMP VIEW 包住租户域物理表（谓词在被测 SQL **之外**，
  与生产"执行层在资产边界注入"同构，见 `sqlite_exec.py` 文档头 §二）；
* **金标侧** = `views=False` + `bfs.tenant_wrap`：手写含租户谓词的等价派生表（W1A 口径）。
两者对**同一条 gold_sql** 必须给出同一个哈希 —— 这正是 §17.6①，由 `consistency.py` 判定；
本文件只把两侧哈希都落在记录里，让报告能逐条核对。

--------------------------------------------------------------------------
五、不进分母的情况（如实，不静默）
--------------------------------------------------------------------------
`infra_error`（匣带 miss / 装配异常）与"金标本身在沙箱执行失败"的用例都标 `scored=False`
并写 `unscored_reason`。§C.4.1 的"EX 分母不含应拒答题"另由 `expected_behavior` 处理。

--------------------------------------------------------------------------
六、节点超时：真打轮放大、回放轮保持契约
--------------------------------------------------------------------------
历史实测（5 条 live）：旧的“预算当硬超时”曾在 `normalize` / `bind` 上触发 `TimeoutError`。
U-107 后 LLM 节点改走 `resolve_route` → `hard_timeout_s`（§10.2），真打轮再按 `harness.py` §五放大。
⇒ 真打轮经 `build_graph(node_timeout_overrides=)`（该缝的 docstring 明说"仅供测试放大超时"）
放大，派生口径见 `harness.py` §五；**回放轮不放大**（不出网），那一轮仍跑契约超时。
后果如实：**真打轮的 EX 不覆盖 §5.3 超时契约**（§17.4），且放大值必须出现在 `config` 里。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import _bootstrap

_bootstrap.bootstrap()

import attribution as attr  # noqa: E402
import build_frozen_set as bfs  # noqa: E402  # W1A 的唯一哈希实现（只读复用）
import equivalence as eq  # noqa: E402
from app.graph.build import NODE_TIMEOUT_S  # noqa: E402  # 契约超时的唯一真相
from harness import (  # noqa: E402
    Harness,
    describe_node_timeouts,
    detect_gate_self_defect,
    eval_node_timeouts,
    identity_for_case,
)
from sqlite_exec import open_sandbox_connection, to_sqlite_sql  # noqa: E402

DEFAULT_OUT = os.path.join(_bootstrap.HERE, "results_v1.json")
DEFAULT_CASSETTE = os.path.join(_bootstrap.HERE, "cassettes", "w6_batch.jsonl")

#: 单条真 LLM 调用的经验上界（本次会话实测：一条 easy 用例 6.5k tokens / ¥0.002）。
#: 只用于 `--yes` 前的**成本预估**，不进任何结论。
_OBSERVED_INPUT_TOKENS = 6500
_OBSERVED_COST_CNY = 0.002

#: 可安全重试的传输层故障；`LlmTimeout` 刻意不在其中（15s/契约超时是判据事件）。
_TRANSIENT_RETRY_KINDS = frozenset(
    {"ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "RemoteProtocolError"}
)
_TRANSIENT_RETRY_MARKERS = frozenset(
    {"LlmCircuitOpen", "LlmUpstreamError", "LlmConcurrencyExceeded", "upstream_fault_then_template_miss"}
)


def _error_markers(record: Mapping[str, Any]) -> set[str]:
    detail = record.get("terminal_error_detail") or {}
    if not isinstance(detail, Mapping):
        return set()
    return {str(v) for v in detail.values() if v is not None}


def _is_hard_timeout_record(record: Mapping[str, Any]) -> bool:
    return "LlmTimeout" in _error_markers(record) or "TimeoutError" in _error_markers(record)


def _is_transient_transport_record(record: Mapping[str, Any]) -> bool:
    """只认传输/上游可用性故障；硬超时永远返回 False。"""
    if record.get("terminal_event") != "error":
        return False
    if _is_hard_timeout_record(record):
        return False
    markers = _error_markers(record)
    return bool(markers & (_TRANSIENT_RETRY_KINDS | _TRANSIENT_RETRY_MARKERS))


def _resume_should_skip(record: Mapping[str, Any]) -> bool:
    """断点续跑只跳过已终结且**不可自动重试**的记录。

    - complete/refuse/clarify：已完成，跳过；
    - 硬超时：按判据事件留在原记录，**不重试**；
    - 传输层故障：允许再跑一次（是否重试由 runner 的退避参数控制）；
    - 其他未评分/未知错误：保守重跑一次。
    """
    if record.get("scored") is not True:
        return False
    if record.get("terminal_event") != "error":
        return True
    if _is_hard_timeout_record(record):
        return True
    return not _is_transient_transport_record(record)


def _load_checkpoint(path: str, *, expected_content_hash: str) -> dict[str, dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("dataset_content_hash") != expected_content_hash:
            raise ValueError(
                "checkpoint 的 dataset_content_hash 与当前冻结集不一致："
                f"{entry.get('dataset_content_hash')} != {expected_content_hash}"
            )
        record = entry.get("record")
        if isinstance(record, Mapping) and record.get("case_id"):
            out[str(record["case_id"])] = dict(record)
    return out


def _append_checkpoint(
    path: str,
    record: Mapping[str, Any],
    *,
    dataset_content_hash: str,
    checkpoint_meta: Mapping[str, Any] | None,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset_content_hash": dataset_content_hash,
        **(dict(checkpoint_meta or {})),
        "record": dict(record),
    }
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# 一、沙箱执行（金标侧 / 被测侧共用）
# ---------------------------------------------------------------------------

class _ParamCursor:
    """把"带命名参数的 SQL"接进 W1A 的 `result_hash`（它只会 `cur.execute(sql)`）。

    ⚠️ 只转发，不做任何值加工 —— 参数绑定仍由 `sqlite3` 完成（N-14 的防注入姿势不变）。
    """

    def __init__(self, cursor: Any, params: Mapping[str, Any]) -> None:
        self._cursor = cursor
        self._params = dict(params or {})

    def execute(self, sql: str) -> None:
        if self._params:
            self._cursor.execute(sql, self._params)
        else:
            self._cursor.execute(sql)

    @property
    def description(self) -> Any:
        return self._cursor.description

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()


def run_in_sandbox(
    sql: str,
    params: Mapping[str, Any] | None = None,
    *,
    tenant: str | None,
    views: bool,
    db_path: str,
    tenant_scoped_physicals: Mapping[str, str],
) -> dict[str, Any]:
    """在沙箱里执行一条 SQL，返回 `{hash, table, error}`（两种租户边界同函数覆盖）。

    `views=True` ⇒ 边界在 TEMP VIEW 上，SQL 本身**不再**包租户谓词（`tenant=None` 传给
    `result_hash`）；`views=False` ⇒ 走 W1A 的 `tenant_wrap`（手写等价谓词）。
    执行失败**不抛**：沙箱缺表达式（方言缺口）是**被测事实**，要进记录而不是打断整批。
    """
    con = (
        open_sandbox_connection(
            db_path, tenant_id=tenant, tenant_scoped_physicals=tenant_scoped_physicals
        )
        if views
        else sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    )
    #: 🔴 出站契约是 psycopg 的 `%(name)s`（`sql_params` 是接口契约的一部分），沙箱是
    #: sqlite3 的 `:name` ⇒ 不做这一步方言桥，**任何带绑定参数的被测 SQL 都恒
    #: `OperationalError: near "%"`**，预测侧永远是空表。2026-10-03 真打批次 EX=0 的
    #: 第一条根因就在这里（不是"模型全错"）—— 金标不带参数，所以只有预测侧被打死。
    sql = to_sqlite_sql(sql)
    try:
        cur = con.cursor()
        digest, nrows, ncols = bfs.result_hash(
            _ParamCursor(cur, params), sql, None if views else tenant
        )
        cur2 = con.cursor()
        _ParamCursor(cur2, params).execute(
            sql if views else bfs.tenant_wrap(sql, tenant)
        )
        table = eq.Table.from_cursor(cur2)
        return {"hash": digest, "rows": nrows, "cols": ncols, "table": table, "error": None}
    except sqlite3.Error as exc:
        return {
            "hash": None,
            "rows": None,
            "cols": None,
            "table": eq.Table((), ()),
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 二、用例筛选
# ---------------------------------------------------------------------------

def load_cases(
    dataset: Mapping[str, Any],
    *,
    ids: list[str] | None = None,
    behavior: str | None = None,
    difficulty: str | None = None,
    level: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """按 CLI 条件筛冻结集（**保持文件原序** —— 跑批顺序影响成本预估的可比对性）。"""
    cases = list(dataset.get("cases") or [])
    if ids:
        wanted = set(ids)
        cases = [c for c in cases if str(c.get("case_id")) in wanted]
    if behavior:
        cases = [c for c in cases if str(c.get("expected_behavior")) == behavior]
    if difficulty and level:
        key = f"difficulty_{difficulty}"
        cases = [c for c in cases if str(c.get(key)) == level]
    if limit is not None:
        cases = cases[:limit]
    return cases


# ---------------------------------------------------------------------------
# 三、单条用例
# ---------------------------------------------------------------------------

def second_round_question(
    case: Mapping[str, Any],
    terminal_event: str | None,
    *,
    answers: Mapping[str, str] | None = None,
) -> str | None:
    """G-8 二轮回路：首轮 `clarify` 后，用「补答」把题面补全，再走一次图。

    补答来源只取**冻结集自带**的 `clarify_expected.candidates[0]`（争议集里已经写明
    两个竞争口径），不猜、不调模型 —— 保证"补答"是数据而不是第二次推断。
    返回 `None` = 不该跑二轮（非 clarify 终态 / 该用例没有候选口径）。

    ⚠️ 首轮判定**不被改写**：本函数只生产第二轮的输入题面，首轮 `terminal_event`
    仍按原样落进记录（`record["second_round"]` 是**附加字段**）。
    """
    if terminal_event != "clarify":
        return None
    # 外部答案文件优先（`--second-round-answers`）：冻结集里 18 条 clarify 只有 1 条带 candidates，
    # 不引入外部补答就无法对多数澄清用例跑二轮。answers 是**数据**，不调模型。
    if answers:
        given = answers.get(str(case.get("case_id")))
        if given and str(given).strip():
            return f"{case.get('question')}（补充口径：{str(given).strip()}）"
    expected = case.get("clarify_expected")
    if not isinstance(expected, Mapping):
        return None
    candidates = [str(c) for c in (expected.get("candidates") or []) if str(c).strip()]
    if not candidates:
        return None
    question = str(case.get("question") or "")
    return f"{question}（补充口径：{candidates[0]}）"


def second_round_success(terminal_event: str | None, infra_error: str | None) -> bool:
    """「澄清后一次成功」的判定：第二轮**真的走到 complete** 且不是基建中断。

    只认 `complete`：`refuse`/`clarify`/`error` 都不是"补答后答出来了"。
    """
    return terminal_event == "complete" and not infra_error


#: τ 采样原始读数的 schema 版本（C2）。与 `app/graph/nodes/bind.py::TAU_RAW_SCHEMA` **必须同值**，
#: 派生器（`tau_samples.py`）只认这一个版本 —— 两边漂了会让样本**静默变少**。
TAU_RAW_SCHEMA = "W8_TAU_RAW/v1"


def _column_of_candidate(candidate_id: str) -> str:
    """`资产.列` → `列`（金标反解只用列名，不猜表名）。

    ⚠️ 为什么只比列名：`gold_sql` 里列名常不带表前缀（`SELECT sum(pay_amount) FROM v_order_paid`），
    而候选键必然是 `资产.列`。带前缀严格匹配会**全不命中**，把每条都判成 `unmatched`；
    只比列名会引入"同名列"的假命中 ⇒ 所以**多命中就判 unmatched**，不挑一个更像的。
    """
    return candidate_id.rsplit(".", 1)[-1]


#: 聚合函数参数里的列 = "**被测量的那个字段**"（L4 绑定的正是它）。
#: ⚠️ 只认这五个聚合：它们是语义包里 `agg` 的全集（sum/avg/count/min/max）。
#:
#: 🔴 W8 第 66 轮 C2-1：**参数列允许是 `*`**（`COUNT(*)`）—— 旧正则把 `*` 排除在外，
#: 于是 `COUNT(*)` 与"聚合参数在候选集里找不到"混成同一条路（都表现为"没有参数"）。
#: 现在 `*` 被显式捕获，由 `_agg_target_columns` 判成"**无可反解的被测字段**"。
_AGG_ARG = re.compile(
    r"\b(sum|avg|count|min|max)\s*\(\s*(distinct\s+)?([A-Za-z_][A-Za-z0-9_.]*|\*)",
    re.I,
)
#: `FROM x` / `JOIN x` 的表名（用于把候选**按资产前缀**收敛到本次查询真正用到的表）。
_GOLD_TABLES = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
#: SQL 关键字 —— 聚合参数**不是**这些（`SUM(CASE WHEN ...)` 里的 `CASE` 是表达式开头，
#: 不是列名）。把它当列名会把"表达式"伪装成"被测字段"。
_SQL_KEYWORDS = frozenset({
    "case", "when", "then", "else", "end", "distinct", "nullif", "coalesce",
    "sum", "avg", "count", "min", "max", "select", "from", "where",
})


def _agg_target_columns(gold_sql: str) -> tuple[list[str], bool]:
    """从 `gold_sql` 里取出"**被测量的那个字段**"的候选列名。

    返回 `(列名列表, 是否存在无参聚合)`。

    ## 形态区分（W8 第 66 轮 C2-1，QA §87.3-①-②）

    | 形态 | 例子 | 目标列 | `has_star_agg` |
    |---|---|---|---|
    | 聚合**带**参数 | `SUM(pay_amount)` | `pay_amount` | False |
    | `COUNT(DISTINCT x)` | `COUNT(DISTINCT sub_order_id)` | `sub_order_id` | False |
    | 聚合**无**参数 | `COUNT(*)` | —— | **True** |

    🔴 `COUNT(*)` 为什么要单列：它**没有**被测字段 —— `COUNT(*)` 的答案只取决于行数，
    与任何一列都无关 ⇒ 反解不出金标 ⇒ 必须 `unmatched`。
    （`GROUP BY` 的维度列**不**作为兜底：那不是"被测量本身"，
    且实测会跨资产假匹配 —— `SELECT v_shop.shop_id, COUNT(*) FROM v_order_paid
    JOIN v_shop ...` 的 `v_shop.shop_id` 会被配成 `v_order_paid.shop_id`。
    宁可少，不可假。）
    """
    targets: list[str] = []
    has_star_agg = False
    for _fn, _distinct, arg in _AGG_ARG.findall(gold_sql):
        if arg == "*":
            has_star_agg = True
            continue
        col = arg.split(".")[-1].lower()
        # `SUM(CASE WHEN ...)` ⇒ 抓到的是表达式开头 `CASE`，不是列名 ⇒ 跳过。
        if col in _SQL_KEYWORDS:
            continue
        targets.append(col)
    return sorted(set(targets)), has_star_agg


def _asset_of(candidate_id: str) -> str:
    """`资产.列` → `资产`（无点则整串，视为"没有资产前缀"）。"""
    return candidate_id.rsplit(".", 1)[0] if "." in candidate_id else candidate_id


def _gold_for_tau(
    case: Mapping[str, Any], expected: str, candidate_ids: list[str]
) -> dict[str, Any]:
    """把冻结集 `gold_sql` **反解**到候选集（C2；QA 点句：匹配不上写 null + reason，不许猜）。

    三种状态，**不可混用**：

    | `gold_status` | 含义 | 派生器怎么用 |
    |---|---|---|
    | `matched` | 金标候选**唯一**确定 | 样本可用，`gold_candidate_id` 进 `ScoreSample` |
    | `expected_clarify` | 该题**本就该澄清**（`expected_behavior=clarify`） | 样本可用，`gold_candidate_id=None`（安全侧样本） |
    | `unmatched` | 反解不出唯一金标 | 🔴 **不进样本**（不是"该澄清"！） |

    🔴 为什么 `unmatched` 必须跳过而不是当 `None`：`ScoreSample.gold_candidate_id is None`
    的语义是"**本该澄清**"。把"我没反解出来"塞进同一个 `None`，等于凭空造出一批
    "该澄清未澄清"的样本 —— 校准结果会朝"更容易澄清"的方向漂（NFR-7.1 最不希望的方向）。

    ## 反解规则（W8 第 66 轮 C2-1 返工后；QA §87.3-①）

    | 级 | 规则 | 失败落 `gold_unmatched_reason` |
    |---|---|---|
    | ① | **表作用域**：`gold_sql` 的 `FROM`/`JOIN` 表名 → 候选的资产前缀。**空即失败，不回退全候选** | `gold_table_not_in_candidates` |
    | ② | **目标列**：只取**聚合函数的参数列**（`SUM(x)`→`x`、`COUNT(DISTINCT x)`→`x`）。`COUNT(*)` 无参数 ⇒ 无可反解的被测字段 | `no_target_column` |
    | ③ | **命中**：作用域内**列名等于**目标列的候选。**恰好 1 个** → `matched`；0 个 → `no_column_overlap`；≥2 个 → `multiple_candidates_match` | —— |

    🔴 **为什么删掉「列名在 gold_sql 里出现过」的兜底**（QA §87.2 的核心指控）：
    旧规则在②落空时退回"作用域内任何在 gold_sql 出现过的列名都算命中" ⇒
    `pay_time`／`pay_status`／`category_l1`／`refund_status` 这类**过滤列**
    被当成被测字段。实测（同一份 raw）：旧口径 matched 61 条，其中 **27 条（44%）**
    的 gold 分数**低于**同候选集次高分 ⇒ 金标本身选错 ⇒ 采样会把 τ 校到错的位置。
    新口径 matched **29** 条；残余 8 条低分逐条核对后**都是"打分器把次优排在金标
    前面"的真实观测**（τ 要量的正是这个），不是金标选错 ⇒ **宁可少，不可假**。

    ⚠️ 为什么**不**用 `GROUP BY` 的维度列兜底：实测它会**跨资产假匹配** ——
    `SELECT v_shop.shop_id, COUNT(*) FROM v_order_paid JOIN v_shop ...` 的
    `v_shop.shop_id` 会被配成 `v_order_paid.shop_id`（同列名、错资产）。
    宁可少，不可假 ⇒ `COUNT(*)` 一律 `unmatched`。
    """
    gold_sql = str(
        case.get("gold_sql") or (case.get("gold") or {}).get("gold_sql") or ""
    )
    digest = hashlib.sha256(gold_sql.encode("utf-8")).hexdigest() if gold_sql else None
    base = {
        "gold_sql_present": bool(gold_sql),
        "gold_sql_sha256": digest,
        "gold_candidate_id": None,
        "gold_match_rule": None,
        "gold_candidates_considered": len(candidate_ids),
        "gold_unmatched_reason": None,
        # 🔴 W8 第 66 轮 C2-1：`COUNT(*)` 的存在与否恒定落盘（**不只在失败分支**）——
        # 读者要能区分"这条题结构上没有可反解的被测字段"与"有但没命中"。
        "gold_has_star_agg": False,
    }
    if expected == "clarify":
        return {**base, "gold_status": "expected_clarify"}
    if not gold_sql:
        return {**base, "gold_status": "unmatched", "gold_unmatched_reason": "empty_gold_sql"}
    if not candidate_ids:
        return {**base, "gold_status": "unmatched", "gold_unmatched_reason": "no_l4_candidates"}

    # ① 表作用域：**空即失败，绝不回退全候选**（QA §87.3-①-①）。
    tables = {name.lower() for name in _GOLD_TABLES.findall(gold_sql)}
    scoped = [cid for cid in candidate_ids if _asset_of(cid).lower() in tables]
    if not scoped:
        return {
            **base,
            "gold_status": "unmatched",
            "gold_unmatched_reason": "gold_table_not_in_candidates",
        }

    # ② 目标列：只认聚合函数的参数列（`COUNT(*)` ⇒ 无可反解的被测字段）。
    targets, has_star_agg = _agg_target_columns(gold_sql)
    if not targets:
        return {
            **base,
            "gold_status": "unmatched",
            "gold_unmatched_reason": "no_target_column",
            "gold_has_star_agg": has_star_agg,
        }

    # 目标列存在 ⇒ 把 `COUNT(*)` 的事实也记下来（matched 分支同样可见）。

    # ③ 命中：**只认列名相等**（作用域内），不认"在 gold_sql 里出现过"。
    hits = [cid for cid in scoped if _column_of_candidate(cid).lower() in targets]
    if len(hits) == 1:
        return {
            **base,
            "gold_status": "matched",
            "gold_candidate_id": hits[0],
            "gold_match_rule": "aggregate_arg",
            "gold_has_star_agg": has_star_agg,
        }
    if not hits:
        return {**base, "gold_status": "unmatched", "gold_unmatched_reason": "no_column_overlap"}
    return {
        **base,
        "gold_status": "unmatched",
        "gold_unmatched_reason": "multiple_candidates_match",
        # 命中集合原样留下：多命中是"金标与候选集不匹配"的事实，不是可以择一解决的歧义。
        "gold_ambiguous_matches": hits,
    }


#: 二轮问句已带补答 ⇒ 冻结集的 `gold_sql` 只对**首轮问句**成立，二轮的 gold **未定义**。
#: 把这个状态单列，而不是复用 `expected_clarify`：后者会被 `ScoreSample` 读成
#: "本该澄清"（安全侧样本）——而二轮明明答出来了，那是**凭空造样本**。
GOLD_NOT_DEFINED_SECOND_ROUND: Final[str] = "not_defined_for_second_round"


def _tau_raw(
    run: Any,
    case: Mapping[str, Any],
    expected: str,
    *,
    second_round: bool = False,
) -> dict[str, Any]:
    """一条记录的 `tau_raw`：L4 原始读数 + 金标反解（C2）。

    `l4_raw is None` = 本次没走到 L4（`bind` 之前就终止 / 无字段级候选）——
    照常给键，写 `ok=False, reason="l4_not_reached"`，**不用空对象冒充"跑过但没分"**。

    ⚠️ `second_round=True` 时金标一律 `not_defined_for_second_round`：二轮问句是
    "原问句 + 补充口径"，冻结集的 `gold_sql` 描述的是**首轮问句**的答案。
    两边混用会让"补答后唯一"被误当成"本该澄清"，把样本推向"更容易澄清"的方向。
    """
    raw = dict(getattr(run, "l4_raw", None) or {})
    if not raw:
        raw = {
            "schema": TAU_RAW_SCHEMA,
            "source": None,
            "ok": False,
            "reason": "l4_not_reached",
            "candidate_ids": [],
            "scores": [],
            "rank": [],
            "scorer": {"model_id": None, "prompt_version": None},
        }
    candidate_ids = [str(cid) for cid in (raw.get("candidate_ids") or [])]
    if second_round:
        return {
            **raw,
            "gold_status": GOLD_NOT_DEFINED_SECOND_ROUND,
            "gold_candidate_id": None,
            "gold_match_rule": None,
            "gold_unmatched_reason": "second_round_question_changed",
            "gold_sql_present": bool(case.get("gold_sql")),
        }
    return {**raw, **_gold_for_tau(case, expected, candidate_ids)}


async def score_case(
    harness: Harness,
    case: dict[str, Any],
    *,
    allowlist: Mapping[str, Any],
    db_path: str,
    second_round: bool = False,
    second_round_answers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """跑一条用例并产出**可 JSON 化**的完整记录（判定与归因都在这里，不再回头戳 state）。

    ⚠️ 必须是协程：整批共用**一个** event loop（`run_batch` 只 `asyncio.run` 一次）。
    每条用例各自 `asyncio.run` 会让 `ChatClient` 的 `httpx.AsyncClient` 留在上一个
    已关闭的 loop 上 —— 实测第 3 条就报 `RuntimeError: Event loop is closed`。
    """
    case_id = str(case["case_id"])
    expected = str(case.get("expected_behavior") or "execute")
    tenant = str(case.get("eval_tenant") or "T_A")
    run = await harness.run_case_async(
        case_id=case_id, question=str(case["question"]), tenant=tenant
    )

    record: dict[str, Any] = {
        "case_id": case_id,
        "question": case["question"],
        "tenant": tenant,
        "expected_behavior": expected,
        "difficulty_struct": case.get("difficulty_struct"),
        "difficulty_semantic": case.get("difficulty_semantic"),
        "nodes": list(run.nodes),
        "terminal_event": run.terminal_event,
        "terminal_code": run.terminal_code,
        # 🔴 P0-A-4：上游失败的**根因细节**（`{"model":…, "kind":…}` 等）。此前只落 `code`
        # ⇒ `LLM_UPSTREAM_ERROR` 分不清"上游抖/超时"与"响应解码失败"（第 41–43 轮实测猜错三轮）。
        "terminal_error_detail": run.terminal_error_detail,
        "outcome": run.outcome,
        "refusal_reason": run.refusal_reason,
        "binding_status": run.binding_status,
        #: 🔴 W76-1：层号（L1/L2/L3/L4）逐 case 落盘 —— `CalibrationReport` 第 8 条要的
        #: 运行时层分布只能从这里汇总（评测装配根不注入 QueryPlanStore）。
        "binding_layer": run.binding_layer,
        "sql_text": run.sql_text,
        "sql_params": dict(run.sql_params),
        "sql_dialect": run.sql_dialect,
        "limit_injected": run.limit_injected,
        "applied_predicates": list(run.applied_predicates),
        "gate_decisions": run.gate_decisions,
        "gate1_reject_rule": run.gate1_reject_rule,
        "exec_error_class": run.exec_error_class,
        "degradations": list(run.degradations),
        # 候选规模 = L4 截断偏差的分母（实测每候选 ≈36.6 tok，512 上限只容 ≈14 个）。
        "retrieval_counts": dict(harness.retrieval.last_counts),
        "latency_ms": run.latency_ms,
        "tokens": run.tokens,
        "cost_cny": run.cost_cny,
        "infra_error": run.infra_error,
        "scored": True,
        "unscored_reason": None,
        # G-8 二轮：默认 None（未开跑）；`--second-round` 时由尾部块填
        "second_round": None,
        # 🔴 W8 第 65 轮（C2）：τ 采样的**原始读数**（候选稳定键 / 分数 / rank / 打分器 / 金标反解）。
        #    §65 只写 schema 与派生器，**不采 τ、不改 BINDING_TAU_***。
        "tau_raw": _tau_raw(run, case, expected),
    }

    if run.infra_error:
        record.update(scored=False, unscored_reason=f"infra: {run.infra_error}")
        record["verdict"] = None
        record["attribution"] = None
        return record

    # ---- 金标侧：同一沙箱、两种租户边界（§17.6① 的实物）----
    gold_sql = str(case.get("gold_sql") or "")
    gold_view = gold_wrap = None
    if gold_sql:
        gold_view = run_in_sandbox(
            gold_sql, tenant=tenant, views=True,
            db_path=db_path, tenant_scoped_physicals=harness.tenant_scoped_physicals,
        )
        gold_wrap = run_in_sandbox(
            gold_sql, tenant=tenant, views=False,
            db_path=db_path, tenant_scoped_physicals=harness.tenant_scoped_physicals,
        )
        if gold_wrap["error"]:
            record.update(
                scored=False,
                unscored_reason=f"gold_exec_failed: {gold_wrap['error']}",
            )
    record["gold"] = {
        "gold_sql": gold_sql,
        "frozen_hash": case.get("gold_result_hash"),
        "via_view": _slim(gold_view),
        "via_wrap": _slim(gold_wrap),
        # §17.6① 的逐条判据（这里只记账，判定归 consistency.py）
        "view_eq_wrap": bool(gold_view and gold_wrap and gold_view["hash"] == gold_wrap["hash"]),
        "wrap_eq_frozen": bool(
            gold_wrap and gold_wrap["hash"] == case.get("gold_result_hash")
        ),
    }

    # ---- 等价判定：只有"期望 execute 且两侧都跑出了表"才进分母 ----
    # 🔴 预测侧的表**必须**与金标同器同界（沙箱 + TEMP VIEW + 同一哈希函数），不能读
    # state 的 `result_rows`：07 §5.2.1 把 `result_rows` 定为**体积字段**（execute 只
    # `context.hold_rows`，行不进 state，state 留 `result_columns`/`row_count`/指纹）。
    # 读它 ⇒ 预测侧恒 0 行 ⇒ EX 恒 0，而这是测量器件的形状，不是被测系统被证明为 0。
    # 在线"用户看到的表"另有口径（脱敏后的行经 SSE `result` 帧），那里由组 8 + 缓存承接，
    # 评测面拿不到；此处把在线 row_count 一并记账，两个口径不一致时留在记录里可见。
    pred_table = eq.Table((), ())
    verdict = None
    pred_sandbox = None
    if expected == "execute" and gold_sql and gold_view and not gold_view["error"]:
        if run.sql_text:
            pred_sandbox = run_in_sandbox(
                run.sql_text,
                run.sql_params,
                tenant=tenant,
                views=True,
                db_path=db_path,
                tenant_scoped_physicals=harness.tenant_scoped_physicals,
            )
            pred_table = pred_sandbox["table"]
        pred_hash = pred_sandbox["hash"] if pred_sandbox else None
        verdict = eq.compare_tables(
            gold_view["table"],
            pred_table,
            gold_sql=gold_sql,
            pred_sql=run.sql_text,
            hash_matches=_hash_eq(pred_hash, case.get("gold_result_hash")),
        )
        record["predicted"] = {
            "hash": pred_hash,
            "columns": list(pred_table.columns),
            "rows": len(pred_table.rows),
            "shape": eq.shape_of(pred_table),
            # 两个口径同时记账：`state_row_count` = 在线链路自己报的行数（组 8 的
            # `row_count`，脱敏后、未复算）；`rows` = 沙箱复算口径。不一致就是缺陷信号。
            "state_row_count": run.row_count,
            "sandbox_error": (pred_sandbox or {}).get("error"),
        }
    record["verdict"] = (
        None
        if verdict is None
        else {
            "equivalent": verdict.equivalent,
            "hash_matches": verdict.hash_matches,
            "tags": list(verdict.tags),
            "diffs": list(verdict.diffs),
            "unmatched": verdict.unmatched,
            "equivalent_despite_hash_mismatch": verdict.equivalent_despite_hash_mismatch,
        }
    )

    # ---- 归因：只对"没按期望收口 / 结果不等价"的用例做 ----
    # ⚠️ 交互类（clarify / refuse）**同样要归因**：`expected=refuse` 却执行了就是
    # `security_leak`（P0）。早期版本把非 execute 一律记成"无归因"，等于让红线事故
    # 从 §C.7 分布里消失 —— 那是比"数字难看"更坏的结果。
    equivalent = None if verdict is None else verdict.equivalent
    if expected == "execute":
        failed = not (verdict is not None and verdict.equivalent)
    else:
        failed = run.terminal_event != expected
    if not failed:
        record["attribution"] = None
    else:
        defect = _gate_defect_if_rejected(run.sql_text, allowlist, run.gate_decisions)
        a = attr.attribute(
            case=case,
            predicted_sql=run.sql_text or None,
            terminal_event=run.terminal_event,
            equivalent=equivalent,
            exec_error_class=run.exec_error_class,
            equiv_tags=verdict.tags if verdict else (),
            binding_state=run.binding_status,
            gate_self_defect=defect,
        )
        record["attribution"] = {"category": a.category, "signal": a.signal, "severity": a.severity}

    # ---- G-8 二轮回路（默认关；`--second-round` 才跑）----
    # 首轮 clarify 判定**不改写**：这里只追加 `second_round` 字段。
    if second_round:
        question2 = second_round_question(
            case, run.terminal_event, answers=second_round_answers
        )
        if question2 is not None:
            run2 = await harness.run_case_async(
                case_id=f"{case_id}#r2", question=question2, tenant=tenant
            )
            record["second_round"] = {
                "attempted": True,
                "question": question2,
                "terminal_event": run2.terminal_event,
                "terminal_code": run2.terminal_code,
                "nodes": list(run2.nodes),
                "tokens": dict(run2.tokens),
                "cost_cny": run2.cost_cny,
                "infra_error": run2.infra_error,
                "success": second_round_success(run2.terminal_event, run2.infra_error),
                # C2：二轮往往才是**真的走到 bind**（首轮停在 clarify，L4 没跑）⇒ 二轮的
                # `tau_raw` 才是 τ 样本的主要来源，必须一并落盘，否则样本基数被吃掉一半。
                "tau_raw": _tau_raw(run2, case, expected, second_round=True),
            }
        else:
            record["second_round"] = {"attempted": False, "reason": "no_supplement_source"}
    else:
        record["second_round"] = None
    return record


def _gate_defect_if_rejected(
    sql: str | None,
    allowlist: Mapping[str, Any],
    gate_decisions: Mapping[str, str],
) -> str | None:
    """只在 gate1 实际拒绝时检查其自伤形态。

    `detect_gate_self_defect` 是静态形态检测；若 gate1 已经放行（例如排序别名
    已被 `_resolve_column` 正常解析），该形态不能覆盖一手 `pass/True` 事实。
    """
    if not str(gate_decisions.get("1") or "").startswith("reject/"):
        return None
    return detect_gate_self_defect(sql or "", allowlist)

def _slim(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {k: result[k] for k in ("hash", "rows", "cols", "error")}


def _hash_eq(a: str | None, b: str | None) -> bool | None:
    if a is None or b is None:
        return None
    return a == b


# ---------------------------------------------------------------------------
# 四、整批
# ---------------------------------------------------------------------------

def _plan(
    cases: list[dict[str, Any]],
    *,
    live: bool,
    cassette: str,
    mode: str,
    node_timeouts: Mapping[str, float] | None,
) -> str:
    by: dict[str, int] = {}
    for c in cases:
        by[str(c.get("expected_behavior") or "execute")] = (
            by.get(str(c.get("expected_behavior") or "execute"), 0) + 1
        )
    lines = [
        "执行计划（§C.6.1：先报告再跑批）",
        f"  用例数        : {len(cases)}  按期望行为 {by}",
        f"  LLM 来源      : {'真打上游 + 录制' if live else '匣带回放（不出网）'}",
        f"  匣带          : {cassette}  mode={mode}",
        "  执行方式      : 串行，单线程，整批一个 event loop",
        "  节点超时      : "
        + (
            "契约值（07 §5.3 同形；本轮覆盖超时回归）"
            if node_timeouts is None
            else "已放大 ⇒ "
            # 🔴 必须用 `.get()`：U-104 把 5 个 LLM 节点移出 `NODE_TIMEOUT_S`、U-107 又把它们的
            #   硬超时改成执行期解析 ⇒ 放大表是**并集**（`harness.eval_node_timeouts`），直接下标
            #   会让这张"先报告再跑批"（§C.6.1）的计划在 `bind` 上 `KeyError` 崩掉
            #   （2026-10-03 实测：不带 `--yes` 只打印计划也 rc=1 ⇒ 自那次改动后没人打出过计划）。
            + ", ".join(
                f"{k}={v:g}s"
                for k, v in sorted(node_timeouts.items())
                if v != NODE_TIMEOUT_S.get(k)
            )
            + "（EX 不覆盖 §5.3 超时契约；表内无契约值的 LLM 节点："
            + ", ".join(sorted(set(node_timeouts) - set(NODE_TIMEOUT_S)))
            + "）"
        ),
    ]
    if live:
        lines.append(
            f"  成本预估      : ≈{len(cases) * _OBSERVED_INPUT_TOKENS:,} tokens"
            f" / ≈¥{len(cases) * _OBSERVED_COST_CNY:.3f}"
            f"（单条样本实测 {_OBSERVED_INPUT_TOKENS:,}tok/¥{_OBSERVED_COST_CNY}，"
            "难题与 repair 轮次会显著高于此）"
        )
    else:
        lines.append("  成本预估      : 0（回放不出网；miss 会当场打断该条并记 infra_error）")
    return "\n".join(lines)


async def run_batch(
    cases: list[dict[str, Any]],
    *,
    live: bool,
    cassette: str,
    mode: str,
    db_path: str,
    column_top: int | None,
    node_timeout_overrides: Mapping[str, float] | None,
    max_concurrency: int | None = None,
    checkpoint_path: str | None = None,
    resume_records: Mapping[str, Mapping[str, Any]] | None = None,
    checkpoint_meta: Mapping[str, Any] | None = None,
    transport_retries: int = 2,
    transport_backoff_s: float = 2.0,
    second_round: bool = False,
    second_round_answers: Mapping[str, str] | None = None,
    batch_id: str | None = None,
    max_cost_cny: float | None = None,
) -> dict[str, Any]:
    """串行跑完整批。**整批只有一个 event loop**（纪律由 `run_batch_sync` 唯一持有）。

    `Harness` 在循环**内**构造：`ChatClient` 会建 `httpx.AsyncClient` 与信号量，
    构造期所在的 loop 就是它此后绑定的 loop —— 在外面构造、里面复用是另一半条
    "Event loop is closed"。

    `batch_id`：本次跑批的**独立身份**（τ 采样要 3 次独立批次才构成 `repeats`）。
    `max_cost_cny`：**累计计费硬上限**（W76 派单要求"越过硬上限立即停"）。每跑完一条
    就把 `cost_cny` 累加；越过即**不再开始下一条**，并在返回值里落 `budget_stop`。
    它只增不减、按记录自报的 `cost_cny` 计（与 summary 同一个口径）。
    """
    harness = Harness(
        live=live,
        cassette_path=cassette,
        cassette_mode=mode,
        column_top=column_top,
        node_timeout_overrides=node_timeout_overrides,
        max_concurrency=max_concurrency,
    )
    allowlist = harness.semantics.guard_allowlist(
        identity_for_case("ALLOWLIST", "T_A"), max_rows=None
    )
    records: list[dict[str, Any]] = []
    resumed = dict(resume_records or {})
    spent = 0.0
    budget_stop: dict[str, Any] | None = None
    try:
        for index, case in enumerate(cases, start=1):
            if budget_stop is not None:
                break
            case_id = str(case["case_id"])
            existing = resumed.get(case_id)
            if existing is not None and _resume_should_skip(existing):
                print(f"[{index}/{len(cases)}] {case_id} checkpoint-skip", flush=True)
                records.append(dict(existing))
                continue

            started = time.monotonic()
            print(f"[{index}/{len(cases)}] {case_id}", flush=True)
            record: dict[str, Any] = {}
            retry_attempt = 0
            while True:
                record = await score_case(
                    harness, case, allowlist=allowlist, db_path=db_path,
                    second_round=second_round,
                    second_round_answers=second_round_answers,
                )
                if _is_transient_transport_record(record) and retry_attempt < max(0, transport_retries):
                    delay = max(0.0, transport_backoff_s) * (2 ** retry_attempt)
                    retry_attempt += 1
                    print(
                        f"    transient upstream failure; retry {retry_attempt}/"
                        f"{max(0, transport_retries)} after {delay:.1f}s",
                        flush=True,
                    )
                    await asyncio.sleep(delay)
                    continue
                break
            # 墙钟（含沙箱复算）。`latency_ms` 来自图内计时，超时中断的用例拿不到，
            # 没有这一列就没法把"卡住"和"很快失败"区分开（真打批次必须能看出去向）。
            record["wall_s"] = round(time.monotonic() - started, 3)
            record["runner_transport_retries"] = retry_attempt
            if batch_id is not None:
                record["batch_id"] = batch_id
            records.append(record)
            spent += float(record.get("cost_cny") or 0.0)
            if checkpoint_path:
                _append_checkpoint(
                    checkpoint_path,
                    record,
                    dataset_content_hash=str((checkpoint_meta or {}).get("dataset_content_hash") or ""),
                    checkpoint_meta=checkpoint_meta,
                )
            if max_cost_cny is not None and spent >= float(max_cost_cny):
                #: 派单原文：越过硬上限**立即停**，不得为追结果重试。已跑完的这一条照样入账。
                budget_stop = {
                    "reason": "max_cost_cny_exceeded",
                    "max_cost_cny": float(max_cost_cny),
                    "spent_cny": round(spent, 6),
                    "stopped_after_case": case_id,
                    "completed_cases": len(records),
                    "requested_cases": len(cases),
                }
                print(
                    "budget stop: spent "
                    f"{spent:.4f} CNY >= cap {float(max_cost_cny):.4f} after {case_id}",
                    flush=True,
                )
                break
    finally:
        written = harness.save_cassette()
        await harness.aclose()
    return {
        "records": records,
        "cassette_entries_written": written,
        "node_timeout_overrides": dict(harness.node_timeout_overrides),
        "max_concurrency": harness.max_concurrency,
        "budget_stop": budget_stop,
    }


def run_batch_sync(cases: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """同步壳（Windows 惯例）。**唯一**的 `asyncio.run` 落点 —— 别再在别处开 loop。"""
    return asyncio.run(run_batch(cases, **kwargs))


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """本次 run 的分布（headline 数字由 `reporter.py` 负责，这里只做**跑批当场**的核对面）。"""
    scored = [r for r in records if r.get("scored")]
    execute = [r for r in scored if r["expected_behavior"] == "execute"]
    cats: dict[str, int] = {}
    for r in records:
        category = (r.get("attribution") or {}).get("category")
        if category:
            cats[category] = cats.get(category, 0) + 1
    terminals: dict[str, int] = {}
    for r in records:
        key = str(r.get("terminal_event"))
        terminals[key] = terminals.get(key, 0) + 1
    layers: dict[str, int] = {}
    for r in records:
        key = str(r.get("binding_layer") or "none")
        layers[key] = layers.get(key, 0) + 1
    # 超时是"外因"还是"被测事实"要能一眼分开看：放大后仍超时 = 真慢/真挂。
    n_timeout = sum(1 for r in records if "TimeoutError" in str(r.get("infra_error")))
    walls = sorted(float(r["wall_s"]) for r in records if r.get("wall_s") is not None)
    return {
        "n_records": len(records),
        "n_scored": len(scored),
        "n_unscored": len(records) - len(scored),
        "n_node_timeout": n_timeout,
        "n_execute_scored": len(execute),
        # EX 分母里"根本没出 SQL"的条数必须单列：否则 0/N 会被读成"模型写错了 SQL"，
        # 而实际是它在前面的节点就收口成了 refuse/clarify。
        "n_execute_with_sql": sum(1 for r in execute if r.get("sql_text")),
        "n_equivalent": sum(1 for r in execute if (r.get("verdict") or {}).get("equivalent")),
        "terminal_distribution": terminals,
        "binding_layer_distribution": layers,
        "attribution_distribution": cats,
        "tokens_total": sum(int((r.get("tokens") or {}).get("total") or 0) for r in records),
        "cost_cny_total": round(sum(float(r.get("cost_cny") or 0) for r in records), 6),
        "wall_s": {
            "max": walls[-1] if walls else None,
            "median": walls[len(walls) // 2] if walls else None,
            "sum": round(sum(walls), 3) if walls else None,
        },
        # ---- G-8 二轮回路读数（`--second-round` 才有非零值）----
        # 口径：attempted = 首轮 clarify 且拿到补答来源；success = 第二轮走到 complete 且非基建中断。
        "n_second_round_attempted": sum(
            1 for r in records if (r.get("second_round") or {}).get("attempted")
        ),
        "n_second_round_success": sum(
            1 for r in records if (r.get("second_round") or {}).get("success")
        ),
        # 第二轮 tokens/cost 单列，避免与首轮混账（首轮才是可比的基线成本）。
        "second_round_tokens_total": sum(
            int(((r.get("second_round") or {}).get("tokens") or {}).get("total") or 0)
            for r in records
        ),
        "second_round_cost_cny_total": round(sum(
            float((r.get("second_round") or {}).get("cost_cny") or 0) for r in records
        ), 6),
    }


def _backup(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = f"{path}.bak-{stamp}"
    shutil.move(path, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CommerceQL W6 评测批量执行器")
    parser.add_argument("--cases", help="逗号分隔的 case_id 白名单")
    parser.add_argument("--behavior", choices=("execute", "clarify", "refuse"))
    parser.add_argument("--difficulty", choices=("struct", "semantic"))
    parser.add_argument("--level", help="配合 --difficulty 的难度取值")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true", help="真打上游并录制匣带")
    parser.add_argument(
        "--contract-timeouts",
        action="store_true",
        help="钉在 07 §5.3 契约超时上跑（超时回归专用；真打轮会大面积假失败，见 §六）",
    )
    parser.add_argument("--cassette", default=DEFAULT_CASSETTE)
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--db", default=_bootstrap.SANDBOX_DB)
    parser.add_argument("--column-top", type=int, default=None)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="逐条 JSONL 检查点路径；配合 --resume 可断点续跑",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 --checkpoint 读取已完成记录；硬超时记录按判据保留，传输故障可继续等待重试",
    )
    parser.add_argument(
        "--transport-retries",
        type=int,
        default=2,
        help="runner 层对 ConnectError/CircuitOpen 等传输故障的最大重试次数；LlmTimeout 不重试",
    )
    parser.add_argument(
        "--transport-backoff-s",
        type=float,
        default=2.0,
        help="runner 层传输故障退避基数（秒）；第 n 次等待 base*2^n",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="本次批次的额外并发帽，只收窄 Settings.LLM_MAX_CONCURRENCY",
    )
    parser.add_argument("--yes", action="store_true", help="确认执行（不带则只打印计划）")
    parser.add_argument(
        "--provenance",
        default=None,
        help=(
            "批次来源说明，原样落进 `config.provenance`。回放轮必填：否则报告只能说"
            "「本轮未真打」，把已经花过钱的 §17.2 录制事实说没了（漏报同样是失真）。"
        ),
    )
    parser.add_argument(
        "--second-round",
        action="store_true",
        help="G-8 二轮回路：首轮 clarify 后用冻结集的 clarify_expected.candidates[0] 做补答再走一次图",
    )
    parser.add_argument(
        "--second-round-answers",
        default=None,
        help="JSON 文件：{case_id: \"补答文本\"}；冻结集外补充答来源（不改冻结集）",
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="本次跑批的独立身份（W76 τ 采样：3 次独立批次才构成 repeats）",
    )
    parser.add_argument(
        "--max-cost-cny",
        type=float,
        default=None,
        help="累计计费硬上限（元）。每跑完一条累加，越过即停并落 budget_stop",
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    #: T-11②：构建身份在**任何写盘之前**取。匣带和结果文件是本轮自己的产物 ⇒ 跑到收尾再去读
    #: `git status`，会把"我写了产物"说成"被测代码不等于这棵树"（`git_dirty=True` 假阳）。
    stamp = _bootstrap.build_stamp()

    evidence = _bootstrap.verify_frozen_inputs()
    if not evidence["checks"]["all_ok"]:
        print("N-13 验真失败：冻结集/沙箱与指纹不一致，拒绝启动。", file=sys.stderr)
        print(json.dumps(evidence["checks"], ensure_ascii=False, indent=2))
        return 3
    print(
        f"验真通过：dataset={evidence['dataset_version']} cases={evidence['n_cases']} "
        f"content_hash={str(evidence['content_hash'])[:16]}…"
    )
    if args.verify_only:
        return 0

    checkpoint_path = args.checkpoint
    if args.resume and not checkpoint_path:
        checkpoint_path = str(Path(args.out).with_suffix(".checkpoint.jsonl"))
    resume_records: dict[str, dict[str, Any]] = {}
    if args.resume:
        resume_records = _load_checkpoint(
            str(checkpoint_path), expected_content_hash=str(evidence["content_hash"])
        )
        print(f"断点续跑：checkpoint={checkpoint_path} loaded={len(resume_records)}")

    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = load_cases(
        dataset,
        ids=args.cases.split(",") if args.cases else None,
        behavior=args.behavior,
        difficulty=args.difficulty,
        level=args.level,
        limit=args.limit,
    )
    if not cases:
        print("筛选后 0 条用例 —— 检查 --cases / --behavior / --level 是否拼错。", file=sys.stderr)
        return 4

    # 超时策略：真打轮放大（否则健康链路会被 §5.3 的 0.2s/2.0s 掐断），回放轮钉契约。
    node_timeouts = (
        None if (args.contract_timeouts or not args.live) else eval_node_timeouts()
    )

    print(_plan(
        cases,
        live=args.live,
        cassette=args.cassette,
        mode="record" if args.live else args.mode,
        node_timeouts=node_timeouts,
    ))
    if not args.yes:
        print("\n未带 --yes：只打印计划，不执行。")
        return 0

    batch = run_batch_sync(
        cases,
        live=args.live,
        cassette=args.cassette,
        mode="record" if args.live else args.mode,
        db_path=args.db,
        column_top=args.column_top,
        node_timeout_overrides=node_timeouts,
        max_concurrency=args.max_concurrency,
        second_round=args.second_round,
        second_round_answers=(
            json.loads(Path(args.second_round_answers).read_text(encoding="utf-8"))
            if args.second_round_answers else None
        ),
        checkpoint_path=checkpoint_path,
        resume_records=resume_records if args.resume else None,
        checkpoint_meta={
            "dataset_content_hash": evidence["content_hash"],
            "git_rev": stamp.get("git_rev"),
            "git_dirty": stamp.get("git_dirty"),
        },
        transport_retries=max(0, args.transport_retries),
        transport_backoff_s=max(0.0, args.transport_backoff_s),
        batch_id=args.batch_id,
        max_cost_cny=args.max_cost_cny,
    )
    summary = summarize(batch["records"])
    payload = {
        "frozen_evidence": evidence,
        "config": {
            "live": args.live,
            "cassette": args.cassette,
            "mode": "record" if args.live else args.mode,
            "db": args.db,
            "column_top": args.column_top,
            "n_requested": len(cases),
            "provenance": args.provenance,
            "node_timeouts": describe_node_timeouts(batch["node_timeout_overrides"]),
            "max_concurrency": batch.get("max_concurrency"),
            "checkpoint": checkpoint_path,
            "resume": bool(args.resume),
            "transport_retries": max(0, args.transport_retries),
            "transport_backoff_s": max(0.0, args.transport_backoff_s),
            "batch_id": args.batch_id,
            "max_cost_cny": args.max_cost_cny,
            "budget_stop": batch.get("budget_stop"),
        },
        "summary": summary,
        "records": batch["records"],
    }
    #: T-11②：产物自报构建身份 ⇒ `reporter._first_declared` 能在**顶层**取到 `generated_at`／`git_rev`，
    #: 这一格的取证等级才会从 `mtime_only` 升到 `self_reported`。值取自开跑前那次 `build_stamp()`。
    payload.update(stamp)
    backed_up = _backup(args.out)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    if backed_up:
        print(f"旧结果已备份：{backed_up}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
