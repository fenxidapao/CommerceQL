"""Spider 电商类 7 库 523 题 -> 数据集 + 金标自执行读数（U-182，零出站、零 LLM、零写库）。

用法：

    python eval/spider/build_dataset.py --spider-root <...>/spider_data
    python eval/spider/build_dataset.py --check

金标真源 = `train_spider.json` 的 `query` 字段（Spider 官方发布）：

  1. `sql` 字段是结构树（`from`/`select`/`where` 的 dict），不是 SQL 文本，不用；
  2. `train_gold.sql` 有 8,659 行、含 `train_others` 的问题，与 7,000 行按下标对不齐，
     按行号取金标会错配，不用。

⚠️ 选库是本项目做的：全 166 库按强电商表名筛出 29 库，再取题数最多的 7 库。
   报告口径只能写「Spider 电商类子集（7/166 库，523 题）」并明写选择偏差，
   不得写「Spider dev 全量」（dev 段 20 库零电商表，已实测）。

⚠️ 比对器是本项目实现：官方 `evaluation.py` 不在盘（实测 `spider_data/` 与父目录均无）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
OUT_DATASET = HERE / "dataset_ecom7_v1.json"

DATASET_VERSION = "spider_ecom7_v1"
CREATED_AT = "2026-11-10"
U_ID = "U-182"
ROWS_CAP = 5000
TIMEOUT_S = 10.0

DBS: tuple[str, ...] = (
    "tracking_orders",
    "customers_and_invoices",
    "department_store",
    "cre_Drama_Workshop_Groups",
    "customers_and_addresses",
    "sakila_1",
    "tracking_share_transactions",
)

SELECTION_RULE = (
    "全 166 库按强电商表名（Customers/Orders/Products/Order_Items/Invoices/"
    "Shipments/Payments）命中数筛出 29 库（合计 1,576 题，全部在 train 段），"
    "再取题数最多的 7 库 = 523 题；选库由本项目做出，非 Spider 官方划分"
)
BIAS_NOTE = (
    "报告只能写「Spider 电商类子集（7/166 库，523 题）」并明写选库偏差；"
    "不得写「Spider dev 全量」——dev 段 20 库强电商表命中 0"
)
GOLD_RULE = (
    "gold_query = train_spider.json 的 query 字段（官方发布，523/523 非空且可自执行）；"
    "sql 字段为结构树 dict，不使用；train_gold.sql 8,659 行含 train_others、"
    "与 7,000 行按下标对不齐，不使用"
)
COMPARE_RULE = (
    "结果级集合比对：金标由本件 gold_query 现执行取行，模型结果与之比较；"
    "gold_query 含 ORDER BY 时按有序摘要比，否则按无序摘要比；"
    "比对器为本项目实现（官方 evaluation.py 不在盘），报告须写明"
)


def _norm_value(value: Any) -> Any:
    """把 sqlite 取值归一成可 json 化、可摘要的稳定形态。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, bytes):
        return "hex:" + value.hex()
    return str(value)


