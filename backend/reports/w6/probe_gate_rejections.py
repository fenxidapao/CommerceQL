"""W6 探针：gate1 的两条**独立**拒绝路径（稳定复现、零 LLM、零 SQL 执行）。

结论用途：进 `reports/w6/RELAY.md`（上呈架构/W2C/W2A/W1A）与 §17.4 缺口表。

F1 —— `ORDER BY <SELECT 投影别名>` → R06
---------------------------------------------------------------------------
机制（`app/guard/ast_gate.py` 逐行定位）：
- `_check_columns` 对全树每个 `exp.Column` 调 `_resolve_column`；
- `_resolve_column` 只在 `_scope_tables(scope)` 的映射里找归属，而 `_scope_tables`
  登记的是**表位**（asset / CTE / 派生表别名），**不含当前 SELECT 自己的投影别名**；
- 无表前缀且无 owner 命中 ⇒ `owners == []` ⇒ 返回 `None` ⇒ `R06_COLUMN_ALLOWLIST`。
- 对照实验刻意用 **`products` 域**（`v_shop`/`v_product`）：该域在语义包里
  **没有**默认谓词 ⇒ 排除 F2 的混淆，剩下的唯一变量就是别名。

F2 —— 默认谓词按 `asset.domain` 注入到该域**所有物理表** → R06
---------------------------------------------------------------------------
`_inject_predicates` 遍历全树表实例，按 `assets[name]["domain"]` 查 `default_predicates`
并逐个注入（限定到该表的 alias）。语义包 `assets[].domain` 把
`v_region` / `v_dim_date` / `v_campaign` / `v_order_refund` 都归到 **`orders`** 域，
而 `orders` 档的三条谓词（`is_test_order` / `refund_status` / `pay_status`）
**只有 `v_order_paid` 有这些列** ⇒ 任何"单查维表"或"事实表 ⋈ 维表"的 SQL
都被注入出一个不存在的列 ⇒ 必然 R06。

⚠️ 契约侧的反证（这才是裁定依据，不是"实现不像我预期"）：
- **附录 A §A.7.1**（最高权威）把 `default_predicates` 定义在**指标**上，
  且例子逐条带表别名：`"o.pay_status = 'paid'"` —— 即**指标级、绑定到事实表**；
- 语义包 §5 `default_predicates` 区块每条都带 **`applies_to: [gmv, order_cnt, …]`（指标名）**，
  域键只是分组；
- `SemanticBundleRuntime.policy()` 把 `applies_to`/`id` **丢掉**，只透出
  `{domain: [谓词串]}` ⇒ 下游 `ast_gate` 于是只能"按域注所有表"。
⇒ 缺口链条：W1A 的域归类 + W2A 的 policy 投影丢字段 + W2C 的按域注入，
   **三段合起来**才产生这个结果，所以本探针不指名单一归属窗口。

F3 —— 冻结集上的实际爆炸半径（纯静态、可复算）
---------------------------------------------------------------------------
按 `gold_sql` 的 `FROM/JOIN` 表集合统计触达"**被注入出不存在的列**"资产的用例数。
判据是**列级**的（该域谓词列 ⊄ 本资产白名单列），不是"是不是粒度表 `v_order_paid`"：
`traffic` 档的 `uv >= 0` 对 `v_traffic_daily` 完全合法，按表名判会把整个流量域误计入。

实测（`probe_gate_rejections.json`，2026-09-18）：被污染资产 4 个
（`v_region` / `v_dim_date` / `v_campaign` 缺全部 3 列，`v_order_refund` 缺 `is_test_order`+`pay_status`），
冻结集 **14/166 = 8.43%** 受影响，且**全部**落在 `expected_behavior=execute`
（clarify 18 条 / refuse 24 条不受影响）⇒ 这 14 条是"可回答却被闸门杀掉"，
**不得**计入模型能力。`products` 域在语义包里**没有**默认谓词档 ⇒ 无注入。

这是 §17.4 与"EX 解释口径"的输入。

跑法（CommerceQL 根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_gate_rejections.py
产物：同目录 `probe_gate_rejections.json`（UTF-8 证据块，报告器可直接引用）
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

import sqlglot  # noqa: E402

from app.core.contracts import IdentityContext  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1  # noqa: E402
from app.guard.ast_gate import _inject_predicates  # noqa: E402  # 仅取证用（不改）
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

# ---------------------------------------------------------------------------
# F1：products 域（无默认谓词）⇒ 唯一变量是"排序键写的是投影别名"
# ---------------------------------------------------------------------------
# ⚠️ 刻意用 `v_product`：`v_shop` 没有 `list_price` 列（实测列集只有
#    shop_id/shop_name/city/category_l1/open_date），用它会让四条对照**全部**因
#    "列不在白名单"而 R06，别名这个变量就被吞掉了（探针失去隔离力）。
_PROJ = "SELECT category_l1, SUM(list_price) AS avg_price FROM v_product GROUP BY category_l1 "
F1_CASES = {
    "expr_sort": _PROJ + "ORDER BY SUM(list_price) DESC",
    "bare_alias_sort": _PROJ + "ORDER BY avg_price DESC",
    "qualified_alias_sort": _PROJ + "ORDER BY v_product.avg_price DESC",
    "underlying_col_sort": _PROJ + "ORDER BY category_l1 DESC",
}

# ---------------------------------------------------------------------------
# F2：orders 域内的维表 / 另一张事实表 ⇒ 唯一变量是"这张表恰好没有那三列"
# ---------------------------------------------------------------------------
F2_CASES = {
    "v_region_alone": "SELECT region_name FROM v_region",
    "v_dim_date_alone": "SELECT month FROM v_dim_date",
    "v_campaign_alone": "SELECT campaign_name FROM v_campaign",
    "fact_join_dim": (
        "SELECT r.region_name, SUM(o.pay_amount) FROM v_order_paid o "
        "JOIN v_region r ON o.region_code = r.code GROUP BY r.region_name"
    ),
    "grain_table_alone": "SELECT pay_amount FROM v_order_paid",
}

_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w.]*)", re.I)
_GRAIN_ASSET = "v_order_paid"


def _ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="probe-gate", task_id="probe-gate", session_id="probe-gate",
        tenant_id="T_A", user_id="probe", role=Role.ANALYST,
    )


def _gate(allowlist: dict, sql: str) -> dict:
    r = run_gate1(sql, allowlist)
    return {
        "sql": sql,
        "passed": r.gate_result.passed,
        "rule_id": r.gate_result.rule_id,
        "reason": r.gate_result.reason,
        "applied_predicates": list(r.applied_predicates),
        "rewritten_sql": r.rewritten_sql,
    }


def _injection_forecast(allowlist: dict, sql: str) -> str:
    """只看 `_inject_predicates` 会产出什么（拒绝态下 `rewritten_sql` 恒空串，无法取证）。"""
    tree = sqlglot.parse_one(sql, read="postgres")
    _inject_predicates(tree, allowlist)
    return tree.sql(dialect="postgres")


def _pred_columns(allowlist: dict) -> dict[str, set[str]]:
    """域 → 该域全部默认谓词引用的列名集合（谓词解析失败 ⇒ 空集 = 不判）。"""
    out: dict[str, set[str]] = {}
    for domain, preds in (allowlist["default_predicates"] or {}).items():
        cols: set[str] = set()
        for pred in preds:
            try:
                node = sqlglot.parse_one(str(pred), dialect="postgres")
            except sqlglot.errors.ParseError:
                continue
            cols.update(c.name for c in node.find_all(sqlglot.exp.Column))
        out[str(domain)] = cols
    return out


def f3_blast_radius(allowlist: dict) -> dict:
    """受影响判据 = **gold_sql 触达了"会被注入出不存在的列"的资产**（列级，不是表名级）。

    ⚠️ 不用"是否粒度表"当判据（我第一版就是这么错的）：`traffic` 档的 `uv >= 0`
    对 `v_traffic_daily` 完全合法，按表名判会把整个流量域误计入。
    """
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    domain_of = {name: str(entry.get("domain")) for name, entry in allowlist["assets"].items()}
    columns_of = {
        name: set((entry.get("columns") or {}).keys())
        for name, entry in allowlist["assets"].items()
    }
    pred_cols = _pred_columns(allowlist)
    poisoned_assets = {
        name: sorted(pred_cols[domain_of[name]] - columns_of[name])
        for name in allowlist["assets"]
        if domain_of.get(name) in pred_cols and pred_cols[domain_of[name]] - columns_of[name]
    }
    hit, clean, unparsable = [], [], 0
    for case in dataset["cases"]:
        gold = str(case.get("gold_sql") or "")
        tables = {m.group(1) for m in _TABLE_RE.finditer(gold)}
        if not tables:
            unparsable += 1
        touched = sorted(tables & poisoned_assets.keys())
        (hit if touched else clean).append(
            {"case_id": case["case_id"], "assets": touched}
            if touched
            else case["case_id"]
        )
    return {
        "n_cases": len(dataset["cases"]),
        "predicate_columns_by_domain": {k: sorted(v) for k, v in pred_cols.items()},
        "poisoned_assets_missing_columns": poisoned_assets,
        "n_affected": len(hit),
        "affected_share": round(len(hit) / max(1, len(dataset["cases"])), 4),
        "affected": hit,
        "unaffected_case_ids_sample": [c if isinstance(c, str) else c["case_id"] for c in clean[:10]],
        "gold_sql_with_no_table_ref": unparsable,
        "by_expected_behavior": _by_behavior(dataset["cases"], hit),
    }


def _by_behavior(cases: list[dict], hit: list[dict]) -> dict:
    ids = {h["case_id"] for h in hit}
    out: dict[str, list[int]] = {}
    for case in cases:
        key = str(case.get("expected_behavior") or "execute")
        out.setdefault(key, [0, 0])
        out[key][0 if case["case_id"] in ids else 1] += 1
    return {k: {"affected": v[0], "unaffected": v[1]} for k, v in sorted(out.items())}


def main() -> int:
    loaded = load_bundle(_bootstrap.BUNDLE_PATH)
    runtime = SemanticBundleRuntime(loaded)
    allowlist = runtime.guard_allowlist(_ctx(), max_rows=None)

    f1 = {name: _gate(allowlist, sql) for name, sql in F1_CASES.items()}
    f2 = {name: _gate(allowlist, sql) for name, sql in F2_CASES.items()}
    injected = {name: _injection_forecast(allowlist, sql) for name, sql in F2_CASES.items()}

    f3 = f3_blast_radius(allowlist)

    out = {
        "f1_order_by_projection_alias": f1,
        "f2_default_predicates_injected_by_domain": {**f2, "evidence_injected_sql": injected},
        "f3_frozen_set_blast_radius": f3,
        "asset_domains": {k: str(v.get("domain")) for k, v in allowlist["assets"].items()},
        "default_predicates_by_domain": {
            k: list(v) for k, v in (allowlist["default_predicates"] or {}).items()
        },
        "domains_without_default_predicates": sorted(
            {str(v.get("domain")) for v in allowlist["assets"].values()}
            - set(allowlist["default_predicates"] or {})
        ),
        "findings": {
            "F1": "投影别名作排序键 → R06（`ast_gate._scope_tables` 不登记同 scope 的投影别名；`_projection_names` 已存在，缺的是这一环接线）。归属：W2C。",
            "F2": "默认谓词按 `asset.domain` 注入到该域所有物理表实例 → 维表/第二事实表被注入出不存在的列 → R06。契约侧：附录 A §A.7.1 的 `default_predicates` 是**指标级且带表别名**；语义包 §5 每条带 `applies_to=[指标名]`；`SemanticBundleRuntime.policy()` 投影时丢掉 `applies_to` ⇒ 下游只能按域注入。归属：W1A（域归类）+ W2A（policy 丢字段）+ W2C（按域注入），本窗口只取证不改。",
            "F3": (
                f"冻结集实测 {f3['n_affected']}/{f3['n_cases']}（{f3['affected_share']:.2%}）的 gold_sql "
                f"触达会被注入缺列的资产；受影响判据 = 列级（谓词列 ⊄ 该资产白名单列），"
                f"不是'是不是粒度表'。这些用例的 gate1 拒绝**不得**计入模型能力"
                "（归因单列一类，编号待架构窗口分配）。"
            ),
        },
    }
    path = os.path.join(HERE, "probe_gate_rejections.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("== F1 排序键形态 ==")
    for name, r in f1.items():
        print(f"  {name:26s} passed={r['passed']!s:5s} rule={r['rule_id']}")
    print("== F2 orders 域内非粒度资产 ==")
    for name in F2_CASES:
        r = f2[name]
        print(f"  {name:26s} passed={r['passed']!s:5s} rule={r['rule_id']}")
        print(f"      injected -> {injected[name][:170]}")
    print("== F3 冻结集受影响面 ==")
    print(json.dumps(out["f3_frozen_set_blast_radius"], ensure_ascii=False)[:600])
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
