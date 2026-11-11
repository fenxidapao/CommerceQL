"""few-shot 同源题排除的只读核验（P1）。

零网络、零 LLM、零 DB 连接：只比 seed 件的 `source_case_id` 与 v3 冻结集 case_id，
并核 B7 匣带里 SQL 生成提示词是否真的注入了示例。

输出 ``fewshot_leak_check.json``。复算：``python eval/olist/probe_u183_fewshot_leak.py``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OUT = ROOT / "fewshot_leak_check.json"


def main() -> None:
    seed = json.loads((REPO / "eval/gold_query_seed_v1.json").read_text(encoding="utf-8"))
    ds = json.loads((ROOT / "dataset_v3_frozen.json").read_text(encoding="utf-8"))
    seed_sources = {s["source_case_id"] for s in seed["seeds"]}
    v3_ids = {c["case_id"] for c in ds["cases"]}
    overlap = sorted(seed_sources & v3_ids)

    cassette_hits: list[dict[str, Any]] = []
    for i in (1, 2, 3):
        path = ROOT / f"cassettes/olist_v3_r{i}.jsonl"
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        gen = [r["request"]["messages"][0]["content"] for r in rows
               if "SQL 生成" in r["request"]["messages"][0]["content"][:80]]
        body = "".join(json.dumps(r, ensure_ascii=False) for r in rows)
        cassette_hits.append({
            "cassette": f"eval/olist/cassettes/olist_v3_r{i}.jsonl",
            "n_records": len(rows),
            "n_sqlgen_prompts": len(gen),
            "example_token_in_sqlgen_system": sum(s.count("示例") for s in gen),
            "few_shot_token_hits": body.lower().count("few_shot"),
        })

    payload = {
        "schema": "U183_FEWSHOT_LEAK_CHECK/v1",
        "probe": "eval/olist/probe_u183_fewshot_leak.py",
        "recompute": "python eval/olist/probe_u183_fewshot_leak.py",
        "seed": {"path": "eval/gold_query_seed_v1.json",
                 "n_seeds": len(seed["seeds"]),
                 "n_distinct_sources": len(seed_sources),
                 "warning": seed.get("warning")},
        "frozen_v3": {"path": "eval/olist/dataset_v3_frozen.json", "n_cases": len(v3_ids)},
        "n_overlap": len(overlap),
        "overlap_ids": overlap,
        "b7_cassettes": cassette_hits,
        "b7_fewshot_injected": any(h["example_token_in_sqlgen_system"] > 0 for h in cassette_hits),
        "verdict": (
            "B7 三批的 SQL 生成提示词里「示例」命中为 0 ⇒ 当时 few-shot 未生效，"
            "故 70.88% 不含示例增益、也不存在同源泄漏；"
            "seed 的 source_case_id 与 v3 冻结集交集为 " + str(len(overlap)) +
            "，但 P2 注入 few-shot 前仍须在 `_few_shots_for` 加同源题排除，"
            "否则换题集后会产生泄漏。"
        ),
        "prerequisite": {
            "item": "app.gold_query 真库行数与 Top-5 内容",
            "status": "NOT_VERIFIED",
            "why": "本探针零 DB 连接，不能拿 docs/10:40 的书面登记冒充实测",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name, "n_seeds", len(seed["seeds"]),
          "overlap", len(overlap), "b7_injected", payload["b7_fewshot_injected"])
    for h in cassette_hits:
        print(" ", h["cassette"], h["example_token_in_sqlgen_system"], h["few_shot_token_hits"])


if __name__ == "__main__":
    main()
