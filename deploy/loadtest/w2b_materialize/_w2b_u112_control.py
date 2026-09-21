"""W2B · `U-112` 正向对照（一次性探针，**不属于交付物**）。

## 为什么不用 git stash 做对照

本会话里 `git stash push` 被 harness 杀在半途，之后 `.git/refs` 在本进程视图中消失
（`FileNotFoundError`），git 因此报 "not a git repository"。改用**进程内 monkeypatch**
做对照：不碰仓库、不碰工作区文件，结论同样硬。

## 对照设计

同一份 `pgvector` 取数夹具（作用域内 1 行、`score = None` = W7 实测的 NULL 分数形态），
只换 `PgVectorStore._row_to_hit` 的实现：

- **A 组（修复前）**：`score=float(row["score"])` 无条件转换 ⇒ 应抛 `TypeError`；
  而 `TypeError` **不是** `EmbeddingUnavailable` ⇒ `search.py` 的
  `except EmbeddingUnavailable` 抓不到 ⇒ 逃出 `link` ⇒ runner 兜底 `error(INTERNAL)`。
- **B 组（修复后）**：`_row_to_hit` 返回 `None` ⇒ `topk` 抛 `EmbeddingUnavailable`
  ⇒ 被既有出口接住 ⇒ `degraded(embedding_unavailable, sparse_only)`。

两组的差别必须**只来自实现本身**，故夹具、向量、作用域参数完全相同。

跑法：python _w2b_u112_control.py
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
sys.path.insert(0, str(REPO / "backend"))

from app.core.enums import RetrievalMode  # noqa: E402
from app.retrieval import dense as dense_mod  # noqa: E402
from app.retrieval.dense import EmbeddingUnavailable, PgVectorStore, VectorHit  # noqa: E402
from app.retrieval.search import RetrievalService  # noqa: E402

#: W7 活体实测的形态：作用域内有行，但 `embedding IS NULL` ⇒ `1 - (NULL <=> v)` = NULL
NULL_ROWS: list[dict[str, Any]] = [{"ref": "order_paid", "kind": "asset", "score": None}]

VEC = [1.0, 0.0, 0.0, 0.0]
SCOPE = {"tenant_id": "t1", "bundle_version": "2026.09.14.1", "limit": 5}

#: 类体里定义的那个 staticmethod 描述符 —— A 组打完补丁后用它还原
ORIGINAL_ROW_TO_HIT = PgVectorStore.__dict__["_row_to_hit"]


def old_row_to_hit(row: Mapping[str, Any]) -> VectorHit:
    """修复前的实现（`dense.py:279` 那一行，逐字）。"""
    return VectorHit(
        ref=str(row["ref"]),
        kind=str(row["kind"]),
        score=float(row["score"]),
    )


async def fetch_rows(sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    return NULL_ROWS


def make_service() -> RetrievalService:
    """真 `RetrievalService` + 真 `PgVectorStore`（只把 embedder 换成常量替身）。"""
    from app.retrieval.sparse import SparseSearch
    from tests.unit._retrieval_fixture import load_bundle_view

    class FakeEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [VEC for _ in texts]

    class EmptySparse:
        async def search(self, question: str, **kwargs: Any) -> list[Any]:
            return []

    return RetrievalService(
        view=load_bundle_view(),
        embedder=FakeEmbedder(),
        vector_store=PgVectorStore(fetch_rows),
        sparse=EmptySparse(),  # type: ignore[arg-type]
        weights={"dense": 0.40, "sparse": 0.35, "value": 0.15, "graph": 0.10},
        rrf_k=60,
        cache=None,
    )


async def group_a() -> None:
    print("=" * 78)
    print("A 组 · 修复前（`score=float(row['score'])`）")
    print("=" * 78)
    dense_mod.PgVectorStore._row_to_hit = staticmethod(old_row_to_hit)  # type: ignore[method-assign]
    try:
        await PgVectorStore(fetch_rows).topk(VEC, **SCOPE)
    except BaseException as exc:  # noqa: BLE001 — 就是要看异常类型
        caught_by_existing_exit = isinstance(exc, EmbeddingUnavailable)
        print(f"  topk 抛出      : {type(exc).__name__}: {exc}")
        print(f"  是 EmbeddingUnavailable 吗 : {caught_by_existing_exit}")
        print(f"  ⇒ search.py 的 `except EmbeddingUnavailable` 能接住吗 : {caught_by_existing_exit}")
        if not caught_by_existing_exit:
            print("  ⇒ 接不住 ⇒ 逃出 link ⇒ runner 兜底 error(INTERNAL)（= W7 活体栈）")
    else:
        print("  topk 没抛 —— 与预期不符，停止后续判定")
        return

    print()
    print("  [服务级] 真 RetrievalService.search_full（同夹具、同作用域）")
    try:
        service = make_service()
        ctx = _identity()
        result = await service.search_full("订单分析", ctx, RetrievalMode.HYBRID)
    except BaseException as exc:  # noqa: BLE001
        print(f"     ⇒ 服务层抛出 {type(exc).__name__} —— 没有降级载荷可用")
        print(f"       （连 degraded 都没机会发，这就是 'INTERNAL' 的形状）")
    else:
        print(f"     ⇒ 竟然返回了：mode={result.mode} degraded={result.degraded}")


async def group_b() -> None:
    print()
    print("=" * 78)
    print("B 组 · 修复后（当前工作区实现）")
    print("=" * 78)
    dense_mod.PgVectorStore._row_to_hit = ORIGINAL_ROW_TO_HIT  # type: ignore[method-assign]
    try:
        await PgVectorStore(fetch_rows).topk(VEC, **SCOPE)
    except EmbeddingUnavailable as exc:
        print(f"  topk 抛出      : EmbeddingUnavailable: {exc}")
        print("  ⇒ search.py 能接住 ✅")
    except BaseException as exc:  # noqa: BLE001
        print(f"  topk 抛出      : {type(exc).__name__}: {exc}  ← 不该是别的类型")
        return
    else:
        print("  topk 没抛 —— 与预期不符")
        return

    print()
    print("  [服务级] 真 RetrievalService.search_full（同夹具、同作用域）")
    service = make_service()
    result = await service.search_full("订单分析", _identity(), RetrievalMode.HYBRID)
    print(f"     mode            = {result.mode}")
    print(f"     degraded        = {result.degraded}")
    print(f"     degraded_reason = {result.degraded_reason}")
    print(f"     action_taken    = {result.action_taken}")
    ok = (
        str(result.mode) == "sparse_only"
        and result.degraded
        and str(result.degraded_reason) == "embedding_unavailable"
    )
    print(f"     ⇒ 判据（mode=sparse_only 且 reason=embedding_unavailable）: {'满足 ✅' if ok else '不满足 ❌'}")


def _identity() -> Any:
    from app.core.contracts import IdentityContext, Role

    return IdentityContext(
        trace_id="ctl", task_id="ctl", session_id="ctl",
        tenant_id="t1", user_id="u1", role=Role.ANALYST,
    )


async def main() -> None:
    print(f"对照夹具：{len(NULL_ROWS)} 行，score=None（= embedding 全 NULL 时的 `1 - (NULL <=> v)`）")
    print()
    await group_a()
    await group_b()


if __name__ == "__main__":
    asyncio.run(main())
