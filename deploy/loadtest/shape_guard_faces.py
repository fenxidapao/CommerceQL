"""T-26 · ⑱ 形状守卫的**三面尺**现算件（零 DB / 零 LLM / 零额度，纯文本计数）。

为什么要有这个文件（不是"再写一份注释"）
--------------------------------------------------------------------------
`deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑱ 注记里，覆盖数在两轮之间从
**8** 变成 **11** —— 两次都是**手工 `grep -c` 出来的整数写进散文**。行号会漂、注释里的
整数不会跟着漂，于是"引覆盖数"这件事在本仓库已经是第二次两跑矛盾（QA 第 10 轮 T-26）。

本件把三把尺的**定义**固定成代码，并把"哪一面"变成读数的必要成分：
今后引覆盖数只能写 `F-pred / F-guard / F-consume` 三个名字之一 ＋ 本件的输出，
不再抄整数。

三把尺（都是**固定串**，不是"大概这类行"，所以 `grep -F` 也能逐条复算）
--------------------------------------------------------------------------
- **F-pred 判据谓词面** = 非注释行里出现排除式谓词本体
  `split_part(task_path, ', ', 2) <> '__start__'`。
  同时给 `F-pred 去守卫自身`（同一行也产 `shape_ok` 的那些 = ⑱ 自己），
  因为历史上"8 处"指的是**建在它之上的判据**、"11 处"指的是**含守卫自身**——
  两个数都对，差的是面，不是对错。
- **F-guard 守卫面** = 非注释行里 `as shape_ok` 且其后**不**跟 `__`
  （`s.shape_ok as shape_ok__T23` 是**输出别名**，不是守卫定义位；不排除它就把消费面算进守卫面）。
- **F-consume 消费位面** = 非注释行里出现 `not <别名>.shape_ok` 或
  `not (select shape_ok from shape)` —— 即"守卫翻了会让判定词变不可判"的那一支。

跑法：
    PYTHONUTF8=1 .venv/Scripts/python.exe deploy/loadtest/shape_guard_faces.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 三个承载同一把尺的文件（⑱ 是唯一定义处，另两处是指针抄本）。
FILES = (
    "deploy/loadtest/r23_thread_from_checkpoints.sql",
    "backend/reports/w4/probe_prod_checkpoint_terminal.sql",
    "backend/reports/w6/probe_audit_invariant.py",
)

PRED = "split_part(task_path, ', ', 2) <> '__start__'"
GUARD = "as shape_ok"
CONSUME_MARKS = ("not shape.shape_ok", "not s.shape_ok", "not (select shape_ok from shape)")


def _is_comment(line: str) -> bool:
    """SQL 的 `--`、Python 的 `#`/docstring 缩进注释都算注记位 —— 它们**不是**被消费的谓词。"""
    stripped = line.strip()
    return stripped.startswith("--") or stripped.startswith("#")


def _count(path: Path) -> dict[str, int]:
    out = {"F-pred": 0, "F-pred去守卫自身": 0, "F-guard": 0, "F-consume": 0}
    for line in path.read_text(encoding="utf-8").splitlines():
        if _is_comment(line):
            continue
        hits_pred = PRED in line
        # `as shape_ok__T23` 是别名不是守卫定义 ⇒ 后随 `__` 要排除
        hits_guard = GUARD in line and "as shape_ok__" not in line
        hits_consume = any(mark in " ".join(line.split()) for mark in CONSUME_MARKS)
        out["F-pred"] += hits_pred
        out["F-pred去守卫自身"] += hits_pred and not hits_guard
        out["F-guard"] += hits_guard
        out["F-consume"] += hits_consume
    return out


def violations() -> list[str]:
    """结构不变式（不是数值核对 —— 数值本来就会随追加漂）。

    每个承载这把尺的文件必须**三面齐全**：写了排除式判据（F-pred>0）却没有守卫定义位（F-guard=0）
    或没有消费位（F-consume=0），就是"这条判据没接否决位"—— T-23 修掉的正是这一形，
    所以它不能只靠人记得，必须由本件红。
    """
    out: list[str] = []
    for rel in FILES:
        path = REPO / rel
        if not path.exists():
            out.append(f"{rel}: 承载文件缺失 ⇒ 覆盖面不可引")
            continue
        counts = _count(path)
        if counts["F-pred"] and not counts["F-guard"]:
            out.append(f"{rel}: F-pred={counts['F-pred']} 但 F-guard=0 ⇒ 有判据、无守卫定义位")
        if counts["F-pred"] and not counts["F-consume"]:
            out.append(f"{rel}: F-pred={counts['F-pred']} 但 F-consume=0 ⇒ 守卫没接成否决位（旁注）")
    return out


def main() -> int:
    totals = {"F-pred": 0, "F-pred去守卫自身": 0, "F-guard": 0, "F-consume": 0}
    for rel in FILES:
        path = REPO / rel
        if not path.exists():
            print(f"[缺件] {rel} —— 尺子的承载文件不见了，覆盖面不可引")
            continue
        counts = _count(path)
        for key in totals:
            totals[key] += counts[key]
        print(f"{rel:58} " + "  ".join(f"{k}={v}" for k, v in counts.items()))
    print("-" * 100)
    print(f"{'三面合计':58} " + "  ".join(f"{k}={v}" for k, v in totals.items()))
    print("\n引用规则（T-26）：引覆盖数必须写面名（F-pred / F-pred去守卫自身 / F-guard / F-consume）"
          "＋ 本件输出；不得抄本文件任何一版的历史整数。")
    bad = violations()
    for v in bad:
        print(f"🔴 {v}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
