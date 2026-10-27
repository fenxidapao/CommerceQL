#!/usr/bin/env python
"""Olist 轨的落盘守卫 —— W1 的 P0 写保护。

归属窗口：W1 实施窗（`docs/07 §4.8` 的 `U-143`）。

为什么需要它
------------
`eval/build_frozen_set.py` 的 `OUT_DATASET` / `OUT_MANIFEST` 与
`eval/build_gold_seed.py` 的 `DATASET` / `OUT` 都是**写死常量**。
在 Olist 轨误调这两者的 `main()` / `build()` 会直接覆盖合成冻结集。
⇒ 本模块是 Olist 侧**唯一**的落盘入口：任何输出先过 `guard_output_path()`。

边界
----
· 只复用 `build_frozen_set` 的纯函数，不新写第二份哈希口径（AGENTS.md §5 第 1 条）。
· **禁止**调用 `build_frozen_set.main()` / `build_gold_seed.main()`。
· W1 的输出只落 `eval/olist/**`；冻结件由 W2 在同一个目录下生成。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
REPO_ROOT = EVAL_ROOT.parent

OLIST_ROOT = HERE

#: 合成轨的四个冻结件 —— 任何一条被 Olist 轨写到都是事故。
FROZEN_PATHS: tuple[Path, ...] = (
    EVAL_ROOT / "dataset_v1_frozen.json",
    EVAL_ROOT / "gold_query_seed_v1.json",
    EVAL_ROOT / "MANIFEST_v1.json",
    EVAL_ROOT / "red_team_cases_v1.json",
)

_RESOLVED_FROZEN = tuple(p.resolve() for p in FROZEN_PATHS)
_RESOLVED_OLIST_ROOT = OLIST_ROOT.resolve()


class FrozenWriteError(RuntimeError):
    """Olist 轨试图写合成冻结件，或写到 `eval/olist/` 之外的路径。"""


def guard_output_path(path: str | os.PathLike[str]) -> Path:
    """把输出路径解析成绝对路径；不合法就抛 `FrozenWriteError`。

    两条判据：① 不得等于四个冻结件之一；② 必须是 `eval/olist/` 的**严格后代**。
    用 `resolve()` 先归一化，符号链接与 `..` 都逃不掉。
    """
    target = Path(path).resolve()
    if target in _RESOLVED_FROZEN:
        raise FrozenWriteError(
            f"拒绝写入合成冻结件：{target}\n"
            f"Olist 轨只能写 {_RESOLVED_OLIST_ROOT} 之下；冻结件由 W2 在 eval/olist/ 下生成。"
        )
    if _RESOLVED_OLIST_ROOT not in target.parents:
        raise FrozenWriteError(
            f"拒绝写入 eval/olist 之外的路径：{target}\n"
            f"允许的根 = {_RESOLVED_OLIST_ROOT}"
        )
    return target


def write_json(path: str | os.PathLike[str], obj: Any, *, indent: int = 2) -> Path:
    """经守卫落一份 JSON（UTF-8、LF、末尾换行）。"""
    target = guard_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
        fh.write("\n")
    return target


def load_frozen_pure():
    """取 `build_frozen_set` 的纯函数入口（需要 `eval/` 已在 `sys.path` 上）。

    只借 `tenant_wrap` / `result_hash` / `case_content_hash` —— 不碰它的 `main()`。
    """
    try:
        import build_frozen_set
    except ModuleNotFoundError as exc:  # pragma: no cover - 只在调用方漏 bootstrap 时触发
        raise ModuleNotFoundError(
            "build_frozen_set 不可导入：请先把 <repo>/eval 放进 sys.path"
            "（`eval/_bootstrap.py::bootstrap()` 会做这件事）"
        ) from exc
    return build_frozen_set
