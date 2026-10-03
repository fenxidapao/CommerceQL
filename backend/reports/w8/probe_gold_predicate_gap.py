"""W8 探针：EX=0 的账落在**金标口径**还是落在被测系统？（零 LLM、零写库）

为什么要单独打这一枪：2026-10-03 真打批次 `n_equivalent=0`（124 条 execute 全灭）。
修掉两处测量缺陷（`run_in_sandbox` 不做 `%(name)s→:name` 方言桥、预测侧误读 state 的
体积字段 `result_rows`）之后预测侧终于有值，但仍然 0 等价 —— 下一问只能是：
**金标和被测系统算的是不是同一个数**。

判据形状（同器同界，只换一个变量 = 默认谓词）：
  A = 金标原样在沙箱跑（TEMP VIEW 租户边界）
  B = 金标 + 语义包对该金标所用事实表声明的**默认谓词**，同一沙箱再跑
  P = 被测系统出站的 SQL（gate1 注入默认谓词之后的最终 SQL）同一沙箱跑
若 `P≠A` 而 `P=B` 占多数 ⇒ 病灶是**冻结集金标没带指标默认谓词**（GMV/订单量按语义包
定义只算已支付·非退款·非测试单，而 `gold_sql` 是裸 `SUM(pay_amount)`），
这不是"模型不行"，也不是闸门不行，而是**判据与定义不同源**；
若 `P≠B` 占多数 ⇒ 才是真的模型/链路能力缺口。

⚠️ 本探针**不改**冻结集（`N-13` 验真会当场失败），只把"该不该重造金标"这件事量化出来。

跑法（CommerceQL 根目录）：
    PYTHONUTF8=1 .venv/Scripts/python.exe backend/reports/w8/probe_gold_predicate_gap.py
产物：同目录 `probe_gold_predicate_gap.json`
"""

from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w8 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import equivalence as eq  # noqa: E402
import harness as eval_harness  # noqa: E402
import runner as eval_runner  # noqa: E402
import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402

RESULTS = os.path.join(ROOT, "eval", "results_v1.json")
DB = _bootstrap.SANDBOX_DB
OUT = os.path.join(HERE, "probe_gold_predicate_gap.json")


def _predicates_for_gold(gold_sql: str, domain_preds: dict[str, list[str]],
                        asset_of_table: dict[str, str]) -> list[str]:
    """金标用到哪张事实表 ⇒ 该表所属域的默认谓词（原样，不加限定符）。"""
    tree = sqlglot.parse_one(gold_sql, dialect="postgres")
    domains: list[str] = []
    for table in tree.find_all(exp.Table):
        domain = asset_of_table.get(table.name)
        if domain and domain not in domains:
            domains.append(domain)
    out: list[str] = []
    for domain in domains:
        out.extend(domain_preds.get(domain, []))
    return out


def _patched_gold(gold_sql: str, predicates: list[str]) -> str:
    """把默认谓词 AND 进金标自己的 WHERE（sqlglot 负责插在 GROUP/ORDER/LIMIT 之前）。"""
    tree = sqlglot.parse_one(gold_sql, dialect="postgres")
    for pred in predicates:
        node = sqlglot.parse_one(pred, dialect="postgres")
        tree = tree.where(node, append=True, copy=False)
    return tree.sql(dialect="postgres")


def main() -> int:
    with open(RESULTS, encoding="utf-8") as fh:
        payload = json.load(fh)
    harness = eval_harness.Harness(cassette_path=None, live=False)
    runtime = harness.runtime

    #: 语义包面：域 → 默认谓词；物理表 → 域
    allowlist_keys = runtime.guard_allowlist(
        eval_harness.identity_for_case("PROBE", "T_A"), max_rows=None
    )
    domain_preds = {
        str(d): [str(p) for p in ps]
        for d, ps in (allowlist_keys.get("default_predicates") or {}).items()
    }
    table_domain = {
        name: str(entry.get("domain") or "")
        for name, entry in (allowlist_keys.get("assets") or {}).items()
    }
    tsphysics = harness.tenant_scoped_physicals

    def run(sql: str, tenant: str, params=None) -> dict:
        return eval_runner.run_in_sandbox(
            sql, params, tenant=tenant, views=True, db_path=DB,
            tenant_scoped_physicals=tsphysics,
        )

    rows = []
    for rec in payload["records"]:
        if rec.get("expected_behavior") != "execute" or not rec.get("sql_text"):
            continue
        gold_sql = str((rec.get("gold") or {}).get("gold_sql") or "")
        if not gold_sql:
            continue
        tenant = rec["tenant"]
        pred = run(rec["sql_text"], tenant, rec.get("sql_params") or None)
        a = run(gold_sql, tenant)
        preds = _predicates_for_gold(gold_sql, domain_preds, table_domain)
        b = run(_patched_gold(gold_sql, preds), tenant) if preds else a
        eq_a = pred["table"] is not None and a["table"] is not None and bool(
            eq.compare_tables(a["table"], pred["table"],
                              gold_sql=gold_sql, pred_sql=rec["sql_text"]).equivalent
        )
        eq_b = pred["table"] is not None and b["table"] is not None and bool(
            eq.compare_tables(b["table"], pred["table"],
                              gold_sql=gold_sql, pred_sql=rec["sql_text"]).equivalent
        )
        rows.append({
            "case_id": rec["case_id"],
            "tenant": tenant,
            "outcome": rec.get("outcome"),
            "gold_predicates": preds,
            "pred_eq_gold": eq_a,
            "pred_eq_gold_with_predicates": eq_b,
            "gold_value": (a["table"].rows[:1] if a["table"] else None),
            "gold_p_value": (b["table"].rows[:1] if b["table"] else None),
            "pred_value": (pred["table"].rows[:1] if pred["table"] else None),
            "errors": [pred.get("error"), a.get("error"), b.get("error")],
        })

    def tally(key):
        return dict(collections.Counter(str(r[key]) for r in rows).most_common())

    both = [r for r in rows if not r["pred_eq_gold"]]
    saved_by_predicates = [
        r for r in both if r["pred_eq_gold_with_predicates"] and r["gold_predicates"]
    ]
    out = {
        "as_of": f"results_v1.json git_rev={payload.get('git_rev')} mode={payload['config']['mode']}",
        "n_cases_with_sql": len(rows),
        "pred_eq_gold": tally("pred_eq_gold"),
        "pred_eq_gold_with_predicates": tally("pred_eq_gold_with_predicates"),
        "rescued_by_default_predicates": len(saved_by_predicates),
        "still_wrong_after_predicates": sum(
            1 for r in both if not r["pred_eq_gold_with_predicates"]
        ),
        "rescued_case_ids": [r["case_id"] for r in saved_by_predicates],
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
