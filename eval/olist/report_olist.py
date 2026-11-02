#!/usr/bin/env python
"""Olist 60 题报告（W2，`U-144`）：离线证据 ＋ 3 批 `EX_official`。

两件事必须分开，否则读数会互相冒充
--------------------------------
1. **`EX_official`** 只来自 `eval/grid.py::build_grid`：分母 = 有机器难度标签且 `scored`
   的 execute 题；交互题（`difficulty_struct is None`）不进分母。
2. **交互正确** 的判据是运行时终态，不是 `verdict.equivalent`：
   `terminal_event == expected_behavior and infra_error is None`（与 `runner.py` 同一条）。
   `verdict` 对交互题恒 `None` ⇒ 用 `passed` 推会永远得到 0/5。

源模式（`gold.frozen_hash is None`）下 `wrap_eq_frozen` / `hash_matches` 是构造性的
`False`（`"x" == None`），本报告一律渲染 `n/a (source mode)`，不得报成"金标不一致"。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OLIST_DIR = Path(__file__).resolve().parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from eval.grid import build_grid  # noqa: E402
from eval.olist import run_olist as R  # noqa: E402
from eval.olist.build_dataset import FrozenWriteError, guard_output_path, write_json  # noqa: E402
from eval.olist.hashing import case_full_hash  # noqa: E402

FIXED_LINES = (
    "EX_official = {passed} / scored_total = {pct}%",
    "分母构成：scored={scored} | struct_null_skipped={skipped} | execute={execute} | "
    "with_sql={with_sql} | with_result={with_result} | equivalent={equivalent}",
    "交互正确（不计入 EX）：refuse {refuse_ok}/2 ｜ clarify {clarify_ok}/3",
    "沙箱方言缺口（单列，不是模型错）：{dialect_gap}",
    "若报 EX_exec（非官方，仅 coverage）：{ex_exec}/55",
)


def interaction_correct(record: Mapping[str, Any]) -> bool:
    """运行时交互正确：终态等于期望行为，且没有基础设施错误。**不读 `passed`。**"""
    return (
        record.get("terminal_event") == record.get("expected_behavior")
        and record.get("infra_error") is None
    )


#: 沙箱是 SQLite、闸门一按 postgres 解析：这些函数在闸门 R14 就被拒，
#: 走不到执行层，故 `attribution` 不会给出 `sandbox_dialect_gap`。报告层单列。
_POSTGRES_ONLY_TOKENS = (
    "to_char(", "date_trunc(", "::timestamp", "::date", "::numeric",
    "interval ", "extract(",
)


def is_sandbox_dialect_gap(record: Mapping[str, Any]) -> bool:
    """方言缺口：归因已标，或闸门 R14 拒了 postgres 专有函数/转换。"""
    if (record.get("attribution") or {}).get("category") == "sandbox_dialect_gap":
        return True
    if str(record.get("gate1_reject_rule") or "") != "R14":
        return False
    sql = str(record.get("sql_text") or "").lower()
    return any(token in sql for token in _POSTGRES_ONLY_TOKENS)


#: v2 三类修复 + R14 的分桶标签。**唯一真相在这里** —— `backend/reports/exv2/diagnosis.md`
#: 的读数与报告正文都用这一个函数，不另写第二份口径。
BUCKET_LABELS: tuple[str, ...] = ("as_order", "round", "delivery", "r14")


def case_buckets(
    case: Mapping[str, Any], record: Mapping[str, Any]
) -> frozenset[str]:
    """把一个 case 归到 v2 的三类修复桶 + R14 桶（**可同时命中多个桶**，调用方自行去重）。

    · `as_order`：`terminal_code == SQL_SYNTAX_ERROR`。v1 实测这 7 条**全部**是
      「订单表别名写成保留字 `order`」（从匣带复原模型 SQL 逐条验证，见
      `backend/reports/exv2/diagnosis.md` §2）；判据只认终态码，不猜错误文本
      （v1 记录里 `sql_text` 为 `None`、`terminal_error_detail` 为空，猜不了）。
    · `round`：gold SQL 含 `ROUND(` **且**判不等价 —— 差异形状是"金标舍入、模型未舍入"。
    · `delivery`：`metrics` 含 `delivery_late_rate` **且**判不等价（与 `round` 相交，不重复计总数）。
    · `r14`：`gate1_reject_rule == "R14"`（方言缺口，本窗不修、单列）。

    `as_order` / `r14` 是**前置独占**桶（两者互斥且不再计入 `round`/`delivery`），因为这类题
    根本没走到值比较；否则 R14 的 12 条会把 `round` 桶虚增一倍（v1 r1：13 → 26）。
    """
    terminal = str(record.get("terminal_code") or "")
    rule = str(record.get("gate1_reject_rule") or "")
    # **前置优先级**：`as_order` / `r14` 先行独占 —— 这两类题根本走不到"值比较"，
    # 若同时计入 `round` 会把它们重复算进"舍入口径"的账上（v1 r1 会从 13 虚增到 26）。
    if terminal == "SQL_SYNTAX_ERROR":
        return frozenset({"as_order"})
    if rule == "R14":
        return frozenset({"r14"})
    buckets: set[str] = set()
    equivalent = (record.get("verdict") or {}).get("equivalent")
    gold_sql = str((record.get("gold") or {}).get("gold_sql") or "")
    if "ROUND(" in gold_sql.upper() and equivalent is False:
        buckets.add("round")
    metrics = record.get("metrics") or case.get("metrics") or []
    if "delivery_late_rate" in metrics and equivalent is False:
        buckets.add("delivery")
    return frozenset(buckets)


def bucket_counts(
    cases: Iterable[Mapping[str, Any]], records: Iterable[Mapping[str, Any]]
) -> dict[str, int]:
    """逐桶计数（一个 case 可计入多桶；`round` 与 `delivery` 有交集，勿相加当总数）。"""
    by_id = {str(case.get("case_id")): case for case in cases}
    counts = dict.fromkeys(BUCKET_LABELS, 0)
    for record in records:
        for name in case_buckets(by_id.get(str(record.get("case_id")), {}), record):
            counts[name] += 1
    return counts


#: v2（三类非模型修复已落）专属的「已知偏差」条目。默认路径**不渲染**这些行 ——
#: 它们只在给了 `--baseline-results`（= 出 v2 报告）时替换掉 v1 的偏差陈述。
_V2_BULLETS: tuple[str, ...] = (
    "- **`AS order` 保留字（`U-150`）**：v1 的 `SQL_SYNTAX_ERROR` 已归零，逐批现算见 §6；"
    "规则写进 `gen_sql_v1` / `gen_sql_complex_v1` / `repair_v1` 三份 **SQL 侧**提示词，"
    "共用 `DIALECT_NOTE` 一字未动（它被 **10** 个模板注入，含 8 个非 SQL 模板）。",
    "- **gold 去 `ROUND`（`U-151`）**：两侧都按原始精度比较；`REL_TOL=1e-6`、排序口径与判据措辞"
    "**均未改**。反向风险同框：模型若自己舍入，同样是 1e-5 级相对差而判不等。",
    "- **`delivery_late_rate` ×100（`U-152`）**：语义包 `2026.10.31.1` 的表达式前置 `100.0 *`，"
    "一并消掉 SQLite 整数除法归零；v1 的 bundle 与冻结件**一字未改**。",
    "- **R14 / 方言缺口 12 条**：三批一致（见 §6），本窗未修、单列、**不归因模型**。",
    "- **端点与模型**：v2 = `deepseek-v4.1-flash` @ 阿里云百炼；v1 = `deepseek-flash` @ 官方 "
    "`api.deepseek.com`。按总控 2026-10-31 裁定**合并成一次读数**，端点差异在此留一句、不拆两套。",
    "- **匣带**：提示词变更使 v1 匣带**预期 miss**（key = `sha256(path + canonical body)`），"
    "不重录、不补录、不花钱；属预期失效，不是回归退化。",
    "- **预算上限是累计值**：`--max-cost-cny` / `--max-calls` 比的是 `prior + 本批`"
    "（`eval/runner.py::_breached`），**不是每批上限**。",
    "- **三类桶的 0 ≠ 「三类都修干净了」**：`as_order`/`delivery` 的 0 是实测，"
    "`round` 的 0 **部分是桶定义使然**（v2 的 gold 已无 `ROUND`）；逐例转换数与仍未等价的 "
    "`o38`（时间基准差，不是舍入）见 §6.1。",
)


def _mean_std(values: list[float]) -> str:
    if not values:
        return "UNVERIFIED"
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else None
    return f"{mean:.4f} ± " + (f"{std:.4f}" if std is not None else "n/a") + f"（n={len(values)}）"


def _bucket_row(
    cases: Iterable[Mapping[str, Any]], batch_records: list[list[dict[str, Any]]], name: str
) -> str:
    return " / ".join(str(bucket_counts(cases, batch)[name]) for batch in batch_records)


def _flip_section(
    cases: Iterable[Mapping[str, Any]],
    base_records: list[list[dict[str, Any]]],
    records: list[list[dict[str, Any]]],
) -> list[str]:
    """逐例对撞：v1 的「桶内失败」在 v2 里变成了什么。**全部现算，不写死任何条次**。

    注意两条口径：交互题 `verdict` 恒 `None` ⇒ 天然不进"失败"计数（`c03` 只出现在
    `as_order` 桶的 60 题口径里，不进 EX 分母比对）；`r14` 桶不参与逐例（本窗不修）。
    """
    by_id = {str(c.get("case_id")): c for c in cases}
    lines = [
        "| 批次位 | v1 桶内失败 | → 等价 | 仍失败 | 非桶失败→等价 | 回归（v1 等价、v2 失败） |",
        "|---|---|---|---|---|---|",
    ]
    per_bucket: dict[str, list[int]] = {name: [0, 0, 0] for name in BUCKET_LABELS}
    tot = {"fail": 0, "conv": 0, "still": 0, "extra": 0, "regress": 0}
    for idx, (base, now) in enumerate(zip(base_records, records), start=1):
        v1 = {str(r["case_id"]): r for r in base}
        v2 = {str(r["case_id"]): r for r in now}
        conv = still = extra = regress = 0
        still_ids: list[str] = []
        regress_ids: list[str] = []
        for cid, r1 in v1.items():
            bset = case_buckets(by_id.get(cid, {}), r1) - {"r14"}
            was_neq = (r1.get("verdict") or {}).get("equivalent") is False
            now_neq = (v2.get(cid, {}).get("verdict") or {}).get("equivalent") is False
            if bset and was_neq:
                for name in bset:
                    per_bucket[name][0] += 1
                    per_bucket[name][1 if not now_neq else 2] += 1
            if bset and was_neq and not now_neq:
                conv += 1
            elif bset and was_neq and now_neq:
                still += 1
                still_ids.append(cid)
            elif not bset and was_neq and not now_neq:
                extra += 1
            elif not was_neq and now_neq:
                regress += 1
                regress_ids.append(cid)
        lines.append(
            f"| r{idx} | {conv + still} | {conv} | {still}"
            + (f"（{'、'.join(f'`{x}`' for x in still_ids)}）" if still_ids else "")
            + f" | {extra} | {regress}"
            + (f"（{'、'.join(f'`{x}`' for x in regress_ids)}）" if regress_ids else "")
            + " |"
        )
        tot["fail"] += conv + still
        tot["conv"] += conv
        tot["still"] += still
        tot["extra"] += extra
        tot["regress"] += regress
    lines.append(
        f"| **合计** | **{tot['fail']}** | **{tot['conv']}** | **{tot['still']}** | "
        f"**{tot['extra']}** | **{tot['regress']}** |"
    )
    lines += [
        "",
        "按桶拆（同一批内一个 case 可同时计入 `round` 与 `delivery`，**勿相加当总数**）：",
        "",
        "| 桶 | v1 失败条次 | → 等价 | 仍失败 |",
        "|---|---|---|---|",
    ]
    for name in BUCKET_LABELS:
        if name == "r14":
            continue
        total, conv, still = per_bucket[name]
        lines.append(f"| `{name}` | {total} | {conv} | {still} |")
    return lines


def _v2_sections(
    *,
    cases: list[dict[str, Any]],
    stats: list[dict[str, Any]],
    batch_ids: list[str],
    records: list[list[dict[str, Any]]],
    baseline: Mapping[str, Any],
    note: str | None,
) -> list[str]:
    """§5 的 v2 专属条目 + §6 的 v1→v2 对比。**只在给了 baseline 时调用**。"""
    out: list[str] = list(_V2_BULLETS)
    if note:
        out.append(f"- {note}")

    base_stats: list[dict[str, Any]] = list(baseline.get("stats") or [])
    base_records: list[list[dict[str, Any]]] = list(baseline.get("records") or [])
    base_label = str(baseline.get("label") or "v1")
    ex_now = [float(s["ex"]) for s in stats]
    ex_base = [float(s["ex"]) for s in base_stats]

    out += [
        "",
        "## 6. v1 → v2 对比（按总控 2026-10-31 裁定：合并成一次读数）",
        "",
        "| 指标 | " + base_label + " | v2（本报告） |",
        "|---|---|---|",
        f"| `EX_official` | {_mean_std(ex_base)} | {_mean_std(ex_now)} |",
        "| 每批 EX | " + " / ".join(f"{v:.4f}" for v in ex_base) + " | "
        + " / ".join(f"{v:.4f}" for v in ex_now) + " |",
        "| scored 分母 | " + " / ".join(str(s["scored_total"]) for s in base_stats) + " | "
        + " / ".join(str(s["scored_total"]) for s in stats) + " |",
        "| 交互 refuse | " + " / ".join(
            f"{s['refuse_correct']}/{s['refuse_total']}" for s in base_stats
        ) + " | " + " / ".join(f"{s['refuse_correct']}/{s['refuse_total']}" for s in stats) + " |",
        "| 交互 clarify | " + " / ".join(
            f"{s['clarify_correct']}/{s['clarify_total']}" for s in base_stats
        ) + " | " + " / ".join(f"{s['clarify_correct']}/{s['clarify_total']}" for s in stats) + " |",
        "| 方言缺口（单列） | " + " / ".join(
            str(s["sandbox_dialect_gap"]) for s in base_stats
        ) + " | " + " / ".join(str(s["sandbox_dialect_gap"]) for s in stats) + " |",
    ]

    if records and base_records:
        for name, text in (
            ("as_order", "`SQL_SYNTAX_ERROR`（60 题口径，含 `c03` clarify；EX 分母内 6/5/5）"),
            ("round", "`round` 桶（gold 含 `ROUND` 且不等价）"),
            ("delivery", "`delivery_late_rate` 桶（含于 `round`）"),
            ("r14", "R14 / 方言缺口桶（本窗不修）"),
        ):
            out.append(
                f"| {text} | {_bucket_row(cases, base_records, name)} | "
                f"{_bucket_row(cases, records, name)} |"
            )
        out += [
            "",
            "> 桶口径 = `eval/olist/report_olist.py::case_buckets`（唯一真相，"
            "`backend/reports/exv2/diagnosis.md` 的读数由同一函数现算）；"
            "`delivery` 含于 `round`，**两张表不可相加当非等价总数**。",
            "",
            "### 6.1 逐例转换（同一 case、同一批次位；桶标签取 **v1** 侧）",
            "",
        ]
        out += _flip_section(cases, base_records, records)
        out += [
            "",
            "> ⚠️ **三类桶的 0 证据强度不同**：`as_order` 的 0 = 无 `SQL_SYNTAX_ERROR`（实测）；"
            "`delivery` 的 0 = ×100 后判等（实测）；`round` 的 0 **部分是定义使然**"
            "（v2 的 gold 已无 `ROUND`，桶自然为空），真正能说的是上表的「逐例转换」数，"
            "而仍未等价的那条是**时间基准差**（`o38`：金标按 `review_creation_date` 过滤，"
            "模型按 `order_purchase_timestamp`），不是舍入差。",
            "> 因此 **`+31.26pp` 是净观测差，不能整笔记在 3 类修复账上**：端点/模型也换了"
            "（v2 百炼 `deepseek-v4.1-flash`、v1 官方 `deepseek-flash`），端点效应未拆分。",
        ]
        unscored_flips: list[str] = []
        for idx, (base, now) in enumerate(zip(base_records, records), start=1):
            now_map = {str(r["case_id"]): r for r in now}
            for r1 in base:
                cid = str(r1["case_id"])
                if not r1.get("scored") and now_map.get(cid, {}).get("scored"):
                    unscored_flips.append(f"`{cid}`（r{idx}）")
        if unscored_flips:
            out.append(
                f"> 分母变化来源：{'、'.join(unscored_flips)} 在 v1 记 `unscored`、v2 记 `scored`"
                " ⇒ 该批分子分母可能**同 +1**，别把它当成「多对了一道」。"
            )

    out += [
        "",
        f"> 批次：v2 = {batch_ids}；{base_label} = {list(baseline.get('batch_ids') or [])}。",
        "",
    ]
    return out


def _results_map(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for record in records:
        verdict = record.get("verdict") or {}
        mapping[str(record["case_id"])] = {
            "scored": bool(record.get("scored")),
            "passed": bool(verdict.get("equivalent")) if isinstance(verdict, dict) else False,
            "category": (record.get("attribution") or {}).get("category") or "unattributed",
        }
    return mapping


def _count(records: Iterable[Mapping[str, Any]], field: str) -> int:
    return sum(1 for record in records if record.get(field))


def batch_stats(cases: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    grid = build_grid(cases, _results_map(records))
    execute = [r for r in records if r.get("expected_behavior") == "execute"]
    clarify = [r for r in records if r.get("expected_behavior") == "clarify"]
    refuse = [r for r in records if r.get("expected_behavior") == "refuse"]
    with_result = [
        r for r in execute
        if r.get("predicted") and (r.get("predicted") or {}).get("sandbox_error") is None
    ]
    return {
        "scored_total": grid.scored_total,
        "scored_passed": grid.scored_passed,
        "ex": grid.ex,
        "struct_null_skipped": sum(
            1 for c in cases
            if c.get("difficulty_struct") is None or c.get("difficulty_semantic") is None
        ),
        "n_execute": len(execute),
        "with_sql": _count(execute, "sql_text"),
        "with_result": len(with_result),
        "equivalent": grid.scored_passed,
        "ex_exec": (grid.scored_passed / len(execute)) if execute else None,
        "n_unscored": sum(1 for r in records if not r.get("scored")),
        "n_false_clarify": sum(1 for r in execute if r.get("terminal_event") == "clarify"),
        "n_false_refuse": sum(1 for r in execute if r.get("terminal_event") == "refuse"),
        "sandbox_dialect_gap": sum(1 for r in records if is_sandbox_dialect_gap(r)),
        "clarify_correct": sum(1 for r in clarify if interaction_correct(r)),
        "clarify_total": len(clarify),
        "refuse_correct": sum(1 for r in refuse if interaction_correct(r)),
        "refuse_total": len(refuse),
        "matrix": grid.matrix(),
        "attribution": dict(grid.attribution),
    }


def _dataset_hashes(dataset_path: Path) -> tuple[str, str]:
    import build_frozen_set as bfs

    raw = R.load_cases(dataset_path)
    return bfs.case_content_hash(raw["cases"]), case_full_hash(raw["cases"])


def validate_batches(
    batches: list[dict[str, Any]], cases: list[dict[str, Any]],
    content_hash: str, full_hash: str,
) -> list[dict[str, Any]]:
    """校验批次身份与证据链；返回逐批 stats。任一不成立即拒绝出 EX。"""
    if not batches:
        return []
    ids = [
        str((b.get("config") or {}).get("batch_id") or b.get("batch_id") or "")
        for b in batches
    ]
    if any(not batch_id for batch_id in ids):
        raise ValueError(f"批次缺 config.batch_id：{ids}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"批次 batch_id 重复：{ids}")

    all_ids = {str(c["case_id"]) for c in cases}
    stats: list[dict[str, Any]] = []
    for batch in batches:
        evidence = batch.get("frozen_evidence") or {}
        if evidence.get("content_hash") != content_hash:
            raise ValueError(
                f"批次 {(batch.get('config') or {}).get('batch_id') or batch.get('batch_id')} "
                "的 content_hash 与数据集不一致"
            )
        if evidence.get("full_hash") != full_hash:
            raise ValueError(
                f"批次 {(batch.get('config') or {}).get('batch_id') or batch.get('batch_id')} "
                "的 full_hash 与数据集不一致"
            )
        records = list(batch.get("records") or [])
        record_ids = {str(r.get("case_id")) for r in records}
        if record_ids != all_ids:
            missing = sorted(all_ids - record_ids)
            extra = sorted(record_ids - all_ids)
            raise ValueError(
                f"批次 {(batch.get('config') or {}).get('batch_id') or batch.get('batch_id')} "
                "用例不完整："
                f"missing={missing} extra={extra}（冒烟批不得当 EX 用）"
            )
        stats.append(batch_stats(cases, records))
    return stats


def _fmt_ex(ex: float | None) -> str:
    return "UNVERIFIED" if ex is None else f"{ex:.4f}"


def _fixed_lines(values: Mapping[str, Any]) -> list[str]:
    return [line.format(**values) for line in FIXED_LINES]


def render_markdown(
    *,
    dataset_path: Path,
    mode: str,
    cases: list[dict[str, Any]],
    gold: dict[str, Any] | None,
    control: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    stats: list[dict[str, Any]],
    batch_ids: list[str],
    title: str = "Olist 60 题评测报告（W2）",
    records: list[list[dict[str, Any]]] | None = None,
    baseline: dict[str, Any] | None = None,
    note: str | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"> 数据集：`{dataset_path.as_posix()}` ｜ 模式：{mode} ｜ "
        + ("offline · 未跑 live" if not stats else "3 个独立批次（各自进程 + 各自 --batch-id）"),
        "",
        "## 1. 结论（固定五行）",
        "",
        "```",
    ]
    if not stats:
        lines += _fixed_lines({
            "passed": "UNVERIFIED",
            "pct": "UNVERIFIED",
            "scored": "UNVERIFIED",
            "skipped": sum(1 for c in cases if c.get("difficulty_struct") is None),
            "execute": sum(
                1 for c in cases
                if (c.get("expected_behavior") or "execute") == "execute"
            ),
            "with_sql": "UNVERIFIED",
            "with_result": "UNVERIFIED",
            "equivalent": "UNVERIFIED",
            "refuse_ok": "UNVERIFIED",
            "clarify_ok": "UNVERIFIED",
            "dialect_gap": "UNVERIFIED",
            "ex_exec": "UNVERIFIED",
        })
    else:
        mean_ex = statistics.fmean(s["ex"] for s in stats)
        std_ex = statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
        first = stats[0]
        lines += _fixed_lines({
            "passed": first["scored_passed"],
            "pct": f"{first['ex'] * 100:.2f}",
            "scored": first["scored_total"],
            "skipped": first["struct_null_skipped"],
            "execute": first["n_execute"],
            "with_sql": first["with_sql"],
            "with_result": first["with_result"],
            "equivalent": first["equivalent"],
            "refuse_ok": first["refuse_correct"],
            "clarify_ok": first["clarify_correct"],
            "dialect_gap": first["sandbox_dialect_gap"],
            "ex_exec": first["equivalent"],
        })
    lines += ["```", ""]
    if stats:
        mean_ex = statistics.fmean(s["ex"] for s in stats)
        std_ex = statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
        lines += [
            f"`EX_official` = {mean_ex:.4f} ± "
            + (f"{std_ex:.4f}" if std_ex is not None else "n/a")
            + f"（3 批均值 ± 样本标准差，n={len(stats)}；batch_id={batch_ids}）",
            "",
            "> 固定五行中的 `EX_official` / 分母构成 / 交互正确取**第一批**的逐例读数；"
            "跨批汇总以本行的均值±样本标准差为准（μ 与 σ 不可混批）。",
        ]

    lines += [
        "",
        "## 2. 分母构成",
        "",
        "| batch_id | scored | passed | EX | struct_null_skipped | execute | with_sql | "
        "with_result | equivalent | n_unscored | false_clarify | false_refuse | dialect_gap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for batch_id, stat in zip(batch_ids, stats, strict=True):
        lines.append(
            f"| {batch_id} | {stat['scored_total']} | {stat['scored_passed']} | "
            f"{_fmt_ex(stat['ex'])} | {stat['struct_null_skipped']} | {stat['n_execute']} | "
            f"{stat['with_sql']} | {stat['with_result']} | {stat['equivalent']} | "
            f"{stat['n_unscored']} | {stat['n_false_clarify']} | {stat['n_false_refuse']} | "
            f"{stat['sandbox_dialect_gap']} |"
        )
    if not stats:
        lines.append(
            "| — | UNVERIFIED | UNVERIFIED | UNVERIFIED | 5 | 55 | UNVERIFIED | UNVERIFIED | "
            "UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |"
        )

    cell_counts: dict[tuple[str, str], int] = {}
    for case in cases:
        if (case.get("expected_behavior") or "execute") != "execute":
            continue
        key = (str(case.get("difficulty_struct")), str(case.get("difficulty_semantic")))
        cell_counts[key] = cell_counts.get(key, 0) + 1
    lines += [
        "",
        "### 4×3 网格（数据集现算，execute 题）",
        "",
        "| struct \\ semantic | low | medium | high |",
        "|---|---|---|---|",
    ]
    for level in ("easy", "medium", "hard", "extra"):
        lines.append(
            f"| {level} | "
            + " | ".join(str(cell_counts.get((level, sem), 0)) for sem in ("low", "medium", "high"))
            + " |"
        )
    lines.append(
        "| **合计** | "
        + " | ".join(
            str(sum(cell_counts.get((level, sem), 0) for level in ("easy", "medium", "hard", "extra")))
            for sem in ("low", "medium", "high")
        )
        + " |"
    )

    lines += [
        "",
        "## 3. 交互正确（运行时判据，不计入 EX）",
        "",
        "判据 = `terminal_event == expected_behavior and infra_error is None`；"
        "**不读 `verdict.equivalent`**（交互题 verdict 恒 None）。",
        "",
    ]
    if stats:
        lines.append(
            "| batch_id | refuse | clarify |\n|---|---|---|\n"
            + "\n".join(
                f"| {batch_id} | {s['refuse_correct']}/{s['refuse_total']} | "
                f"{s['clarify_correct']}/{s['clarify_total']} |"
                for batch_id, s in zip(batch_ids, stats, strict=True)
            )
        )
    else:
        lines.append("refuse `UNVERIFIED`/2 ｜ clarify `UNVERIFIED`/3（未跑 live）")

    lines += [
        "",
        "## 4. 金标与口径（离线证据）",
        "",
    ]
    if gold:
        lines += [
            f"- n_cases / n_execute / n_interaction = {gold.get('n_cases')} / "
            f"{gold.get('n_execute_cases')} / {gold.get('n_interaction_cases')}",
            f"- gold_executable = {gold.get('gold_executable')}/"
            f"{gold.get('n_execute_cases')}；caliber_match = {gold.get('caliber_match')}/"
            f"{gold.get('n_execute_cases')}；interaction_valid = "
            f"{gold.get('interaction_valid')}/{gold.get('n_interaction_cases')}",
            f"- content_hash = `{gold.get('content_hash')}`",
            f"- full_hash = `{gold.get('full_hash')}`",
            f"- sandbox_db_sha256 = `{gold.get('sandbox_db_sha256')}`",
            "- `wrap_eq_frozen` / `hash_matches`：`n/a (source mode)`"
            "（源 YAML 无 `gold_result_hash`；构造性 False 不是不一致）"
            if mode == "stamped" else
            "- `wrap_eq_frozen` / `hash_matches`：按冻结件逐例校验",
        ]
    else:
        lines.append("- 未提供 `--gold`：金标侧读数 `UNVERIFIED`。")

    if profile:
        checks = profile.get("checks") or {}
        lines += [
            "",
            "### N-13（Olist profile）",
            "",
            f"- mode = {profile.get('mode')}；all_ok = **{checks.get('all_ok')}**",
            "- dataset_content_hash = "
            f"`{(checks.get('dataset_content_hash') or {}).get('ok')}`；dataset_full_hash = "
            f"`{(checks.get('dataset_full_hash') or {}).get('ok')}`；sandbox_db_sha256 = "
            f"`{(checks.get('sandbox_db_sha256') or {}).get('ok')}`",
        ]

    if control:
        pos = control.get("positive") or {}
        neg = control.get("negative") or {}
        lines += [
            "",
            "### 仪器正/负控（不是模型 EX）",
            "",
            f"- positive = {pos.get('scored_passed')}/{pos.get('scored_total')}；"
            f"negative = {neg.get('scored_passed')}/{neg.get('scored_total')}；"
            f"not_ex_official = {control.get('not_ex_official')}",
            "- 负控用**同列名、同行数**的扰动值，确保走值比较分支（空表会走列数早退）。",
        ]

    lines += [
        "",
        "## 5. 已知偏差",
        "",
        "- 无 `ordered` / `percent_ok`：排序只在两侧 SQL 都含 ORDER BY 时按序比；"
        "容差固定 `REL_TOL=1e-6`。",
        "- `ast_gate` 是 postgres 方言、沙箱是 SQLite ⇒ 预期出现 `sandbox_dialect_gap`，"
        "单列、不归因模型。",
        "- Olist 数据实际止于 2018-08（9 月 1 单、10 月 0 单）。",
        "- `gold_executable` 的分母是 55 条 execute；交互题无 gold，不冒充可执行 SQL。",
    ]
    if baseline is None:
        # 默认路径（v1 报告）：以下 6 条是**当时的实测陈述**，一字不动 ——
        # `docs/portfolio/README.md` 的复算命令要求与 `eval/olist/report.md` 逐字节一致。
        lines += [
            "- 模型把表别名写成 `AS order`（SQL 保留字）⇒ 本轮 7/55 条 `SQL_SYNTAX_ERROR`；"
            "这是生成缺陷，不是方言缺口。",
            "- gold 做了 `ROUND`、模型常未做 ⇒ `REL_TOL=1e-6` 判不等（AOV/评分/延迟率多例）；"
            "本轮不改判据，W3 裁定是去 gold 的 ROUND 还是把舍入写进 bundle/prompt。",
            "- `delivery_late_rate` 的 bundle expression 未乘 100，模型照 expression 生成 ⇒ "
            "SQLite 整数除法归零；这是 bundle 与 gold 口径不一致，不归因模型。",
            "- 批次 r1 有 1 条 `GraphRecursionError`（o19）记 `unscored`，"
            "故该批分母 54；其余两批分母 55。",
            "- 零出站回放复核（r1 匣带）：59/60 逐例一致；o19 的 `GraphRecursionError` "
            "**不复现**（回放记 `scored` 但仍不等值）⇒ 回放批 23/55、首发 23/54。"
            "官方 EX 仍取首发三批，回放件 `results_v1_r1_replay.json` 只作复核证据。",
            "",
        ]
    else:
        lines += _v2_sections(
            cases=cases,
            stats=stats,
            batch_ids=batch_ids,
            records=records or [],
            baseline=baseline,
            note=note,
        )
    return "\n".join(lines)


def _load_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 60 题报告（offline / 3 批 EX）")
    parser.add_argument("--dataset", default=str(OLIST_DIR / "dataset_v1.yaml"))
    parser.add_argument("--results", nargs="*", default=[])
    parser.add_argument("--profile", default=None)
    parser.add_argument("--gold", default=None)
    parser.add_argument("--control", default=None)
    parser.add_argument("--out", default=str(OLIST_DIR / "report.md"))
    parser.add_argument("--json-out", default=str(OLIST_DIR / "report.json"))
    # --- v2 支持（全部可选）：不给这 4 个参数时，输出与 v1 报告**逐字节一致** ---
    parser.add_argument(
        "--title", default="Olist 60 题评测报告（W2）", help="一级标题（v2 报告用）"
    )
    parser.add_argument(
        "--baseline-results", nargs="*", default=[],
        help="对照组（v1）的批次结果；给了才渲染 §6 对比、才替换 §5 的 v1 偏差陈述",
    )
    parser.add_argument(
        "--baseline-dataset", default=None, help="对照组数据集（仅用于报告头脚注，可省）"
    )
    parser.add_argument("--note", default=None, help="追加到 §5 的一条自由备注")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print(f"数据集不存在：{dataset_path}", file=sys.stderr)
        return 3

    try:
        out = guard_output_path(args.out)
        json_out = guard_output_path(args.json_out)
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2

    spec = R.load_annotated_cases(dataset_path)
    cases = spec["cases"]
    content_hash, full_hash = _dataset_hashes(dataset_path)
    mode = "frozen" if dataset_path.suffix.lower() == ".json" else "stamped"

    gold = _load_json(Path(args.gold)) if args.gold else None
    control = _load_json(Path(args.control)) if args.control else None
    profile = _load_json(Path(args.profile)) if args.profile else None

    batches = [_load_json(Path(p)) for p in args.results]
    try:
        stats = validate_batches(batches, cases, content_hash, full_hash)
    except ValueError as exc:
        print(f"批次校验失败：{exc}", file=sys.stderr)
        return 3
    batch_ids = [
        str((b.get("config") or {}).get("batch_id") or b.get("batch_id"))
        for b in batches
    ]

    # 对照组（v1）：**不走** `validate_batches` —— 那会用当前数据集（v2）的两个 hash
    # 去校验 v1 批次，必然不一致；对照组的合法性由它自己的报告承担。
    baseline: dict[str, Any] | None = None
    if args.baseline_results:
        base_batches = [_load_json(Path(p)) for p in args.baseline_results]
        baseline = {
            "label": "v1",
            "stats": [batch_stats(cases, b["records"]) for b in base_batches],
            "records": [b["records"] for b in base_batches],
            "batch_ids": [
                str((b.get("config") or {}).get("batch_id") or b.get("batch_id"))
                for b in base_batches
            ],
        }

    markdown = render_markdown(
        dataset_path=dataset_path, mode=mode, cases=cases, gold=gold,
        control=control, profile=profile, stats=stats, batch_ids=batch_ids,
        title=args.title,
        records=[b["records"] for b in batches],
        baseline=baseline,
        note=args.note,
    )
    out.write_text(markdown, encoding="utf-8", newline="\n")

    payload = {
        "mode": "offline" if not stats else "batches",
        "dataset": dataset_path.as_posix(),
        "content_hash": content_hash,
        "full_hash": full_hash,
        "batch_ids": batch_ids,
        "batches": stats,
        "ex_official": (
            None if not stats else {
                "mean": statistics.fmean(s["ex"] for s in stats),
                "std": (
                    statistics.stdev(s["ex"] for s in stats) if len(stats) > 1 else None
                ),
                "n": len(stats),
            }
        ),
        "interaction_judge": "terminal_event == expected_behavior and infra_error is None",
        "fixed_lines": _fixed_lines({
            "passed": (stats[0]["scored_passed"] if stats else "UNVERIFIED"),
            "pct": (f"{stats[0]['ex'] * 100:.2f}" if stats else "UNVERIFIED"),
            "scored": (stats[0]["scored_total"] if stats else "UNVERIFIED"),
            "skipped": (stats[0]["struct_null_skipped"] if stats else
                        sum(1 for c in cases if c.get("difficulty_struct") is None)),
            "execute": (stats[0]["n_execute"] if stats else
                        sum(1 for c in cases if (c.get("expected_behavior") or "execute") == "execute")),
            "with_sql": (stats[0]["with_sql"] if stats else "UNVERIFIED"),
            "with_result": (stats[0]["with_result"] if stats else "UNVERIFIED"),
            "equivalent": (stats[0]["equivalent"] if stats else "UNVERIFIED"),
            "refuse_ok": (stats[0]["refuse_correct"] if stats else "UNVERIFIED"),
            "clarify_ok": (stats[0]["clarify_correct"] if stats else "UNVERIFIED"),
            "dialect_gap": (stats[0]["sandbox_dialect_gap"] if stats else "UNVERIFIED"),
            "ex_exec": (stats[0]["equivalent"] if stats else "UNVERIFIED"),
        }),
        "evidence": {
            "gold": {
                "path": str(args.gold) if args.gold else None,
                "n_cases": (gold or {}).get("n_cases"),
                "gold_executable": (gold or {}).get("gold_executable"),
                "caliber_match": (gold or {}).get("caliber_match"),
                "interaction_valid": (gold or {}).get("interaction_valid"),
            },
            "control": {
                "path": str(args.control) if args.control else None,
                "all_ok": (control or {}).get("all_ok"),
                "not_ex_official": (control or {}).get("not_ex_official"),
            },
            "profile": {
                "path": str(args.profile) if args.profile else None,
                "all_ok": ((profile or {}).get("checks") or {}).get("all_ok"),
            },
        },
    }
    write_json(json_out, payload, indent=2)
    print(f"[out] {out.relative_to(REPO_ROOT).as_posix()}")
    print(f"[json] {json_out.relative_to(REPO_ROOT).as_posix()}")
    if stats:
        print(f"EX_official = {payload['ex_official']['mean']:.4f} ± "
              f"{payload['ex_official']['std']:.4f} (n={len(stats)})")
    else:
        print("EX_official = UNVERIFIED（offline，未跑 live）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
