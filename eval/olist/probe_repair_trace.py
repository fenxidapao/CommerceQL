#!/usr/bin/env python
"""repair 回路复算探针（T-04，零 LLM／零出站／只读输入）。

对象：`eval/olist/report_olist.py:477` 的 `repair` 列。
问题：该列现读 `repair = sum(1 for r in batch if r.get("second_round"))`
—— 数的是 **`second_round`（G-8 澄清补答）**，不是图内 `repair` 节点。
所以「三批 0/60」只证明没开 `--second-round`，不能证明修复回路没跑过。

本探针改用已落盘的 `nodes` 字段（每条记录的节点执行序列）直接数 `repair`
出现次数，并单列 `repair_round` / `repair_history` 的落盘率（当前 480 条全
null = 无落盘通道 ⇒ 轮次与「是否改对」不可复算）。

⚠️ 只读：不写结果件、不写账本；`--out` 只写本探针自己的 JSON。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

OLIST_DIR = Path(__file__).resolve().parent
NODE = "repair"


def load_records(path: Path) -> list[dict[str, Any]]:
    """results 件有两种形状（list / dict 里挂 records 或 results），都认。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = (
        data if isinstance(data, list) else data.get("records") or data.get("results") or []
    )
    return [record for record in records if isinstance(record, dict)]


def node_sequence(record: dict[str, Any]) -> list[str]:
    nodes = record.get("nodes")
    return [str(node) for node in nodes] if isinstance(nodes, list) else []


def survey(tag: str, paths: list[Path]) -> dict[str, Any]:
    n = repaired = second_round = 0
    rounds: Counter[int] = Counter()
    terminal_of_repaired: Counter[str] = Counter()
    landing: Counter[str] = Counter()
    case_ids: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        for record in load_records(path):
            n += 1
            seq = node_sequence(record)
            hits = sum(1 for node in seq if node == NODE)
            if hits:
                repaired += 1
                rounds[hits] += 1
                terminal_of_repaired[str(record.get("terminal_code"))] += 1
                case_ids.append(str(record.get("case_id")))
            if record.get("second_round"):
                second_round += 1
            landing["repair_round_present"] += int(record.get("repair_round") is not None)
            landing["repair_history_present"] += int(record.get("repair_history") is not None)
    return {
        "tag": tag,
        "n_records": n,
        "second_round_nonnull": second_round,
        "repair_nodes_seen": repaired,
        "repair_rounds_histogram": {str(k): v for k, v in sorted(rounds.items())},
        "terminal_of_repaired": dict(terminal_of_repaired),
        "repaired_case_ids": case_ids,
        "landing": dict(landing),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="repair 回路复算探针（零 LLM）")
    parser.add_argument("--batches", type=int, nargs="+", default=[1, 2, 3], help="批次号")
    parser.add_argument("--out", type=Path, default=OLIST_DIR / "probe_repair_trace.json")
    args = parser.parse_args(argv)

    groups = {
        "v3": [OLIST_DIR / f"results_v3_r{idx}.json" for idx in args.batches],
        "v2": [OLIST_DIR / f"results_v2_r{idx}.json" for idx in args.batches],
    }
    result = {
        "schema": "T04_REPAIR_TRACE_PROBE/v1",
        "criterion": "图内 repair 节点按已落盘的 nodes 序列计数（不是 second_round）",
        "report_caliber": "eval/olist/report_olist.py:477 现读数 second_round ⇒ 与图内 repair 无关",
        "groups": [survey(tag, paths) for tag, paths in groups.items()],
    }
    for row in result["groups"]:
        print(
            f"{row['tag']}: n={row['n_records']} repair节点={row['repair_nodes_seen']} "
            f"轮次分布={row['repair_rounds_histogram']} "
            f"second_round非空={row['second_round_nonnull']} "
            f"repair_round落盘={row['landing'].get('repair_round_present', 0)}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
