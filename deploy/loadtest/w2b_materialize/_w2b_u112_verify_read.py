"""W2B · `U-112` 物化后的**独立读路径**自证（一次性脚本，不属于交付物）。

为什么要单独写：`_w2b_u112_materialize.py` 的自证只是 `count(embedding)`。
**计数 ≠ 可读**。本脚本用**生产实现**（`PgVectorStore` / `SparseSearch`）真打两条读路径：

1. 稠密：真调 Ollama `bge-m3` 生成查询向量 → `PgVectorStore.topk` → 断言有命中、分数非 NULL、降序；
2. 稀疏：`SparseSearch.search` → 断言有命中。

参数取生产装配值（`deps.py:468-469`：rank_normalization=32 / score_min=0.05）。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CommerceQL" / "backend"))
#: ⚠️ **必须最后插入**（`insert(0)` 后插者优先）：本脚本 import 同级目录的
#: `_w2b_u112_materialize`。若让 `ROOT` 优先，`deploy/w2b_materialize/` 的归档副本
#: 会静默去工作区根拿原件 ⇒ **归档不自足**（2026-09-21 实测：归档副本 import 到的是
#: 工作区根那份，`'w2b_materialize' in __file__ == False`）——原件一旦被删/换机就断。
sys.path.insert(0, str(HERE))

import psycopg  # noqa: E402
from _w2b_u112_materialize import VERSION, rw_dsn  # noqa: E402

from app.retrieval.dense import OllamaEmbedder, PgVectorStore  # noqa: E402
from app.retrieval.sparse import SparseSearch  # noqa: E402

TENANT = "*"
QUESTION = "销售额"
#: `:name` → `%(name)s`，**跳过** `::type` 类型转换（负向后顾：前一个字符不是冒号）。
#: ⚠️ 不能用 `str.replace` —— 它会把 `(:vector)::vector` 的第二段也换掉（历史实锤）。
NAMED = re.compile("(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def to_psycopg(sql: str) -> str:
    return NAMED.sub(lambda m: "%(" + m.group(1) + ")s", sql)


def fetch_factory():
    """`fetch(sql, params)` → psycopg 同步查询（与 deps.py 的生产 fetch 同契约）。"""
    conn = psycopg.connect(rw_dsn())

    async def fetch(sql: str, params: dict) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(to_psycopg(sql), params)  # type: ignore[arg-type]
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    return fetch, conn


def counts() -> tuple[int, int, int]:
    with psycopg.connect(rw_dsn()) as conn:
        total, emb, tsv = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE embedding IS NOT NULL),"
            " count(*) FILTER (WHERE tsv IS NOT NULL AND tsv::text <> '')"
            " FROM app.embed_doc WHERE bundle_version = %s",
            (VERSION,),
        ).fetchone()
    return total, emb, tsv


async def main() -> None:
    total, emb, tsv = counts()
    print(f"[0] 计数: 行数={total} | embedding 非空={emb} | tsv 非空={tsv}")
    assert total == emb == tsv, "物化未就绪，读路径自证无意义"
    print(f"    目标库={rw_dsn().rsplit('@', 1)[-1]} | 版本={VERSION} | 租户={TENANT!r}")

    fetch, conn = fetch_factory()
    try:
        print()
        print("[1] 稠密读路径（真 Ollama 查询向量 → PgVectorStore.topk）")
        embedder = OllamaEmbedder(
            base_url="http://127.0.0.1:11434", model="bge-m3", dim=1024, timeout_s=120
        )
        vec = (await embedder.embed([QUESTION]))[0]
        print(f"  查询向量 dim={len(vec)} | 前 3 维={[round(v, 5) for v in vec[:3]]}")
        dense_hits = await PgVectorStore(fetch).topk(
            vec, tenant_id=TENANT, bundle_version=VERSION, limit=5
        )
        print(f"  命中 {len(dense_hits)} 条：")
        for h in dense_hits:
            print(f"    {h.score:.6f}  [{h.kind}] {h.ref}")
        assert dense_hits, "稠密路径零命中 ⇒ 向量没进检索（物化没生效）"
        assert all(h.score is not None for h in dense_hits), "分数出现 NULL"
        scores = [h.score for h in dense_hits]
        assert scores == sorted(scores, reverse=True), f"未按分降序：{scores}"

        print()
        print("[2] 稀疏读路径（SparseSearch.search）")
        sparse_hits = await SparseSearch(
            fetch, rank_normalization=32, score_min=0.05
        ).search(QUESTION, tenant_id=TENANT, bundle_version=VERSION, limit=5)
        print(f"  命中 {len(sparse_hits)} 条：")
        for h in sparse_hits:
            print(f"    {h.score:.6f}  [{h.kind}] {h.ref}")
        assert sparse_hits, "稀疏路径零命中 ⇒ tsv 没进检索（物化没生效）"

        print()
        print("✅ 两条读路径都真通了（不是计数，是生产实现真打）")
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
