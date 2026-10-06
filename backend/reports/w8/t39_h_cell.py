"""T-39 A：`U-129` 结案引用 ③ 的 H 半格（**零出站**，只读已有 `docker logs` ＋ 盘上回执）。

口径纪律：
- H 的**节点集合按窗现读**（`U-126` v1.7.4 订正① 那句通则），四格相加与含第 5 档相加**两条都给**；
- 取窗必须具名＋每格给 n；作废那跑（`tk_e52c0019…`）在窄窗天然不在、在宽窗在 ⇒ 两把并报；
- 任何一格拿不到读数 ⇒ 写 `UNVERIFIED`，不写"达成"。

复算：`cd CommerceQL && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t39_h_cell.py`
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECEIPT = ROOT / "deploy/loadtest/t38_c3n30_main.json"
WARM = ROOT / "deploy/loadtest/t38_c3n30_warm.json"
OUT = ROOT / "backend/reports/w8/t39_h_cell.json"
CONTAINER = "commerceql-api-1"
VOID_TASK_PREFIX = "tk_e52c0019"
NOMINAL_SLOTS = ("normalize_intent", "plan", "l4_score", "gen_sql")
WINDOWS = {
    "narrow_incl_last_frame": ("2026-10-06T04:25:59Z", "2026-10-06T04:26:22Z"),
    "narrow_excl_last_frame": ("2026-10-06T04:25:59Z", "2026-10-06T04:26:21Z"),
    "wide_r23_window": ("2026-10-06T04:25:00Z", "2026-10-06T04:27:01Z"),
}


def void_run_window() -> tuple[str, str]:
    """作废那跑（预热格）的时间跨度取自 **它自己的回执**，不靠日志里的 run 标识（`llm_call` 行没有 `task_id`）。"""
    w = json.loads(WARM.read_text(encoding="utf-8"))
    return str(w["started_at"]), str(w["finished_at"])


def in_void(ts: str, win: tuple[str, str]) -> bool:
    """把 app 侧 `timestamp`（形如 2026-10-06T04:25:19.595108）裁到秒后与作废窗比字典序（同一 UTC 侧、同一格式才可比）。"""
    a, b = win[0][:19], win[1][:19]
    return a <= ts[:19] <= b


def docker_logs(since: str, until: str) -> list[dict]:
    """`docker logs --since/--until` 取 JSON 行（服务端零写）。行里 docker 前缀在第一个 '{' 之前。"""
    cp = subprocess.run(
        ["docker", "logs", "--since", since, "--until", until, CONTAINER],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if cp.returncode != 0:
        raise SystemExit(f"[尺坏] docker logs rc={cp.returncode}: {cp.stderr[:200]}")
    rows = []
    for line in cp.stdout.splitlines():
        i = line.find("{")
        if i < 0:
            continue
        try:
            obj = json.loads(line[i:])
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "llm_call":
            rows.append(obj)
    return rows


def per_node(rows: list[dict]) -> dict[str, dict]:
    buckets: dict[str, list[int]] = {}
    for r in rows:
        lat = r.get("latency_ms")
        if isinstance(lat, (int, float)):
            buckets.setdefault(str(r.get("task")), []).append(float(lat))
    return {
        task: {"n": len(v), "p50_ms": round(statistics.median(v), 1), "min_ms": min(v), "max_ms": max(v)}
        for task, v in sorted(buckets.items())
    }


def h_of(nodes: dict[str, dict], slots: tuple[str, ...]) -> tuple[float | None, list[str]]:
    """按给定槽位集合相加；任一格拿不到 ⇒ 返回 None ＋ 点名缺哪格（不许静默）。"""
    missing = [s for s in slots if s not in nodes]
    if missing:
        return None, missing
    return round(sum(nodes[s]["p50_ms"] for s in slots) / 1000.0, 2), []


def main() -> int:
    print(f"[ROOT] {ROOT}")
    assert RECEIPT.exists(), f"尺坏：找不到回执 {RECEIPT}"
    main_rec = json.loads(RECEIPT.read_text(encoding="utf-8"))
    warm_rec = json.loads(WARM.read_text(encoding="utf-8"))
    scen = main_rec["scenarios"][0]
    adm, out = scen["admission"], scen["outcomes"]

    void_win = void_run_window()
    result: dict[str, object] = {
        "meta": {
            "window": "W8 第 16 轮 / T-39 A",
            "zero_egress": True,
            "ruler": "backend/reports/w8/t39_h_cell.py",
            "source_of_rows": f"docker logs {CONTAINER}（只读，服务端零写）",
            "rev_and_time": {
                "receipt_git_rev": main_rec["git_rev"],
                "receipt_git_dirty": main_rec["git_dirty"],
                "receipt_started_at": main_rec["started_at"],
                "receipt_finished_at": main_rec["finished_at"],
                "head_at_measurement": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                                      capture_output=True, text=True).stdout.strip(),
            },
            "void_cell_declaration": {
                "task_id": "tk_e52c0019…（只作标识，日志行里**没有** run 标识 ⇒ 归属只能按时间窗）",
                "void_run_window_from_its_own_receipt": list(void_win),
                "void_run_admission": warm_rec["scenarios"][0]["admission"],
                "statement": "首格（预热／作废格）不进任何分母：不进 ok 率、不进 H 的节点集合读数、不进 P95。"
                             "窄窗（主批自有 `started_at→finished_at`）不含它；宽窗（⑮⑰ 那把 04:25:00→04:27:00Z）**含**它的 4 条 ⇒ 两把并报。",
            },
        },
        "ok_rate": {
            "numerator_ok": out.get("ok"),
            "denominator_admitted": adm.get("admitted"),
            "rate_of_admitted": round((out.get("ok", 0) or 0) / adm["admitted"], 4),
            "denominator_fired": scen["requests"],
            "rate_of_fired": round((out.get("ok", 0) or 0) / scen["requests"], 4),
            "note": "两个分母必须点名：`ok/admitted`（准入面，跨批与 W7 那把比只用这把）与 `ok/发出`（含 429 拒的整批面）。",
            "outcomes": out,
            "admission": adm,
        },
        "by_window": {},
        "reference_lines": {
            "U-126_v1.7.4_订正①_名义四格_H": 5.99,
            "U-126_v1.7.5_区间_H": [5.99, 6.18],
            "ruler_for_slots": "H 一律按『当日实际发 LLM 的节点集合』取，不得照抄名义分配（docs/07 U-126 行）",
        },
    }

    for name, (since, until) in WINDOWS.items():
        rows = docker_logs(since, until)
        nodes = per_node(rows)
        h4, miss4 = h_of(nodes, NOMINAL_SLOTS)
        extra = [t for t in nodes if t not in NOMINAL_SLOTS]
        h_all, _ = h_of(nodes, tuple(NOMINAL_SLOTS) + tuple(sorted(extra)))
        void_rows = [r for r in rows if in_void(str(r.get("timestamp", "")), void_win)]
        result["by_window"][name] = {
            "window": [since, until],
            "llm_call_rows": len(rows),
            "void_run_rows_inside": len(void_rows),
            "void_run_tasks_inside": sorted({str(r.get("task")) for r in void_rows}),
            "node_set_present": sorted(nodes),
            "per_node": nodes,
            "H_nominal_four_slots": None if h4 is None else h4,
            "H_missing_slots": miss4,
            "extra_slots_beyond_nominal": sorted(extra),
            "H_including_extra_slots": None if h_all is None else h_all,
            "delta_vs_5.99s_nominal_four": None if h4 is None else round(h4 - 5.99, 2),
        }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    w = result["by_window"]
    for name in WINDOWS:
        cell = w[name]
        print(f"{name}: rows={cell['llm_call_rows']} void_rows_inside={cell['void_run_rows_inside']} "
              f"nodes={cell['node_set_present']} H4={cell['H_nominal_four_slots']} "
              f"H_all={cell['H_including_extra_slots']} per_node={ {k: (v['n'], v['p50_ms']) for k, v in cell['per_node'].items()} }")
    print(f"ok 率 = {result['ok_rate']['numerator_ok']}/{result['ok_rate']['denominator_admitted']} "
          f"= {result['ok_rate']['rate_of_admitted']}")
    print(f"落盘 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
