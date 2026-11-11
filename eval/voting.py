"""按执行结果做多数投票（ADR-11 N 路候选的评测侧投影，U-183 / P2）。

零依赖、纯函数、确定性 tie-break。⚠️ 边界写清楚：

* 本模块只做**结果哈希多数投票**，不生成候选、不执行 SQL、不改 prompt、不改图结构；
* 候选来源可以是 `SqlOutcome.candidates`（单次请求 N 路），也可以是多次独立批；
* 三批独立采样 ≠ 单次请求 N 路，`probe_u183_voting_upper.py` 的 85.26% 是
  **跨批采样 + 绕过闸门**的上界，不是真实单链路读数，不得当成达标证据。

复算：``python -m pytest -q backend/tests/eval/test_voting.py``
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

__all__ = ["VoteResult", "result_digest", "vote_by_result"]


class VoteResult(dict[str, Any]):
    """投票结果（dict 形状便于直接落 JSON，缺值回空不编值）。"""


def result_digest(rows: Any) -> str:
    """把结果表行稳定序列化成摘要；行内类型差异按原样参与，不悄悄归一。"""
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def vote_by_result(candidates: list[dict[str, Any]]) -> VoteResult:
    """按执行结果哈希多数选臂。

    ``candidates`` 每项需含 ``digest``（``None`` 表示该臂执行失败，不参与投票）；
    可选 ``equivalent``（仅用于回报，不参与选臂 —— 选臂不许偷看 gold）。

    并列时取**索引最小**的臂，保证可复算；全臂失败时返回 ``winner=None``。
    """
    valid = [(i, c["digest"]) for i, c in enumerate(candidates)
             if c.get("digest") is not None]
    if not valid:
        return VoteResult(winner=None, vote_size=0, n_arms=len(candidates),
                          n_valid=0, n_distinct=0, tied=False, tie_size=0)
    counts: Counter[str] = Counter(d for _, d in valid)
    top = counts.most_common(1)[0][1]
    tied = sum(1 for _, n in counts.most_common() if n == top) > 1
    winner_digest = next(d for _, d in valid if counts[d] == top)
    winner = next(i for i, d in valid if d == winner_digest)
    winners = [c for i, c in enumerate(candidates) if c.get("digest") == winner_digest]
    return VoteResult(
        winner=winner,
        winner_digest=winner_digest,
        vote_size=top,
        n_arms=len(candidates),
        n_valid=len(valid),
        n_distinct=len(counts),
        tied=tied,
        tie_size=sum(1 for _, n in counts.most_common() if n == top) if tied else 1,
        arms_equivalent=[bool(c.get("equivalent")) for c in winners],
    )
