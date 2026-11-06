"""未决问题台账（`docs/10_未决问题台账.md`）的机器门。

只做四件事，全部 stdlib、零依赖、零出站：
  ① 取号门  ② 关闭门  ③ 跳过门  ④ WIP 闸

用法（仓库根；Windows 控制台加 `PYTHONUTF8=1`）：
    python tools/open_issues.py            # 打印摘要 + 违规
    python tools/open_issues.py --check    # 收口 DoD：有违规即 exit 1

两条设计上的硬要求（都是踩过的）：
  · 解析失败不得视为通过 —— 台账表格一坏就「0 行 0 违规」= 假绿，所以 0 行本身是违规。
  · 首格反引号必须容忍 —— 人写台账习惯给 ID 加反引号，格式口味不能决定门是否生效。

判定逻辑**只有这一份**：契约测试 `backend/tests/contract/test_open_issues_ledger.py`
直接加载本模块的 `validate()`，不复制规则（防两份真相漂移）。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "10_未决问题台账.md"
TDD_PATH = REPO_ROOT / "docs" / "07_技术设计文档_TDD.md"
STATE_PATH = REPO_ROOT / "docs" / "09_当前状态与交接.md"

STATUSES = ("OPEN", "BLOCKED-BY-DATA", "EVIDENCE-MISSING", "WAIVED", "CLOSED")
WIP_STATUSES = ("OPEN", "BLOCKED-BY-DATA", "EVIDENCE-MISSING")
WIP_MAX = 12
N_COLUMNS = 9
COMMAND_TOKENS = ("python", "pytest", "git ", "grep", "ruff", "mypy", "npm ")
PATH_SUFFIXES = (".md", ".py", ".json", ".yaml", ".yml", ".txt", ".sql", ".csv")
EMPTY_REVIEW = ("", "—", "-")

_ID_RE = re.compile(r"^(U-\d{3}|T-\d{2})$")
_SPAN_RE = re.compile(r"`([^`]+)`")


def _normalize_id(cell: str) -> str:
    """首格容忍反引号与空白：`T-01` / T-01 / ` U-154 ` 都归一成裸 ID。"""
    return cell.replace("`", "").strip()


def parse_rows(text: str) -> list[list[str]]:
    """抽出「首格是 ID」的表格行；表头与分隔行按格式自然排除。"""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        cells[0] = _normalize_id(cells[0])
        if _ID_RE.match(cells[0]):
            rows.append(cells)
    return rows


def _first_existing_path(spans: list[str]) -> str | None:
    """在反引号里挑出「像路径」的片段，返回第一个真的落在盘上的。"""
    for span in spans:
        if "/" not in span and not span.endswith(PATH_SUFFIXES):
            continue
        if (REPO_ROOT / span).exists():
            return span
    return None


def validate(ledger_text: str | None = None) -> tuple[list[list[str]], list[str]]:
    """返回 `(rows, violations)`；`violations` 为空才算过门。"""
    text = LEDGER_PATH.read_text(encoding="utf-8") if ledger_text is None else ledger_text
    rows = parse_rows(text)
    violations: list[str] = []
    tdd = TDD_PATH.read_text(encoding="utf-8") if TDD_PATH.is_file() else ""
    state = STATE_PATH.read_text(encoding="utf-8") if STATE_PATH.is_file() else ""

    if not rows:
        violations.append("台账解析出 0 行 —— 表格形状坏了或文件为空；解析失败不得视为通过")

    seen: set[str] = set()
    wip = 0
    has_waived = False

    for cells in rows:
        rid = cells[0]
        if rid in seen:
            violations.append(f"{rid}: ID 重复（一个号只对应一件事）")
            continue
        seen.add(rid)
        if len(cells) != N_COLUMNS:
            violations.append(f"{rid}: 列数 {len(cells)} ≠ {N_COLUMNS}")
            continue

        # 状态格同样容忍反引号与空白：台账里写 `OPEN` / `WAIVED` 是自然习惯，
        # 格式口味不能决定「这条算不算未闭」（否则整表被判成非法状态 = 假红）。
        status = _normalize_id(cells[3])
        symptom, first, close_rule, evidence, review = (
            cells[1],
            cells[2],
            cells[4],
            cells[5],
            cells[8],
        )

        if not symptom:
            violations.append(f"{rid}: 「现象」列空")
        if status not in STATUSES:
            violations.append(f"{rid}: 状态 {status} 不在 5 值枚举内")
            continue

        # ① 取号门
        if rid.startswith("U-") and rid not in tdd:
            violations.append(f"{rid}: 取号门 —— docs/07 查不到该号")
        if rid.startswith("T-") and "待取号" not in first and "非缺陷" not in first:
            violations.append(f"{rid}: 取号门 —— T 行须在「首次登记」注明 待取号 或 非缺陷")

        # ② 关闭门
        if status == "CLOSED":
            if _first_existing_path(_SPAN_RE.findall(evidence)) is None:
                violations.append(f"{rid}: 关闭门 —— 证据路径不在盘上")
            if not any(token in close_rule for token in COMMAND_TOKENS):
                violations.append(f"{rid}: 关闭门 —— 缺可复算命令")

        # ③ 跳过门
        if status == "WAIVED":
            has_waived = True
            if review in EMPTY_REVIEW:
                violations.append(f"{rid}: 跳过门 —— WAIVED 必须写复审触发")

        if status in WIP_STATUSES:
            wip += 1

    if has_waived and "豁免" not in state:
        violations.append("跳过门 —— 台账有 WAIVED 而 docs/09 未同框出现「豁免」")
    if wip > WIP_MAX:
        violations.append(f"WIP 闸 —— 未闭条目 {wip} > {WIP_MAX}，先关后开")

    return rows, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 docs/10 未决问题台账")
    parser.add_argument("--check", action="store_true", help="收口 DoD 用；有违规即非零退出")
    parser.parse_args(argv)

    rows, violations = validate()
    counts = dict.fromkeys(STATUSES, 0)
    for cells in rows:
        status = _normalize_id(cells[3]) if len(cells) == N_COLUMNS else ""
        if status in counts:
            counts[status] += 1
    wip = sum(counts[status] for status in WIP_STATUSES)
    summary = " ".join(f"{status}={counts[status]}" for status in STATUSES)
    print(f"rows={len(rows)} {summary} wip={wip}/{WIP_MAX}")
    for violation in violations:
        print(f"VIOLATION {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
