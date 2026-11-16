"""P5-3 实测报告生成器：U-185 三条口径纪律落码后的三批独立 live。

只读现存 u185_r2/r3/r4 结果件、冻结集与 `voting.py`，所有读数现取；
分母唯一来源 = 冻结集 `n_execute_cases`（95），unscored 计入分母但不计等价。
内建止损闸：任一单批 EX < 0.76 即停止推进，缺批照实写 UNVERIFIED。
不写「85% 达成」除非三批齐且单批全部 ≥85%。

端点口径：百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`，
模型 `deepseek-v4.1-flash`（FAST=STRONG），与 P3 r4/r5 同端点同模型；
key 经进程环境注入（仓库外 wrapper），不落盘。跨轮差值仍不作证据。

复算：``python eval/olist/build_report_u185.py``
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "eval"))

from voting import result_digest, vote_by_result

OUT_MD = ROOT / "report_u185.md"
OUT_JSON = ROOT / "report_u185.json"
PLANNED = [ROOT / f"results_v3_u185_r{i}.json" for i in (2, 3, 4)]
FROZEN = ROOT / "dataset_v3_frozen.json"
STOP_LINE = 0.76
TARGET = 0.85


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    present = [p for p in PLANNED if p.is_file()]
    missing = [p.name for p in PLANNED if not p.is_file()]
    if not present:
        raise SystemExit("NO BATCH RESULTS: " + ", ".join(p.name for p in PLANNED))

    denom = int(load(FROZEN)["n_execute_cases"])
    data = [load(p) for p in present]
    rows = []
    for p, d in zip(present, data, strict=True):
        s = d["summary"]
        eq = s["n_equivalent"]
        unscored = [r["case_id"] for r in d["records"]
                    if r.get("expected_behavior") == "execute" and not r.get("scored")]
        fails = [r["case_id"] for r in d["records"]
                 if r.get("expected_behavior") == "execute"
                 and not (r.get("verdict") or {}).get("equivalent")]
        gate_rejects = {r["case_id"]: r.get("gate1_reject_rule") for r in d["records"]
                        if r.get("terminal_event") == "error"}
        rows.append({
            "batch_id": d.get("batch_id"),
            "file": p.name,
            "denominator": denom,
            "n_execute_scored": s["n_execute_scored"],
            "n_unscored_execute": len(unscored),
            "unscored_cases": unscored,
            "n_equivalent": eq,
            "ex": round(eq / denom, 4),
            "failed_execute_cases": fails,
            "gate_rejects": gate_rejects,
            "usage": d.get("usage"),
            "budget_stop": d.get("budget_stop"),
            "git_rev": d.get("build", {}).get("git_rev"),
        })

    # 多路多数投票：结果件不存逐行表 ⇒ 用预测侧可观测字段（SQL/参数/终态）做摘要代理。
    # 与 `voting.py` 的选臂语义一致（选臂不看 gold），但不是执行结果集哈希。
    by_case: dict[str, list[dict[str, Any]]] = {}
    for d in data:
        for r in d["records"]:
            if r.get("expected_behavior") != "execute":
                continue
            v = r.get("verdict") or {}
            digest = result_digest({
                "sql": r.get("sql_text"),
                "params": r.get("sql_params"),
                "terminal": r.get("terminal_event"),
                "terminal_code": r.get("terminal_code"),
            })
            by_case.setdefault(r["case_id"], []).append({
                "digest": digest,
                "equivalent": bool(v.get("equivalent")),
            })
    vote_pass = 0
    oracle = 0
    vote_detail = []
    for cid, arms in sorted(by_case.items()):
        vote = vote_by_result(arms)
        w = vote["winner"]
        ok = bool(w is not None and arms[w]["equivalent"])
        vote_pass += int(ok)
        oracle += int(any(a["equivalent"] for a in arms))
        vote_detail.append({
            "case_id": cid, "n_arms": len(arms), "winner": w,
            "vote_size": vote["vote_size"], "vote_equivalent": ok,
        })
    n_cases = len(by_case)
    if n_cases != denom:
        raise SystemExit("VOTE DENOM DRIFT: " + str(n_cases) + " != " + str(denom))
    exs = [r["ex"] for r in rows]
    mean = statistics.mean(exs)
    stdev = statistics.stdev(exs) if len(exs) > 1 else 0.0
    stopped_by_gate = min(exs) < STOP_LINE
    budget_hard_stop = any(r["budget_stop"] is not None for r in rows)
    vote_ex = round(vote_pass / n_cases, 4)
    all_reached = (not missing) and all(e >= TARGET for e in exs)
    gap = 81 - round(mean * denom)

    if stopped_by_gate:
        gate_note = ("最低批次 EX = " + str(min(exs)) + " < " + str(STOP_LINE)
                     + " ⇒ 按内建闸停止推进，剩余批次**未跑、UNVERIFIED**；"
                     + "本轮不回滚口径、不放宽阈值、不重跑已完成批次，止损由读数自动判定。")
    else:
        gate_note = "未触发；缺批原因另记，不推定达标。"

    payload = {
        "schema": "U185_REPORT/v1",
        "builder": "eval/olist/build_report_u185.py",
        "recompute": "python eval/olist/build_report_u185.py",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "deepseek-v4.1-flash（FAST=STRONG，与 P3 r4/r5 同端点同模型）",
        "denominator": denom,
        "denominator_source": "eval/olist/dataset_v3_frozen.json::n_execute_cases（U-177 已裁定）",
        "unscored_policy": "unscored 的 execute 题计入分母但不计等价，不因 infra 失败缩分母",
        "planned_batches": len(PLANNED),
        "executed_batches": len(rows),
        "missing_batches": missing,
        "stop_line": STOP_LINE,
        "stopped_by_gate": stopped_by_gate,
        "budget_hard_stop": budget_hard_stop,
        "unverified_batches": missing,
        "batches": rows,
        "mean_ex": round(mean, 4),
        "stdev_ex": round(stdev, 4),
        "gap_to_81": gap,
        "majority_vote": {
            "n_cases": n_cases, "pass": vote_pass, "ex": vote_ex,
            "oracle_union": oracle, "n_arms": len(data),
            "note": ("计划 3 路、实际 " + str(len(data)) + " 路独立采样；投票在报告层，"
                     + "不改 prompt、不改图结构；摘要是预测侧 SQL/终态代理，非执行结果集哈希"
                     + ("；不足三路时并列取首臂退化为先批优先，不构成独立多数证据"
                        if len(data) < 3 else "")),
        },
        "cap_receipt": [
            {"batch_id": r["batch_id"], "calls": (r["usage"] or {}).get("calls"),
             "spent_cny": (r["usage"] or {}).get("cost_cny"),
             "stopped": r["budget_stop"] is not None} for r in rows
        ],
        "all_batches_at_least_85": all_reached,
        "verdict": (
            "计划 " + str(len(PLANNED)) + " 批、实测 " + str(len(rows)) + " 批；"
            + "已跑均值 " + str(round(mean, 4)) + " ± " + str(round(stdev, 4))
            + "；三批齐且单批全部 ≥85% = " + str(all_reached)
            + "；内建止损闸触发 = " + str(stopped_by_gate)
            + "；多路多数投票 " + str(vote_ex)
            + "。未达标与未跑批次照实写，不自创口径。"
        ),
        "vote_detail": vote_detail,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# P5-3 实测报告（U-185 / 2026-11-16）",
        "",
        ("分母：`eval/olist/dataset_v3_frozen.json` 的 `n_execute_cases` = **"
         + str(denom) + "** 条 `execute`（`U-177` 已裁定）；目标 81 题 = 85%。"),
        ("`unscored` 的 execute 题**计入分母但不计等价**；本轨不因 infra 失败缩分母。"),
        ("端点：百炼 `compatible-mode/v1` + 新 key（进程环境注入，不落盘）；模型 "
         + "`deepseek-v4.1-flash`（FAST=STRONG），与 P3 r4/r5 同端点同模型。"
         + "U-185 三条口径纪律（别名一致性 / 季度标签 YYYY-Qn / 指标时间基准列）已含于本批请求体。"),
        "",
        "## 批次完整性与内建止损闸",
        "",
        ("计划 3 批独立 live，实际 **" + str(len(rows)) + "** 批（"
         + "、".join("`" + str(r["batch_id"]) + "`" for r in rows) + "）；缺失 "
         + ("`" + "`、 `".join(missing) + "`" if missing else "无") + "。"),
        ("⚠️ 内建止损闸判定 = **" + str(stopped_by_gate) + "**（任一单批 EX < "
         + str(STOP_LINE) + " 即停止推进）。" + gate_note),
        ("预算硬停 `budget_stop` 触发 = **" + str(budget_hard_stop) + "**。"
         + "⚠️ 预算硬停（调用数/花费上限）与 EX 止损闸（准确率回滚线）是两件事，不得混记。"),
        "",
        "## 独立 live 批次",
        "",
        "| 批次 | 分母 | 计分 | 未计分 | 等价 | EX | calls | 花费(¥) | 硬停 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        u = r["usage"] or {}
        lines.append(
            "| `" + str(r["batch_id"]) + "` | " + str(r["denominator"]) + " | "
            + str(r["n_execute_scored"]) + " | " + str(r["n_unscored_execute"]) + " | "
            + str(r["n_equivalent"]) + " | " + str(r["ex"]) + " | "
            + str(u.get("calls")) + " | " + str(u.get("cost_cny")) + " | "
            + ("触发" if r["budget_stop"] is not None else "未触发") + " |"
        )
    lines += [
        "",
        ("已跑批次均值 `" + str(round(mean, 4)) + " ± " + str(round(stdev, 4)) + "`；"
         + "三批齐且单批全部 ≥85% = **" + str(all_reached) + "**。"),
    ]
    if all_reached:
        lines.append("三批齐且单批全部 ≥81/95 ⇒ **85% 达成**（按本轨判据）。")
    else:
        lines.append("按均值距 81 题仍差 **" + str(gap) + " 题/批**；85% 未达成，差距照实保留。")
    lines += [
        "",
        "**infra 未计分明细**（不是模型答错，但按口径计入分母）：",
        "",
    ]
    for r in rows:
        detail = ("、".join("`" + c + "`" for c in r["unscored_cases"])
                  if r["unscored_cases"] else "无")
        lines.append("- `" + str(r["batch_id"]) + "`：" + detail)
    lines += [
        "",
        "## 失败面（execute 未等价逐例）",
        "",
    ]
    for r in rows:
        lines.append("- `" + str(r["batch_id"]) + "`（" + str(len(r["failed_execute_cases"]))
                     + " 条）：" + "、".join("`" + c + "`" for c in r["failed_execute_cases"]))
        if r["gate_rejects"]:
            lines.append("  - 闸门拒绝：" + "、".join(
                "`" + c + "`=" + str(v) for c, v in sorted(r["gate_rejects"].items())))
    lines += [
        "",
        "## 多路多数投票（报告层，不改 prompt / 不改图）",
        "",
        ("- 计划 3 路独立采样，实际 **" + str(len(data)) + "** 路；"
         + "`eval/voting.py::vote_by_result` 按预测侧可观测字段（SQL/参数/终态）摘要多数选臂，"
         + "**选臂不看 gold**，并列取首臂。"),
        "- 该摘要是**代理**，不是执行结果集哈希；与 P2 反事实探针口径不完全等价。",
        ("- 投票读数 **" + str(vote_pass) + "/" + str(n_cases) + " = " + str(vote_ex)
         + "**；oracle 并集 " + str(oracle) + "（上界，非投票器读数）。"),
        "",
        "## 口径与边界",
        "",
        "- 未写「85% 达成」除非三批齐且单批全部 ≥85%；未跑批次一律 `UNVERIFIED`。",
        "- 不与 70.88% / 65.21% 做跨题集横比当回归证据；与 r4/r5 的跨轮差值亦不作证据（cross-run delta）。",
        "- 冻结集、gold、门禁阈值、判据措辞、旧证据件一字未动；新增件另起文件名。",
        ("- 已跑批次匣带在 `eval/olist/cassettes/`，按 `.gitignore:102` 排除、仅在本地，"
         + "不入库；结果件与报告入库，零成本回放复算需本地匣带在盘（仓库既有约定，非本轮引入）。"),
        ("- 复算：`python eval/olist/build_report_u185.py`；源件 "
         + " / ".join("`eval/olist/" + p.name + "`" for p in present) + "。"),
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("WROTE", OUT_MD.name, OUT_JSON.name)
    print("PLANNED", len(PLANNED), "EXECUTED", len(rows), "MISSING", missing)
    print("DENOM", denom, "BATCH_EX", exs, "MEAN", round(mean, 4), "STD", round(stdev, 4))
    print("STOP_GATE", stopped_by_gate, "BUDGET_STOP", budget_hard_stop, "ALL_GE_85", all_reached)
    print("VOTE", vote_pass, "/", n_cases, "=", vote_ex, "ORACLE", oracle, "GAP", gap)


if __name__ == "__main__":
    main()