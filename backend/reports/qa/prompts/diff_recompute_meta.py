r"""QA 永久尺：**重算类交付的递归 diff**（每轮交付协议里"跑两遍 ⇒ 只许差 meta 字段"那条的可执行化）。

零额度：只读两份 JSON、只往 stdout 印差集，不写盘、不连库、不调模型。

为什么要它：本项目"达成"的复算方式一直是"把同一个取数件重跑一遍，再比两次读数"。
手工比会漏两件事 —— ① 把**时钟派生句**（`age / max_lag` 这类随读数时刻动的散文）误报成判定量差，
② 把真正该钉住的判定量放过去。本件把两件事分开：**白名单只放 meta 前缀**，其余一律算判定量差。

用法（仓库根）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/qa/prompts/diff_recompute_meta.py <A.json> <B.json> [前缀 …]
不带可选前缀时用的默认白名单 = QA 第 8 轮复算 `t33_u130_coupling.json` 那六条（rev／时刻／提交数）。
退出码：0 = 判定量零差（`judgment=0`）；1 = 有判定量差；2 = 用法或解析错。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_META = (
    "generated_at_utc",
    "generated_at",
    "generated_at_cst",
    "reading_window_utc",
    "reading_window_cst",
    "git.rev",
    "git.rev_full",
    "git.commit_count",
    "git.dirty_files",
)


def walk(a: object, b: object, path: str = "") -> list[tuple[str, str, object, object]]:
    diffs: list[tuple[str, str, object, object]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                diffs.append((p, "presence", k in a, k in b))
                continue
            diffs += walk(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append((f"{path}.len", "len", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            diffs += walk(x, y, f"{path}[{i}]")
    else:
        if a != b:
            diffs.append((path, "value", a, b))
    return diffs


def _hit(path: str, meta: tuple[str, ...]) -> bool:
    """白名单匹配：普通前缀 ＋ 以 `~` 开头的**尾缀**规则（用于 `…items[7].静默前置` 这类下标不定的派生句）。"""
    return any((p.endswith(m[1:]) if m.startswith("~") else p.startswith(m)) for p in [path] for m in meta)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        print("用法：diff_recompute_meta.py <A.json> <B.json> [meta 前缀 …]（尾缀规则写作 ~字段名）")
        return 2
    try:
        a = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        b = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[解析失败] {exc}")
        return 2
    meta = tuple(argv[3:]) if len(argv) > 3 else DEFAULT_META

    diffs = walk(a, b)
    in_meta = [d for d in diffs if _hit(d[0], meta)]
    judgment = [d for d in diffs if not _hit(d[0], meta)]
    print(f"A = {argv[1]}\nB = {argv[2]}")
    print(f"白名单 = {'默认六条' if len(argv) <= 3 else ' ＋ '.join(meta)}")
    print(f"差集总数 = {len(diffs)} ｜ meta（允许差） = {len(in_meta)} ｜ **判定量（必须 0）** = {len(judgment)}")
    print("--- meta 差（逐条列出，别只报条数）---")
    for p, kind, x, y in in_meta:
        print(f"  {p} [{kind}]: {json.dumps(x, ensure_ascii=False)[:90]}  ->  "
              f"{json.dumps(y, ensure_ascii=False)[:90]}")
    print("--- 判定量差（非 0 即「重跑不闭合」）---")
    for p, kind, x, y in judgment:
        print(f"  {p} [{kind}]: {json.dumps(x, ensure_ascii=False)[:140]}  ->  "
              f"{json.dumps(y, ensure_ascii=False)[:140]}")
    return 1 if judgment else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
