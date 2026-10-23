"""W75-1/W75-2 的**逐条 delta**（零出站）。

对比 r75（W74-2 多余列窄口后）与 r75-window（W75-1 窗口强制后）两份 166 全量重放，
回答派单 §96.8 的三条红线：

* 只有 M-IDX-09 的 SQL/参数/读值变了；M-IDX-10、C-REP-01 逐字不变；
* 等价总数仍 50、终态分布逐格不变；
* W75-2 的零列守卫在**产物上**可复现（gold 0 列 vs pred 1 列 ⇒ 不等价）。

跑法（CommerceQL 根目录，零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe eval/w75_window_delta.py
产物：`eval/results_r75_window_delta.json`
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402
import equivalence as eq  # noqa: E402

PREV = os.path.join(HERE, "results_r75_full166_extra_columns.json")
NEXT = os.path.join(HERE, "results_r75_full166_window.json")
OUT = os.path.join(HERE, "results_r75_window_delta.json")


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _head(record: dict[str, Any]) -> Any:
    return ((record.get("predicted") or {}).get("shape") or {}).get("head_rows")


def main() -> int:
    prev = _load(PREV)
    nxt = _load(NEXT)
    old = {str(r["case_id"]): r for r in prev["records"]}
    new = {str(r["case_id"]): r for r in nxt["records"]}

    changed_sql = [cid for cid in new if new[cid].get("sql_text") != old[cid].get("sql_text")]
    changed_params = [
        cid for cid in new if new[cid].get("sql_params") != old[cid].get("sql_params")
    ]
    changed_values = [
        cid for cid in new if _head(new[cid]) != _head(old[cid]) and cid not in changed_sql
    ]
    changed_terminal = [
        cid
        for cid in new
        if (new[cid].get("terminal_event"), new[cid].get("terminal_code"))
        != (old[cid].get("terminal_event"), old[cid].get("terminal_code"))
    ]

    zero_gold = eq.compare_tables(
        eq.Table((), ()), eq.Table(("anything",), ())
    )
    repurchase = {}
    for cid in ("M-IDX-09", "M-IDX-10", "C-REP-01"):
        repurchase[cid] = {
            "sql_identical": new[cid].get("sql_text") == old[cid].get("sql_text"),
            "params_identical": new[cid].get("sql_params") == old[cid].get("sql_params"),
            "value_before": _head(old[cid]),
            "value_after": _head(new[cid]),
            "verdict_before": (old[cid].get("verdict") or {}).get("equivalent"),
            "verdict_after": (new[cid].get("verdict") or {}).get("equivalent"),
            "terminal_before": old[cid].get("terminal_event"),
            "terminal_after": new[cid].get("terminal_event"),
        }
    payload = {
        **_bootstrap.build_stamp(),
        "task": "W75-1/2 逐条 delta（零出站；两份 166 重放对比）",
        "prev": {
            "path": "eval/results_r75_full166_extra_columns.json",
            "git_rev": prev.get("git_rev"),
            "git_dirty": prev.get("git_dirty"),
        },
        "next": {
            "path": "eval/results_r75_full166_window.json",
            "git_rev": nxt.get("git_rev"),
            "git_dirty": nxt.get("git_dirty"),
        },
        "changed_sql_cases": changed_sql,
        "changed_sql_params_cases": changed_params,
        "changed_predicted_values_only": changed_values,
        "changed_terminal_cases": changed_terminal,
        "repurchase": repurchase,
        "summary_before": prev["summary"],
        "summary_after": nxt["summary"],
        "w75_2_zero_column_probe": {
            "gold_columns": 0,
            "pred_columns": 1,
            "equivalent": zero_gold.equivalent,
            "diffs": list(zero_gold.diffs),
        },
        "conclusion": {
            "only_m_idx_09_changed": changed_sql == ["M-IDX-09"],
            "equivalence_unchanged": prev["summary"]["n_equivalent"]
            == nxt["summary"]["n_equivalent"]
            == 50,
            "terminal_unchanged": prev["summary"]["terminal_distribution"]
            == nxt["summary"]["terminal_distribution"],
            "m_idx_09_still_not_equivalent": repurchase["M-IDX-09"]["verdict_after"] is False,
            "not_a_two_case_fix": (
                "M-IDX-09/10 仍判不等价（gold 整除=0）；本改动只修系统窗口一致性，"
                "不计入能力提升"
            ),
        },
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {os.path.relpath(OUT, ROOT)}")
    print("changed sql:", changed_sql)
    print("changed params:", changed_params)
    print("changed values only:", changed_values)
    print("changed terminal:", changed_terminal)
    print("zero-column guard:", zero_gold.equivalent, zero_gold.diffs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
