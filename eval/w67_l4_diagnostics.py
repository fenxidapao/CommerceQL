"""W67 诊断：L4 触达面（W67-1）+ L4 成本现状账（W67-2）。零出站、纯只读分析。

派单依据：TASK_BOARD §88.5（QA → W8，2026-10-22 22:20）。

## W67-1 歧义面诊断 —— 回答"哪些题真正落到 L4 判定"

数据源 = `eval/results_r66_tau_raw_replay.json`（166 条，r63 匣带 `w8_r63_full166.jsonl`
的干净重放产物，零出站）。本脚本**不再跑图**，只对该产物做逐条归因：

- 层归因：`binding_status` → 判定层。`resolved_default` 恒为 L3（four_layer.decide 的
  唯一输出态）；`resolved_unique` 才可能出自 L1/L2/L4；`ambiguous` 只能出自 L4 或前置。
- Δ = top1 − top2（tau_raw.scores 降序前二之差；**含并列**，Δ=0 即最高分并列）。
- 判定概念反查：L3 披露文案（`degradations[].detail.binding_disclosure`）与语义包的
  `metrics[].default_binding.reason` / `field_bindings[].default_reason` 逐字匹配。
- 反事实：对 119 条已打分记录，用 **`classify_gap`（判定层的唯一区间判据实现）** 模拟
  "该概念若无 L3 声明会落到哪个态"。τ/ε 取 `core/config.py` 默认（.env 无 BINDING_TAU
  覆盖，2026-10-23 核对）＝ 0.20 / 0.05。

🔴 反事实的**三条局限**（引用结论时必须连带引用，缺一即误读）：
  ① 它是**绑定层单层模拟**，不是端到端回放 —— 撤掉 canonical_asset 会改 planner prompt
    （`payloads.py:449` 渲染 `概念 → canonical_asset` 行）⇒ 请求哈希变 ⇒ 匣带全 miss
    ⇒ **零出站下不可能做真正的全链回放**。
  ② 它假设上游（intent/link/plan）不变 —— 实际上语义包改动可能改变计划与候选。
  ③ 撤声明在 schema 上不可单做：`ambiguous ⇔ 无 canonical_asset` 是双向校验器断言
    （`semantics/models.py:272`），真做必须连 `ambiguous: true` + `candidates` 一起改。

## W67-2 成本账 —— L4 被调用几次、花多少、是否改变过判定

数据源 = 匣带本体（每行一条真实 API 调用的请求+响应+usage）。L4 调用识别判据 =
system prompt 含「字段绑定 L4 打分器」（`app/binding/l4.py` 的固定文案，无歧义）。

- 运行时调用次数 vs 唯一请求数：匣带 `save()` 按 key 覆盖去重（`eval/cassette.py`），
  r63 实跑 119 次调用中有 5 对同哈希请求只留 1 行 ⇒ 匣带 114 行。
- 计价：`app/llm/budget.compute_cost`（缓存命中/未命中分开计价，与结算同源）。
  两档都算；时段归属用数值对账反推（r63 实跑 15:19 北京时间＝高峰窗；r66 重放
  21:30＝非高峰），不猜。
- 判定贡献：来自 W67-1 的层归因（L4 判定条数），本脚本只汇总。

产出：
  eval/results_r67_l4_reach.json
  eval/results_r67_l4_cost.json
"""

from __future__ import annotations

import ast
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import BUNDLE_PATH, bootstrap, build_stamp  # noqa: E402

bootstrap()

#: 进程启动即取构建身份（T-11②）：同进程内先写的产物会把已跟踪文件弄脏，
#: 逐函数调 build_stamp() 会让后写产物自报 dirty=True 假阳（W68 实测）。先取后写。
STAMP = build_stamp()

import yaml  # noqa: E402
from app.binding.four_layer import GapBand, TauConfig, classify_gap  # noqa: E402
from app.llm.budget import TokenUsage, Tier, compute_cost  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_REPLAY = os.path.join(HERE, "results_r66_tau_raw_replay.json")
CASSETTE = os.path.join(HERE, "cassettes", "w8_r63_full166.jsonl")
SRC_R63 = os.path.join(HERE, "results_r63_full166.json")
OUT_REACH = os.path.join(HERE, "results_r67_l4_reach.json")
OUT_COST = os.path.join(HERE, "results_r67_l4_cost.json")
OUT_CUTOVER = os.path.join(HERE, "results_r67_degradations_cutover_inventory.json")

