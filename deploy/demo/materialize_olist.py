"""Olist 语义包物化 + RLS 一致性 + T_B 金丝雀隔离读数。

**必须在 api 容器内跑**（容器里有 `DATABASE_URL` / `ANALYTICS_DB_URL` 与 `/semantic`）：

    docker compose -f deploy/docker-compose.yml exec -T api \
      python - < deploy/demo/materialize_olist.py

为什么写死 Olist 包：容器默认 `SEMANTIC_BUNDLE_PATH` 仍是合成包。若本脚本读
settings，就会给合成资产派生 GRANT/POLICY、给合成表写 docs，而 Olist 五个视图
一条策略都没有 —— app_ro 读数还可能“看起来正常”。所以这里只认
`/semantic/bundle_olist_2018.yaml`，并用版本号 + 资产集合做前置门。

T_B=0 在库里本来平凡成立（沙箱只有 T_A 行）。本脚本每张 `o_*` 各插 1 行
`tenant_id='T_B'` 金丝雀，再读：无 GUC=0 / T_A=原始行数 / T_B=每表 1；采完删除并复核。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from typing import Any, Final

import psycopg

BUNDLE_PATH: Final[str] = "/semantic/bundle_olist_2018.yaml"
EXPECTED_VERSION: Final[str] = "2026.10.27.1"
EXPECTED_ASSETS: Final[frozenset[str]] = frozenset(
    {"v_o_orders", "v_o_order_items", "v_o_products", "v_o_payments", "v_o_reviews"}
)
EXPECTED_ROWS: Final[dict[str, int]] = {
    "v_o_orders": 99_441,
    "v_o_order_items": 112_650,
    "v_o_products": 32_951,
    "v_o_payments": 103_886,
    "v_o_reviews": 99_224,
}
CANARY_TENANT: Final[str] = "T_B"
CANARY_ROWS: Final[dict[str, dict[str, Any]]] = {
    "o_orders": {"tenant_id": CANARY_TENANT, "order_id": "canary_order_1"},
    "o_order_items": {
        "tenant_id": CANARY_TENANT,
        "order_id": "canary_order_1",
        "order_item_id": 1,
    },
    "o_products": {"tenant_id": CANARY_TENANT, "product_id": "canary_product_1"},
    "o_payments": {
        "tenant_id": CANARY_TENANT,
        "order_id": "canary_order_1",
        "payment_sequential": 1,
    },
    "o_reviews": {
        "tenant_id": CANARY_TENANT,
        "review_id": "canary_review_1",
        "order_id": "canary_order_1",
    },
}
_SET_GUC = (
    "SELECT set_config('app.tenant_id', %s, true), "
    "set_config('app.shop_ids', '', true)"
)


def _libpq_url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _load_olist_bundle() -> Any:
    from app.semantics.loader import load_bundle

    loaded = load_bundle(BUNDLE_PATH)
    version = str(loaded.bundle.meta.version)
    assets = {asset.physical_asset for asset in loaded.bundle.assets}
    if version != EXPECTED_VERSION:
        raise SystemExit(f"包版本不符：{version!r} != {EXPECTED_VERSION!r}（疑似合成包）")
    if assets != EXPECTED_ASSETS:
        raise SystemExit(f"资产集合不符：{sorted(assets)} != {sorted(EXPECTED_ASSETS)}")
    return loaded


def _counts(dsn: str, tenant: str | None) -> dict[str, int]:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.transaction():
            if tenant is not None:
                conn.execute(_SET_GUC, (tenant,)).fetchone()
            return {
                view: int(conn.execute(f"SELECT count(*) FROM app.{view}").fetchone()[0])
                for view in EXPECTED_ROWS
            }


def _insert_canaries(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute(_SET_GUC, (CANARY_TENANT,)).fetchone()
            for table, row in CANARY_ROWS.items():
                columns = ", ".join(row)
                placeholders = ", ".join(["%s"] * len(row))
                conn.execute(
                    f"INSERT INTO app.{table} ({columns}) VALUES ({placeholders})",
                    tuple(row.values()),
                )


def _delete_canaries(dsn: str) -> None:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute(_SET_GUC, (CANARY_TENANT,)).fetchone()
            for table, row in CANARY_ROWS.items():
                where = " AND ".join(f"{column} = %s" for column in row)
                conn.execute(
                    f"DELETE FROM app.{table} WHERE {where}",
                    tuple(row.values()),
                )


def _embedder() -> Any:
    from app.core.config import Settings
    from app.retrieval.dense import OllamaEmbedder

    settings = Settings()
    embedder = OllamaEmbedder(
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dim=settings.EMBEDDING_DIM,
        timeout_s=float(settings.EMBEDDING_TIMEOUT_SECONDS),
        cache=None,
    )

    def run(texts: list[str]) -> list[list[float]]:
        return asyncio.run(embedder.embed(texts))

    return run


def _tokenizer() -> Any:
    from app.retrieval.tokenizer import tsvector_source

    return lambda text: tsvector_source(text).split()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 物化 + RLS 一致性 + 金丝雀读数")
    parser.add_argument("--no-embed", action="store_true", help="跳过 embed_doc 派生")
    args = parser.parse_args(argv)

    rw_dsn = os.environ.get("DATABASE_URL")
    ro_dsn = os.environ.get("ANALYTICS_DB_URL")
    if not rw_dsn or not ro_dsn:
        raise SystemExit("缺 DATABASE_URL / ANALYTICS_DB_URL —— 本脚本应在 api 容器内跑")
    rw = _libpq_url(rw_dsn)
    ro = _libpq_url(ro_dsn)

    from app.semantics.materialize import (
        assert_grant_policy_consistency,
        content_sha256,
        materialize,
    )

    loaded = _load_olist_bundle()
    content_hash = "sha256:" + content_sha256(BUNDLE_PATH)
    embed_status = "skipped"
    try:
        if args.no_embed:
            report = materialize(
                loaded, dsn=rw, with_policy=True, content_hash=content_hash
            )
        else:
            try:
                report = materialize(
                    loaded,
                    dsn=rw,
                    tokenizer=_tokenizer(),
                    embedder=_embedder(),
                    with_policy=True,
                    content_hash=content_hash,
                )
                embed_status = report.embedding_status
            except Exception as exc:  # noqa: BLE001 - Ollama 不可用 = 如实降级
                print(f"[warn] embedding 失败，退回无 embed_doc 物化：{exc}", file=sys.stderr)
                report = materialize(
                    loaded, dsn=rw, with_policy=True, content_hash=content_hash
                )
                embed_status = f"fallback:{report.embedding_status}"
    except Exception as exc:  # noqa: BLE001 - 物化失败必须整单失败
        print(f"[error] materialize 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    with psycopg.connect(rw, connect_timeout=10) as conn:
        consistency = assert_grant_policy_consistency(conn, loaded)

    readings: dict[str, dict[str, int]] = {}
    cleanup: dict[str, dict[str, int]] = {}
    failure: str | None = None
    try:
        try:
            _insert_canaries(rw)
        except Exception as exc:  # noqa: BLE001 - 金丝雀失败必须如实落进 JSON
            failure = f"金丝雀插入失败：{type(exc).__name__}: {exc}"
        else:
            readings = {
                "no_guc": _counts(ro, None),
                "T_A": _counts(ro, "T_A"),
                "T_B": _counts(ro, CANARY_TENANT),
            }
            if any(value != 0 for value in readings["no_guc"].values()):
                failure = f"无 GUC 读数不为 0：{readings['no_guc']}"
            elif readings["T_A"] != EXPECTED_ROWS:
                failure = f"T_A 读数不符：{readings['T_A']} != {EXPECTED_ROWS}"
            elif any(value != 1 for value in readings["T_B"].values()):
                failure = f"T_B 金丝雀读数不是每表 1：{readings['T_B']}"
    finally:
        try:
            _delete_canaries(rw)
        except Exception as exc:  # noqa: BLE001 - 清理失败优先于其它失败上报
            failure = f"金丝雀清理失败：{type(exc).__name__}: {exc}"
        cleanup = {
            "T_A": _counts(ro, "T_A"),
            "T_B": _counts(ro, CANARY_TENANT),
        }
        if failure is None and cleanup["T_A"] != EXPECTED_ROWS:
            failure = f"清理后 T_A 未回原值：{cleanup['T_A']}"
        if failure is None and any(value != 0 for value in cleanup["T_B"].values()):
            failure = f"清理后 T_B 不为 0：{cleanup['T_B']}"

    payload = {
        "bundle": {"path": BUNDLE_PATH, "version": str(loaded.bundle.meta.version)},
        "materialize": {
            "version": report.version,
            "grant_policy_executed": report.grant_policy_executed,
            "embedding_status": embed_status,
            "tsv_status": report.tsv_status,
            "warnings": list(report.warnings),
        },
        "consistency": {
            "consistent": consistency.consistent,
            "checked_assets": consistency.checked_assets,
            "mismatches": list(consistency.mismatches),
        },
        "canaries": {table: dict(row) for table, row in CANARY_ROWS.items()},
        "expected_rows": EXPECTED_ROWS,
        "readings": readings,
        "cleanup": cleanup,
        "ok": failure is None and consistency.consistent,
        "failure": failure,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not consistency.consistent:
        return 1
    return 0 if failure is None else 1


if __name__ == "__main__":
    sys.exit(main())
