#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""凭据字面量扫描（DoD④ 的本机替身）—— **规则单一出处**，报告只引本脚本名。

──────── 为什么有这个脚本（W8 第 44 轮，QA §62.7 二）────────
原来这件事写在 `backend/reports/w8/RELAY.md` §廿一 的**命令行里**，靠报告抄正则。
为避免 `.gitleaks.toml`/CI 的连续字面量命中，那条命令行把交替分支**截断**成
`…|postgres://` —— 目的达成，但冒出两个根因：

  ① **对命令行自身自匹配**：报告里那句话本身含该 pattern ⇒ 扫到自己；
  ② **命中面被放大 + 与结论脱钩**：只剩 `postgres://` 时，**任何**提到该 scheme 的文字
     （含报告正文）都算命中（QA 实测：被测 74 文件里命中 7 个，含 `reports/qa/*` 三件），
     而那句话的结论仍写着「命中数必须 = 0」。
（注：自匹配**不是**第 43 轮引入的 —— 改前即自匹配；本轮是趁真因在手一次修干净。）

──────── 本脚本的规矩 ────────
· **正则不在本文件里**：三条规则全部从 `.gitleaks.toml` 的 `[[rules]]` **运行时读**，
  allowlist 语义（`regexes` / `stopwords` / `paths`）也从同一处读 ⇒ 与 CI 同源，
  不会各自演化成"验我自己写的那条正则"。
· **只看指定区间内变更的文件**（默认 `983214c..HEAD`，即 §廿一 那句的同一锚点）。
· 退出码：**0 = 0 命中（通过）**；**1 = 有命中**；**2 = 用法/配置错**。
  ⚠️ 这**不是** `grep` 的约定（`grep` 里 1 才表示"没命中"）—— 本脚本用直白约定，
  §廿一 那行的「scan_rc=…（1 = 0 命中）」注释随之作废（见 RELAY 的 🔻 订正）。

──────── 诚实边界（**不假装等价于 CI**）────────
CI 跑 `gitleaks detect`（`fetch-depth: 0`，**含全部历史**）且 `.gitleaks.toml` 里
`[extend] useDefault = true` ⇒ 它还会套**官方默认规则集**。本脚本：
· 只复放**本项目自有**的 3 条规则（DSN／DeepSeek key／JWT 私钥）；
· 只看**工作区的当前内容**，**不看历史**。
⇒ 本脚本是 CI 的**下界**：它绿不代表 CI 绿（历史泄漏＋默认规则要 CI 才看得见）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GITLEAKS_TOML = _REPO_ROOT / ".gitleaks.toml"
_DEFAULT_SINCE = "983214c"
_TEXT_SUFFIXES = (".json", ".py", ".md")
_MASK_KEEP = 6
#: 🔻 第 45 轮（QA §63.4／§64.1 四）：`--since` 是**提交史**口径 ⇒ 看不到**未跟踪的新件**；
#: `--working-tree` 补这一面。跳过目录与 `tests/unit/test_migration_dsn_hygiene.py`
#: 的 `_SKIP_DIRS` **同源**（理由同：第三方/构建产物里塞满假密钥样本，会把真命中淹掉）。
_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".import_linter_cache", ".lintprobe", "htmlcov",
})


def _load_gitleaks_config() -> dict[str, object]:
    if not _GITLEAKS_TOML.exists():
        print(f"[用法错] 找不到 {_GITLEAKS_TOML} —— 它是规则出处，缺了本脚本扫的是空气", file=sys.stderr)
        raise SystemExit(2)
    with _GITLEAKS_TOML.open("rb") as fh:
        return tomllib.load(fh)


def _rules(cfg: dict[str, object]) -> list[tuple[str, re.Pattern[str]]]:
    rules = cfg.get("rules")
    if not isinstance(rules, list):
        print("[用法错] .gitleaks.toml 的 [[rules]] 结构变了，需同步本脚本", file=sys.stderr)
        raise SystemExit(2)
    out: list[tuple[str, re.Pattern[str]]] = []
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("regex"), str):
            pattern = rule["regex"]
            assert "(?!" not in pattern and "(?<" not in pattern, (
                f"规则 {rule.get('id')} 用了 RE2 不支持的断言 —— gitleaks 会 panic（假阴性）"
            )
            out.append((str(rule.get("id", "?")), re.compile(pattern)))
    return out


