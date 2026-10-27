"""P0 写保护：Olist 轨碰不到合成冻结件（W1，`docs/07 §4.8` 的 `U-143`）。

最强形态不是"我们列了四条路径"，而是**直接拿禁止调用的那两个构建器的输出常量**来试：
`build_frozen_set.OUT_DATASET` / `OUT_MANIFEST`、`build_gold_seed.DATASET` / `OUT`。
哪一天谁改了那些常量，这里会跟着变红，而不是悄悄放行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"
for _p in (str(REPO_ROOT), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import build_frozen_set as bfs  # noqa: E402
import build_gold_seed as bgs  # noqa: E402
from eval.olist.build_dataset import (  # noqa: E402
    FROZEN_PATHS,
    OLIST_ROOT,
    FrozenWriteError,
    guard_output_path,
    write_json,
)

#: 禁止调用的两个构建器**实际落盘的四个路径**（不是另抄一份清单）。
FORBIDDEN_BUILDER_OUTPUTS = {
    "build_frozen_set.OUT_DATASET": bfs.OUT_DATASET,
    "build_frozen_set.OUT_MANIFEST": bfs.OUT_MANIFEST,
    "build_gold_seed.DATASET": bgs.DATASET,
    "build_gold_seed.OUT": bgs.OUT,
}

#: `_bootstrap` 运行时真正拿来做 N-13 验真的三个常量。
BOOTSTRAP_FROZEN_INPUTS = {
    "DATASET_PATH": _bootstrap.DATASET_PATH,
    "GOLD_SEED_PATH": _bootstrap.GOLD_SEED_PATH,
    "RED_TEAM_PATH": _bootstrap.RED_TEAM_PATH,
}


def test_frozen_paths_cover_every_forbidden_builder_output() -> None:
    guarded = {p.resolve() for p in FROZEN_PATHS}
    for label, raw in FORBIDDEN_BUILDER_OUTPUTS.items():
        assert Path(raw).resolve() in guarded, f"{label} 不在守卫清单里：{raw}"


def test_frozen_paths_cover_bootstrap_verification_inputs() -> None:
    guarded = {p.resolve() for p in FROZEN_PATHS}
    for label, raw in BOOTSTRAP_FROZEN_INPUTS.items():
        assert Path(raw).resolve() in guarded, f"{label} 不在守卫清单里：{raw}"


@pytest.mark.parametrize(
    "label,raw", sorted(FORBIDDEN_BUILDER_OUTPUTS.items()), ids=lambda v: str(v).split(".")[0]
)
def test_writing_forbidden_builder_output_raises(label: str, raw: str) -> None:
    before = Path(raw).read_bytes() if Path(raw).exists() else None

    with pytest.raises(FrozenWriteError):
        guard_output_path(raw)
    with pytest.raises(FrozenWriteError):
        write_json(raw, {"should": "never land"})

    after = Path(raw).read_bytes() if Path(raw).exists() else None
    assert after == before, f"{label} 被写动了"


@pytest.mark.parametrize(
    "escape",
    [
        "../dataset_v1_frozen.json",
        "../gold_query_seed_v1.json",
        "../MANIFEST_v1.json",
        "../red_team_cases_v1.json",
        "../olist_escape.json",
        "../../data/olist/olist_sandbox.db",
        "../olist/../../eval/dataset_v1_frozen.json",
    ],
)
def test_relative_escape_from_olist_root_raises(escape: str) -> None:
    with pytest.raises(FrozenWriteError):
        guard_output_path(OLIST_ROOT / escape)


def test_olist_local_output_is_accepted() -> None:
    target = guard_output_path(OLIST_ROOT / "gold10_results.json")
    assert target == (OLIST_ROOT / "gold10_results.json").resolve()


def test_write_json_roundtrip_inside_olist_root() -> None:
    probe = OLIST_ROOT / "_write_guard_probe.json"
    try:
        written = write_json(probe, {"ok": True, "n": 10})
        assert written == probe.resolve()
        raw = probe.read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r\n" not in raw
        assert "ok" in probe.read_text(encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)


def test_olist_root_itself_is_not_writable() -> None:
    with pytest.raises(FrozenWriteError):
        guard_output_path(OLIST_ROOT)
