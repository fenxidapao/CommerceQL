"""评测报告页的三个投影（层号 L3｜归属窗口：W8，T-34）。

**为什么聚合在这里而不是在前端**：`docs/01_需求规格说明书_PRD.md:271` 那一格写的是判据
（「网格由后端聚合，前端不得自算」），`docs/02_附录A_接口契约详解.md:912-913` 把它列为
§A.9.4 的硬要求，`docs/06_UIUX设计文档.md:2264-2266` 进一步写成落地要求
（「前端只渲染 `grid.axes`／`grid.cells[]`／`attribution[]`／`gate.items[]`，一行聚合逻辑都不写」）。
⇒ 本文件是这三处口径在代码里的唯一落点。

**四条设计约束，都是刻意的**：

1. **只投影，不重算已经算过的东西。** 网格／归因／门禁／安全这四组，当期批次的权威数
   来自 `eval/reporter.py` 已入库的门禁报告产物；本文件只做**形状翻译**（含
   `extra → extra_hard` 的标签对齐，见 `_STRUCT_CONTRACT`）。只有产物里没有的口径
   （分位延迟、缓存命中率、拒答与澄清的两类错误率）才在本文件算，每处都点名它抄的是哪一行。
2. **算不出来的写 `null`，并同时进 `unavailable` 清单。** 不许用 `0` 顶替「未测」
   —— `0.0%` 在页面上读起来像一次真实测量，那比空白更危险。
3. **不返回 `gold_sql` 与完整 `predicted_sql`**（`docs/02:1012` 的明文约束）。
4. **门禁报告只与它自报的那一批次联动**（`_linked_gate` 的配对尺 =
   报告里的 `meta.results_artifact.stem`）：配不上就当作没有报告，
   绝不拿别的批次的网格／门禁数冒充当前行。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.present import artifacts

__all__ = ["dataset_ids", "datasets", "run_detail", "runs"]

#: 契约侧的结构档标签（`docs/02:950`）与产物侧标签的对应：产物用 `extra`，契约用 `extra_hard`。
_STRUCT_CONTRACT: Final = ("easy", "medium", "hard", "extra_hard")
_STRUCT_ARTIFACT: Final = ("easy", "medium", "hard", "extra")
_SEMANTIC: Final = ("low", "medium", "high")

#: 逐格验收阈值 = PRD §13.2 的「验收阈值按格子设定」表（`docs/01:1570-1574`）。
#: Extra Hard 行原文是「不设硬性阈值（仅报告）」⇒ 三格全 `None`，页面据此显示「仅报告」。
_TARGETS: Final[Mapping[str, tuple[float | None, float | None, float | None]]] = {
    "easy": (0.95, 0.88, 0.80),
    "medium": (0.90, 0.80, 0.72),
    "hard": (0.75, 0.68, 0.60),
    "extra_hard": (None, None, None),
}

#: 门禁判词的五值词表定义在 `docs/07 §17.3`（G-1…G-8），契约示例只谈到 pass/fail 两值。
#: ⇒ 这里把五值如实小写带出：`partial`／`unverified`／`not_available` 都不是"未通过"的同义词，
#:   折进 `fail` 会把「没验」报成「验出坏」，折进 `pass` 会把「没验」报成「过了」。
#:   本轮在 `docs/02` 的 §A.9.4 处留了同一段订正（`GRID_VERDICTS` 同步导出给测试用）。
_VERDICT: Final = {
    "PASS": "pass",
    "FAIL": "fail",
    "PARTIAL": "partial",
    "UNVERIFIED": "unverified",
    "NOT_AVAILABLE": "not_available",
}
GRID_VERDICTS: Final = frozenset({"pass", "fail", "unverified"})

_UNATTRIBUTED_KEY: Final = "unattributed_share"


def _rate(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _percentile(values: Sequence[float], q: float) -> float | None:
    """最近秩分位（rank = ceil(q·n)）。产物里没有现成的分位数 ⇒ 这一处是真算。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q * len(ordered))))
    return float(ordered[rank - 1])


