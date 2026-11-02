#!/usr/bin/env python
"""B0 基线（30 题）：只给物理表/列 schema，一次 `gen_sql` 调用，不经语义层/闸门/结果校验。

对齐 `计划_合并版.md §3.2 第 5 条` / `§5.4`：

- 30 题子集：从 60 题冻结集的 55 道 execute 中按 4×3 难度格**分层**选 30（确定性）；
- schema：只从 bundle 的 `assets[].columns` 导出物理表 + 列，**不含**指标表达式、
  维度、同义词、join 路径；
- 模型：与 v1 B3 同一端点/模型/温度（官方 `deepseek-flash`，`temperature=0.0`），
  一次调用，不经过 19 节点图、三闸门、结果级校验；
- 判分：与 B3 同一条 `equivalence.compare_tables` + 同一 SQLite 沙箱/租户边界；
- 预算：`--max-cost-cny` / `--max-calls` 硬闸；超过 20% 用例上游失败即停。

⚠️ 本脚本**只**写 `eval/olist/b0_*`；不碰 `dataset_v1_frozen.json` / `report.md` /
`results_v*.json`。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
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

import equivalence as eq  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.llm import LlmCallContext, build_gateway, set_call_context  # noqa: E402
from app.planner.payloads import DIALECT_NOTE  # noqa: E402
from app.planner.schemas import GenSqlResult, output_schema_for  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from eval import runner  # noqa: E402
from eval.olist.build_dataset import FrozenWriteError, guard_output_path  # noqa: E402
from eval.olist.run_olist import load_cases  # noqa: E402

DEFAULT_N = 30
#: B0 不经过闸门，模型可能写出笛卡尔积（实测 o24 >5 分钟未返回）；单条 SQL 的执行上限。
SQL_TIMEOUT_S = 20.0
B0_NOTE = (
    "B0 基线：本题没有查询计划、没有指标口径、没有同义词/join 路径，只有上面的物理表与列。"
    "请直接依据列名和用户问题生成 SQL；无法确定口径时在 blocking_issues 里说明。"
)


def select_cases(spec: dict[str, Any], n: int = DEFAULT_N) -> list[dict[str, Any]]:
    """按 `(difficulty_struct, difficulty_semantic)` 分层选 n 道 execute 题（确定性）。"""
    execute = [
        c for c in spec["cases"] if str(c.get("expected_behavior") or "execute") == "execute"
    ]
    if n >= len(execute):
        return sorted(execute, key=lambda c: str(c["case_id"]))
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in execute:
        cells[(str(case.get("difficulty_struct")), str(case.get("difficulty_semantic")))].append(case)
    for bucket in cells.values():
        bucket.sort(key=lambda c: str(c["case_id"]))
    total = len(execute)
    quotas: dict[tuple[str, str], int] = {}
    remainders: list[tuple[float, tuple[str, str]]] = []
    for key, bucket in cells.items():
        exact = len(bucket) * n / total
        quotas[key] = min(len(bucket), int(exact))
        remainders.append((exact - int(exact), key))
    while sum(quotas.values()) < n:
        progressed = False
        for _, key in sorted(remainders, key=lambda item: (-item[0], item[1])):
            if quotas[key] < len(cells[key]):
                quotas[key] += 1
                progressed = True
                if sum(quotas.values()) == n:
                    break
        if not progressed:
            break
    picked: list[dict[str, Any]] = []
    for key in sorted(cells):
        picked.extend(cells[key][: quotas[key]])
    picked.sort(key=lambda c: str(c["case_id"]))
    if len(picked) != n:
        raise RuntimeError(f"分层选择失败：期望 {n}，实得 {len(picked)}")
    return picked


def build_raw_schema(loaded: Any) -> str:
    """只从 bundle 的 assets/columns 导物理 schema；不含指标/维度/同义词/join。"""
    lines = ["## 物理表与列（只有这些；不含指标口径/维度/同义词/join）"]
    active = set(getattr(loaded, "active_assets", ()) or ())
    for asset in sorted(loaded.bundle.assets, key=lambda a: str(a.logical_name)):
        if active and asset.logical_name not in active:
            continue
        desc = str(getattr(asset, "description", "") or "").strip()
        lines.append(f"- `{asset.physical_asset}`  {desc}")
        for column in getattr(asset, "columns", ()) or ():
            name = str(getattr(column, "name", ""))
            if not name or name == "tenant_id" or getattr(column, "sensitive", None):
                continue
            ctype = str(getattr(column, "type", "") or "")
            comment = str(getattr(column, "comment", "") or "").strip()
            lines.append(f"    - {name} {ctype}：{comment}")
    return "\n".join(lines)


def parse_response(text: str) -> GenSqlResult:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return GenSqlResult.model_validate_json(raw)


def _summarize(records: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    n = len(records)
    equivalent = sum(1 for r in records if r.get("equivalent") is True)
    return {
        "n": n,
        "n_equivalent": equivalent,
        "ex": (equivalent / n) if n else None,
        "n_blocked": sum(1 for r in records if r.get("terminal") == "blocked"),
        "n_error": sum(1 for r in records if r.get("terminal") == "error"),
        "n_gold_error": sum(1 for r in records if r.get("terminal") == "gold_error"),
        "calls": sum(1 for r in records if r.get("call_ok")),
        "tokens_total": sum(int((r.get("tokens") or {}).get("total") or 0) for r in records),
        "cost_cny_total": round(sum(float(r.get("cost_cny") or 0) for r in records), 6),
        **extra,
    }


def score_sql(
    case: dict[str, Any],
    sql: str | None,
    params: dict[str, Any] | None,
    *,
    tenant_scoped: dict[str, str],
    db_path: Path,
) -> dict[str, Any]:
    """B0 的判分：与 B3 同一条 `run_in_sandbox` + `compare_tables`。"""
    tenant = str(case.get("eval_tenant") or "T_A")
    if not sql:
        return {"terminal": "blocked"}
    gold = runner.run_in_sandbox(
        str(case["gold_sql"]),
        None,
        tenant=tenant,
        views=True,
        db_path=str(db_path),
        tenant_scoped_physicals=tenant_scoped,
        timeout_s=SQL_TIMEOUT_S,
    )
    if gold.get("error"):
        return {"terminal": "gold_error", "gold_error": gold["error"]}
    pred = runner.run_in_sandbox(
        sql,
        params,
        tenant=tenant,
        views=True,
        db_path=str(db_path),
        tenant_scoped_physicals=tenant_scoped,
        timeout_s=SQL_TIMEOUT_S,
    )
    verdict = eq.compare_tables(
        gold["table"],
        pred["table"],
        gold_sql=str(case["gold_sql"]),
        pred_sql=sql,
        hash_matches=None,
    )
    return {
        "terminal": "complete",
        "exec_error": pred.get("error"),
        "equivalent": verdict.equivalent,
        "verdict": {
            "equivalent": verdict.equivalent,
            "tags": list(verdict.tags),
            "diffs": list(verdict.diffs),
            "unmatched": verdict.unmatched,
        },
    }


async def run_batch(
    *,
    cases: list[dict[str, Any]],
    loaded: Any,
    db_path: Path,
    max_cost_cny: float,
    max_calls: int,
    batch_id: str,
    checkpoint: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = Settings()
    gateway = build_gateway(settings)
    tenant_scoped = {
        a.physical_asset: "tenant_id"
        for a in loaded.bundle.assets
        if a.tenant_scoped and a.logical_name in loaded.active_assets
    }
    raw_schema = build_raw_schema(loaded)
    records: list[dict[str, Any]] = []
    cost = 0.0
    calls = 0
    errors = 0
    budget_stop = False
    aborted_on_errors = False
    try:
        for idx, case in enumerate(cases, start=1):
            if cost >= max_cost_cny or calls >= max_calls:
                budget_stop = True
                break
            if errors >= max(1, math.ceil(len(cases) * 0.2)) and idx > 10:
                aborted_on_errors = True
                break
            case_id = str(case["case_id"])
            tenant = str(case.get("eval_tenant") or "T_A")
            set_call_context(
                LlmCallContext(task_id=f"b0-{batch_id}-{case_id}", tenant_id=tenant, user_id="b0")
            )
            payload = {
                "raw_question": str(case["question"]),
                "semantic_summary": raw_schema,
                "dialect_note": DIALECT_NOTE,
                "output_schema": output_schema_for("gen_sql"),
                "bundle_version": str(loaded.bundle.meta.version),
                "constraints": B0_NOTE,
            }
            record: dict[str, Any] = {
                "case_id": case_id,
                "question": case["question"],
                "tenant": tenant,
                "gold_sql": case.get("gold_sql"),
                "batch_id": batch_id,
                "call_ok": False,
                "terminal": "error",
                "tokens": {},
                "cost_cny": 0.0,
            }
            started = time.monotonic()
            try:
                response = await gateway.call("gen_sql", payload)
                calls += 1
                cost += float(response.cost_cny)
                record.update(
                    call_ok=True,
                    model=response.model,
                    prompt_version=response.prompt_version,
                    tokens={
                        "input": response.tokens.input,
                        "output": response.tokens.output,
                        "cache_hit": response.tokens.cache_hit,
                        "total": response.tokens.input + response.tokens.output,
                    },
                    cost_cny=float(response.cost_cny),
                )
                result = parse_response(response.text)
                record["blocking_issues"] = list(result.blocking_issues)
                if not result.candidates:
                    record["terminal"] = "blocked"
                    continue
                candidate = result.candidates[0]
                record.update(
                    sql_text=candidate.sql_text,
                    params=dict(candidate.params),
                    rationale=candidate.rationale,
                    confidence=candidate.confidence,
                )
                record.update(
                    score_sql(
                        case,
                        candidate.sql_text,
                        dict(candidate.params),
                        tenant_scoped=tenant_scoped,
                        db_path=db_path,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 单题失败必须落记录，不打断整批
                errors += 1
                record["terminal"] = "error"
                record["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                record["latency_ms"] = int((time.monotonic() - started) * 1000)
                records.append(record)
                if checkpoint is not None:
                    checkpoint.write_text(
                        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            print(
                f"[{idx}/{len(cases)}] {case_id} {record['terminal']} "
                f"eq={record.get('equivalent')} cost=¥{cost:.6f}",
                flush=True,
            )
    finally:
        await gateway.aclose()
    summary = _summarize(
        records,
        batch_id=batch_id,
        model=settings.LLM_MODEL_FAST,
        bundle_version=str(loaded.bundle.meta.version),
        budget={"max_cost_cny": max_cost_cny, "max_calls": max_calls},
        budget_stop=budget_stop,
        aborted_on_errors=aborted_on_errors,
        errors=errors,
        generated_at=datetime.now(UTC).isoformat(),
    )
    return records, summary


def _render_report(
    *, selection: list[dict[str, Any]], b0: dict[str, Any], b3: dict[str, Any]
) -> str:
    s = b0["summary"]
    lines = [
        "# B0 基线（30 题）— W2 补齐",
        "",
        "> 定义 = `计划_合并版.md §3.2 第 5 条`：30 题、只有物理 schema、一次 `gen_sql` 调用，",
        "> 不经语义层/三闸门/结果级校验；同模型/温度（官方 `deepseek-flash`，T=0.0）。",
        "",
        "## 1. 选样",
        "",
        f"- 30 题按 4×3 难度格分层，确定性选取；id：`{', '.join(c['case_id'] for c in selection)}`",
        f"- 模型：`{s['model']}`；bundle：`{s['bundle_version']}`；calls={s['calls']}；"
        f"tokens={s['tokens_total']}；cost=¥{s['cost_cny_total']:.6f}",
        "",
        "## 2. B0 读数",
        "",
        "| 指标 | 读数 |",
        "|---|---|",
        f"| n | {s['n']} |",
        f"| equivalent | {s['n_equivalent']} |",
        f"| EX (B0, 30 题) | {s['ex']:.4f} |" if s["ex"] is not None else "| EX | UNVERIFIED |",
        f"| blocked / error / gold_error | {s['n_blocked']} / {s['n_error']} / {s['n_gold_error']} |",
        f"| budget_stop / aborted_on_errors | {s['budget_stop']} / {s['aborted_on_errors']} |",
        "",
        "## 3. 同 30 题的 B3 对照",
        "",
        "| 批次 | 等价 | 分母 | EX |",
        "|---|---|---|---|",
    ]
    for row in b3["rows"]:
        lines.append(f"| {row['batch_id']} | {row['passed']} | {row['total']} | {row['ex']:.4f} |")
    lines += [
        "",
        f"- B3（v1，官方 `deepseek-flash`）同 30 题均值：**{b3['mean']:.4f} ± {b3['std']:.4f}**（n=3）",
        f"- B0 与 B3 的差：**{s['ex'] - b3['mean']:+.4f}**（B0 − B3；正值=B0 更好）",
        "",
        "> B0 是**故意做弱**的基线：没有指标口径/维度/同义词/join，模型只能按列名猜；",
        "> 因此 B0 低于 B3 是预期方向，不能反过来当模型能力结论。",
        "> B3 取 v1 三批（与 B0 同端点/模型/数据集/bundle/判据）；v2 三批走百炼，"
        "且 gold/bundle 已按 U-151/U-152 升版，不能与 B0 直接比。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B0 30 题基线（W2 补齐）")
    parser.add_argument("--dataset", default=str(OLIST_DIR / "dataset_v1_frozen.json"))
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "olist" / "olist_sandbox.db"))
    parser.add_argument("--bundle", default=str(REPO_ROOT / "semantic" / "bundle_olist_2018.yaml"))
    parser.add_argument("--out", default=str(OLIST_DIR / "b0_30_results.json"))
    parser.add_argument("--report", default=str(OLIST_DIR / "b0_30_report.md"))
    parser.add_argument("--batch-id", default="b0_30")
    parser.add_argument("--max-cost-cny", type=float, default=1.0)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true", help="用 gold SQL 替身验证执行/判分链路（零 LLM）")
    args = parser.parse_args(argv)

    try:
        out = guard_output_path(args.out)
        report_path = guard_output_path(args.report)
    except FrozenWriteError as exc:
        print(f"拒绝写入：{exc}", file=sys.stderr)
        return 2

    spec = load_cases(args.dataset)
    selection = select_cases(spec, DEFAULT_N)
    loaded = load_bundle(args.bundle)
    raw_schema = build_raw_schema(loaded)
    print(
        f"B0 选样 {len(selection)} 题；schema {len(raw_schema)} chars；"
        f"bundle={loaded.bundle.meta.version}"
    )
    if args.dry_run:
        print(raw_schema)
        print("ids=", ",".join(str(c["case_id"]) for c in selection))
        return 0

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"沙箱不存在：{db_path}", file=sys.stderr)
        return 3

    if args.selftest:
        tenant_scoped = {
            a.physical_asset: "tenant_id"
            for a in loaded.bundle.assets
            if a.tenant_scoped and a.logical_name in loaded.active_assets
        }
        records = [
            {
                "case_id": c["case_id"],
                "terminal": "selftest",
                **score_sql(
                    c, str(c["gold_sql"]), None,
                    tenant_scoped=tenant_scoped, db_path=db_path,
                ),
            }
            for c in selection
        ]
        summary = _summarize(records, batch_id="b0_selftest")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["n_equivalent"] == len(selection) else 4

    checkpoint = OLIST_DIR / "b0_30_partial.json"
    records, summary = asyncio.run(
        run_batch(
            cases=selection,
            loaded=loaded,
            db_path=db_path,
            max_cost_cny=args.max_cost_cny,
            max_calls=args.max_calls,
            batch_id=args.batch_id,
            checkpoint=checkpoint,
        )
    )

    ids = {str(c["case_id"]) for c in selection}
    b3_rows: list[dict[str, Any]] = []
    for idx in (1, 2, 3):
        path = OLIST_DIR / f"results_v1_r{idx}.json"
        batch = json.loads(path.read_text(encoding="utf-8"))
        chosen = [
            r for r in batch["records"]
            if str(r["case_id"]) in ids and r.get("scored")
        ]
        passed = sum(1 for r in chosen if (r.get("verdict") or {}).get("equivalent") is True)
        total = len(chosen)
        batch_id = (
            (batch.get("config") or {}).get("batch_id")
            or batch.get("batch_id")
            or f"v1_r{idx}"
        )
        b3_rows.append(
            {
                "batch_id": str(batch_id),
                "passed": passed,
                "total": total,
                "ex": passed / total if total else 0.0,
            }
        )
    import statistics

    exs = [row["ex"] for row in b3_rows]
    b3 = {
        "rows": b3_rows,
        "mean": statistics.fmean(exs),
        "std": statistics.stdev(exs),
    }
    payload = {
        "schema": "B0_30/v1",
        "selection": [str(c["case_id"]) for c in selection],
        "dataset": str(args.dataset),
        "db": str(db_path),
        "bundle": str(args.bundle),
        "summary": summary,
        "b3_same_30": b3,
        "records": records,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_report(selection=selection, b0=payload, b3=b3), encoding="utf-8")
    checkpoint.unlink(missing_ok=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[out] {out}\n[report] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