#: W66 起评测面**新增可见**的网关层降级 reason（QA §88.4① 点名；经精确化）。
#: ⚠️ `switched_to_weak_model` 是 **ActionTaken** 值不是 reason（core/enums.py:467），
#: QA 点句把它与 reason 并列是口径粗糙，本清单按枚举精确定性。
#: ⚠️ `llm_unavailable` 是**双路**值：节点路径（normalize.py:179 UnderstandUnavailable）
#: 一直可见；网关路径（模板兜底等）W66 起才可见。故"网关层新增"仅 `llm_concurrency_exceeded`
#: 一个 reason 值 + 网关路径的 `llm_unavailable` 事件。
GATEWAY_NEW_REASONS = frozenset({"llm_concurrency_exceeded"})

#: τ/ε 现值：`backend/app/core/config.py:136-137` 默认；`.env` 无 BINDING_TAU* 覆盖
#: （2026-10-23 逐行核对）。未校准（CALIBRATED_AT 空）⇒ G-2/G-5 仍 UNVERIFIED，
#: 本诊断**不是**校准，只是把"Δ 落在现行判据的哪个区间"算出来。
TAU = TauConfig(value=0.20, epsilon=0.05)

#: L4 打分器 system prompt 的指纹（`app/binding/l4.py` 固定文案）。
L4_FINGERPRINT = "字段绑定 L4 打分器"

PROVENANCE = "w67 diagnostics: L4 reach + L4 cost, zero egress (read-only over r66 replay + r63 cassette)"


# ============================================================================
# 公共装载
# ============================================================================

def load_reason_map() -> dict[str, dict[str, str]]:
    """披露文案 → 概念（metrics[].default_binding.reason 与 field_bindings[].default_reason）。

    L3 披露 = `resolution.default_reason`（four_layer._try_level3 原样透传），
    而 resolution 的 reason 来源就是这两处（filters.py 步③/§L3）。逐字匹配，
    匹配不上如实写 None，**不许猜**。
    """
    with open(BUNDLE_PATH, encoding="utf-8") as fh:
        bundle = yaml.safe_load(fh)
    mapping: dict[str, dict[str, str]] = {}
    for m in bundle.get("metrics") or []:
        db = m.get("default_binding") or {}
        reason = str(db.get("reason") or "").strip()
        if reason:
            mapping[reason] = {"kind": "metric", "concept": str(m.get("name")), "display": str(m.get("display_name") or "")}
    for fb in bundle.get("field_bindings") or []:
        reason = str(fb.get("default_reason") or "").strip()
        if reason:
            mapping[reason] = {"kind": "field_binding", "concept": str(fb.get("concept")), "display": ""}
    return mapping


def disclosure_of(record: dict[str, Any]) -> str | None:
    """从 degradations 里取绑定披露文案（present_failed 时由 present 节点带入）。"""
    for dg in record.get("degradations") or []:
        detail = dg.get("detail") or {}
        txt = detail.get("binding_disclosure")
        if txt:
            return str(txt)
    return None


def delta_of(tau_raw: dict[str, Any]) -> float | None:
    """Δ = top1 − top2（含并列；样本数 <2 → None）。"""
    scores = sorted((float(s) for s in (tau_raw.get("scores") or [])), reverse=True)
    if len(scores) < 2:
        return None
    return round(scores[0] - scores[1], 6)


_TENANT_PREFIX = re.compile(r"^T_[A-Z]\s*")