def _records(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = run.get("records")
    return [r for r in raw if isinstance(r, Mapping)] if isinstance(raw, list) else []


def _terminal(rec: Mapping[str, Any]) -> str:
    """图终态。⚠️ 不用 `outcome`（那是审计口径）—— 谓词与 `eval/reporter.py:457-463` 同源。"""
    return str(rec.get("terminal_event") or rec.get("outcome") or "?")


def _total_latency_ms(rec: Mapping[str, Any]) -> float | None:
    raw = rec.get("latency_ms")
    if isinstance(raw, Mapping):
        value = raw.get("total")
        return float(value) if isinstance(value, (int, float)) else None
    return None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _refusal(run: Mapping[str, Any]) -> dict[str, Any]:
    """拒答两类错误分开统计。分母谓词逐字抄 `eval/reporter.py:1211-1220`。

    `reason_accuracy` 在产物里**没有计算处**：冻结集有 `refuse_reason`、记录里有
    `refusal_reason`，但两边取值集是否同一词表未核 ⇒ 不自签一条匹配规则，如实 `None`。
    """
    recs = _records(run)
    want = [r for r in recs if str(r.get("expected_behavior")) == "refuse"]
    answerable = [r for r in recs if str(r.get("expected_behavior")) == "execute"]
    return {
        "true_positive_rate": _rate(sum(1 for r in want if _terminal(r) == "refuse"), len(want)),
        "false_positive_rate": _rate(
            sum(1 for r in answerable if _terminal(r) == "refuse"), len(answerable)
        ),
        "reason_accuracy": None,
    }


def _clarify(run: Mapping[str, Any]) -> dict[str, Any]:
    """澄清触发率可算；**澄清后一次成功率与平均轮次在单轮批次上结构上不可测**。

    理由不是"忘了算"：`eval/reporter.py:1224-1235` 写明评测器只跑单轮、没有第二轮回路，
    拿单轮记录去判那一半等于把评测器的能力缺口记成被测系统的失败。
    """
    recs = _records(run)
    want = [r for r in recs if str(r.get("expected_behavior")) == "clarify"]
    return {
        "trigger_accuracy": _rate(sum(1 for r in want if _terminal(r) == "clarify"), len(want)),
        "post_clarify_accuracy": None,
        "avg_rounds": None,
    }


def _cost(run: Mapping[str, Any]) -> dict[str, Any]:
    summary = run.get("summary") or {}
    recs = _records(run)
    total = _num(summary.get("cost_cny_total"))
    cache_hit = sum(int((r.get("tokens") or {}).get("cache_hit") or 0) for r in recs)
    tokens = sum(int((r.get("tokens") or {}).get("total") or 0) for r in recs)
    return {
        "total_cny": total,
        "per_query_cny": round(total / len(recs), 6) if total is not None and recs else None,
        "cache_hit_rate": _rate(cache_hit, tokens),
    }


def _security(gate: Mapping[str, Any] | None) -> dict[str, Any]:
    if gate is None:
        return {"dangerous_sql_passed": None, "cross_tenant_leaks": None, "pii_leaks": None}
    red = gate.get("red_team") or {}
    cross = gate.get("cross_tenant") or {}
    return {
        "dangerous_sql_passed": red.get("leaked"),
        "cross_tenant_leaks": cross.get("leaked"),
        #: 红队产物只有断言计数（`assertion_counts`），没有「PII 泄露条数」这一格 ⇒ 未测。
        "pii_leaks": None,
    }


def _grid(gate: Mapping[str, Any] | None) -> dict[str, Any]:
    """产物 4×3 → 契约 4×3：标签对齐 ＋ 阈值与判词就地绑定 ⇒ 前端零计算。"""
    axes = {"struct": list(_STRUCT_CONTRACT), "semantic": list(_SEMANTIC)}
    if gate is None:
        return {"axes": axes, "cells": []}
    cells: list[dict[str, Any]] = []
    for row in (gate.get("grid") or {}).get("matrix") or []:
        for cell in row:
            artifact_struct = str(cell.get("struct"))
            if artifact_struct not in _STRUCT_ARTIFACT:
                continue
            struct = _STRUCT_CONTRACT[_STRUCT_ARTIFACT.index(artifact_struct)]
            semantic = str(cell.get("semantic"))
            if semantic not in _SEMANTIC:
                continue
            total = int(cell.get("total") or 0)
            if total <= 0:
                continue  # 缺失格不进 cells（模块 docstring 约束 2 的另一面）
            ex = float(cell.get("pass_rate") or 0.0)
            target = _TARGETS[struct][_SEMANTIC.index(semantic)]
            cells.append(
                {
                    "struct": struct,
                    "semantic": semantic,
                    "total": total,
                    "passed": int(cell.get("passed") or 0),
                    "ex": round(ex, 4),
                    "target": target,
                    "verdict": "unverified" if target is None else ("pass" if ex >= target else "fail"),
                }
            )
    return {"axes": axes, "cells": cells}


def _attribution(run: Mapping[str, Any], gate: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """归因分布，**按条数降序**返回（`docs/06:2275` 的横向条形图是把响应数组反着画的）。"""
    dist: Mapping[str, Any] = {}
    if gate is not None:
        split = (gate.get("attribution_split") or {}).get("distribution")
        dist = split or gate.get("attribution_distribution") or {}
    if not dist:
        counts: dict[str, int] = {}
        for rec in _records(run):
            attr = rec.get("attribution")
            if isinstance(attr, Mapping) and attr.get("category"):
                key = str(attr["category"])
                counts[key] = counts.get(key, 0) + 1
        dist = counts
    rows = sorted(((str(k), int(v)) for k, v in dist.items()), key=lambda kv: (-kv[1], kv[0]))
    total = sum(v for _, v in rows)
    return [{"category": k, "count": v, "ratio": _rate(v, total) or 0.0} for k, v in rows]


def _overall(run: Mapping[str, Any], gate: Mapping[str, Any] | None) -> dict[str, Any]:
    recs = _records(run)
    ex = (gate or {}).get("grid", {}).get("ex") if gate is not None else None
    if ex is None:
        summary = run.get("summary") or {}
        ex = _rate(int(summary.get("n_equivalent") or 0), int(summary.get("n_execute_scored") or 0))
    consistency = (gate or {}).get("metric_consistency_c43") or {}
    unattributed = ((gate or {}).get("grid") or {}).get(_UNATTRIBUTED_KEY)
    latencies = [v for v in (_total_latency_ms(r) for r in recs) if v is not None]
    return {
        "ex": round(float(ex), 4) if ex is not None else None,
        "refusal": _refusal(run),
        "clarify": _clarify(run),
        "consistency": {
            "rate": consistency.get("consistent_rate"),
            "attributable_rate": round(1.0 - float(unattributed), 4) if unattributed is not None else None,
        },
        "efficiency": {"seq_scan_rate": None, "cartesian_count": None, "p95_exec_ms": None},
        "security": _security(gate),
        "latency": {"p50_ms": _percentile(latencies, 0.50), "p95_ms": _percentile(latencies, 0.95)},
        "cost": _cost(run),
    }


def _gate_block(gate: Mapping[str, Any] | None) -> dict[str, Any]:
    if gate is None:
        return {"passed": None, "items": []}
    return {
        "passed": (gate.get("gate_summary") or {}).get("all_pass"),
        "items": [
            {
                "id": str(g.get("gate_id")),
                "name": str(g.get("condition")),
                "verdict": _VERDICT.get(str(g.get("verdict")), str(g.get("verdict")).lower()),
                "detail": str(g.get("measured") or "")[:400],
            }
            for g in gate.get("gates") or []
        ],
    }


def _unavailable(gate: Mapping[str, Any] | None, linked: bool, declared: str | None) -> list[dict[str, str]]:
    """页面上每一个 null 都必须在这里有一句解释（模块 docstring 约束 2）。

    `declared` = 在位那份门禁报告**自报的批次出处**（`meta.results_artifact.stem`）；
    `linked` = 那份报告是否配得上本批次。三者要分开判：配上了就没有这一行的必要，
    配不上要说清"配不上"，报告没自报出处要说清"没法配"。
    """
    rows = [
        {
            "field": "run.model／prompt_version／bundle_version",
            "reason": "批次产物未自报构建身份（与 T-11② 同根因；产物侧只有 git_rev／git_dirty，见 provenance）",
        },
        {
            "field": "run.started_at",
            "reason": "产物只有 `generated_at`（批次完成时刻），没有起跑时刻",
        },
        {
            "field": "overall.refusal.reason_accuracy",
            "reason": "冻结集 `refuse_reason` 与记录 `refusal_reason` 的取值集是否同一词表未核 ⇒ 不在此端点自签匹配规则",
        },
        {
            "field": "overall.clarify.post_clarify_accuracy／avg_rounds",
            "reason": "评测器只跑单轮、没有第二轮回路（`eval/reporter.py:1224-1235`）",
        },
        {
            "field": "overall.efficiency.seq_scan_rate／cartesian_count／p95_exec_ms",
            "reason": "记录里没有 exec 段耗时；沙箱无带代价的 EXPLAIN（`eval_metrics.json` 的 `gap_table` 第 1 行）⇒ 无计算处",
        },
        {
            "field": "overall.security.pii_leaks",
            "reason": "红队产物只有断言计数（`red_team.assertion_counts`），没有「PII 泄露条数」这一格",
        },
    ]
    if gate is None:
        rows.insert(
            0,
            {
                "field": "gate／grid／consistency／security",
                "reason": "没有门禁报告产物在位 ⇒ 门禁判定、4×3 网格与安全两组未算（不是 0）",
            },
        )
    elif not linked and declared is not None:
        rows.insert(
            0,
            {
                "field": "gate／grid／consistency／security",
                "reason": (
                    f"门禁报告在位，但它自报的批次出处是 `{declared}` ⇒ 本批次没有对应判定，"
                    "不拿别的批次数冒充（配对尺 = `meta.results_artifact.stem`）"
                ),
            },
        )
    elif not linked:
        rows.insert(
            0,
            {
                "field": "gate／grid",
                "reason": "门禁报告未自报批次出处（本轮之前的旧报告）⇒ 按配对纪律视为无对应报告",
            },
        )
    return rows


def _dataset_id(run: Mapping[str, Any]) -> str:
    version = str((run.get("frozen_evidence") or {}).get("dataset_version") or "unknown")
    return f"ds_v{version}_frozen"


def _read_set(name: str) -> Mapping[str, Any] | None:
    path = artifacts.runs_dir() / name
    return artifacts.read_json(path) if path.is_file() else None


def _dataset_rows() -> list[dict[str, Any]]:
    """评测集清单：主验收集 ＋ 红队集，逐字段只读冻结集文件自己的头部。"""
    rows: list[dict[str, Any]] = []
    main = _read_set("dataset_v1_frozen.json")
    if main is not None:
        rows.append(
            {
                "dataset_id": f"ds_v{main.get('dataset_version')}_frozen",
                "version": str(main.get("dataset_version")),
                "frozen_at": main.get("frozen_at"),
                "case_count": len(main.get("cases") or []),
                "content_hash": main.get("content_hash"),
                #: 标签逐字取自契约（`docs/02:852`），不是本文件自造的描述。
                "purpose": "主验收（双维度 4×3 分层）",
                "status": "frozen",
            }
        )
    red = _read_set("red_team_cases_v1.json")
    if red is not None:
        coverage = red.get("coverage") or {}
        rows.append(
            {
                "dataset_id": f"ds_v{red.get('dataset_version')}_red_team",
                "version": str(red.get("dataset_version")),
                "frozen_at": red.get("frozen_at"),
                "case_count": len(red.get("cases") or []),
                "content_hash": red.get("content_hash"),
                "purpose": (
                    f"红队安全集（覆盖 {len(coverage.get('ast_rules_covered') or [])}/"
                    f"{coverage.get('ast_rules_total')} 条 AST 规则）"
                ),
                "status": "frozen",
            }
        )
    return rows


def dataset_ids() -> list[str]:
    return [str(row["dataset_id"]) for row in _dataset_rows()]


def datasets() -> dict[str, Any]:
    items = _dataset_rows()
    return {"items": items, "total": len(items)}


def _linked_gate(run_id: str, gate: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """门禁报告只认它**自己声明**的那一批次：`meta.results_artifact.stem == run_id`。

    ⚠️ 不用 `dataset_content_hash` 配对：盘上现有 5 份批次产物用的是同一个冻结集，
    按哈希配会把一份报告的网格与判词冒充到另外 4 批上（那是造假，不是近似）。
    ⚠️ 也不用 `git_rev` 配对：报告里的 `meta.git.rev` 是**重算门禁那一刻**的提交，
    批次的 `git_rev` 是**跑评测那一刻**的提交，两者本来就该不同（第 9／10 轮实测同形）。
    报告没自报出处（`results_artifact` 缺 = 本轮之前生成的旧产物）⇒ 一律视为"无对应报告"，
    并在 `unavailable` 里说明，而不是退回去猜。
    """
    if gate is None:
        return None
    declared = str(((gate.get("meta") or {}).get("results_artifact") or {}).get("stem") or "")
    return gate if declared == run_id else None


def _gate_declared_stem(gate: Mapping[str, Any] | None) -> str | None:
    if gate is None:
        return None
    return str(((gate.get("meta") or {}).get("results_artifact") or {}).get("stem") or "") or None


def _headline(run: Mapping[str, Any], gate: Mapping[str, Any] | None) -> dict[str, Any]:
    overall = _overall(run, gate)
    return {
        "ex": overall["ex"],
        "refusal_true_positive_rate": overall["refusal"]["true_positive_rate"],
        "dangerous_sql_passed": overall["security"]["dangerous_sql_passed"],
        "cross_tenant_leaks": overall["security"]["cross_tenant_leaks"],
        "p95_latency_ms": overall["latency"]["p95_ms"],
        "cost_total_cny": overall["cost"]["total_cny"],
    }


def _status(run: Mapping[str, Any]) -> str:
    """产物在位 ⇒ 批次跑完了（`complete`）；没有 records ⇒ `failed`。

    `queued`／`running` 这两个状态**不会出现在本端点**：`POST /admin/eval/run`（A.9.1）
    仍是未落地面，这里只读已入库产物，所以也不伪造一个"运行中"的行。
    """
    return "complete" if _records(run) else "failed"


def runs(
    dataset_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    gate = artifacts.gate_report()
    items: list[dict[str, Any]] = []
    for run_id in artifacts.run_ids():
        run = artifacts.load_run(run_id)
        linked = _linked_gate(run_id, gate)
        items.append(
            {
                "run_id": run_id,
                "dataset_id": _dataset_id(run),
                "model": None,
                "prompt_version": None,
                "bundle_version": None,
                "status": _status(run),
                "gate_passed": (linked or {}).get("gate_summary", {}).get("all_pass"),
                "started_at": None,
                "ended_at": run.get("generated_at"),
                "headline": _headline(run, linked),
                "note": (run.get("config") or {}).get("provenance"),
            }
        )
    items.sort(key=lambda row: str(row["ended_at"] or ""), reverse=True)
    if dataset_id is not None:
        items = [row for row in items if row["dataset_id"] == dataset_id]
    if status is not None:
        items = [row for row in items if row["status"] == status]
    total = len(items)
    return {
        "items": items[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


def _struct_label(raw: Any) -> str:
    label = str(raw)
    return _STRUCT_CONTRACT[_STRUCT_ARTIFACT.index(label)] if label in _STRUCT_ARTIFACT else label


def _case_row(rec: Mapping[str, Any]) -> dict[str, Any]:
    """逐条用例投影。⚠️ 不含 `gold_sql`／`sql_text`（契约 `docs/02:1012` 明令不下发）。"""
    verdict = rec.get("verdict") or {}
    attr = rec.get("attribution") or {}
    return {
        "case_id": str(rec.get("case_id")),
        "question": str(rec.get("question") or ""),
        "difficulty_struct": _struct_label(rec.get("difficulty_struct")),
        "difficulty_semantic": str(rec.get("difficulty_semantic")),
        "expected_behavior": str(rec.get("expected_behavior")),
        "actual_behavior": _terminal(rec),
        "result_equivalent": bool(verdict.get("equivalent")),
        "attribution": str(attr.get("category")) if attr.get("category") else None,
        "latency_ms": _total_latency_ms(rec),
        "cost_cny": rec.get("cost_cny"),
    }


def run_detail(
    run_id: str,
    include_cases: bool,
    limit: int,
    offset: int,
    case_filter: str | None,
) -> dict[str, Any]:
    run = artifacts.load_run(run_id)
    gate = artifacts.gate_report()
    linked = _linked_gate(run_id, gate)
    #: 只有"报告在位但配不上本批次"时才把它的出处写进解释（配上就不算缺口）
    declared = None if linked is not None else _gate_declared_stem(gate)
    recs = _records(run)
    data: dict[str, Any] = {
        "run": {
            "run_id": run_id,
            "dataset_id": _dataset_id(run),
            "dataset_content_hash": (run.get("frozen_evidence") or {}).get("content_hash"),
            "model": None,
            "prompt_version": None,
            "bundle_version": None,
            "status": _status(run),
            "started_at": None,
            "ended_at": run.get("generated_at"),
        },
        #: 契约 §A.9.4 的强制约束（`docs/02:1020`）：跨租户视角必须显式标注。
        #: 冻结集本身跨 `T_A/T_B/T_C`（见 `consistency_17_6.eval_tenants`）⇒ 恒为 cross_tenant。
        "scope": "cross_tenant",
        "overall": _overall(run, linked),
        "grid": _grid(linked),
        "attribution": _attribution(run, linked),
        "gate": _gate_block(linked),
        #: 附加面（契约示例里没有这两个键，本轮在 `docs/02` §A.9.4 处留笔登记）：
        #: 产物出处 ＋ 每个 null 的解释。少了它们，这一页就又变成"看起来像实测"的散文。
        "provenance": {
            "artifact": f"{run_id}.json",
            "runs_dir": str(artifacts.runs_dir()),
            "gate_report": str(artifacts.gate_report_path()),
            "gate_report_linked": linked is not None,
            "gate_report_stem": _gate_declared_stem(gate),
            "batch_git_rev": run.get("git_rev"),
            "batch_git_dirty": run.get("git_dirty"),
            "eval_tenants": (linked or {}).get("consistency_17_6", {}).get("eval_tenants"),
            "rerun_in_endpoint": False,
        },
        "unavailable": _unavailable(gate, linked is not None, declared),
    }
    if include_cases:
        #: 契约默认 `case_filter` 缺省 = 全部用例；`failed` 才是"结果不等价"那一支。
        pool = (
            [r for r in recs if not (r.get("verdict") or {}).get("equivalent")]
            if case_filter == "failed"
            else recs
        )
        if case_filter == "failed":
            pool = [r for r in recs if not (r.get("verdict") or {}).get("equivalent")]
        rows = [_case_row(r) for r in pool]
        data["cases"] = {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < len(rows),
        }
    return data
