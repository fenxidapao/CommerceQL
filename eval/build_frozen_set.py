#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
冻结评测集 v1 构建器

归属窗口：W1A（eval/**）

它做什么
--------
1. 读 `eval/case_library.py` 的声明式用例
2. 在沙箱库上**真实执行**每条 `gold_sql` → 计算 `gold_result_hash`（**禁止手填**）
3. 用 `data/generator/layering.py` 机器判定 4×3 双维度级别（**禁止手写级别**）
4. 断言：① 4×3 每格 ≥ 8 条；② 每条 SQL 可执行；③ must_contain 出现在 SQL 里
5. 产出：
   · `eval/dataset_v1_frozen.json` —— 冻结集本体（含 `content_hash`，N-13）
   · `eval/MANIFEST_v1.json`       —— 可复现证据链（种子 / 参数 / 生成器 sha256 /
                                      沙箱库 sha256 / 网格计数 / 工具版本）

⚠️ **一经生成即冻结**：改集必须同时升 `DATASET_VERSION` 与文件名版本号，不得静默调参。
⚠️ 本脚本**只读**沙箱库（`file:...?mode=ro`），不会改数据。

用法
----
    python eval/build_frozen_set.py                  # 构建并写盘
    python eval/build_frozen_set.py --check          # 只校验（CI 用）：网格达标 + hash 可复现
    python eval/build_frozen_set.py --no-write       # 只跑不写，用于调网格
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "data", "generator"))

from layering import annotate_case, grid  # noqa: E402

DATASET_VERSION = "1"
DB_PATH = os.path.join(ROOT, "data", "ecom_sandbox.db")
OUT_DATASET = os.path.join(HERE, "dataset_v1_frozen.json")
OUT_MANIFEST = os.path.join(HERE, "MANIFEST_v1.json")

MIN_PER_CELL = 8
LEVELS = ["easy", "medium", "hard", "extra"]
SEMS = ["low", "medium", "high"]


# ---------------------------------------------------------------------------
# 规范化与哈希
# ---------------------------------------------------------------------------
def _norm_cell(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, bool):
        return int(v)
    return v


# 语义包里 `tenant_scoped: true` 的资产（v_region / v_dim_date 为 false）
TENANT_SCOPED = ("v_order_paid", "v_order_refund", "v_product", "v_shop",
                 "v_campaign", "v_traffic_daily")


def tenant_wrap(sql: str, tenant: str | None) -> str:
    """把租户过滤**注入到资产边界**（模拟执行层 `SET app.tenant_id` / RLS）。

    为什么不让 gold_sql 自己写 `tenant_id`：
      ① 语义包明确写该列「**不暴露给模型生成**——由执行层注入」；
      ② `tenant_id` 会额外算一个 WHERE 条件单元 → `others +1` →
         会把一堆本该 easy 的用例顶到 medium，使 **`easy × 高` 那一格不可达**。

    做法：把 **FROM / JOIN 位置**的每个租户域表替换成"带租户过滤的同名派生表"。
    由于 `AS <原名>`，SQL 里的 `v_order_paid.xxx` 限定引用**仍可解析**。

    ⚠️ 必须锚定 `FROM|JOIN` 前缀。初版只写 `\\bv_order_paid\\b`，结果把
    `v_order_paid.shop_id` 里的表名也替换了 → 生成 `(SELECT ...) AS v_order_paid.shop_id`
    → 54 条 SQL 报 `near ".": syntax error`（实测抓出）。
    """
    if not tenant:
        return sql
    for t in TENANT_SCOPED:
        sql = re.sub(rf"\b(FROM|JOIN)\s+{re.escape(t)}\b",
                     rf"\1 (SELECT * FROM {t} WHERE tenant_id = '{tenant}') AS {t}", sql)
    return sql


def result_hash(cur: sqlite3.Cursor, sql: str, tenant: str | None) -> tuple[str, int, int]:
    """执行 SQL 并返回 (hash, 行数, 列数)。执行前按 `tenant` 注入租户过滤。

    行序**不影响** hash —— 无 ORDER BY 的 SQL 不保证顺序，若把顺序算进 hash，
    同一个正确结果会因执行计划不同而 hash 不同（假失败）。
    """
    cur.execute(tenant_wrap(sql, tenant))
    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchall()
    norm = sorted(
        ([_norm_cell(v) for v in r] for r in rows),
        key=lambda row: json.dumps(row, ensure_ascii=False, default=str),
    )
    payload = json.dumps({"cols": cols, "rows": norm}, ensure_ascii=False,
                         sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(rows), len(cols)


def case_content_hash(cases: list[dict]) -> str:
    """用例集的 content_hash —— **只覆盖语义内容**，不覆盖生成时刻的偶然差异。

    故意排除的字段：`gold_result_hash`（由执行产生，已在各自字段里）、
    机器判定的分层明细（可由 layering 重算）。
    """
    keep = ("case_id", "question", "domain", "expected_behavior", "gold_sql",
            "business_knowledge_required", "must_contain", "must_not_contain",
            "clarify_expected", "refuse_reason")
    canon = []
    for c in sorted(cases, key=lambda x: x["case_id"]):
        canon.append({k: c.get(k) for k in keep})
    payload = json.dumps(canon, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(check: bool = False, write: bool = True) -> int:
    from case_library import CASES            # 延迟导入，便于 --help 时不被库错误打断

    if not os.path.exists(DB_PATH):
        print(f"[FATAL] 沙箱库不存在：{DB_PATH}\n"
              f"        先跑 python data/generator/seed_generator.py", file=sys.stderr)
        return 2

    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()

    problems: list[str] = []
    annotated: list[dict] = []

    for c in CASES:
        a = annotate_case(c)
        sql = a.get("gold_sql")
        if sql:
            try:
                h, nrows, ncols = result_hash(cur, sql, a.get("eval_tenant"))
                a["gold_result_hash"] = h
                a["gold_result_rows"] = nrows
                a["gold_result_cols"] = ncols
            except Exception as e:                                # noqa: BLE001
                problems.append(f"{a['case_id']}: SQL 执行失败 → {type(e).__name__}: {e}")
                a["gold_result_hash"] = None
        else:
            a["gold_result_hash"] = None
            a["gold_result_rows"] = None
            a["gold_result_cols"] = None

        # must_contain / must_not_contain 自检：断言必须出现在（或不出现于）gold_sql
        if sql:
            low = sql.lower()
            for tok in a.get("must_contain") or []:
                if tok.lower() not in low:
                    problems.append(f"{a['case_id']}: must_contain '{tok}' 不在 gold_sql 里")
            for tok in a.get("must_not_contain") or []:
                if tok.lower() in low:
                    problems.append(f"{a['case_id']}: must_not_contain '{tok}' 却出现在 gold_sql 里")
        # 互斥自检
        if a["expected_behavior"] == "execute" and not sql:
            problems.append(f"{a['case_id']}: execute 类必须给 gold_sql")
        if a["expected_behavior"] != "execute" and sql:
            problems.append(f"{a['case_id']}: {a['expected_behavior']} 类**不得**给 gold_sql"
                            f"（给了就等于把答案泄给被测模型）")
        annotated.append(a)

    con.close()

    # ---- 网格 ----
    g, warns = grid(annotated)
    print("4×3 网格（结构 × 语义）：")
    print(f"{'':10s}" + "".join(f"{s:>10s}" for s in SEMS) + f"{'行合计':>10s}")
    for lv in LEVELS:
        print(f"{lv:10s}" + "".join(f"{g[lv][s]:>10d}" for s in SEMS) + f"{sum(g[lv].values()):>10d}")
    print(f"{'列合计':10s}" + "".join(f"{sum(g[l][s] for l in LEVELS):>10d}" for s in SEMS)
          + f"{sum(sum(g[l].values()) for l in LEVELS):>10d}")
    for w in warns:
        print("  [WARN]", w, file=sys.stderr)

    counts = {b: sum(1 for a in annotated if a["expected_behavior"] == b)
              for b in ("execute", "clarify", "refuse")}
    print(f"\n行为分布：{counts}｜总计 {len(annotated)} 条")

    if problems:
        print(f"\n[FAIL] {len(problems)} 条问题：", file=sys.stderr)
        for p in problems[:40]:
            print("   -", p, file=sys.stderr)
        return 1

    empty = [f"[{l}×{s}]" for l in LEVELS for s in SEMS if g[l][s] < MIN_PER_CELL]
    if empty:
        print(f"\n[FAIL] DoD③ 不达标，以下格子 < {MIN_PER_CELL}：{' '.join(empty)}", file=sys.stderr)
        return 1
    print(f"\n[OK] DoD③ 全部 12 格 ≥ {MIN_PER_CELL}")

    chash = case_content_hash(annotated)
    print(f"[OK] content_hash = {chash}")

    if check:
        if not os.path.exists(OUT_DATASET):
            print("[FAIL] 冻结集文件不存在", file=sys.stderr)
            return 1
        old = json.load(open(OUT_DATASET, encoding="utf-8"))
        if old.get("content_hash") != chash:
            print(f"[FAIL] 冻结集已漂移：盘上={old.get('content_hash')} 重算={chash}",
                  file=sys.stderr)
            return 1
        if old.get("dataset_version") != DATASET_VERSION:
            print("[FAIL] 版本号不一致", file=sys.stderr)
            return 1
        print("[OK] 冻结集与用例库一致（未漂移）")
        return 0

    if not write:
        return 0

    dataset = {
        "dataset_version": DATASET_VERSION,
        "frozen_at": "2026-09-16",
        "frozen_rule": "一经生成即冻结；任何改动必须升 dataset_version 并重算 content_hash",
        "content_hash": chash,
        "sandbox_db_sha256": file_sha256(DB_PATH),
        "grid": {lv: {s: g[lv][s] for s in SEMS} for lv in LEVELS},
        "difficulty_note": (
            "difficulty_struct 由 data/generator/layering.py 按上游 evaluation.py 的 "
            "count_component1/2/others + eval_hardness **机器判定**（不是手写）。"
            "JOIN 采用上游代码口径（表数-1）；站点标签口径见 difficulty_struct_sitelabel。"
            "difficulty_semantic 由 business_knowledge_required 的标签按附录 C §C.3.3 判定。"
        ),
        "cases": annotated,
    }
    json.dump(dataset, open(OUT_DATASET, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=2)

    # ---- MANIFEST：可复现证据链 ----
    gen = os.path.join(ROOT, "data", "generator", "seed_generator.py")
    params = subprocess.run([sys.executable, gen, "--dump-params"],
                            capture_output=True, text=True, encoding="utf-8").stdout
    manifest = {
        "produced_by_window": "W1A",
        "dataset_version": DATASET_VERSION,
        "content_hash": chash,
        "sandbox": {
            "path": os.path.relpath(DB_PATH, ROOT).replace("\\", "/"),
            "bytes": os.path.getsize(DB_PATH),
            "sha256": file_sha256(DB_PATH),
            "generator": "data/generator/seed_generator.py",
            "generator_sha256": file_sha256(gen),
            "params": json.loads(params),
            "reproduce": ("python data/generator/seed_generator.py "
                          "--out data/ecom_sandbox.db  # 同种子 → 同字节"),
        },
        "layering": {
            "tool": "data/generator/layering.py",
            "sha256": file_sha256(os.path.join(ROOT, "data", "generator", "layering.py")),
            "upstream_reference": "github.com/taoyds/spider · evaluation.py (行 206/299/303/324/329/362)",
            "known_discrepancies": ["U-29 component2 定义", "U-30 JOIN 计数口径"],
        },
        "counts": counts,
        "grid": {lv: {s: g[lv][s] for s in SEMS} for lv in LEVELS},
        "environment": {
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
        },
    }
    json.dump(manifest, open(OUT_MANIFEST, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=2)
    print(f"[OK] written {os.path.relpath(OUT_DATASET, ROOT)}")
    print(f"[OK] written {os.path.relpath(OUT_MANIFEST, ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="冻结评测集 v1 构建器")
    ap.add_argument("--check", action="store_true", help="只校验是否漂移（CI 用）")
    ap.add_argument("--no-write", action="store_true", help="只跑不写")
    args = ap.parse_args(argv)
    return build(check=args.check, write=not args.no_write)


if __name__ == "__main__":
    raise SystemExit(main())
