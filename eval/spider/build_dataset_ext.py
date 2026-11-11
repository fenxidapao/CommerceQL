"""扩库题集构建器（U-182 扩库，零出站、零 LLM、零写库）。

为什么单独一件而不改 `build_dataset.py`：
  · `build_dataset.py` 的 `DBS` 是 7 库硬编码，且已产出 `dataset_ecom7_v1.json`（523 题，
    内容哈希已被 r1–r5 五份证据引用）。改它会让旧件的 `content_hash` 失去可比性；
  · 扩库只增不减：新库题集另存一件，case_id 用 `ex-` 前缀，与旧件 `sp-` 不会撞号。

金标口径与 `build_dataset.py` 逐字一致（不改判据）：
  gold_query = `train_spider.json` 的 `query` 字段（官方发布）；`sql` 字段是结构树 dict、
  `train_gold.sql` 8,659 行含 `train_others` 按行号取会错配，两者都不用。

库集来源 = `eval/spider/bundles_ready_u182.json` 的 `ready_dbs`（只含已过真加载器
`load_bundle` 的库），**不在这里再维护第二份库清单**。

用法：
    python eval/spider/build_dataset_ext.py --spider-root <...>/spider_data
    python eval/spider/build_dataset_ext.py --check
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
READY = HERE / "bundles_ready_u182.json"
OUT_DATASET = HERE / "dataset_ecom29_v1.json"

DATASET_VERSION = "spider_ecom29_v1"
CREATED_AT = "2026-11-11"
U_ID = "U-182"
ROWS_CAP = 5000
TIMEOUT_S = 10.0
CASE_PREFIX = "ex-"

SELECTION_RULE = (
    "库集 = eval/spider/bundles_ready_u182.json 的 ready_dbs（已逐个过真加载器 load_bundle 的库）；"
    "电商类判定按表名 token（ORDER/INVOICE/CUSTOMER/PAYMENT/SHIPMENT/PRODUCT/CART/REFUND），"
    "实测 28 库（强表名 21 / 宽表名 28，强集是宽集子集）"
)
BIAS_NOTE = (
    "报告只能写「Spider 电商类子集（28/166 库，N 题）」并明写选库偏差；"
    "不得写「Spider dev 全量」—— dev 段 20 库强电商表命中 0（已实测）"
)
GOLD_RULE = (
    "gold_query = train_spider.json 的 query 字段（官方发布，可自执行）；"
    "sql 字段为结构树 dict 不使用；train_gold.sql 8,659 行含 train_others、与 7,000 行按下标对不齐，不使用"
)
COMPARE_RULE = (
    "结果级集合比对：金标由本件 gold_query 现执行取行，模型结果与之比较；"
    "gold_query 含 ORDER BY 时按有序摘要比，否则按无序摘要比；"
    "比对器为本项目实现（官方 evaluation.py 不在盘），报告须写明"
)


def _norm_value(value: Any) -> Any:
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


def _exec(db_path: Path, sql: str):
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


def build(spider_root: Path, dbs: list[str]) -> dict[str, Any]:
    src = spider_root / "train_spider.json"
    if not src.is_file():
        raise SystemExit("缺 train_spider.json: " + str(src))
    raw = src.read_bytes()
    rows = json.loads(raw.decode("utf-8"))

    db_stats: dict[str, dict[str, Any]] = {}
    for db_id in dbs:
        path = _db_path(spider_root, db_id)
        if not path.is_file():
            raise SystemExit("缺 sqlite: " + str(path))
        blob = path.read_bytes()
        db_stats[db_id] = {
            "sqlite": str(path.relative_to(spider_root)).replace("\\", "/"),
            "sqlite_bytes": len(blob),
            "sqlite_sha256": hashlib.sha256(blob).hexdigest(),
            "cases": 0, "gold_ok": 0, "gold_fail": 0,
            "zero_rows": 0, "order_sensitive": 0,
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
                "case_id": CASE_PREFIX + "%04d" % (len(cases) + 1),
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
        "dataset": "eval/spider/dataset_ecom29_v1.json",
        "created_at": CREATED_AT,
        "u_id": U_ID,
        "case_id_prefix": CASE_PREFIX,
        "source": {
            "file": "train_spider.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "rows_total": len(rows),
            "dbs_total": 166,
            "subset_dbs": list(dbs),
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
    return {
        "dataset_version": dataset["dataset_version"],
        "dbs": len(dataset["source"]["subset_dbs"]),
        "subset_cases": len(cases),
        "gold_ok": sum(1 for c in cases if c["gold_ok"]),
        "gold_fail": sum(1 for c in cases if not c["gold_ok"]),
        "zero_rows": sum(1 for c in cases if c["gold_ok"] and c["gold_rows"] == 0),
        "order_sensitive": sum(1 for c in cases if c["gold_order_sensitive"]),
        "content_hash": dataset["content_hash"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spider 扩库题集构建器（U-182）")
    ap.add_argument("--spider-root", required=False, default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(OUT_DATASET))
    args = ap.parse_args(argv)

    if not READY.is_file():
        raise SystemExit("缺 ready 清单: " + str(READY))
    ready = json.loads(READY.read_text(encoding="utf-8"))
    dbs = [str(x) for x in (ready.get("ready_dbs") or [])]
    if not dbs:
        raise SystemExit("ready_dbs 为空")

    if args.spider_root is None:
        if not args.check:
            ap.error("非 --check 模式必须给 --spider-root")
        existing = json.loads(Path(args.out).read_text(encoding="utf-8"))
        print(json.dumps({"check": "no-root", "content_hash": existing["content_hash"]},
                         ensure_ascii=False))
        return 0

    dataset = build(Path(args.spider_root), dbs)
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
