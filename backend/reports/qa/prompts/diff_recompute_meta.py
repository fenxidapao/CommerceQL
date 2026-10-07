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


def _hit(path: str, meta: tuple[str, ...], *, dotted_anywhere: bool = False) -> bool:
    """白名单匹配：普通前缀 ＋ 以 `~` 开头的**尾缀**规则（用于 `…items[7].静默前置` 这类下标不定的派生句）。

    🔴 `dotted_anywhere`（QA 第 25 轮加）：白名单里带点的规则（`git.rev`）默认**只按前缀**匹配 ⇒
    从根走的递归路径是 `meta.git.rev` / `gate_provenance.report_git.rev`，**不会**被豁免 ⇒
    "同树两遍"用默认白名单就能得 rc 0，"跨代（换代件 ⟷ 新件）"用同一把白名单会得到非零判定量。
    开这个开关 = 让带点规则在**任意层**匹配（`p == m` 或 `p` 以 `.`+m 结尾或 `p` 含 `.`+m+`.`）。
    ⚠️ 它只改变"算不算 meta"，**不隐藏差集**：两把计数与逐条差集永远都印，退出码用哪一把由开关决定。
    """
    for m in meta:
        if m.startswith("~"):
            if path.endswith(m[1:]):
                return True
            continue
        if path.startswith(m):
            return True
        if dotted_anywhere and "." in m and (path == m or path.endswith("." + m) or ("." + m + ".") in ("." + path + ".")):
            return True
    return False


def main(argv: list[str]) -> int:
    relax = "--relax-dotted" in argv
    argv = [a for a in argv if a != "--relax-dotted"]
    if len(argv) < 3:
        print(__doc__)
        print("用法：diff_recompute_meta.py <A.json> <B.json> [meta 前缀 …] [--relax-dotted]（尾缀规则写作 ~字段名）")
        return 2
    try:
        a = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        b = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[解析失败] {exc}")
        return 2
    meta = tuple(argv[3:]) if len(argv) > 3 else DEFAULT_META

    diffs = walk(a, b)
    strict = [d for d in diffs if not _hit(d[0], meta)]
    loose = [d for d in diffs if not _hit(d[0], meta, dotted_anywhere=True)]
    in_strict = [d for d in diffs if _hit(d[0], meta)]
    print(f"A = {argv[1]}\nB = {argv[2]}")
    print(f"白名单 = {'默认六条' if len(argv) <= 3 else ' ＋ '.join(meta)}")
    print(f"差集总数 = {len(diffs)}")
    print(f"  【严格＝前缀】meta（允许差） = {len(in_strict)} ｜ **判定量** = {len(strict)}")
    print(f"  【宽松＝带点规则任意层】判定量 = {len(loose)}"
          f" ｜ 两把之差（被宽松豁免掉的） = {len(strict) - len(loose)}")
    print(f"  退出码取 = {'宽松' if relax else '严格'}")
    print("--- 差集逐条（一条都不藏）---")
    for p, kind, x, y in diffs:
        tag = "meta(严格)" if _hit(p, meta) else ("meta(仅宽松)" if _hit(p, meta, dotted_anywhere=True) else "判定量")
        print(f"  [{tag}] {p} {kind}: {json.dumps(x, ensure_ascii=False)[:110]}  ->  "
              f"{json.dumps(y, ensure_ascii=False)[:110]}")
    judged = loose if relax else strict
    if relax and strict and not loose:
        print("⚠️ 本判定来自 --relax-dotted：换代比对把 rev／commit_count 一类身份字段豁免掉了 ⇒ 引用时必须点名'哪些路径是被豁免的身份字段'。")
    return 1 if judged else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