def _allowlist(cfg: dict[str, object]) -> tuple[list[re.Pattern[str]], list[str], list[re.Pattern[str]]]:
    allow = cfg.get("allowlist")
    if not isinstance(allow, dict):
        print("[用法错] .gitleaks.toml 的 [allowlist] 结构变了，需同步本脚本", file=sys.stderr)
        raise SystemExit(2)
    excused = [re.compile(str(p)) for p in allow.get("regexes", [])]
    stopwords = [str(w).lower() for w in allow.get("stopwords", [])]
    paths = [re.compile(str(p)) for p in allow.get("paths", [])]
    return excused, stopwords, paths


def _changed_files(since: str, root: Path = _REPO_ROOT) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{since}..HEAD"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if proc.returncode != 0:
        print(f"[用法错] git diff 失败（锚点 {since} 是否存在？）：{proc.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().endswith(_TEXT_SUFFIXES)]


def _worktree_files(root: Path) -> list[str]:
    """工作树口径：全仓文本件（含**未跟踪**的新件），跳过 `_SKIP_DIRS`。"""
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _SKIP_DIRS & set(path.parts):
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        out.append(path.relative_to(root).as_posix())
    return out


def _mask(secret: str) -> str:
    return secret[:_MASK_KEEP] + "…" + f"（{len(secret)} 字符）" if len(secret) > _MASK_KEEP else "…"


def _scan(root: Path, paths: list[str], rules: list[tuple[str, re.Pattern[str]]],
          excused: list[re.Pattern[str]], stopwords: list[str],
          allow_paths: list[re.Pattern[str]]) -> list[str]:
    hits: list[str] = []
    for rel in paths:
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        path_excused = any(p.search(rel) for p in allow_paths)
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule_id, pattern in rules:
                for match in pattern.finditer(line):
                    secret = match.group(0)
                    if path_excused or any(p.search(secret) for p in excused):
                        continue
                    if any(w in secret.lower() for w in stopwords):
                        continue
                    hits.append(f"{rel}:{lineno}  [{rule_id}]  {_mask(secret)}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="凭据字面量扫描（DoD④ 本机替身；规则出处 = .gitleaks.toml）")
    ap.add_argument("--since", default=_DEFAULT_SINCE, help=f"区间起点（默认 {_DEFAULT_SINCE}）")
    ap.add_argument("--working-tree", action="store_true",
                    help="改扫**工作树**（含未跟踪新件），而非 `--since` 区间内的已提交件")
    ap.add_argument("--root", default=str(_REPO_ROOT), help="扫描根（测试用；默认仓库根）")
    args = ap.parse_args()

    root = Path(args.root)
    cfg = _load_gitleaks_config()
    rules = _rules(cfg)
    excused, stopwords, allow_paths = _allowlist(cfg)

    if args.working_tree:
        paths = _worktree_files(root)
        face = f"工作树全仓文本件（跳过 {len(_SKIP_DIRS)} 类构建/第三方目录）"
    else:
        paths = _changed_files(args.since, root)
        face = f"git diff --name-only {args.since}..HEAD"

    print(f"面 = {face}，文本后缀 {_TEXT_SUFFIXES}")
    print(f"规则出处 = .gitleaks.toml（{len(rules)} 条：{'｜'.join(r[0] for r in rules)}）")
    print(f"allowlist 语义已同步（regexes={len(excused)}｜stopwords={len(stopwords)}｜paths={len(allow_paths)}）")
    print(f"被测文件 = {len(paths)} 件")

    hits = _scan(root, paths, rules, excused, stopwords, allow_paths)
    if hits:
        print(f"\n🔴 命中 {len(hits)} 处（CI 的 gitleaks 会红）：")
        for h in hits:
            print("   " + h)
        return 1
    print("\n✅ 0 命中（本项目自有规则 × 本次面）")
    print("⚠️ 本脚本是 CI 的下界：gitleaks 默认规则集（useDefault=true）与**全历史**不在本脚本内。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