def _digest(rows: list[list[Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sorted_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def _db_path(spider_root: Path, db_id: str) -> Path:
    return spider_root / "database" / db_id / (db_id + ".sqlite")


def _exec(db_path: Path, sql: str) -> tuple[bool, str, list[list[Any]], int]:
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    deadline = time.monotonic() + TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
    try:
        cur = con.cursor()
        cur.execute(sql)
        fetched = cur.fetchmany(ROWS_CAP)
        cols = len(cur.description or ())
        return True, "", [[_norm_value(v) for v in row] for row in fetched], cols
    except Exception as exc:  # noqa: BLE001 - 探针要把任何失败都变成读数
        return False, type(exc).__name__ + ": " + str(exc)[:160], [], 0
    finally:
        con.close()


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build(spider_root: Path) -> dict[str, Any]:
    src = spider_root / "train_spider.json"
    if not src.is_file():
        raise SystemExit("缺 train_spider.json: " + str(src))
    raw = src.read_bytes()
    rows = json.loads(raw.decode("utf-8"))

    db_stats: dict[str, dict[str, Any]] = {}
    for db_id in DBS:
        path = _db_path(spider_root, db_id)
        if not path.is_file():
            raise SystemExit("缺 sqlite: " + str(path))
        blob = path.read_bytes()
        db_stats[db_id] = {
            "sqlite": str(path.relative_to(spider_root)).replace("\\", "/"),
            "sqlite_bytes": len(blob),
            "sqlite_sha256": hashlib.sha256(blob).hexdigest(),
            "cases": 0,
            "gold_ok": 0,
            "gold_fail": 0,
            "zero_rows": 0,
            "order_sensitive": 0,
        }

    cases: list[dict[str, Any]] = []
    for row in rows:
        db_id = row.get("db_id")
        if db_id not in db_stats:
            continue
        gold = str(row.get("query") or "").strip()
        ok, err, result, cols = _exec(_db_path(spider_root, db_id), gold)
        order_sensitive = "order by" in gold.lower()
        cases.append(
            {
                "case_id": "sp-%04d" % (len(cases) + 1),
                "db_id": db_id,
                "question": row.get("question"),
                "gold_query": gold,
                "gold_ok": ok,
                "gold_error": err,
                "gold_rows": len(result),
                "gold_cols": cols,
                "gold_order_sensitive": order_sensitive,
                "gold_digest_ordered": _digest(result),
                "gold_digest_sorted": _digest(_sorted_rows(result)),
            }
        )
        stat = db_stats[db_id]
        stat["cases"] += 1
        if ok:
            stat["gold_ok"] += 1
        else:
            stat["gold_fail"] += 1
        if ok and not result:
            stat["zero_rows"] += 1
        if order_sensitive:
            stat["order_sensitive"] += 1

    chash = "sha256:" + hashlib.sha256(_canon(cases).encode("utf-8")).hexdigest()
    return {
        "dataset_version": DATASET_VERSION,
        "dataset": "eval/spider/dataset_ecom7_v1.json",
        "created_at": CREATED_AT,
        "u_id": U_ID,
        "source": {
            "file": "train_spider.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "rows_total": len(rows),
            "dbs_total": 166,
            "subset_dbs": list(DBS),
            "subset_cases": len(cases),
            "selection_rule": SELECTION_RULE,
            "bias_note": BIAS_NOTE,
        },
        "gold_rule": GOLD_RULE,
        "compare_rule": COMPARE_RULE,
        "rows_cap": ROWS_CAP,
        "content_hash": chash,
        "db_stats": db_stats,
        "cases": cases,
    }


def _summary(dataset: dict[str, Any]) -> dict[str, Any]:
    cases = dataset["cases"]
    stats = dataset["db_stats"]
    return {
        "dataset_version": dataset["dataset_version"],
        "subset_cases": len(cases),
        "gold_ok": sum(1 for c in cases if c["gold_ok"]),
        "gold_fail": sum(1 for c in cases if not c["gold_ok"]),
        "zero_rows": sum(1 for c in cases if c["gold_ok"] and c["gold_rows"] == 0),
        "order_sensitive": sum(1 for c in cases if c["gold_order_sensitive"]),
        "per_db": {k: v["cases"] for k, v in stats.items()},
        "content_hash": dataset["content_hash"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spider 电商类 7 库数据集构建器（U-182）")
    ap.add_argument("--spider-root", required=False, default=None,
                    help="Spider 数据根（含 train_spider.json 与 database/）")
    ap.add_argument("--check", action="store_true", help="只校验已落件是否漂移（CI 用）")
    ap.add_argument("--out", default=str(OUT_DATASET))
    args = ap.parse_args(argv)

    if args.spider_root is None:
        if not args.check:
            ap.error("非 --check 模式必须给 --spider-root")
        existing = json.loads(Path(args.out).read_text(encoding="utf-8"))
        print(json.dumps({"check": "no-root", **{"content_hash": existing["content_hash"]}},
                         ensure_ascii=False))
        return 0

    dataset = build(Path(args.spider_root))
    out = Path(args.out)

    if args.check:
        if not out.is_file():
            print(json.dumps({"drift": True, "reason": "missing file"}, ensure_ascii=False))
            return 1
        existing = json.loads(out.read_text(encoding="utf-8"))
        drift = {
            "content_hash": existing.get("content_hash") != dataset["content_hash"],
            "cases": len(existing.get("cases") or []) != len(dataset["cases"]),
        }
        print(json.dumps({"drift": any(drift.values()), **drift, **_summary(dataset)},
                         ensure_ascii=False))
        return 1 if any(drift.values()) else 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataset, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"written": str(out), "bytes": out.stat().st_size, **_summary(dataset)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
