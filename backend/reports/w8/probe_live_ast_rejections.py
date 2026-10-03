"""W8 探针：把 2026-10-03 真打批次里 **32 条 `GATE_AST_REJECTED`** 逐条归因（零 LLM、零执行）。

为什么要单独打这一枪（不是重复 `reports/w6/probe_gate_rejections.py`）：
W6 那支探针证的是**静态爆炸半径**（按 `gold_sql` 的表集合预测会中招的用例 = 14/166）。
本轮是**真打产物**：模型自己写的 SQL 里带了哪些列、闸门派发了哪条规则，是实测的 32 条。
两件事的读数不能互相代替 —— 静态预测会把"模型自己编了个列"也算进闸门缺陷，
而闸门缺陷（按域注入出不存在的列）又会伪装成"模型不行"。⇒ 本探针逐条把两者**拆开**。

分类口径（每条只落一类，优先级从上到下）：
- `injection_self_defect` —— `detect_gate_self_defect` 命中 F1/F2 ⇒ 闸门的账，不得计入模型能力；
- `model_unknown_column` —— 模型写的列**不在**该资产可见列面、且不是注入产物 ⇒ 模型的账；
- `literal_policy` —— R14：列出树里全部字面量与白名单三类，逐条点名哪一类没接住；
- `limit_form` —— R04/R10 等其余规则：直接回显触发形状（LIMIT 表达式 / JOIN 条件）。

跑法（CommerceQL 根目录）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/probe_live_ast_rejections.py
产物：同目录 `probe_live_ast_rejections.json`
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

import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402

from app.core.enums import Role  # noqa: E402
from app.guard import run_gate1  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

import harness as eval_harness  # noqa: E402

RESULTS = os.path.join(ROOT, "eval", "results_v1.json")
OUT = os.path.join(HERE, "probe_live_ast_rejections.json")


def _allowlist(runtime: SemanticBundleRuntime, case_id: str, tenant: str) -> dict:
    identity = eval_harness.identity_for_case(case_id, tenant, role=Role.ANALYST)
    return runtime.guard_allowlist(identity, max_rows=None)


def _model_columns(tree: exp.Expr, allowlist: dict) -> tuple[list[str], list[str]]:
    """返回 (模型引用的列里不在该资产可见面的, 全部限定列引用)。"""
    assets = allowlist.get("assets") or {}
    tables = {t.name: t for t in tree.find_all(exp.Table)}
    known, unknown = [], []
    for col in tree.find_all(exp.Column):
        qual = col.table or ""
        entry = assets.get(qual) if qual else None
        if entry is None:                       # 无限定 / 别名 / 未知表 ⇒ 交闸门自己判
            continue
        face = set((entry.get("columns") or {}).keys())
        item = f"{qual}.{col.name}"
        (known if col.name in face else unknown).append(item)
    return sorted(set(unknown)), [f"{c.table or '<bare>'}.{c.name}" for c in tree.find_all(exp.Column)]


def _literals(tree: exp.Expr, allowlist: dict) -> dict[str, list[str]]:
    allowed = {str(v) for v in (allowlist.get("allowed_constants") or ())}
    out: dict[str, list[str]] = {"in_bundle_allowlist": [], "not_in_allowlist": []}
    for lit in tree.find_all(exp.Literal):
        text = str(lit.this)
        key = "in_bundle_allowlist" if text in allowed or f"'{text}'" in allowed else "not_in_allowlist"
        out[key].append(text)
    return out


def _limit_shape(tree: exp.Expr) -> str:
    lim = tree.args.get("limit")
    return "<无 LIMIT>" if lim is None else lim.sql(dialect="postgres")


def main() -> int:
    payload = json.load(open(RESULTS, encoding="utf-8"))
    records = payload["records"]
    rejected = [r for r in records if r.get("terminal_code") == "GATE_AST_REJECTED"]
    runtime = SemanticBundleRuntime(load_bundle(_bootstrap.BUNDLE_PATH))

    rows = []
    for rec in rejected:
        sql = rec.get("sql_text") or ""
        allowlist = _allowlist(runtime, rec["case_id"], rec["tenant"])
        report = run_gate1(sql, allowlist)
        self_defect = eval_harness.detect_gate_self_defect(sql, allowlist)
        try:
            tree = sqlglot.parse_one(sql, dialect="postgres")
        except sqlglot.errors.ParseError:
            tree = None
        unknown_cols, all_cols = _model_columns(tree, allowlist) if tree else ([], [])
        rows.append({
            "case_id": rec["case_id"],
            "tenant": rec["tenant"],
            "rule": report.gate_result.rule_id,
            "record_rule": rec.get("gate1_reject_rule"),
            "self_defect": self_defect,
            "applied_predicates": list(report.applied_predicates),
            "model_unknown_columns": unknown_cols,
            "model_columns": all_cols,
            "literals": _literals(tree, allowlist) if tree else None,
            "limit_expr": _limit_shape(tree) if tree else None,
            "sql": sql,
            "question": rec["question"],
        })

    def tally(items):
        return dict(collections.Counter(items).most_common())

    classes = []
    for row in rows:
        if row["self_defect"]:
            classes.append("injection_self_defect")
        elif row["rule"] == "R06" and row["model_unknown_columns"]:
            classes.append("model_unknown_column")
        elif row["rule"] == "R14":
            classes.append("literal_policy")
        else:
            classes.append("other:" + str(row["rule"]))

    out = {
        "as_of": "2026-10-03 真打批次 results_v1.json git_rev="
                 f"{payload.get('git_rev')} dirty={payload.get('git_dirty')}",
        "n_rejected": len(rows),
        "rule_tally_record_side": tally(r.get("gate1_reject_rule") for r in rejected),
        "rule_tally_recomputed": tally(r["rule"] for r in rows),
        "class_tally": tally(classes),
        "self_defect_tally": tally(r["self_defect"] for r in rows if r["self_defect"]),
        "model_unknown_column_tally": tally(
            c for r in rows for c in r["model_unknown_columns"] if not r["self_defect"]
        ),
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
