#!/usr/bin/env python
"""Gold Query 入库器（T-05；07 §11.7 **租户私有库**）。

三件事：读 `seeds` → 归一化 SQL 算 `ast_fingerprint` → 生成**幂等** INSERT 脚本。
本脚本**不连库、不读 `.env`**：写入由 `psql` 在容器内执行（消费见 `--sql-out`）。

⚠️ 泄漏风险（入库前必读）
`eval/gold_query_seed_v1.json` 的 `derived_from` 现读 = `eval/dataset_v1_frozen.json`。
把它当 few-shot、再用同一冻结集跑 EX = 把金标 SQL 喂进 prompt 去考同一批题，读数会虚高。
故每行 `source` 带 `case:<source_case_id>`，评测侧可据此排除该批题，或把该轮 EX 标注为「含泄漏」。

⚠️ 字段来源
`seeds` 里**没有** `ast_fingerprint`（现读 119/119 缺），而 `app.gold_query.ast_fingerprint` 是
NOT NULL 且进唯一键 `(ast_fingerprint, domain)` ⇒ 必须由本脚本按确定性规则算出，不能编。
归一化用 sqlglot（postgres 方言）；解析失败回落到空白归一，仍保持确定性。

用法（仓库根）：
    PYTHONUTF8=1 python tools/ingest_gold_query.py \
        --bundle-version 2026.10.16.2 --tenant T_A \
        --sql-out ../CommerceQL-archive/local/tmp_gold_query_ingest.sql
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = REPO_ROOT / "eval" / "gold_query_seed_v1.json"
DEFAULT_SQL_OUT = REPO_ROOT.parent / "CommerceQL-archive" / "local" / "tmp_gold_query_ingest.sql"

COLUMNS = (
    "gold_id",
    "tenant_id",
    "question",
    "sql",
    "domain",
    "verified_by",
    "verified_at",
    "source",
    "ast_fingerprint",
    "bundle_version",
)


def normalize_sql(sql: str) -> str:
    """确定性归一：能解析就按 sqlglot postgres 重排（`normalize=True`），否则空白归一。"""
    try:
        import sqlglot  # noqa: PLC0415 - 只在生成期需要，保持导入失败可降级
    except ImportError:
        return " ".join(sql.split())
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:  # noqa: BLE001 - 解析失败必须仍能算出一个稳定指纹
        return " ".join(sql.split())
    return str(tree.sql(dialect="postgres", normalize=True))


def ast_fingerprint(sql: str) -> str:
    digest = hashlib.sha256(normalize_sql(sql).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:40]}"


def lit(value: str) -> str:
    """SQL 字面量（seeds 里含 `'2026-08-01'` 这类引号，必须转义）。"""
    return "'" + str(value).replace("'", "''") + "'"


def build_rows(
    seeds: list[dict[str, Any]], *, tenant: str, bundle_version: str, verified_by: str
) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for seed in seeds:
        seed_id = str(seed.get("seed_id") or "").strip()
        question = str(seed.get("question") or "")
        sql = str(seed.get("gold_sql") or seed.get("sql") or "")
        domain = str(seed.get("domain") or "").strip()
        if not (seed_id and question and sql and domain):
            continue
        source = (
            "eval/gold_query_seed_v1.json#"
            f"{seed_id}(case:{seed.get('source_case_id') or 'unknown'})"
        )
        rows.append(
            (
                seed_id,
                tenant,
                question,
                sql,
                domain,
                verified_by,
                "now()",
                source,
                ast_fingerprint(sql),
                bundle_version,
            )
        )
    return rows


def render(rows: list[tuple[str, ...]]) -> str:
    body = ",\n    ".join(
        "("
        + ", ".join("now()" if v == "now()" else lit(v) for v in row)
        + ")"
        for row in rows
    )
    return (
        "BEGIN;\n"
        f"INSERT INTO app.gold_query ({', '.join(COLUMNS)})\nVALUES\n    {body}\n"
        "ON CONFLICT (ast_fingerprint, domain) DO NOTHING;\n"
        "COMMIT;\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gold Query 入库脚本生成器（不连库）")
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--tenant", default="T_A", help="租户私有库的 tenant_id（§11.7）")
    parser.add_argument(
        "--bundle-version",
        default="2026.10.16.2",
        help="必须等于 api 容器现挂语义包的 meta.version，否则 few_shots 召回不到",
    )
    parser.add_argument("--verified-by", default="owner-authorised-import-2026-11-06")
    parser.add_argument("--sql-out", type=Path, default=DEFAULT_SQL_OUT)
    args = parser.parse_args(argv)

    payload = json.loads(args.seed_file.read_text(encoding="utf-8"))
    seeds = payload.get("seeds") or []
    rows = build_rows(
        seeds,
        tenant=args.tenant,
        bundle_version=args.bundle_version,
        verified_by=args.verified_by,
    )

    args.sql_out.parent.mkdir(parents=True, exist_ok=True)
    args.sql_out.write_text(render(rows), encoding="utf-8")

    domains = Counter(row[4] for row in rows)
    fingerprints = {row[8] for row in rows}
    print(f"seeds_read={len(seeds)} rows_built={len(rows)} unique_fingerprint={len(fingerprints)}")
    print(f"domains={dict(domains)}")
    print(f"tenant={args.tenant} bundle_version={args.bundle_version}")
    print(f"[sql] {args.sql_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