def _parse_l4_request(req: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """L4 请求 user 消息 → (归一化问句, 候选元组)。解析失败抛 ValueError（宁可炸不许错配）。"""
    user = req["messages"][-1]["content"]
    m_q = re.search(r"\[归一化后的问题\]\s*\n(.+?)\n\s*\n\[", user, re.S)
    m_c = re.findall(r"^\s*\d+\.\s+(\S+)\s*$", user, re.M)
    if not m_q or not m_c:
        raise ValueError("L4 请求解析失败：问句或候选段缺失")
    return m_q.group(1).strip(), tuple(m_c)


def _normalized_question_of(record: dict[str, Any]) -> str:
    """记录侧的问句：剥租户前缀再剥句首「的」（实测归一化把 'T_A 的X' 归一成 'X'）。

    ⚠️ 这是**匹配近似**，不是复刻归一化组件：残余未匹配的记录会如实列在
    `unmatched_case_ids`，不许为凑数放宽到模糊匹配。
    """
    q = _TENANT_PREFIX.sub("", str(record.get("question") or "")).strip()
    return re.sub(r"^的\s*", "", q).strip()


# ============================================================================
# W67-1 —— reach
# ============================================================================

#: binding_status → 判定层。`None` 表示没到 bind 判定（intent 澄清 / plan 拒答 / 错误）。
#: `resolved_unique` 可能出自 L1/L2/L4 三层，本数据集未出现，出现时必须标 multi。
STATE_TO_LAYER: dict[str | None, str] = {
    "resolved_default": "L3",
    "resolved_unique": "L1|L2|L4(不可区分,本数据集未出现)",
    "ambiguous": "L4(或前置 fail-safe)",
    "unresolved": "前置(概念未解析/候选全灭)",
    None: "未到绑定判定",
}


def run_reach(records: list[dict[str, Any]], reason_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    layer_counter: Counter[str] = Counter()
    concept_counter: Counter[str] = Counter()
    deltas: list[float] = []
    city_cases: list[dict[str, Any]] = []
    unexplained_disclosure: list[str] = []

    for r in records:
        tau_raw = r.get("tau_raw") or {}
        status = r.get("binding_status")
        layer = STATE_TO_LAYER.get(status, f"未知态:{status}")
        layer_counter[layer] += 1
        disc = disclosure_of(r) if status == "resolved_default" else None
        concept: dict[str, str] | None = None
        if disc is not None:
            concept = reason_map.get(disc.strip())
            if concept is None:
                unexplained_disclosure.append(f"{r['case_id']}:{disc[:40]}")
            else:
                concept_counter[f"{concept['kind']}:{concept['concept']}"] += 1
        delta = delta_of(tau_raw) if tau_raw.get("ok") else None
        if delta is not None:
            deltas.append(delta)
        entry: dict[str, Any] = {
            "case_id": r["case_id"],
            "question": r.get("question"),
            "expected_behavior": r.get("expected_behavior"),
            "terminal_event": r.get("terminal_event"),
            "nodes_reached_bind": "bind" in (r.get("nodes") or []),
            "binding_status": status,
            "decided_at_layer": layer,
            "reached_l4_decision": layer.startswith("L4") or status == "resolved_unique",
            "l4_scores_present": bool(tau_raw.get("ok")),
            "l4_not_reached_reason": tau_raw.get("reason") if not tau_raw.get("ok") else None,
            "n_l4_candidates": len(tau_raw.get("candidate_ids") or []),
            "delta": delta,
            "judged_concept": concept,
            "disclosure_text": disc,
        }
        if "城市" in str(r.get("question") or "") or str(r["case_id"]).startswith("C-CITY"):
            city_cases.append(entry)
        per_case.append(entry)

    # —— 反事实：119 条已打分记录，若无 L3 声明会判成什么（classify_gap 现行判据）——
    counterfactual_states: Counter[str] = Counter()
    for r in records:
        tau_raw = r.get("tau_raw") or {}
        if not tau_raw.get("ok"):
            continue
        d = delta_of(tau_raw)
        if d is None:
            continue
        verdict = classify_gap(d, TAU)
        counterfactual_states[str(verdict.state)] += 1

    # —— τ 扫描（信息性；ε 取现行 0.05，另给 ε=0 变体对账 QA §88.5-四 的表）——
    def sweep(epsilon: float) -> list[dict[str, Any]]:
        rows = []
        n_expected_clarify = sum(
            1 for r in records if r.get("expected_behavior") == "clarify"
        )
        for tau_v in (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
            cfg = TauConfig(value=tau_v, epsilon=epsilon)
            amb = sum(
                1
                for r in records
                if (r.get("tau_raw") or {}).get("ok")
                and (d := delta_of(r["tau_raw"])) is not None
                and str(classify_gap(d, cfg).state) == "ambiguous"
            )
            rows.append({
                "tau": tau_v,
                "epsilon": epsilon,
                "l4_ambiguous": amb,
                "l4_resolved_unique": sum(
                    1
                    for r in records
                    if (r.get("tau_raw") or {}).get("ok")
                    and (d := delta_of(r["tau_raw"])) is not None
                    and str(classify_gap(d, cfg).state) == "resolved_unique"
                ),
                "would_be_clarify_total": amb + n_expected_clarify,
                "clarify_rate_vs_166": round((amb + n_expected_clarify) / 166, 4),
            })
        return rows

    delta_zero = sum(1 for d in deltas if d == 0.0)
    deltas_sorted = sorted(deltas)
    summary = {
        "n_records": len(records),
        "layer_decided_counter": dict(layer_counter),
        "n_reached_l4_decision_true": sum(1 for e in per_case if e["reached_l4_decision"]),
        "n_l3_decided": layer_counter.get("L3", 0),
        "n_bind_reached": sum(1 for e in per_case if e["nodes_reached_bind"]),
        "n_l4_scored": sum(1 for e in per_case if e["l4_scores_present"]),
        "delta_stats": {
            "n": len(deltas),
            "n_delta_zero": delta_zero,
            "min": deltas_sorted[0] if deltas else None,
            "p25": deltas_sorted[len(deltas_sorted) // 4] if deltas else None,
            "median": deltas_sorted[len(deltas_sorted) // 2] if deltas else None,
            "p75": deltas_sorted[(3 * len(deltas_sorted)) // 4] if deltas else None,
            "max": deltas_sorted[-1] if deltas else None,
        },
        "counterfactual_states_tau020_eps005": dict(counterfactual_states),
        "judged_concept_counter": dict(concept_counter),
        "n_disclosure_unexplained": len(unexplained_disclosure),
    }
    return {
        "provenance": PROVENANCE,
        "task": "W67-1 歧义面诊断：找出真正落到 L4 判定的题并读出 Δ 分布",
        **STAMP,
        "config": {
            "source_file": "eval/results_r66_tau_raw_replay.json",
            "source_cassette": "eval/cassettes/w8_r63_full166.jsonl",
            "tau": TAU.value,
            "epsilon": TAU.epsilon,
            "tau_source": "backend/app/core/config.py 默认值（.env 无 BINDING_TAU* 覆盖，未校准）",
            "zero_egress": True,
        },
        "headline": {
            "l4_decision_count": summary["n_reached_l4_decision_true"],
            "verdict": (
                "冻结集 166 条中，真正落到 L4 判定的题 = 0 条。119 条 binding 全部在 L3"
                "（resolved_default）终止；16 条 expected_clarify 全部在 intent 阶段澄清"
                "（nodes 止于 clarify_out，从未进入 bind）；其余在 plan 拒答或错误终态。"
                "「城市」类歧义题（ambiguous:true，L3 必不命中）也不例外——它们在 intent"
                " 就被澄清或在 plan 被拒，从未走到 bind。"
            ),
            "root_cause": (
                "结构性根因（代码依据）：bind 节点只对 plan.metrics[0].name 一个概念做绑定"
                "（backend/app/graph/nodes/bind.py _concept_of），「城市」这类出现在维度/分组位"
                "的概念从不进入绑定判定；当问题本身问的就是歧义概念时（C-CITY-01/04），intent"
                " 节点先行澄清。⇒ L4 打分被无条件调用（119 次），但分数从未进入任何判定。"
            ),
        },
        "summary": summary,
        "city_ambiguity_cases": city_cases,
        "tau_sweep_eps005": sweep(0.05),
        "tau_sweep_eps0_for_qa_reconciliation": sweep(0.0),
        "counterfactual_limitations": [
            "①绑定层单层模拟，非端到端回放：撤 canonical_asset 会改 planner prompt"
            "（payloads.py 渲染『概念 → canonical_asset』行）⇒ 请求哈希变 ⇒ 匣带全 miss"
            " ⇒ 零出站下无法做真全链回放。",
            "②假设上游（intent/link/plan）与候选集不变 —— 实际语义包改动可能改变计划。",
            "③schema 上不能只撤 canonical_asset：ambiguous ⇔ 无 canonical_asset 为双向校验"
            "（semantics/models.py），真做须连带 ambiguous:true + candidates。",
            "④判定概念反查依赖披露文案逐字匹配（116/119 有文案；3 条无 present_failed 降级"
            "则无文案，judged_concept=null，不影响层归因——层归因只依赖 binding_status）。",
        ],
        "records": per_case,
    }


# ============================================================================
# W67-2 —— cost
# ============================================================================

def _usage_of(resp: dict[str, Any]) -> tuple[int, int, int]:
    u = resp.get("usage") or {}
    return (
        int(u.get("prompt_tokens") or 0),
        int(u.get("prompt_cache_hit_tokens") or 0),
        int(u.get("completion_tokens") or 0),
    )


def _cost_cny(prompt: int, cache_hit: int, completion: int, tier: Tier) -> float:
    usage = TokenUsage(input=prompt, output=completion, cache_hit=cache_hit)
    return float(compute_cost("deepseek-flash", usage, tier))


def run_cost(records: list[dict[str, Any]]) -> dict[str, Any]:
    l4_entries: list[dict[str, Any]] = []
    all_entries: list[dict[str, Any]] = []
    with open(CASSETTE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            req = ast.literal_eval(rec["request"]) if isinstance(rec["request"], str) else rec["request"]
            resp = ast.literal_eval(rec["response"]) if isinstance(rec["response"], str) else rec["response"]
            entry = {
                "key": rec["key"],
                "is_l4": L4_FINGERPRINT in req["messages"][0]["content"],
                "usage": _usage_of(resp),
            }
            if entry["is_l4"]:
                entry["req_key"] = _parse_l4_request(req)
            all_entries.append(entry)
            if entry["is_l4"]:
                l4_entries.append(entry)

    n_l4_lines = len(l4_entries)
    l4_tokens = {
        "prompt": sum(e["usage"][0] for e in l4_entries),
        "cache_hit": sum(e["usage"][1] for e in l4_entries),
        "completion": sum(e["usage"][2] for e in l4_entries),
    }
    l4_tokens["prompt_miss"] = l4_tokens["prompt"] - l4_tokens["cache_hit"]

    cost_by_tier = {}
    for tier in (Tier.OFF_PEAK, Tier.PEAK):
        l4_cost = sum(_cost_cny(*e["usage"], tier=tier) for e in l4_entries)
        total_cost = sum(_cost_cny(*e["usage"], tier=tier) for e in all_entries)
        cost_by_tier[tier.value] = {
            "l4_cost_cny": round(l4_cost, 6),
            "total_cost_cny": round(total_cost, 6),
            "l4_share": round(l4_cost / total_cost, 4) if total_cost else None,
        }

    # —— 时段对账：算出的总额 vs 产物自报总额 ⇒ 反推各自跑批所处时段，不猜 ——
    r63 = json.load(open(SRC_R63, encoding="utf-8"))
    r63_reported = float((r63.get("summary") or {}).get("cost_cny_total") or 0)
    r66_reported = float(
        sum(float(r.get("cost_cny") or 0) for r in records)
    )
    tier_inference = {
        "r63_live_reported_total_cny": r63_reported,
        "r63_live_nearest_tier": _nearest(cost_by_tier, r63_reported),
        "r63_live_started_at_utc": r63.get("generated_at"),
        "r66_replay_reported_total_cny": round(r66_reported, 6),
        "r66_replay_nearest_tier": _nearest(cost_by_tier, r66_reported),
        "r66_replay_generated_at": json.load(open(SRC_REPLAY, encoding="utf-8")).get("generated_at"),
        "note": "r63 实跑 2026-10-22T07:19Z = 北京时间 15:19（周四，14:00-18:00 高峰窗）；"
                "r66 重放 13:30Z = 21:30（非高峰）。与数值对账互证。",
    }

    # —— record ↔ L4 调用匹配：以归一化问句为主键，候选集做包含关系校验 ——
    # ⚠️ 不能拿候选元组当主键：这批的 L4 请求候选几乎恒同（同 31 列，来自 link 的字段级候选）；
    # 也不能拿 tau_raw.candidate_ids 精确比：它只含**打出了分**的候选（31 请求 → 30 打分，
    # 上游少打/截断时更少），是请求集合的子集而非全集。
    l4_by_question: dict[str, tuple[str, ...]] = {}
    l4_by_question_nospace: dict[str, tuple[str, ...]] = {}
    for e in l4_entries:
        q, cands = e["req_key"]
        if q in l4_by_question and l4_by_question[q] != cands:
            raise ValueError(f"L4 请求主键冲突：同问句不同候选集（{q[:40]}…）——匹配判据需重审")
        l4_by_question[q] = cands
        l4_by_question_nospace.setdefault("".join(q.split()), cands)

    matched: dict[str, list[str]] = defaultdict(list)
    unmatched: list[str] = []
    matched_via_nospace: list[str] = []
    subset_violations: list[dict[str, Any]] = []
    for r in records:
        tau_raw = r.get("tau_raw") or {}
        if not tau_raw.get("ok"):
            continue
        q = _normalized_question_of(r)
        scored = {str(c) for c in tau_raw["candidate_ids"]}
        req_cands = l4_by_question.get(q) or l4_by_question_nospace.get("".join(q.split()))
        if req_cands is None:
            unmatched.append(r["case_id"])
            continue
        if q not in l4_by_question:
            matched_via_nospace.append(r["case_id"])
        if not scored <= set(req_cands):
            subset_violations.append({"case_id": r["case_id"], "question": q})
        matched[q].append(r["case_id"])

    n_runtime_calls = sum(len(v) for v in matched.values()) + len(unmatched)
    n_unique_requests = len(matched)

    per_case = sorted(
        (
            {
                "case_id": r["case_id"],
                "l4_runtime_call": bool((r.get("tau_raw") or {}).get("ok")),
                "request_matched": (
                    bool((r.get("tau_raw") or {}).get("ok"))
                    and (
                        _normalized_question_of(r) in l4_by_question
                        or "".join(_normalized_question_of(r).split()) in l4_by_question_nospace
                    )
                ),
                "n_candidates": len((r.get("tau_raw") or {}).get("candidate_ids") or []),
                "changed_decision": False,
            }
            for r in records
        ),
        key=lambda e: e["case_id"],
    )

    shared = [
        {"normalized_question": q, "case_ids": cases, "n": len(cases)}
        for q, cases in sorted(matched.items())
        if len(cases) > 1
    ]
    return {
        "provenance": PROVENANCE,
        "task": "W67-2 L4 触发条件与成本现状账（只出材料，不改行为；挂 U-117 / §88.4②）",
        **STAMP,
        "config": {
            "source_cassette": "eval/cassettes/w8_r63_full166.jsonl",
            "l4_call_fingerprint": L4_FINGERPRINT,
            "pricing_source": "backend/app/llm/budget.py PRICES + compute_cost（与结算同源，缓存分档）",
            "model": "deepseek-flash",
            "zero_egress": True,
        },
        "headline": {
            "l4_runtime_calls": n_runtime_calls,
            "l4_unique_requests": n_unique_requests,
            "l4_cassette_lines": n_l4_lines,
            "n_records_unmatched": len(unmatched),
            "n_matched_via_nospace": len(matched_via_nospace),
            "unmatched_case_ids": unmatched,
            "unmatched_note": (
                "残余未匹配 = 归一化组件做了**同义词/词序级改写**（如『销售额』→『GMV』、"
                "『总访客数』→『总访客数（UV）』、『在架商品有多少个』→『在架商品数是多少』），"
                "无法用无语义假设的规则安全复原；匹配判据只用了『剥租户前缀 + 剥句首「的」"
                "+ 去空白』三级，全部无语义假设。"
            ),
            "dedup_note": (
                f"r63 实跑发起 {n_runtime_calls} 次 L4 调用（每条走到 bind 且有字段级候选的记录恰 1 次）；"
                f"匣带 save() 按 key 覆盖去重后留 {n_l4_lines} 行（= 唯一请求哈希数）。"
                f"本表 l4_unique_requests={n_unique_requests} 是**按问句匹配到的唯一请求数**"
                f"（{n_l4_lines} 行匣带中有 {len(unmatched)} 行对应的记录因归一化改写未被匹配，"
                "见 unmatched_note）；两者口径不同，勿混用。"
            ),
            "subset_violations": subset_violations,
            "l4_tokens": l4_tokens,
            "l4_decision_contribution": {
                "n_records_decided_at_l4": 0,
                "verdict": (
                    "L4 打分在这批上一次也没有改变过任何判定：119 条 binding 全部由 L3 终止"
                    "（W67-1 层归因），L4 分数算完即弃。U-117 原提案（改触发条件）的成本依据成立。"
                ),
            },
            "u117_reference": "TASK_BOARD §88.4②：114 次/¥1.27/58% 为 QA 估算口径"
                              "（prompt 全按未命中计）；本表按 compute_cost 缓存分档计价，两档都列。",
        },
        "cost_by_tier": cost_by_tier,
        "tier_inference": tier_inference,
        "shared_request_groups": shared,
        "per_case": per_case,
    }


def _nearest(cost_by_tier: dict[str, dict[str, Any]], reported: float) -> str:
    off = abs(cost_by_tier["off_peak"]["total_cost_cny"] - reported)
    peak = abs(cost_by_tier["peak"]["total_cost_cny"] - reported)
    return "off_peak" if off <= peak else "peak"


# ============================================================================
# W67-3 —— degradation sink 口径变更影响清单（只读盘点，不改任何既有产物）
# ============================================================================

def _skipped_class(name: str, _data: Any) -> str:
    """无 records[] 产物的逐类归档（W68-4：不再静默跳过，逐类说明）。"""
    n = name.lower()
    if "gate_recompute" in n:
        return "gate_recompute_门禁重算聚合"
    if "matrix" in n:
        return "matrix_判定矩阵对比"
    if "stab_" in n:
        return "stability_单题稳定性探针"
    if "tau" in n:
        return "tau_采样审计与摘要"
    if "secret" in n:
        return "secret_scan_秘密扫描证据"
    if any(k in n for k in ("probe", "diagnosis", "401", "timeout", "availability", "dense")):
        return "probe_探针与诊断一次性产物"
    if "materialize" in n:
        return "materialize_物化核对"
    if "equiv" in n:
        return "equiv_等价性审计"
    if "error" in n:
        return "error_错误率与形态盘点"
    if "refusal" in n:
        return "over_refusal_过拒盘点"
    return "aggregate_其它聚合摘要（无逐条记录）"


def run_cutover_inventory() -> dict[str, Any]:
    files = sorted(glob.glob(os.path.join(HERE, "results_*.json")))
    inventory = []
    skipped: list[dict[str, Any]] = []
    for path in files:
        name = os.path.basename(path)
        try:
            data = json.load(open(path, encoding="utf-8-sig"))
        except Exception as exc:
            skipped.append(
                {"file": f"eval/{name}", "skip_class": "parse_error",
                 "detail": type(exc).__name__}
            )
            continue
        recs = data.get("records") or []
        if not isinstance(recs, list) or not recs:
            #: W68-4 订正（QA 派单 §4）：此前在这里静默 continue，把"无 records[] 的
            #: 聚合形态产物"漏在 n_files_scanned 之外（152 实为有 records 的子集）。
            #: 现在纳入 skipped 正表并逐类计数。
            skipped.append({
                "file": f"eval/{name}",
                "skip_class": _skipped_class(name, data),
                "top_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            })
            continue
        reasons: Counter[str] = Counter()
        for r in recs:
            for dg in r.get("degradations") or []:
                if isinstance(dg, dict):
                    reasons[str(dg.get("reason"))] += 1
        inventory.append({
            "file": f"eval/{name}",
            "n_records": len(recs),
            "n_records_with_degradations": sum(
                1 for r in recs if r.get("degradations")
            ),
            "reasons_observed": dict(reasons),
            "has_gateway_new_reason": bool(GATEWAY_NEW_REASONS & set(reasons)),
        })
    n_with = sum(1 for e in inventory if e.get("has_gateway_new_reason"))
    by_class: Counter[str] = Counter(e["skip_class"] for e in skipped)
    return {
        "provenance": PROVENANCE,
        "task": "W67-3 评测面 degradations 口径变更影响清单（W66 起 _EvalDegradationSink 才把网关层降级接进 GraphState）"
                "；W68-4 订正：n_files_scanned 实为『有非空 records 的文件数』，改名 n_files_with_records"
                "并补全量计数与跳过类说明",
        **STAMP,
        "rule": {
            "pre_w66": "评测面 records[].degradations 只含**节点层**降级"
                       "（normalize/link/plan/present/embed 等经 RunContext 上报的）。",
            "post_w66": "自 W66（_EvalDegradationSink，见 eval/harness.py）起，网关层降级"
                        "（llm_concurrency_exceeded 等，原只进日志）也进 records[].degradations。",
            "precision_notes": [
                "switched_to_weak_model 是 ActionTaken 不是 reason（core/enums.py DegradedReason 8 值里没有它）。",
                "llm_unavailable 是双路值：节点路径（normalize UnderstandUnavailable）一直可见，"
                "故旧产物含 llm_unavailable 不构成反例；网关路径的同类事件 W66 起才可见。",
                "因此『W66 前缺网关层』的可检验特征 = 产物中 llm_concurrency_exceeded 恒不出现"
                "（本清单实测：有 records 的产物中 0 个含它，唯一例外是 W66 自己的饱和产物，见下）。",
                "W68-4 口径订正：eval/results_*.json 全量 n_files_total 个；只有 n_files_with_records 个"
                "带非空 records[]（可逐条查 degradations）；另有 n_files_skipped 个为聚合形态"
                "（无 records[]），不构成反例但也未纳入正表——跳过清单与逐类计数见 skipped_categories / skipped_files。",
            ],
        },
        "n_files_total": len(files),
        "n_files_with_records": len(inventory),
        "n_files_skipped": len(skipped),
        "n_files_with_gateway_new_reason": n_with,
        "skipped_categories": dict(by_class),
        "skipped_files": skipped,
        "expected_post_w66_holders": [
            "eval/results_r66_saturation_graph.json（W66 D5-1 饱和串跑，llm_concurrency_exceeded 图级证据）",
        ],
        "inventory": inventory,
    }


def main() -> None:
    records = json.load(open(SRC_REPLAY, encoding="utf-8"))["records"]
    reason_map = load_reason_map()

    reach = run_reach(records, reason_map)
    with open(OUT_REACH, "w", encoding="utf-8") as fh:
        json.dump(reach, fh, ensure_ascii=False, indent=2)

    cost = run_cost(records)
    with open(OUT_COST, "w", encoding="utf-8") as fh:
        json.dump(cost, fh, ensure_ascii=False, indent=2)

    cutover = run_cutover_inventory()
    with open(OUT_CUTOVER, "w", encoding="utf-8") as fh:
        json.dump(cutover, fh, ensure_ascii=False, indent=2)

    print("== W67-1 reach ==")
    print(json.dumps(reach["headline"], ensure_ascii=False, indent=2))
    print(json.dumps(reach["summary"], ensure_ascii=False, indent=2))
    print("== W67-2 cost ==")
    print(json.dumps(cost["headline"], ensure_ascii=False, indent=2))
    print(json.dumps(cost["cost_by_tier"], ensure_ascii=False, indent=2))
    print(json.dumps(cost["tier_inference"], ensure_ascii=False, indent=2))
    print("== W67-3 cutover inventory ==")
    print("n_files total/with_records/skipped:",
          cutover["n_files_total"], cutover["n_files_with_records"], cutover["n_files_skipped"],
          "with_gateway_new_reason:", cutover["n_files_with_gateway_new_reason"])


if __name__ == "__main__":
    main()
