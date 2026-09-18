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
实测（5 条 live）：健康链路会在 `normalize`(2.0s) 与 `bind`(0.2s) 上 `TimeoutError` ——
07 §5.3 的契约值容不下一次真实 LLM 出站，这是**契约之间的冲突**（已上呈），不是被测缺陷。
⇒ 真打轮经 `build_graph(node_timeout_overrides=)`（该缝的 docstring 明说"仅供测试放大超时"）
放大，派生口径见 `harness.py` §五；**回放轮不放大**（不出网），那一轮仍跑契约超时。
后果如实：**真打轮的 EX 不覆盖 §5.3 超时契约**（§17.4），且放大值必须出现在 `config` 里。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from sqlite_exec import open_sandbox_connection  # noqa: E402

DEFAULT_OUT = os.path.join(_bootstrap.HERE, "results_v1.json")
DEFAULT_CASSETTE = os.path.join(_bootstrap.HERE, "cassettes", "w6_batch.jsonl")

#: 单条真 LLM 调用的经验上界（本次会话实测：一条 easy 用例 6.5k tokens / ¥0.002）。
#: 只用于 `--yes` 前的**成本预估**，不进任何结论。
_OBSERVED_INPUT_TOKENS = 6500
_OBSERVED_COST_CNY = 0.002


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

async def score_case(
    harness: Harness,
    case: dict[str, Any],
    *,
    allowlist: Mapping[str, Any],
    db_path: str,
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
        "outcome": run.outcome,
        "refusal_reason": run.refusal_reason,
        "binding_status": run.binding_status,
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
    pred_table = eq.Table(run.result_columns, run.result_rows)
    verdict = None
    if expected == "execute" and gold_sql and gold_view and not gold_view["error"]:
        pred_hash = _pred_hash(harness, run, db_path, tenant)
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
        defect = detect_gate_self_defect(run.sql_text, allowlist)
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
    return record


def _slim(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {k: result[k] for k in ("hash", "rows", "cols", "error")}


def _pred_hash(
    harness: Harness, run: Any, db_path: str, tenant: str
) -> str | None:
    """被测 SQL 的**金标同口径**哈希（复算一次；在线的 `result_fingerprint` 是另一套算法，不能混用）。"""
    if not run.sql_text:
        return None
    again = run_in_sandbox(
        run.sql_text,
        run.sql_params,
        tenant=tenant,
        views=True,
        db_path=db_path,
        tenant_scoped_physicals=harness.tenant_scoped_physicals,
    )
    return again["hash"]


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
            + ", ".join(
                f"{k}={v:g}s"
                for k, v in sorted(node_timeouts.items())
                if v != NODE_TIMEOUT_S[k]
            )
            + "（EX 不覆盖 §5.3 超时契约）"
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
) -> dict[str, Any]:
    """串行跑完整批。**整批只有一个 event loop**（纪律由 `run_batch_sync` 唯一持有）。

    `Harness` 在循环**内**构造：`ChatClient` 会建 `httpx.AsyncClient` 与信号量，
    构造期所在的 loop 就是它此后绑定的 loop —— 在外面构造、里面复用是另一半条
    "Event loop is closed"。
    """
    harness = Harness(
        live=live,
        cassette_path=cassette,
        cassette_mode=mode,
        column_top=column_top,
        node_timeout_overrides=node_timeout_overrides,
    )
    allowlist = harness.semantics.asset_allowlist(identity_for_case("ALLOWLIST", "T_A"))
    records: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(cases, start=1):
            started = time.monotonic()
            print(f"[{index}/{len(cases)}] {case['case_id']}", flush=True)
            record = await score_case(
                harness, case, allowlist=allowlist, db_path=db_path
            )
            # 墙钟（含沙箱复算）。`latency_ms` 来自图内计时，超时中断的用例拿不到，
            # 没有这一列就没法把"卡住"和"很快失败"区分开（真打批次必须能看出去向）。
            record["wall_s"] = round(time.monotonic() - started, 3)
            records.append(record)
    finally:
        written = harness.save_cassette()
        await harness.aclose()
    return {
        "records": records,
        "cassette_entries_written": written,
        "node_timeout_overrides": dict(harness.node_timeout_overrides),
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
        "attribution_distribution": cats,
        "tokens_total": sum(int((r.get("tokens") or {}).get("total") or 0) for r in records),
        "cost_cny_total": round(sum(float(r.get("cost_cny") or 0) for r in records), 6),
        "wall_s": {
            "max": walls[-1] if walls else None,
            "median": walls[len(walls) // 2] if walls else None,
            "sum": round(sum(walls), 3) if walls else None,
        },
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
    parser.add_argument("--yes", action="store_true", help="确认执行（不带则只打印计划）")
    parser.add_argument(
        "--provenance",
        default=None,
        help=(
            "批次来源说明，原样落进 `config.provenance`。回放轮必填：否则报告只能说"
            "「本轮未真打」，把已经花过钱的 §17.2 录制事实说没了（漏报同样是失真）。"
        ),
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

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
        },
        "summary": summary,
        "records": batch["records"],
    }
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
