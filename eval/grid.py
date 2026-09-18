"""4×3 双维度分层网格（07 §17.1 评测层 / 附录 C §C.3.3；08 §3.8 产出③）。

归属窗口：W6。

口径不变量的落地点（§17.6）
--------------------------------------------------------------------------
* **I-1** 轴 1 一律取 `difficulty_struct`（上游代码口径，`JOIN += len(table_units)−1`、
  子查询计入）。`difficulty_struct_sitelabel` **只作对照**，本模块**不读**它 ——
  字段白名单由 `reporter.assert_field_whitelist()` 静态把关，双保险。
* **I-2** 分层用的难度**必须在未注入租户谓词的 `gold_sql` 上复算**并与冻结标签比对；
  复算不一致 = 数据集与 `layering.py` 版本漂移（N-13 的前兆），当场抛错而不是悄悄用一边。
* **I-3** v1 的 `medium` 语义档因沙箱物化了大区列而存在**高估**：本模块只如实呈现，
  **不就地改**（改了 `content_hash` 就不是冻结集了），高估声明写进报告的"已知限制"。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = ["LEVELS", "SEMS", "Cell", "Grid", "build_grid", "recompute_struct_labels"]

LEVELS: Final[tuple[str, ...]] = ("easy", "medium", "hard", "extra")
SEMS: Final[tuple[str, ...]] = ("low", "medium", "high")


@dataclass(slots=True)
class Cell:
    difficulty_struct: str
    difficulty_semantic: str
    total: int = 0
    passed: int = 0
    attribution: Counter[str] = field(default_factory=Counter)

    @property
    def pass_rate(self) -> float | None:
        return None if self.total == 0 else self.passed / self.total

    def as_row(self) -> dict[str, Any]:
        return {
            "struct": self.difficulty_struct,
            "semantic": self.difficulty_semantic,
            "total": self.total,
            "passed": self.passed,
            "pass_rate": None if self.pass_rate is None else round(self.pass_rate, 4),
            "attribution": dict(self.attribution),
        }


@dataclass(slots=True)
class Grid:
    cells: dict[tuple[str, str], Cell]
    #: 分母口径：§C.4.1 "EX 的分母不含应拒答题"。
    scored_total: int = 0
    scored_passed: int = 0
    attribution: Counter[str] = field(default_factory=Counter)

    def cell(self, struct: str, semantic: str) -> Cell:
        return self.cells[(struct, semantic)]

    @property
    def ex(self) -> float | None:
        return None if self.scored_total == 0 else self.scored_passed / self.scored_total

    def matrix(self) -> list[list[dict[str, Any]]]:
        return [[self.cell(s, m).as_row() for m in SEMS] for s in LEVELS]

    def unattributed_share(self) -> float:
        total = sum(self.attribution.values())
        return 0.0 if total == 0 else self.attribution.get("unattributed", 0) / total


def recompute_struct_labels(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """I-2 的复算：在**未注入**的 `gold_sql` 上重跑 `layering.classify_struct`。

    返回不一致项（空列表 = 冻结标签与上游代码口径逐字一致）。
    """
    import layering  # data/generator/layering.py（I-1 的唯一实现，W1A 归属、只读复用）

    drift: list[str] = []
    for case in cases:
        sql = case.get("gold_sql")
        if not sql:
            continue
        expect = case.get("difficulty_struct")
        got = layering.classify_struct(str(sql))["difficulty_struct"]
        if expect != got:
            drift.append(f"{case.get('case_id')}: 冻结 {expect} vs 复算 {got}")
    return drift


def build_grid(
    cases: Iterable[Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
) -> Grid:
    """按冻结标签铺 12 格。

    `results[case_id]` 需含：`scored`（是否进 EX 分母）、`passed`、`category`（归因）。
    未跑到的用例（缺 results 项）**不进分母**，单独由调用方以"未覆盖"呈现 ——
    把"没跑"混进"跑挂"是评测报告最容易被误读的一处。
    """
    cells = {(s, m): Cell(s, m) for s in LEVELS for m in SEMS}
    grid = Grid(cells=cells)
    for case in cases:
        struct = str(case.get("difficulty_struct") or "")
        semantic = str(case.get("difficulty_semantic") or "")
        if struct not in LEVELS or semantic not in SEMS:
            continue
        cell = cells[(struct, semantic)]
        res = results.get(str(case.get("case_id")))
        if res is None or not res.get("scored"):
            continue
        cell.total += 1
        grid.scored_total += 1
        if res.get("passed"):
            cell.passed += 1
            grid.scored_passed += 1
        else:
            category = str(res.get("category") or "unattributed")
            cell.attribution[category] += 1
            grid.attribution[category] += 1
    return grid
