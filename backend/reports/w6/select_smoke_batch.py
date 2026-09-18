"""W6 真 LLM 冒烟批的**取题**（确定性、可复算、不挑简单题）。

为什么要有这个脚本（而不是手敲 20 个 case_id）：
    D1 裁定「约 20 条真 LLM 冒烟」，其余标 UNVERIFIED。若这 20 条是我手挑的，
    那么报告里的 EX / 拒答率 / 澄清率就是**选题偏置**的读数 —— 而 §C.6.1 纪律一
    要的是"批次构成写清楚、可复算"。所以取样规则必须落在代码里：

    1. 按 `expected_behavior` 配额（execute 12 / refuse 5 / clarify 3）——
       refuse 与 clarify 是**必须保底**的：G-5 的分子分母是"应拒答题"，
       G-8 的前半句是"澄清率"，一个纯 execute 批次会让这两条永远 NOT_AVAILABLE
       （上一轮 5 条批次正是这个形状）。
    2. execute 内部再按 `difficulty_struct` 分层，**每层至少 1 条**
       （G-2 的判据点是 easy×low 格，缺样本就只能判 NOT_AVAILABLE）。
    3. 层内用 `sha1(SEED:case_id)` 排序取前 k 条 —— 固定种子 ⇒ 任何人复跑得到同一组，
       且**与题目难易无关**，做不到"挑简单的打"。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/select_smoke_batch.py
产物：同目录 `smoke_batch_ids.json`，并把逗号分隔的 case_id 打到 stdout（喂 `--cases`）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

#: 换种子 = 换批次 = 报告里的百分比不可比，所以它必须写死并留在产物里。
SEED = "w6-smoke-20260918"
QUOTA = {"execute": 12, "refuse": 5, "clarify": 3}


def _rank(case_id: str) -> str:
    return hashlib.sha1(f"{SEED}:{case_id}".encode()).hexdigest()


def pick(cases: list[dict]) -> list[dict]:
    """按 (behavior, struct) 分层，**轮转**取题：每层先各拿 1 条，再回到第一层拿第 2 条。

    轮转而不是"先分层再随机"的理由：配额 < 层数时它仍然覆盖到每一层（G-2 的 easy×low
    不会因为随机落空而变成 NOT_AVAILABLE），配额 > 层数时它自动均匀铺开。
    """
    out: list[dict] = []
    for behavior, quota in QUOTA.items():
        pool = [c for c in cases if str(c.get("expected_behavior")) == behavior]
        strata = {
            name: sorted(rows, key=lambda c: _rank(str(c["case_id"])))
            for name, rows in _group(pool).items()
        }
        target = min(quota, len(pool))
        chosen: list[dict] = []
        idx = 0
        while len(chosen) < target:
            before = len(chosen)
            for name in sorted(strata):
                rows = strata[name]
                if idx < len(rows):
                    chosen.append(rows[idx])
                    if len(chosen) >= target:
                        break
            if len(chosen) == before:  # 每层都取空了
                break
            idx += 1
        out.extend(chosen[:quota])
    return sorted(out, key=lambda c: str(c["case_id"]))


def _group(pool: list[dict]) -> dict[str, list[dict]]:
    strata: dict[str, list[dict]] = {}
    for c in pool:
        strata.setdefault(str(c.get("difficulty_struct")), []).append(c)
    return strata


def main() -> int:
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = list(dataset["cases"])
    chosen = pick(cases)
    by_behavior: dict[str, int] = {}
    by_cell: dict[str, int] = {}
    for c in chosen:
        b = str(c["expected_behavior"])
        by_behavior[b] = by_behavior.get(b, 0) + 1
        cell = f"{b}/{c.get('difficulty_struct')}/{c.get('difficulty_semantic')}"
        by_cell[cell] = by_cell.get(cell, 0) + 1

    payload = {
        "seed": SEED,
        "rule": (
            "按 expected_behavior 配额（execute/refuse/clarify）分层，execute 内再按 "
            "difficulty_struct 每层保底 1 条；层内按 sha1(SEED:case_id) 排序取前 k。"
            "选题与难易无关 ⇒ 报告里的百分比不掺杂选题偏置。"
        ),
        "quota": QUOTA,
        "n_dataset_cases": len(cases),
        "n_selected": len(chosen),
        "by_behavior": dict(sorted(by_behavior.items())),
        "by_cell": dict(sorted(by_cell.items())),
        "case_ids": [str(c["case_id"]) for c in chosen],
    }
    path = os.path.join(HERE, "smoke_batch_ids.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(",".join(payload["case_ids"]))
    print(json.dumps({k: payload[k] for k in ("n_selected", "by_behavior", "by_cell")},
                     ensure_ascii=False), file=sys.stderr)
    print(f"written: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
