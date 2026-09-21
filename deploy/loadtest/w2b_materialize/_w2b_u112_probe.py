"""W2B · `U-112` 取证探针（一次性，**不属于交付物**；放仓库外故不入 git）。

三问：
  A. 复核 W7 的读数（`app.embed_doc` 行数 / embedding NULL / tsv 非空 / 租户 / bundle）
  B. **实测** `dense.py` 那条 SQL 在向量列全 NULL 时的返回形态（是否真出 NULL 分数）
  C. 探测 issue② 的前置条件：宿主机 Ollama 是否可答、`bge-m3` 是否在册

跑法：python _w2b_u112_probe.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

RO_DSN = "postgresql://app_ro:app_ro_pwd@localhost:5432/ecom"
OLLAMA = "http://127.0.0.1:11434"


def _dump(title: str, cur, sql: str, params=None) -> list[tuple]:
    # ⚠️ 不做 `:name` → `%(name)s` 的朴素替换：本文件的 SQL 直写 `%(name)s`。
    #    原因见 part_b 开头的说明（`(:vector)::vector` 会被替换循环吃掉）。
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    rows = cur.fetchall()
    print(f"\n--- {title}")
    print("    cols:", cols)
    for r in rows:
        print("    ", r)
    if not rows:
        print("     <0 rows>")
    return rows


def part_a() -> None:
    print("=" * 78)
    print("A. app.embed_doc 读数复核（W7 声明：197 行 / embedding NULL=197 / tsv 非空=0）")
    print("=" * 78)
    with psycopg.connect(RO_DSN, connect_timeout=5) as conn, conn.cursor() as cur:
        _dump(
            "A1 总数与分 kind",
            cur,
            """
            SELECT count(*) AS total_rows,
                   count(embedding) AS emb_not_null,
                   count(tsv) AS tsv_not_null,
                   count(*) FILTER (WHERE tsv IS NOT NULL AND tsv::text <> '') AS tsv_nonempty
            FROM app.embed_doc
            """,
        )
        _dump(
            "A2 分 kind（同口径）",
            cur,
            """
            SELECT kind, count(*) AS rows,
                   count(embedding) AS emb_not_null,
                   count(*) FILTER (WHERE tsv IS NOT NULL AND tsv::text <> '') AS tsv_nonempty
            FROM app.embed_doc
            GROUP BY kind ORDER BY kind
            """,
        )
        _dump(
            "A3 作用域（tenant_id / bundle_version）",
            cur,
            """
            SELECT tenant_id, bundle_version, count(*)
            FROM app.embed_doc
            GROUP BY tenant_id, bundle_version ORDER BY 3 DESC
            """,
        )
        _dump("A4 pgvector 扩展", cur, "SELECT extname, extversion FROM pg_extension ORDER BY 1")
        _dump(
            "A5 向量列类型",
            cur,
            """
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema='app' AND table_name='embed_doc'
            ORDER BY ordinal_position
            """,
        )


def part_b() -> None:
    print("\n" + "=" * 78)
    print("B. dense.py 那条 SQL 的实测返回形态（全 NULL 向量列下是否真出 NULL 分数）")
    print("=" * 78)
    print("   ⚠️ 注意：`(:vector)::vector` 里 `:vector` 出现两次 —— 朴素的")
    print("      `sql.replace(':vector', '%(vector)s')` 会把 `::vector` 也吃掉，")
    print("      产出 `(%(vector)s):%(vector)s` ⇒ 语法错误。故本探针用 `%(vector)s` 直写。")
    vec = "[" + ",".join(["0.0"] * 1024) + "]"
    sql = """
        SELECT ref, kind,
               1 - (embedding <=> (%(vector)s)::vector) AS score
        FROM app.embed_doc
        WHERE bundle_version = %(bundle_version)s
          AND tenant_id IN (%(tenant_id)s, '*')
        ORDER BY embedding <=> (%(vector)s)::vector, doc_id
        LIMIT %(limit)s
    """
    with psycopg.connect(RO_DSN, connect_timeout=5) as conn, conn.cursor() as cur:
        rows = _dump(
            "B1 原样执行（app_ro 视角，tenant=t1，bundle=2026.09.14.1）",
            cur,
            sql,
            {"vector": vec, "bundle_version": "2026.09.14.1", "tenant_id": "t1", "limit": 5},
        )
        nulls = sum(1 for r in rows if r[2] is None)
        print(f"\n    ⇒ 返回 {len(rows)} 行，其中 score IS NULL = {nulls} 行")
        if nulls:
            print("    ⇒ 实测成立：`float(row['score'])` 会拿到 None → TypeError（与 W7 的栈一致）")

        # B2：加 IS NOT NULL 过滤后的形态（评估"过滤 vs 降级"两条路各自的后果）
        _dump(
            "B2 若加 `AND embedding IS NOT NULL`（对照：会变成 0 行 = 静默空）",
            cur,
            sql.replace(
                "AND tenant_id IN (%(tenant_id)s, '*')",
                "AND tenant_id IN (%(tenant_id)s, '*') AND embedding IS NOT NULL",
            ),
            {"vector": vec, "bundle_version": "2026.09.14.1", "tenant_id": "t1", "limit": 5},
        )
        # B3：稀疏侧在 tsv 全 NULL 时的形态（确认它不会出 NULL 分数）
        _dump(
            "B3 稀疏侧（tsv 全 NULL）—— `@@` 已过滤，故不会出 NULL 分数",
            cur,
            """
            SELECT ref, kind, ts_rank_cd(tsv, query, 32) AS score
            FROM app.embed_doc, to_tsquery('simple', %(terms)s) query
            WHERE tsv @@ query
              AND bundle_version = %(bundle_version)s
              AND tenant_id IN (%(tenant_id)s, '*')
            ORDER BY score DESC, doc_id
            LIMIT %(limit)s
            """,
            {"terms": "'销售'", "bundle_version": "2026.09.14.1", "tenant_id": "t1", "limit": 5},
        )


def part_c() -> None:
    print("\n" + "=" * 78)
    print("C. issue② 前置条件：宿主机 Ollama / bge-m3")
    print("=" * 78)
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=4) as resp:
            body = json.loads(resp.read().decode())
        names = [m.get("name") for m in body.get("models", [])]
        print(f"    Ollama 可达 ✅  模型在册 {len(names)} 个")
        for n in names:
            print("      -", n)
        hit = [n for n in names if n and n.startswith("bge-m3")]
        print(f"\n    bge-m3 {'在册 ✅' if hit else '**不在册** ❌'}  {hit}")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"    Ollama **不可达** ❌  {type(exc).__name__}: {exc}")
        print("    ⇒ 物化灌向量（issue②）当前**跑不了**：embedder 侧没有可用的 Ollama 端点。")


if __name__ == "__main__":
    part_a()
    part_b()
    part_c()
