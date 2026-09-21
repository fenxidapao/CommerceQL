"""W6 · 把 W7 的**真实回执文件**逐份过一遍真读端 + 真 gates（跨窗口口径核对）。

为什么要有这个文件
--------------------------------------------------------------------------
W7 换 G-6 的 P95 口径时给了一句"十份历史回执逐份过你们真读端 + 真 gates：全部 UNVERIFIED"。
这种跨窗口声明**不能照抄**：它取决于我方的读端实现（`loadtest_pressure()` 取哪一层的 p95、
`gates.py` 在什么条件下降档），而读端刚被我改过。所以自己跑一遍，读数写进产物。

纪律：本文件只读 `deploy/loadtest/*.json`（W7 的产物），一个字都不写回去；
输出只落在本目录 `probe_loadtest_receipts.json`。

跑法（CommerceQL 根目录，零 LLM / 零网络）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_loadtest_receipts.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402  # 复用同一个 ROOT / sys.path 装配（U-41 同源纪律）

_bootstrap.bootstrap()

import gates as gates_mod  # noqa: E402
import reporter as rp  # noqa: E402

#: 扫描面 = 该目录**全部** JSON。刻意不用 `receipt*.json`：那个 glob 会漏掉
#: `baseline_c5.json`（实测唯一喂真 gates 出 PASS 的一份）和两份 preflight。
RECEIPT_GLOB = os.path.join(ROOT, "deploy", "loadtest", "*.json")
OUT = os.path.join(HERE, "probe_loadtest_receipts.json")


def judge(receipt_path: str) -> dict[str, object]:
    """一份回执 → 真读端 → 真 gates，只取 G-6 那一行。"""
    pressure = rp.loadtest_pressure(receipt_path)
    if pressure is None:
        return {"read端": "None（不可读 / schema 不符 / 无 p95）", "verdict": "NOT_AVAILABLE"}
    gate = next(
        g for g in gates_mod.evaluate_gates(pressure=pressure) if g.gate_id == "G-6"
    )
    raw = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    scenarios = [s for s in (raw.get("scenarios") or [])]
    return {
        "verdict": gate.verdict,
        "measured": gate.measured,
        "caveats": list(gate.caveats),
        "scenarios_n": len(scenarios),
        "caveated_scenarios": sum(1 for s in scenarios if s.get("g6_caveat")),
        "p95_scope_values": sorted({str(s.get("p95_scope")) for s in scenarios}),
        "has_admission": any(s.get("admission") for s in scenarios),
        # W7 声明这堆历史格里有 14 个 stale `true` ⇒ 我方产物要能自己数，不靠转述。
        "g6_p95_le_8s_values": sorted({str(s.get("g6_p95_le_8s")) for s in scenarios}),
        "stale_true_cells": sum(1 for s in scenarios if s.get("g6_p95_le_8s") is True),
        "null_caveat_scenarios": sum(1 for s in scenarios if s.get("g6_caveat") is None),
        "has_all_ms_p95": any(
            (s.get("latency_ms_all_ms") or {}).get("p95") is not None for s in scenarios
        ),
    }


def main() -> int:
    paths = sorted(glob.glob(RECEIPT_GLOB))
    results = {os.path.relpath(p, ROOT).replace("\\", "/"): judge(p) for p in paths}
    tally: dict[str, int] = {}
    for r in results.values():
        tally[str(r["verdict"])] = tally.get(str(r["verdict"]), 0) + 1
    payload = {
        "reader": "eval/reporter.loadtest_pressure + eval/gates.evaluate_gates(pressure=…)",
        "schema_string_read_verbatim": rp.LOADTEST_SCHEMA,
        "n_files": len(paths),
        "verdict_tally": tally,
        "any_pass": any(r["verdict"] == "PASS" for r in results.values()),
        "stale_true_cells_total": sum(int(r.get("stale_true_cells", 0)) for r in results.values()),
        "null_caveat_scenarios_total": sum(
            int(r.get("null_caveat_scenarios", 0)) for r in results.values()),
        "files": results,
        "note": (
            "读端**不做未知键校验**（W7 刻意不升 schema 版本号，新增字段在读的路径之外）；"
            "判定口径：`g6_caveat` 非空 ⇒ 至多 UNVERIFIED；p95 只标了非全请求口径 ⇒ 至多 PARTIAL；"
            "有 `latency_ms_all_ms` ⇒ 用全请求分位数判。"
            "🔴 2026-09-21 起再加一条：caveat 为 null **但**既无 `admission` 又无全请求分位数 ⇒ "
            "也判不了达标（那个 null 只代表产自 U-106 之前的判据）。同轮把扫描面从 `receipt*.json` "
            "扩到 `*.json` —— 旧 glob 恰好漏掉了唯一出 PASS 的 baseline_c5.json。"
        ),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"回执 {len(paths)} 份：{tally}")
    for name, r in results.items():
        print(f"  {r['verdict']:14s} {name}  scenarios={r.get('scenarios_n')} "
              f"caveated={r.get('caveated_scenarios')} scope={r.get('p95_scope_values')}")
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
