"""W6 · §C.4.3 核心指标口径一致性比对（G-7 的**唯一**输入产物）。

为什么必须有这个文件（而不是把覆盖率探针喂给 G-7）
--------------------------------------------------------------------------
上一轮 `reporter` 把 `probe_metric_coverage.json` 当 `consistency=` 传给 G-7。那份产物里
只有"题面命中了多少指标词形"，**没有** §C.4.3 要的 `total/consistent/unattributed` ⇒
G-7 恰好落成 `NOT_AVAILABLE`。看起来"保守"，实际是**喂错了件**：真比对压根没跑过，
而报告读起来像是"跑了但没数据"。本文件把那条真比对跑出来。

§C.4.3 到底比什么（以及本探针比的是什么）
--------------------------------------------------------------------------
原文的对比对象是"核心指标（GMV / 订单量 / UV / 客单价 / 退款率）的**已确认权威值**"，
判定"相对误差 < 0.1%"，且"不一致时必须能归因到具体谓词/时间边界"。

本项目里**不存在**外部 BI 权威值可引（PRD 未给）。可用的、且**非自证**的权威定义只有一处：
**语义包** —— `metrics[].expression` + `default_predicates` + `time_basis`，
owner=finance/operations，是 §17.6 I-1「口径唯一来源」指定的那一处。
⇒ 本探针的比对双方：

* **权威侧**：按语义包声明的表达式与默认谓词，在同一沙箱、同一租户边界上**直接实现**的 SQL；
* **题库侧**：冻结集 `gold_sql`（W1A 产物，`content_hash` 冻结，本窗口改不了）。

两侧实现独立 ⇒ 不一致就是真不一致（要么 W1A 的 gold 漏了口径谓词，要么语义包写错）。
**这不是**对外部 BI 数字的验证，报告必须带着这句话。

差异怎么才算"可归因"（防空转的关键）
--------------------------------------------------------------------------
"逐步加谓词最后一定等于权威 SQL"—— 那样判"可归因"是**自证**。所以本探针要求三件事同时成立：

1. gold 的聚合表达式与语义包表达式**逐字同形**（只允许逻辑资产名前缀差异）；
   表达式不同 ⇒ 差异来自"算了另一个量"，谓词清单解释不了 ⇒ 记 `unattributed`；
2. gold 的 WHERE **确实缺**语义包默认谓词（缺集非空）；
3. 沿"缺集"逐条补齐后复算，能在 0.1% 内收敛到权威值。

三条任一不成立 ⇒ 该条差异不可归因（§C.4.3：不可归因的不一致 = 不可接受的缺陷）。

跑法（CommerceQL 根目录，零 LLM / 零成本）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w6/probe_metric_values.py
产物：同目录 `probe_metric_values.json`（`total/consistent/unattributed` 供 G-7 直读）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # reports/w6 -> backend -> repo
for _p in (os.path.join(ROOT, "eval"), os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from harness import Harness  # noqa: E402  # 租户域清单的唯一导出点
from probe_metric_coverage import metric_terms  # noqa: E402  # 可达词形的唯一实现
from runner import run_in_sandbox  # noqa: E402  # 两种租户边界的唯一执行入口

from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

__all__ = ["CORE_METRICS", "REL_TOL", "main"]

#: §C.4.3 点名的五个核心指标（顺序即报告顺序）。
CORE_METRICS: tuple[str, ...] = ("gmv", "order_cnt", "uv", "aov", "refund_rate")

#: "口径不一致"的判定阈值 —— §C.4.3 原文"相对误差 < 0.1%"。
REL_TOL: float = 1e-3

_GROUP_RE = re.compile(r"\bGROUP\s+BY\b", re.I)
_WHERE_RE = re.compile(
    r"\bWHERE\b(.*?)(?=\bGROUP\b|\bORDER\b|\bLIMIT\b|\bHAVING\b|$)", re.I | re.S
)
_SELECT_RE = re.compile(r"^\s*SELECT\s+(.*?)\s+FROM\s+", re.I | re.S)
_TIME_RE = re.compile(
    r"\b(?:(?P<table>\w+)\.)?(?P<col>pay_time|stat_date|create_time)\s*"
    r"(?P<op>>=|<=|<|>)\s*'(?P<val>[^']*)'",
    re.I,
)


def _qualify(fragment: str, asset: str, view: str) -> str:
    """语义包按**逻辑资产**书写（`order_paid.pay_amount`），沙箱按 `physical_asset` 落库（`v_order_paid.…`）。

    映射取自 bundle 的 `assets[].physical_asset`，**不是** "加个 `v_` 前缀" 的约定 ——
    约定会在下一个语义包版本里静默失效，而这里的失效表现是"比对两边算的不是同一张表"。
    这一跳只是渲染：只替换限定前的资产名，不碰列名/常量/运算符 ⇒ 不改口径。
    """
    return re.sub(rf"\b{re.escape(asset)}\.", f"{view}.", fragment)


_RELATION_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.I)


def _canon(expr: str) -> str:
    """表达式同形性比较用的规范化：去空白、去 `<关系>.` 限定、小写。

    ⚠️ 去掉表限定符是**有条件的**安全：调用方必须先用 `_relations()` 确认 gold 只读
    该指标自己那张关系，否则"a.uv = b.uv"这种跨表差异会被规范化抹平成"同形"。
    """
    no_qualifier = re.sub(r"\b\w+\.", "", expr)
    return re.sub(r"\s+", "", no_qualifier).lower()


def _relations(sql: str) -> set[str]:
    """SQL 里出现的全部关系名（FROM / JOIN）。"""
    return {m.group(1).lower() for m in _RELATION_RE.finditer(sql)}


def _scalar(out: dict[str, Any]) -> float | None:
    """从一次沙箱执行结果里取 1×1 标量。形状不对 ⇒ None（不猜）。"""
    if out.get("error"):
        return None
    rows = list(getattr(out.get("table"), "rows", ()) or ())
    if len(rows) != 1 or len(rows[0]) != 1 or rows[0][0] is None:
        return None
    return float(rows[0][0])


def _rel_err(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a - b) / (abs(b) or 1.0)


def _time_clauses(gold_sql: str, time_basis: str) -> list[str]:
    """只取**该指标时间基准**上的过滤条件（其余条件由 `_scope_is_pure` 判为范围外）。"""
    return [
        m.group(0)
        for m in _TIME_RE.finditer(gold_sql)
        if m.group("col").lower() == str(time_basis).lower()
    ]


def _where_terms(gold_sql: str) -> list[str]:
    where = _WHERE_RE.search(gold_sql)
    if not where:
        return []
    parts = re.split(r"\bAND\b", where.group(1), flags=re.I)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]


def _select_expr(gold_sql: str) -> str:
    m = _SELECT_RE.match(gold_sql)
    return m.group(1) if m else ""


def _authority_sql(expr: str, view: str, clauses: list[str], preds: list[str]) -> str:
    where = clauses + preds
    return f"SELECT {expr} FROM {view}" + (f" WHERE {' AND '.join(where)}" if where else "")


def _attribute(
    *,
    gold_sql: str,
    metric: dict[str, Any],
    gold_value: float,
    authority_value: float,
    tenant: str,
    db_path: str,
    ts_physicals: dict[str, str],
) -> dict[str, Any]:
    """按"缺哪些默认谓词"逐条补齐复算，判定差异能否归因到口径元素。"""
    asset = str(metric["asset"])
    view = str(metric["view"])
    expr = _qualify(str(metric["expression"]), asset, view)
    clauses = _time_clauses(gold_sql, str(metric["time_basis"]))
    gold_terms = [_canon(t) for t in _where_terms(gold_sql)]
    all_preds = [_qualify(p, asset, view) for p in metric["default_predicates"]]
    missing = [p for p in all_preds if _canon(p) not in gold_terms]
    present = [p for p in all_preds if _canon(p) in gold_terms]

    steps: list[dict[str, Any]] = []
    prev = gold_value
    for i, pred in enumerate(missing, start=1):
        cumulative = present + missing[:i]
        sql = _authority_sql(expr, view, clauses, cumulative)
        out = run_in_sandbox(
            sql, tenant=tenant, views=True, db_path=db_path, tenant_scoped_physicals=ts_physicals
        )
        val = _scalar(out)
        steps.append(
            {
                "added_predicate": pred,
                "sql": sql,
                "value": val,
                "error": out.get("error"),
                "delta_vs_prev": None if val is None or prev is None else round(val - prev, 6),
            }
        )
        if val is not None:
            prev = val

    same_expression = _canon(_select_expr(gold_sql)) == _canon(expr)
    recon_err = _rel_err(prev, authority_value)
    converged = recon_err is not None and recon_err < REL_TOL
    return {
        "same_expression": same_expression,
        "gold_expression": _select_expr(gold_sql),
        "authority_expression": str(metric["expression"]),
        "missing_predicates": missing,
        "already_present_predicates": present,
        "steps": steps,
        "reconstructed_value": prev,
        "explained_by_predicate": bool(same_expression and missing and converged),
        "why_not_explained": (
            None
            if (same_expression and missing and converged)
            else "；".join(
                        filter(
                            None,
                            [
                                None if same_expression else "gold 的聚合表达式与语义包不同（差异不是谓词能解释的）",
                                None if missing else "gold 已含全部默认谓词 ⇒ 差异无口径元素可归",
                                None if converged else "补齐谓词后仍不收敛到权威值",
                            ],
                        )
                    )
                    or None
        ),
    }


def main() -> int:
    loaded = load_bundle(_bootstrap.BUNDLE_PATH)
    terms = metric_terms(loaded, SemanticBundleRuntime(loaded))
    by_name = {str(m.name): m for m in loaded.bundle.metrics}
    physical_of = {
        str(a.logical_name): str(a.physical_asset) for a in loaded.bundle.assets
    }
    dataset = _bootstrap.load_json(_bootstrap.DATASET_PATH)
    cases = list(dataset["cases"])
    db_path = _bootstrap.SANDBOX_DB

    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    harness = Harness()
    try:
        ts_physicals = dict(harness.tenant_scoped_physicals)

        for case in cases:
            question = str(case.get("question") or "")
            gold_sql = str(case.get("gold_sql") or "")
            if not gold_sql or str(case.get("expected_behavior") or "") != "execute":
                continue
            if _GROUP_RE.search(gold_sql):
                continue  # 分组题没有"单个总量"可比

            hit = [
                name for name in CORE_METRICS
                if any(t and t in question for t in terms.get(name, []))
            ]
            if not hit:
                continue
            if len(hit) > 1:
                excluded.append(
                    {"case_id": case["case_id"], "reason": f"题面同时命中多个核心指标词形：{hit}"}
                )
                continue

            name = hit[0]
            metric_obj = by_name[name]
            asset = str(getattr(metric_obj.default_binding, "asset", "") or "")
            view = physical_of.get(asset)
            metric = {
                "asset": asset,
                "view": view,
                "expression": str(metric_obj.expression or ""),
                "time_basis": str(getattr(metric_obj, "time_basis", "") or ""),
                "default_predicates": [str(p) for p in (metric_obj.default_predicates or ())],
            }
            if not asset or not metric["expression"]:
                excluded.append(
                    {"case_id": case["case_id"], "reason": f"{name} 缺 default_binding.asset 或 expression"}
                )
                continue
            if not view:
                excluded.append(
                    {"case_id": case["case_id"], "reason": f"{asset} 在 bundle.assets 里没有 physical_asset"}
                )
                continue
            if view not in ts_physicals:
                excluded.append(
                    {"case_id": case["case_id"], "reason": f"{view}（{asset} 的物理关系）不在租户域资产清单里，无法定边界"}
                )
                continue

            if _relations(gold_sql) != {view.lower()}:
                excluded.append(
                    {
                        "case_id": case["case_id"],
                        "reason": f"gold 读的不是该指标的关系：{sorted(_relations(gold_sql))} ≠ [{view}]",
                    }
                )
                continue

            time_clauses = _time_clauses(gold_sql, metric["time_basis"])
            non_time = [t for t in _where_terms(gold_sql) if not _time_clauses(t, metric["time_basis"])]
            pure = [t for t in non_time if _canon(t) in {_canon(p) for p in metric["default_predicates"]}]
            if len(non_time) != len(pure):
                excluded.append(
                    {
                        "case_id": case["case_id"],
                        "reason": f"gold 还带了非时间、非默认谓词的条件：{[t for t in non_time if t not in pure][:3]}",
                    }
                )
                continue

            tenant = str(case.get("eval_tenant") or "T_A")
            gold_out = run_in_sandbox(
                gold_sql, tenant=tenant, views=True, db_path=db_path, tenant_scoped_physicals=ts_physicals
            )
            gold_value = _scalar(gold_out)

            preds = [_qualify(p, asset, view) for p in metric["default_predicates"]]
            auth_sql = _authority_sql(
                _qualify(metric["expression"], asset, view), view, time_clauses, preds
            )
            auth_out = run_in_sandbox(
                auth_sql, tenant=tenant, views=True, db_path=db_path, tenant_scoped_physicals=ts_physicals
            )
            auth_value = _scalar(auth_out)

            err = _rel_err(gold_value, auth_value)
            row: dict[str, Any] = {
                "case_id": str(case["case_id"]),
                "metric": name,
                "tenant": tenant,
                "question": question,
                "gold_sql": re.sub(r"\s+", " ", gold_sql).strip(),
                "authority_sql": auth_sql,
                "gold_value": gold_value,
                "authority_value": auth_value,
                "rel_error": None if err is None else round(err, 6),
                "consistent": bool(err is not None and err < REL_TOL),
                "gold_error": gold_out.get("error"),
                "authority_error": auth_out.get("error"),
                "attribution": None,
            }
            if gold_value is not None and auth_value is not None and not row["consistent"]:
                row["attribution"] = _attribute(
                    gold_sql=gold_sql,
                    metric=metric,
                    gold_value=gold_value,
                    authority_value=auth_value,
                    tenant=tenant,
                    db_path=db_path,
                    ts_physicals=ts_physicals,
                )
            rows.append(row)
    finally:
        asyncio.run(harness.aclose())

    comparable = [r for r in rows if r["gold_value"] is not None and r["authority_value"] is not None]
    differing = [r for r in comparable if not r["consistent"]]
    unattributed = [
        r for r in differing if not (r["attribution"] or {}).get("explained_by_predicate")
    ]
    out = {
        "threshold_rel_error": REL_TOL,
        "core_metrics": list(CORE_METRICS),
        "total": len(comparable),
        "consistent": sum(1 for r in comparable if r["consistent"]),
        "consistent_rate": round(
            sum(1 for r in comparable if r["consistent"]) / len(comparable), 4
        )
        if comparable
        else 0.0,
        "unattributed": len(unattributed),
        "differing": [r["case_id"] for r in differing],
        "unattributed_cases": [r["case_id"] for r in unattributed],
        "metrics_covered": sorted({r["metric"] for r in comparable}),
        "rows": rows,
        "excluded": excluded,
        "comparison_basis": (
            "权威侧 = 语义包 `metrics[].expression + default_predicates + time_basis` 在同一沙箱、"
            "同一租户边界（TEMP VIEW）上的直接实现；被比侧 = 冻结集 `gold_sql`（W1A，content_hash 冻结）。"
            "⚠️ 本项目无外部 BI 权威值可引 ⇒ 本产物验的是**内部口径一致性**，"
            "不是对外部报表数字的验证（§C.4.3 的「已确认权威值」只能降级到这一层，报告须如实写）。"
        ),
        "caveat": (
            "只纳入「题面命中单个核心指标词形 + gold 无 GROUP BY + WHERE 除时间边界与默认谓词外无其他条件」"
            "的用例；被排除者逐条列在 `excluded`，不静默丢。"
            "可归因判据是三条同时成立（表达式同形 + 缺集非空 + 补齐后收敛），见本文件 docstring。"
        ),
    }
    path = os.path.join(HERE, "probe_metric_values.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(f"可比对 {out['total']} 条 / 一致 {out['consistent']}（{out['consistent_rate']:.1%}）"
          f" / 不可归因 {out['unattributed']}")
    print(f"覆盖指标：{out['metrics_covered']}；排除 {len(excluded)} 条")
    for r in differing[:8]:
        att = r["attribution"] or {}
        print(f"  差异 {r['case_id']} {r['metric']}: gold={r['gold_value']} auth={r['authority_value']} "
              f"rel_err={r['rel_error']} 缺谓词={att.get('missing_predicates')} "
              f"可归因={att.get('explained_by_predicate')} {att.get('why_not_explained') or ''}")
    print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
