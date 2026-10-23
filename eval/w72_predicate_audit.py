"""W72 零出站审计：D 类谓词缺口 / G-7 判据对象 / refund_rate 泄漏定位 / 列配对 id↔name。

派单：W8 第 72 轮（2026-10-23 14:56）。四件事全部**只读**：
- W72-1：全量 execute 的 gold WHERE 与包内 metric 级 ``default_predicates`` 求差
- W72-2：核实 ``gates.py`` G-7 取的是 ``probe_metric_values.json`` 的 consistent/total，
          并另算 system vs authority（不改判据）
- W72-3：定位 refund_rate 谓词泄漏（只给文件行号与实算证据，**不改代码**）
- W72-4：列配对 id↔name 材料（不改 equivalence.py）

零出站：不打任何 API；沙箱是本地 sqlite。tokens 计费 = 0。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from _bootstrap import BUNDLE_PATH, bootstrap, build_stamp  # noqa: E402

bootstrap()

#: 进程启动即取构建身份：先取后写，避免同进程写盘弄脏后续 stamp（W68 实测）。
STAMP = build_stamp()

import yaml  # noqa: E402

from app.semantics import load_bundle  # noqa: E402
import equivalence as eq  # noqa: E402
import runner  # noqa: E402

ROOT = os.path.dirname(HERE)
BUNDLE = BUNDLE_PATH
SANDBOX = os.path.join(ROOT, "data", "ecom_sandbox.db")
SRC_R66 = os.path.join(HERE, "results_r66_tau_raw_replay.json")
PROBE = os.path.join(ROOT, "backend", "reports", "w6", "probe_metric_values.json")

OUT_GAP = os.path.join(HERE, "results_r72_d_predicate_gap.json")
OUT_G7 = os.path.join(HERE, "results_r72_g7_object.json")
OUT_LEAK = os.path.join(HERE, "results_r72_refund_leak_localization.json")
OUT_PAIR = os.path.join(HERE, "results_r72_column_pairing.json")

PROVENANCE = "W72 零出站审计（r66 重放 + 冻结集 + 语义包 + 沙箱 sqlite；tokens 计费 = 0）"


# ============================================================================
# 公共：语义包谓词索引（带行号）
# ============================================================================

def _pred_index() -> dict[str, Any]:
    """metric → 包内 ``default_predicates`` + 行号；域级块亦带行号。"""
    raw = open(BUNDLE, encoding="utf-8").read().splitlines()
    data = yaml.safe_load(open(BUNDLE, encoding="utf-8"))

    starts = [(i + 1, ln.split("name:", 1)[1].strip())
              for i, ln in enumerate(raw) if ln.startswith("  - name:")]
    spans: dict[str, tuple[int, int]] = {}
    for idx, (line_no, name) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(raw)
        spans[name] = (line_no, end)

    metrics: dict[str, Any] = {}
    for m in data.get("metrics") or []:
        name = m["name"]
        lo, hi = spans.get(name, (0, 0))
        block_line = None
        pred_lines: dict[str, int] = {}
        if lo:
            in_block = False
            for i in range(lo - 1, min(hi, len(raw))):
                s = raw[i].strip()
                if s.startswith("default_predicates:"):
                    block_line = i + 1
                    in_block = True
                    continue
                if in_block:
                    if s.startswith("- "):
                        pred_lines[s[2:].strip().strip('"').strip("'")] = i + 1
                    elif s and not s.startswith("#"):
                        break
        metrics[name] = {
            "predicates": list(m.get("default_predicates") or ()),
            "predicate_lines": pred_lines,
            "block_line": block_line,
            "span": [lo, hi],
            "synonyms": m.get("synonyms") or [],
            "expression": m.get("expression"),
        }

    # 域级块：顶层 `default_predicates:`（0 缩进）下的二级 key
    domain: dict[str, list[dict[str, Any]]] = {}
    top = next((i for i, ln in enumerate(raw) if ln.rstrip() == "default_predicates:"), None)
    if top is not None:
        cur_domain = None
        cur_item: dict[str, Any] | None = None
        for i in range(top + 1, len(raw)):
            ln = raw[i]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            if not ln.startswith(" "):
                break
            if re.match(r"^  [A-Za-z_]+:\s*$", ln):
                cur_domain = ln.strip().rstrip(":")
                domain.setdefault(cur_domain, [])
                cur_item = None
            elif ln.lstrip().startswith("- id:"):
                cur_item = {"id": ln.split(":", 1)[1].strip(), "line": i + 1}
                domain[cur_domain].append(cur_item)
            elif cur_item is not None:
                s = ln.strip()
                if s.startswith("predicate:"):
                    cur_item["predicate"] = s.split(":", 1)[1].strip().strip('"').strip("'")
                    cur_item["predicate_line"] = i + 1
                elif s.startswith("applies_to:"):
                    raw_list = s.split(":", 1)[1].strip()
                    cur_item["applies_to"] = [x.strip() for x in raw_list.strip("[]").split(",") if x.strip()]
    return {"metrics": metrics, "domain": domain}


# ============================================================================
# 谓词三态化与 SQL WHERE 处理
# ============================================================================

_PRED_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.]*)\s*(<>|!=|>=|<=|=|>|<)\s*('[^']*'|\"[^\"]*\"|[A-Za-z_]+|-?\d+(?:\.\d+)?)"
)


def _norm_val(v: str) -> str:
    v = v.strip()
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
    return v.strip().lower()


def _triples(text: str) -> list[tuple[str, str, str]]:
    """把谓词/SQL 片段解析成 (列名去限定, 算子, 归一值) 三元组。"""
    out: list[tuple[str, str, str]] = []
    for col, op, val in _PRED_RE.findall(text or ""):
        col = col.split(".")[-1]
        op = "<>" if op == "!=" else op
        out.append((col, op, _norm_val(val)))
    return out


def _where_span(sql: str) -> tuple[int, int] | None:
    """返回顶层 WHERE 子句的 (start, end)：end 不含后续 GROUP/ORDER/LIMIT。"""
    low = sql.lower()
    depth = 0
    where_at = -1
    for i, ch in enumerate(low):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and low.startswith(" where ", i):
            where_at = i
    if where_at < 0:
        return None
    tail_kw = (" group by ", " order by ", " limit ", " having ")
    end = len(sql)
    depth = 0
    for i in range(where_at + 7, len(low)):
        ch = low[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            for kw in tail_kw:
                if low.startswith(kw, i):
                    end = i
                    break
            if end != len(sql):
                break
    return where_at, end


def _inject(sql: str, predicates: list[str]) -> str:
    """把谓词 AND 进**拥有目标表的那个 SELECT**（AST 层，不用字符串拼）。

    为什么不用正则插 WHERE：M-IDX-09 的金标是 `SELECT … FROM (SELECT … WHERE pay_time…)`，
    外层没有 WHERE，正则会把谓词拼到内层 GROUP BY 之后 → `near "WHERE": syntax error`
    （W72 首版实测踩到）。AST 选择「深度最大且含 FROM 的 SELECT」，与 ast_gate 的注入语义一致。
    """
    if not predicates:
        return sql
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, dialect="postgres")

        def _depth(node) -> int:
            d, p = 0, node.parent
            while p is not None:
                p, d = p.parent, d + 1
            return d

        selects = [s for s in tree.find_all(exp.Select)]
        targets = sorted(selects, key=_depth, reverse=True)
        for sel in targets:
            #: sqlglot 30 的 FROM 键是 `from_`（不是 `from`）；用 args 判空而非 find_all(From)
            if not (sel.args.get("from_") or sel.args.get("from")):
                continue
            for pred_sql in predicates:
                #: ⚠️ `where(..., copy=True)` 返回新节点**不改原树**（W72 首版静默无效的根因）
                sel.where(exp.condition(pred_sql), append=True, copy=False)
            return tree.sql(dialect="postgres")
        return sql
    except Exception:
        return sql


def _matched_metrics(q: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[tuple[int, str, str]] = []
    for name, meta in metrics.items():
        for syn in meta["synonyms"]:
            if syn and syn in q:
                hits.append((len(syn), name, syn))
    hits.sort(reverse=True)
    seen: dict[str, str] = {}
    for _, name, syn in hits:
        seen.setdefault(name, syn)
    return [{"metric": n, "synonym": s} for n, s in seen.items()]


# ============================================================================
# W72-1 D 类：gold 漏包内 default_predicates
# ============================================================================

def build_gap(index: dict[str, Any], sandbox) -> dict[str, Any]:
    loaded = load_bundle(BUNDLE)
    tsf = {a.physical_asset: "tenant_id"
           for a in loaded.bundle.assets
           if a.tenant_scoped and a.logical_name in loaded.active_assets}
    metrics = index["metrics"]
    records = [r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]
               if r.get("terminal_event") == "complete" and (r.get("gold") or {}).get("gold_sql")]
    g7_ids = {row["case_id"] for row in
              json.load(open(PROBE, encoding="utf-8")).get("rows", [])}

    rows: list[dict[str, Any]] = []
    for r in records:
        cid = r["case_id"]
        q = str(r.get("question") or "")
        gold = r["gold"]["gold_sql"]
        tenant = r.get("tenant") or "T_A"
        hits = _matched_metrics(q, metrics)

        span = _where_span(gold)
        where_txt = gold[span[0]:span[1]] if span else ""
        present = _triples(where_txt)

        per_metric: list[dict[str, Any]] = []
        required_all: list[str] = []
        for h in hits:
            name = h["metric"]
            meta = metrics[name]
            req = meta["predicates"]
            missing = [p for p in req if not _contains(present, p)]
            # 反向口径：同列不同值（如 pay_status='unpaid' 对包内 pay_status='paid'）
            conflict = [p for p in req if _conflicts(present, p)]
            per_metric.append({
                "metric": name,
                "synonym": h["synonym"],
                "bundle_block_line": meta["block_line"],
                "bundle_predicate_lines": meta["predicate_lines"],
                "required": req,
                "missing": missing,
                "conflicting": conflict,
            })
            required_all.extend(p for p in req if p not in required_all)

        missing_all = [p for p in required_all if not _contains(present, p)]
        conflict_all = [p for p in required_all if _conflicts(present, p)]

        #: 归因强度：比率类指标（expression 含 `/`）要求 gold 也是比率形；
        #: 否则命中的只是同义词字面（如「零转化」命中 pay_cvr，但问的是筛选 SKU 列表）
        weak = []
        for h in hits:
            expr = str(metrics[h["metric"]].get("expression") or "")
            if "/" in expr and "/" not in gold:
                weak.append(h["metric"])

        entry: dict[str, Any] = {
            "case_id": cid,
            "question": q,
            "tenant": tenant,
            "gold_sql": gold,
            "gold_where": where_txt.strip(),
            "metrics_matched": [h["metric"] for h in hits],
            "required_predicates": required_all,
            "missing_predicates": missing_all,
            "conflicting_predicates": conflict_all,
            "per_metric": per_metric,
            "defect": bool(missing_all or conflict_all),
            "in_g7_probe_set": cid in g7_ids,
            "attribution_weak_metrics": weak,
            "notes": [],
        }
        if weak:
            entry["notes"].append(
                "归因偏弱：" + "、".join(weak) + " 的包内 expression 是比率形，而 gold 不是 ⇒ "
                "同义词只是字面命中（该条不计入主账，单列 weak_attribution）"
            )
        if not hits:
            entry["notes"].append("问句未命中任何包内指标同义词 ⇒ 本规则无从比对（不计缺陷）")

        # —— 沙箱实算：gold 原值 vs 补谓词后值 ——
        if missing_all and hits:
            g0 = sandbox(gold, tenant=tenant)
            patched = _inject(gold, missing_all)
            g1 = sandbox(patched, tenant=tenant)
            pred_sql = r.get("sql_text") or ""
            p = sandbox(pred_sql, r.get("sql_params") or {}, tenant=tenant) if pred_sql else {}
            entry["sandbox"] = {
                "patched_sql": patched,
                "gold_rows_before": g0.get("rows"),
                "gold_rows_after": g1.get("rows"),
                "gold_error_before": g0.get("error"),
                "gold_error_after": g1.get("error"),
                "gold_value_before": _scalar(g0.get("table")),
                "gold_value_after": _scalar(g1.get("table")),
                "gold_hash_before": g0.get("hash"),
                "gold_hash_after": g1.get("hash"),
                "value_changed": (g0.get("hash") is not None and g1.get("hash") is not None
                                  and g0.get("hash") != g1.get("hash")),
                "pred_value": _scalar(p.get("table")) if p else None,
                "pred_error": (p or {}).get("error"),
            }
            # 等价结论是否改变
            before = after = None
            if g0.get("table") is not None and p.get("table") is not None:
                before = eq.compare_tables(g0["table"], p["table"],
                                           gold_sql=gold, pred_sql=pred_sql).equivalent
            if g1.get("table") is not None and p.get("table") is not None:
                after = eq.compare_tables(g1["table"], p["table"],
                                          gold_sql=patched, pred_sql=pred_sql).equivalent
            entry["sandbox"]["equivalent_before"] = before
            entry["sandbox"]["equivalent_after"] = after
            entry["sandbox"]["flips_to_equivalent"] = bool(after) and not before
        rows.append(entry)

    # —— E-MET-08 单独标注 ——
    emet08 = next((x for x in rows if x["case_id"] == "E-MET-08"), None)
    emet08_note = {
        "case_id": "E-MET-08",
        "included_in_execute_scope": emet08 is not None,
        "gold_sql": (emet08 or {}).get("gold_sql"),
        "verdict": (
            "合法反向口径（题面明写「含未支付」⇒ gold `pay_status = 'unpaid'` 是对的）；"
            "包内 default_predicates 是**默认**值不是绝对约束，题面显式覆盖时应当豁免。"
            "但它是 D 类规则的边界：机械求差会把它误判成 conflict，故单列。"
            if emet08 else
            "该条终态非 complete（r66=refuse）⇒ 不在 execute 作用域内；"
            "gold `pay_status = 'unpaid'` 属题面显式指定的反向口径，合法。"
        ),
        "terminal_event": next((rec.get("terminal_event") for rec in
                                json.load(open(SRC_R66, encoding="utf-8"))["records"]
                                if rec["case_id"] == "E-MET-08"), None),
    }

    # —— 汇总 ——
    defect_rows = [x for x in rows if x["defect"] and x["notes"] == []]
    by_metric: dict[str, dict[str, Any]] = {}
    for x in defect_rows:
        for pm in x["per_metric"]:
            if not pm["missing"] and not pm["conflicting"]:
                continue
            slot = by_metric.setdefault(pm["metric"], {"n": 0, "cases": [],
                                                       "missing_combos": Counter()})
            slot["n"] += 1
            slot["cases"].append(x["case_id"])
            slot["missing_combos"][tuple(pm["missing"] or pm["conflicting"])] += 1
    by_metric = {k: {**v, "missing_combos": {str(k2): v2 for k2, v2 in v["missing_combos"].items()}}
                 for k, v in by_metric.items()}

    flips = [x["case_id"] for x in rows
             if (x.get("sandbox") or {}).get("flips_to_equivalent")]
    value_changed = [x["case_id"] for x in rows
                     if (x.get("sandbox") or {}).get("value_changed")]

    harmless = [x["case_id"] for x in rows
                if x["defect"] and x["notes"] == []
                and (x.get("sandbox") or {}).get("value_changed") is False]

    return {
        "provenance": PROVENANCE,
        "task": "W72-1 D 类补审：gold WHERE 与包内 metric 级 default_predicates 求差（只出表，不改 gold）",
        **STAMP,
        "method": (
            "① 问句按包内 synonyms 最长匹配定位指标；② 取该指标 metric 级 default_predicates 为应有集"
            "（loader.py:384-408 保证它是域级 applies_to 的子集）；③ 解析 gold 顶层 WHERE 的三元组求差；"
            "④ 沙箱同租户重跑 gold 原样 / 补谓词版 / 系统预测，用 equivalence.compare_tables 判等价"
        ),
        "scope": {
            "n_execute_with_gold": len(rows),
            "scope_definition": "terminal_event == complete 且 gold_sql 非空（r66 重放产物）",
        },
        "headline": {
            "n_defect": len(defect_rows),
            "n_defect_total_incl_weak": sum(1 for x in rows if x["defect"]),
            "n_weak_attribution": sum(1 for x in rows if x["defect"] and x["attribution_weak_metrics"]),
            "weak_attribution_cases": [x["case_id"] for x in rows
                                       if x["defect"] and x["attribution_weak_metrics"]],
            "n_missing_only": sum(1 for x in defect_rows if x["missing_predicates"]),
            "n_conflict": sum(1 for x in defect_rows if x["conflicting_predicates"]),
            "n_value_changed": len(value_changed),
            "n_value_unchanged_harmless": len(harmless),
            "harmless_cases": harmless,
            "harmless_split": {
                "defensive_only": [c for c in harmless if c not in ("M-IDX-09", "M-IDX-10")],
                "unchanged_but_anomalous": [c for c in harmless if c in ("M-IDX-09", "M-IDX-10")],
            },
            "harmless_reason": "补谓词后沙箱结果哈希不变 —— ① `uv >= 0` 这类防御性谓词（数据无负数）"
                               "与 uv/pay_cvr 缺口属数值无害；② M-IDX-09/10 补谓词后**仍为 0**"
                               "（系统预测 0.16/0.13）⇒ 那不是谓词无害，是复购口径另有问题，"
                               "本轮只登记、不归因（超出 D 类范围）",
            "n_flips_to_equivalent": len(flips),
            "flip_cases": flips,
            "g7_subset": {
                "n": sum(1 for x in rows if x["in_g7_probe_set"]),
                "n_gold_where_time_only": sum(
                    1 for x in rows if x["in_g7_probe_set"]
                    and not re.search(r"pay_status|refund_status|is_test_order|uv\s*>=|on_sale",
                                      x["gold_where"] or "", re.IGNORECASE)),
                "cases": [{"case_id": x["case_id"], "metric": x["metrics_matched"],
                           "gold_where": x["gold_where"],
                           "missing": x["missing_predicates"]}
                          for x in rows if x["in_g7_probe_set"]],
            },
            "by_metric": by_metric,
        },
        "emet08_reverse_caliber": emet08_note,
        "rows": rows,
    }


def _contains(present: list[tuple[str, str, str]], pred: str) -> bool:
    """谓词是否已被 gold 覆盖（列 + 算子 + 值全等）。"""
    want = _triples(pred)
    if not want:
        return True
    for t in want:
        if t not in present:
            return False
    return True


def _conflicts(present: list[tuple[str, str, str]], pred: str) -> bool:
    """gold 有同列但不同值（反向口径）。"""
    for col, op, val in _triples(pred):
        for pcol, pop, pval in present:
            if pcol == col and pop == op and pval != val:
                return True
    return False


def _scalar(table: eq.Table | None) -> Any:
    if table is None:
        return None
    if len(table.rows) == 1 and len(table.rows[0]) == 1:
        v = table.rows[0][0]
        return round(v, 8) if isinstance(v, float) else v
    return None


# ============================================================================
# W72-2 G-7 判据对象核实 + 两案提案
# ============================================================================

def build_g7(sandbox) -> dict[str, Any]:
    probe = json.load(open(PROBE, encoding="utf-8"))
    records = {r["case_id"]: r for r in
               json.load(open(SRC_R66, encoding="utf-8"))["records"]}
    thr = float(probe.get("threshold_rel_error") or 1e-3)

    rows = []
    sys_ok = 0
    for row in probe["rows"]:
        cid = row["case_id"]
        rec = records.get(cid) or {}
        tenant = row.get("tenant") or rec.get("tenant") or "T_A"
        auth = row.get("authority_value")
        gold_v = row.get("gold_value")
        system_v, sys_err = None, None
        pred_sql = rec.get("sql_text") or ""
        if pred_sql:
            res = sandbox(pred_sql, rec.get("sql_params") or {}, tenant=tenant)
            sys_err = res.get("error")
            system_v = _scalar(res.get("table"))
        rel_err = (abs(system_v - auth) / abs(auth)) if (system_v is not None and auth) else None
        ok = rel_err is not None and rel_err <= thr
        sys_ok += int(ok)
        rows.append({
            "case_id": cid,
            "metric": row.get("metric"),
            "authority_value": auth,
            "gold_value": gold_v,
            "gold_consistent": bool(row.get("consistent")),
            "system_value": system_v,
            "system_error": sys_err,
            "system_rel_error": rel_err,
            "system_consistent": ok,
            "missing_predicates": (row.get("attribution") or {}).get("missing_predicates"),
        })

    return {
        "provenance": PROVENANCE,
        "task": "W72-2 G-7 判据对象核实与提案（只出材料，不改 gates.py / 探针脚本）",
        **STAMP,
        "code_fact": {
            "g7_branch": "eval/gates.py:488-508",
            "read_fields": ["consistent", "total", "unattributed", "comparison_basis"],
            "input_artifact": "backend/reports/w6/probe_metric_values.json",
            "input_wiring": "eval/reporter.py:948-949 / 1031（consistency = _load(probe_metric_values.json)）",
            "conclusion": (
                "G-7 现状消费者的确是该文件的 consistent/total；而该文件的 rows[] 比的是 "
                "gold_value vs authority_value ⇒ 度量对象 = 题库口径一致性，不是系统能力"
            ),
        },
        "calibration": {
            "threshold_rel_error": thr,
            "gold_vs_authority": {
                "consistent": int(probe.get("consistent") or 0),
                "total": int(probe.get("total") or 0),
                "rate": round(int(probe.get("consistent") or 0) / int(probe.get("total") or 1), 4),
                "definition": "题库金标与语义包/权威口径是否一致（现行 G-7 读数）",
            },
            "system_vs_authority": {
                "consistent": sys_ok,
                "total": len(rows),
                "rate": round(sys_ok / max(len(rows), 1), 4),
                "definition": "系统预测值与权威值是否一致（同一把尺 rel_err ≤ 1e-3）",
                "failures": [r["case_id"] for r in rows if not r["system_consistent"]],
            },
            "red_line": "system vs authority = %.1f%% 仍 < 95%% ⇒ 不得写成「G-7 通过」" % (100.0 * sys_ok / max(len(rows), 1)),
        },
        "proposals": [
            {
                "option": "A",
                "title": "维持现口径，改名「题库口径一致性」并移出八格",
                "why": "现行实现度量的对象确实是题库；它是有价值的回归检查（防止改题库时口径漂移），"
                       "但不是系统能力，放在八格里会持续被误读为「系统口径 7.7%」",
                "cost": {
                    "files": ["eval/gates.py（G-7 分支改名/移出）", "eval/reporter.py（八格汇总里去掉该格）",
                              "deploy/runbook/README.md（门禁清单同步）"],
                    "regression": "历史读数不需重算（口径不变，只是移出八格）；但**八格变七格**，"
                                  "所有引用「PASS x/8」的外部材料都要改",
                    "egress": 0,
                },
                "risk": "少一格 = 少一个约束；题库与包的一致性一旦漂移将无门禁拦截",
            },
            {
                "option": "B",
                "title": "改为 system vs authority 作为 G-7 真身",
                "why": "门禁要管的是「系统算出来的数对不对」，权威值比对才是这个语义；"
                       "且现行口径可被『把 gold 换成 authority_sql』刷绿（QA §93.4 已指出）",
                "cost": {
                    "files": ["eval/gates.py（G-7 分支改读字段）",
                              "探针脚本 backend/reports/w6 的产出侧（新增 system_value/system_consistent）",
                              "eval/reporter.py（G-7 证据行）"],
                    "regression": "须重算历史读数（7.7% → 84.6%），须重跑基线快照，须总控签",
                    "egress": 0,
                },
                "risk": "system 侧取值依赖 sandbox 重跑预测 SQL ⇒ 引入执行环境依赖；"
                        "另：84.6% < 95% ⇒ 门禁由 FAIL 变为「更接近但仍 FAIL」，不得宣称通过",
            },
        ],
        "rows": rows,
    }


# ============================================================================
# W72-3 refund_rate 谓词泄漏：定位证据（不改代码）
# ============================================================================

def build_leak(index: dict[str, Any], sandbox) -> dict[str, Any]:
    records = {r["case_id"]: r for r in
               json.load(open(SRC_R66, encoding="utf-8"))["records"]}
    probe = json.load(open(PROBE, encoding="utf-8"))
    auth = {r["case_id"]: r["authority_value"] for r in probe["rows"]}
    metric = index["metrics"]["refund_rate"]
    domain_preds = index["domain"].get("orders") or []
    leak_pred = "refund_status <> 'refunded'"
    leak_domain = next((d for d in domain_preds if d.get("predicate") == leak_pred), None)

    cases = []
    for cid in ("M-IDX-05", "M-IDX-06"):
        rec = records.get(cid) or {}
        gold = (rec.get("gold") or {}).get("gold_sql") or ""
        pred_sql = rec.get("sql_text") or ""
        # 去掉泄漏谓词后的等价 SQL（仅用于证明它把分子清零）
        clean = pred_sql
        for frag in (" AND v_order_paid.refund_status <> 'refunded'",
                     " AND refund_status <> 'refunded'"):
            clean = clean.replace(frag, "")
        r_leak = sandbox(pred_sql, rec.get("sql_params") or {}, tenant=rec.get("tenant") or "T_A")
        r_clean = sandbox(clean, rec.get("sql_params") or {}, tenant=rec.get("tenant") or "T_A")
        r_gold = sandbox(gold, tenant=rec.get("tenant") or "T_A")
        cases.append({
            "case_id": cid,
            "question": rec.get("question"),
            "applied_predicates": list(rec.get("applied_predicates") or ()),
            "bundle_metric_predicates": metric["predicates"],
            "bundle_metric_block_line": metric["block_line"],
            "leaked_predicate": leak_pred,
            "value_with_leak": _scalar(r_leak.get("table")),
            "value_without_leak": _scalar(r_clean.get("table")),
            "value_gold": _scalar(r_gold.get("table")),
            "authority_value": auth.get(cid),
            "error_with_leak": r_leak.get("error"),
            "sql_with_leak": pred_sql,
            "sql_without_leak": clean,
        })

    return {
        "provenance": PROVENANCE,
        "task": "W72-3 refund_rate 谓词泄漏定位（只定位，不改代码、不改包、不改判据）",
        **STAMP,
        "root_cause": {
            "summary": "注入按**资产所属域**取整份域级谓词表，未按指标自身 default_predicates 过滤 ⇒ "
                       "orders 域的 dp_order_002（refund_status <> 'refunded'）被无差别注入 refund_rate",
            "code_sites": [
                {"file": "backend/app/guard/ast_gate.py", "line": 460,
                 "code": "def _inject_predicates(root: exp.Expr, allowlist: Mapping[str, Any]) -> list[str]:",
                 "note": "函数签名只有 root + allowlist，**没有指标维度** ⇒ 注入侧无法按指标过滤"},
                {"file": "backend/app/guard/ast_gate.py", "line": 463,
                 "code": "pred_by_domain: Mapping[str, Sequence[str]] = allowlist.get(\"default_predicates\") or {}",
                 "note": "谓词表以**域**为键，装载时已丢失 metric 维度与 applies_to"},
                {"file": "backend/app/guard/ast_gate.py", "line": 477,
                 "code": "predicates = pred_by_domain.get(asset.get(\"domain\", \"\"), [])",
                 "note": "按资产 domain 取整份谓词表，不看「当前查询算的是哪个指标」"},
                {"file": "backend/app/guard/ast_gate.py", "line": 491,
                 "code": "for pred_sql in predicates:",
                 "note": "逐条注入；dp_order_002 就是这样进到 refund_rate 的 WHERE 里"},
                {"file": "backend/app/core/contracts.py", "line": 386,
                 "code": "default_predicates: Mapping[str, Sequence[str]]",
                 "note": "交付契约类型本身只有「域→谓词串」，没有 metric→谓词 ⇒ 注入方无处可查"},
                {"file": "backend/app/semantics/loader.py", "line": 384,
                 "code": "default_predicates：applies_to ⊆ 已定义指标；与 metrics[].default_predicates 双向一致",
                 "note": "包加载期**已经**校验了两级一致（含 applies_to），但该信息在投影成 guard_allowlist 时被压平"},
                {"file": "backend/app/graph/nodes/gate1_ast.py", "line": 56,
                 "code": "allowlist = deps.semantics.guard_allowlist(identity, max_rows=…)",
                 "note": "节点手里**有** state（含 plan.metrics），但只按 identity 取 allowlist ⇒ 指标名没往下传"},
            ],
            "why_not_bind": (
                "不是 bind 未覆盖：bind 只负责把概念绑到资产/字段，不下发谓词；"
                "谓词注入发生在 gate1 的 AST 改写阶段（`_inject_predicates`），"
                "那里拿到的 allowlist 只有域级列表"
            ),
        },
        "bundle_evidence": {
            "metric_block_line": metric["block_line"],
            "metric_predicates": metric["predicates"],
            "metric_predicate_lines": metric["predicate_lines"],
            "forbidden_note": "bundle 第 591 行（refund_rate 块内）：本指标的谓词**不含** "
                              "refund_status <> 'refunded' —— 分子正是靠退款行为算出来的",
            "domain_leak_origin": {
                "id": (leak_domain or {}).get("id"),
                "line": (leak_domain or {}).get("line"),
                "predicate_line": (leak_domain or {}).get("predicate_line"),
                "applies_to": (leak_domain or {}).get("applies_to"),
                "note": "applies_to 明确不含 refund_rate ⇒ A 级（域级）本身没错，是注入侧丢了这个过滤",
            },
        },
        "cases": cases,
        "fix_plan": {
            "status": "PROPOSED（未实装；派单要求「先出方案再动手 + 需点句」）",
            "approach": (
                "把指标维度带进注入链，**按指标自身 default_predicates 覆盖域级并集**，"
                "指标不可确定时回落域级（保持现状 = fail-closed，不放松）"
            ),
            "steps": [
                "① contracts.GuardAllowlist 增加 `metric_predicates: Mapping[str, Sequence[str]]`"
                "（来源 bundle.metrics[].default_predicates，loader 已保证与域级一致）",
                "② SemanticBundlePort.guard_allowlist 投影该键（与 assets 同一次取用，不额外查库）",
                "③ graph/nodes/gate1_ast.py 从 state['plan'].metrics 取指标名（去重）并下传",
                "④ ast_gate.run_gate1 / _inject_predicates 增加 metrics 参数："
                "metrics 非空且全部有指标级声明 ⇒ 用其**并集**替换域级集；否则回落域级",
                "⑤ 多指标共存冲突（如 refund_rate + gmv 同 SELECT）无法同时满足 ⇒ 记 warning 并回落域级，"
                "不静默选边",
            ],
            "touch_points": [
                "backend/app/core/contracts.py:382-386（allowlist 类型）",
                "backend/app/semantics/port.py / materialize（投影 metric_predicates）",
                "backend/app/guard/ast_gate.py:460-509（注入选择逻辑）",
                "backend/app/graph/nodes/gate1_ast.py:56-64（传 plan 指标）",
            ],
            "unit_tests": [
                "test_refund_rate_does_not_get_refund_status_filter（refund_rate 的 SQL 不得含 refund_status <> 'refunded'）",
                "test_gmv_keeps_three_predicates（gmv 必须同时含 pay_status / refund_status / is_test_order）",
                "test_metric_predicates_override_domain（指标级 ⊂ 域级时以指标级为准）",
                "test_unknown_metric_falls_back_to_domain（无指标 / 取不到时保持域级，不放松）",
            ],
            "verification": "replay r63 匣带 M-IDX-05/06 + 全量 166（零出站）+ 单测；**不真打**",
            "expected_effect": (
                "M-IDX-05/06 refund_rate 由 0.0 → 0.0501/0.0500（与权威值一致）；"
                "system vs authority 由 11/13 → 13/13（其余不动的前提下）"
            ),
            "blast_radius": (
                "所有带 default_predicates 的查询都会走新分支 ⇒ 必须跑全量 166 回归；"
                "r63 匣带可继续 replay（不改 prompt、不改 SQL 结构，只改注入的谓词集）⇒ 不需重基线"
            ),
        },
    }


# ============================================================================
# W72-4 列配对 id↔name 材料（不改 equivalence.py）
# ============================================================================

def _normalize_gold(sql: str, question: str, missing: list[str]) -> tuple[str, list[str]]:
    """把金标归一到「只剩列身份差异」：补 D 类缺谓词 + 去掉题面没问的在架过滤。

    ⚠️ 只用于**诊断列配对**（W72-4），不是建议改 gold —— 产物里逐条标注 ``counterfactual``。
    """
    applied: list[str] = []
    out = sql
    if missing:
        out = _inject(out, missing)
        applied.append(f"+ 补 D 类谓词 {len(missing)} 条")
    asks_on_sale = any(w in question for w in ("在架", "在售", "上架", "下架", "停售"))
    if not asks_on_sale and re.search(r"\bon_sale\s*=\s*(1|true)\b", out, re.IGNORECASE):
        out = re.sub(r"\s+AND\s+[A-Za-z_.]*on_sale\s*=\s*(?:1|true)\b", "", out, flags=re.IGNORECASE)
        applied.append("- 去 on_sale=1（题面未问在架）")
    return out, applied


def build_pairing(sandbox, index: dict[str, Any]) -> dict[str, Any]:
    metrics = index["metrics"]
    records = [r for r in json.load(open(SRC_R66, encoding="utf-8"))["records"]
               if r.get("terminal_event") == "complete" and (r.get("sql_text") or "")]

    rows = []
    for r in records:
        cid = r["case_id"]
        tenant = r.get("tenant") or "T_A"
        question = str(r.get("question") or "")
        gold_sql = (r.get("gold") or {}).get("gold_sql") or ""
        pred_sql = r["sql_text"]

        hits = _matched_metrics(question, metrics)
        required = []
        for h in hits:
            for p in metrics[h["metric"]]["predicates"]:
                if p not in required:
                    required.append(p)
        span = _where_span(gold_sql)
        present = _triples(gold_sql[span[0]:span[1]] if span else "")
        missing = [p for p in required if not _contains(present, p)]

        norm_gold, norm_ops = _normalize_gold(gold_sql, question, missing)

        params = r.get("sql_params") or {}

        def _run(sql: str) -> dict[str, Any]:
            #: 金标不带绑定参数；只有预测 SQL 才用 sql_params
            return sandbox(sql, params if sql == pred_sql else {}, tenant=tenant)

        g = _run(gold_sql)
        p = _run(pred_sql)
        if g.get("error") or p.get("error") or g.get("table") is None or p.get("table") is None:
            continue
        g2 = _run(norm_gold) if norm_gold != gold_sql else g

        def _shape(table_g: eq.Table, table_p: eq.Table) -> dict[str, Any]:
            gcols = list(table_g.columns)
            pcols = list(table_p.columns)
            pairs, _ = eq._pair_columns(table_g, table_p)
            paired_g = {i for i, _ in pairs}
            paired_p = {j for _, j in pairs}
            un_g = [i for i in range(len(gcols)) if i not in paired_g]
            un_p = [j for j in range(len(pcols)) if j not in paired_p]
            cand = None
            if len(un_g) == 1 and len(un_p) == 1:
                gi, pi = un_g[0], un_p[0]
                gname, pname = gcols[gi], pcols[pi]
                kind = ("id_vs_name"
                        if (gname.lower().endswith("_id") and pname.lower().endswith("_name"))
                        else "other")
                ok, detail = _bijection_ok(table_g, table_p, pairs, gi, pi)
                cand = {"gold_column": gname, "pred_column": pname, "kind": kind,
                        "bijection_ok": ok, "detail": detail,
                        #: 单行单列时双射恒成立（1→1），那是"值比较"不是"身份映射" ⇒ 不得计翻转
                        "vacuous": bool(len(table_g.rows) <= 1 and len(gcols) == 1),
                        "flips_if_allowed": bool(ok and kind == "id_vs_name")}
            return {"gold_columns": gcols, "pred_columns": pcols,
                    "pairs": [{"gold": gcols[i], "pred": pcols[j]} for i, j in pairs],
                    "unmatched_gold": [gcols[i] for i in un_g],
                    "unmatched_pred": [pcols[j] for j in un_p],
                    "failure_kind": (
                        None if not un_g and not un_p else
                        "列数不同（金标 %d / 预测 %d）" % (len(gcols), len(pcols))
                        if len(gcols) != len(pcols) else
                        "id↔name（各剩 1 列）" if (cand and cand["kind"] == "id_vs_name") else
                        "值不同（同名列无法按多重集配对）"
                    ),
                    "candidate": cand}

        strict_v = eq.compare_tables(g["table"], p["table"], gold_sql=gold_sql, pred_sql=pred_sql)
        strict_fail = any("列无法配对" in str(d) for d in strict_v.diffs)
        norm_v = (eq.compare_tables(g2["table"], p["table"], gold_sql=norm_gold, pred_sql=pred_sql)
                  if g2.get("table") is not None else None)
        norm_fail = bool(norm_v and any("列无法配对" in str(d) for d in norm_v.diffs))

        # id↔name 形态是否存在（与是否报错无关）
        has_shape = (any(str(c).lower().endswith("_id") for c in g["table"].columns)
                     and any(str(c).lower().endswith("_name") for c in p["table"].columns))

        if not (strict_fail or norm_fail or has_shape):
            continue

        rows.append({
            "case_id": cid,
            "question": question,
            "rows_gold": len(g["table"].rows),
            "rows_pred": len(p["table"].rows),
            "normalized_gold": norm_gold,
            "normalization_ops": norm_ops,
            "strict": {"column_pairing_failed": strict_fail, **_shape(g["table"], p["table"]),
                       "equivalent": bool(strict_v.equivalent)},
            "normalized": ({"column_pairing_failed": norm_fail,
                            **_shape(g2["table"], p["table"]),
                            "equivalent": bool(norm_v.equivalent)} if norm_v else None),
        })

    def _cand(x: dict, mode: str) -> dict | None:
        return ((x.get(mode) or {}).get("candidate") or None)

    def _is_idname_flip(x: dict, mode: str) -> bool:
        c = _cand(x, mode)
        return bool(c and c["kind"] == "id_vs_name" and c["flips_if_allowed"] and not c["vacuous"])

    strict_flips = [x["case_id"] for x in rows if _is_idname_flip(x, "strict")]
    norm_flips = [x["case_id"] for x in rows if _is_idname_flip(x, "normalized")]
    idname_all = [x["case_id"] for x in rows
                  if any((_cand(x, m) or {}).get("kind") == "id_vs_name"
                         for m in ("strict", "normalized"))]
    vacuous = [x["case_id"] for x in rows
               if any((_cand(x, m) or {}).get("vacuous") for m in ("strict", "normalized"))]
    other = [x["case_id"] for x in rows
             if any((_cand(x, m) or {}).get("kind") == "other" for m in ("strict", "normalized"))]

    return {
        "provenance": PROVENANCE,
        "task": "W72-4 列配对 id↔name 材料（只出材料，不改 equivalence.py）",
        **STAMP,
        "method": (
            "对 r66 每条有预测 SQL 的 complete 记录，在同一沙箱/租户边界重跑金标与预测："
            "① strict = 原样金标；② normalized = 补 D 类缺谓词并去掉题面未问的 on_sale（**仅诊断用**）；"
            "两种模式各自跑 compare_tables，再用 _pair_columns 找未配对列；"
            "对「恰好各剩 1 列且 gold=*_id / pred=*_name」做双射可验证性检查"
            "（按其余已配对列对齐行，检查 id→name 是函数且单射）。"
            "单行单列时双射恒成立 ⇒ 标 vacuous 且**不计翻转**。"
        ),
        "headline": {
            "n_scanned_with_pred_sql": len(records),
            "n_records_involved": len(rows),
            "strict_column_pairing_failures": sum(1 for x in rows
                                                  if (x.get("strict") or {}).get("column_pairing_failed")),
            "strict_failure_kinds": dict(Counter(
                (x.get("strict") or {}).get("failure_kind") for x in rows
                if (x.get("strict") or {}).get("column_pairing_failed"))),
            "normalized_failure_kinds": dict(Counter(
                (x.get("normalized") or {}).get("failure_kind") for x in rows
                if (x.get("normalized") or {}).get("column_pairing_failed"))),
            "id_vs_name_cases": idname_all,
            "n_id_vs_name": len(idname_all),
            "flip_if_allowed_strict": strict_flips,
            "flip_if_allowed_normalized": norm_flips,
            "n_flip_strict": len(strict_flips),
            "n_flip_normalized": len(norm_flips),
            "vacuous_bijection_cases": vacuous,
            "other_candidates_with_bijection": [
                x["case_id"] for x in rows
                if any((_cand(x, m) or {}).get("kind") == "other"
                       and (_cand(x, m) or {}).get("bijection_ok") for m in ("strict", "normalized"))
            ],
            "note": (
                "strict 模式只有 X-ENUM-07 能露出 id↔name（其余被 D 类数值差或 B 类 on_sale 差挡在配对之前）；"
                "normalized 模式才露出 H-CAT-01…05 这一族。两种模式都只是诊断，不是改 gold 的建议。"
                "反向证据：kind=other 的候选里也有 "
                f"{sum(1 for x in rows if any((_cand(x, m) or {}).get('kind') == 'other' and (_cand(x, m) or {}).get('bijection_ok') for m in ('strict', 'normalized')))} "
                "条满足「双射」——因为两侧数值列各值唯一时任意配对都是双射 ⇒ "
                "『允许一一映射』若不加 id↔name 限定，会把纯数值差异也判成等价。"
            ),
        },
        "risk": [
            "① 双射成立只证明「存在一一对应」，不证明**该对应是对的**：两家店同名或 name 列是自由文本时，"
            "仍可能凑出双射而掩盖真错（QA 点名的误配风险）。",
            "② 一旦允许 id↔name 配对，判据就无法区分「同一实体的两种表示」与「换错了维度/实体」——"
            "例如预测把 shop_id 换成 city 起别名 xxx_name，只要行数对上就能凑出双射。",
            "③ 本条属等价判据口径变更 ⇒ 上呈总控，本轮不动 equivalence.py。",
        ],
        "recommended_if_approved": (
            "只对「gold 列名以 _id 结尾 + pred 列名以 _name 结尾 + 行数相同 + 其余列多重集全等 + "
            "双射可验证 + 非 vacuous」开一个**窄口**，并新增 Tag（如 COL_ID_NAME_MAP）在报告里显式计数，"
            "不静默计等价；同时要求配对的双射来源可查（同表 id↔name 映射），不接受跨表推断。"
        ),
        "rows": rows,
    }


def _bijection_ok(gold: eq.Table, pred: eq.Table, pairs: list[tuple[int, int]],
                  gi: int, pi: int) -> tuple[bool, dict[str, Any]]:
    """按其余已配对列对齐行，检查 id→name 为函数且单射。"""
    if len(gold.rows) != len(pred.rows):
        return False, {"reason": "行数不同"}
    g_other = [i for i, _ in pairs]
    p_other = [j for _, j in pairs]
    buckets: dict[tuple, list[tuple[Any, Any]]] = defaultdict(list)
    for gr in gold.rows:
        buckets[eq._row_key(tuple(gr[i] for i in g_other))].append(("g", gr[gi]))
    for pr in pred.rows:
        buckets[eq._row_key(tuple(pr[j] for j in p_other))].append(("p", pr[pi]))
    mapping: dict[Any, Any] = {}
    for key, items in buckets.items():
        gvals = sorted(str(v) for tag, v in items if tag == "g")
        pvals = sorted(str(v) for tag, v in items if tag == "p")
        if len(gvals) != len(pvals):
            return False, {"reason": f"对齐失败：{key} 两侧行数 {len(gvals)}/{len(pvals)}"}
        for gv, pv in zip(gvals, pvals):
            if gv in mapping and mapping[gv] != pv:
                return False, {"reason": f"同一 id 映射到多个 name：{gv}"}
            mapping[gv] = pv
    if len(set(mapping.values())) != len(mapping):
        return False, {"reason": "非单射（多个 id 映射到同一 name）"}
    return True, {"n_mapped": len(mapping),
                  "sample": dict(list(mapping.items())[:3])}


# ============================================================================
# main
# ============================================================================

def main() -> None:
    index = _pred_index()
    loaded = load_bundle(BUNDLE)
    tsf = {a.physical_asset: "tenant_id"
           for a in loaded.bundle.assets
           if a.tenant_scoped and a.logical_name in loaded.active_assets}

    def sandbox(sql: str, params: dict | None = None, tenant: str | None = None) -> dict:
        return runner.run_in_sandbox(sql, params or {}, tenant=tenant, views=True,
                                     db_path=SANDBOX, tenant_scoped_physicals=tsf)

    gap = build_gap(index, sandbox)
    _dump(OUT_GAP, gap)
    print("W72-1:", json.dumps(gap["headline"], ensure_ascii=False)[:1200])

    g7 = build_g7(sandbox)
    _dump(OUT_G7, g7)
    print("W72-2:", json.dumps(g7["calibration"], ensure_ascii=False)[:600])

    leak = build_leak(index, sandbox)
    _dump(OUT_LEAK, leak)
    print("W72-3:", json.dumps([{k: c[k] for k in
                                 ("case_id", "value_with_leak", "value_without_leak", "authority_value")}
                                for c in leak["cases"]], ensure_ascii=False))

    pair = build_pairing(sandbox, index)
    _dump(OUT_PAIR, pair)
    print("W72-4:", json.dumps(pair["headline"], ensure_ascii=False))


def _dump(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
