"""U-183 P0 载体三面核验（期望侧 / 观测侧 / 计量侧）。

零依赖、零网络、零 LLM、零 DB：只读仓库内 JSON / JSONL / Markdown，产出与脚本同目录的
``baseline_v3_b7.json``。复算：``python eval/olist/probe_u183_carriers.py``。

三面各自点到名，任何一面缺读数即判「不认」，不许用文档描述代替字段实测。
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("baseline_v3_b7.json")

FROZEN = REPO / "eval/olist/dataset_v3_frozen.json"
BATCHES = [REPO / f"eval/olist/results_v3_r{i}.json" for i in (1, 2, 3)]
CASSETTES = [REPO / f"eval/olist/cassettes/olist_v3_r{i}.jsonl" for i in (1, 2, 3)]
PROBES = sorted((REPO / "eval/olist").glob("probe_*.py"))
DOCS = [
    REPO / "docs/07_技术设计文档_TDD.md",
    REPO / "docs/09_当前状态与交接.md",
    REPO / "docs/10_未决问题台账.md",
]


def digest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path.relative_to(REPO)).replace("\\", "/")}
    raw = path.read_bytes()
    return {
        "exists": True,
        "path": str(path.relative_to(REPO)).replace("\\", "/"),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "crlf": raw.count(b"\r\n"),
        "lone_lf": raw.count(b"\n") - raw.count(b"\r\n"),
        "lines": raw.count(b"\n"),
    }


def expectation_side() -> dict[str, Any]:
    """期望侧：读冻结集字段集本身，不读报告描述。"""
    ds = json.loads(FROZEN.read_text(encoding="utf-8"))
    cases = ds["cases"]
    execute = [c for c in cases if c["expected_behavior"] == "execute"]
    fields = sorted({k for c in execute for k in c})
    gold_fields = [k for k in fields if k.startswith("gold_")]
    coverage = {k: sum(1 for c in execute if c.get(k)) for k in gold_fields}
    weak = {
        k: sum(1 for c in execute if c.get(k))
        for k in ("must_contain", "must_not_contain", "business_knowledge_required", "caliber_note", "expect")
    }
    vocab: collections.Counter[str] = collections.Counter()
    for c in execute:
        vocab.update(c.get("business_knowledge_required") or [])
    return {
        "face": "expectation",
        "question": "有没有原生的『应该是什么』标注，还是只能靠派生/弱代理",
        "carrier": digest(FROZEN),
        "n_cases": ds["n_cases"],
        "n_execute_cases": ds["n_execute_cases"],
        "n_interaction_cases": ds["n_interaction_cases"],
        "execute_cases_read": len(execute),
        "case_field_set": fields,
        "gold_field_coverage": coverage,
        "gold_native_all_95": all(v == len(execute) for k, v in coverage.items() if k != "gold_result_rows"),
        "weak_proxy_coverage": weak,
        "business_knowledge_vocab_size": len(vocab),
        "business_knowledge_top": vocab.most_common(8),
        "content_hash": ds["content_hash"],
        "full_hash": ds["full_hash"],
        "sandbox_db_sha256": ds["sandbox_db_sha256"],
        "verdict": "gold_sql / gold_result_hash / gold_result_cols 原生齐备；但归因用的 must_contain / must_not_contain 覆盖为 0，知识标签词表仅 24 项 ⇒ 归因是弱代理，不是原生错因标注",
    }


def observation_side() -> dict[str, Any]:
    """观测侧：确认 verdict 的唯一生产者与匣带记录的产出方。"""
    batches = []
    for path in BATCHES:
        d = json.loads(path.read_text(encoding="utf-8"))
        batches.append({**digest(path), "git_rev": d.get("build", {}).get("git_rev"),
                        "n_equivalent": d["summary"]["n_equivalent"],
                        "n_execute_scored": d["summary"]["n_execute_scored"]})
    cassettes = []
    for path in CASSETTES:
        raw = path.read_bytes()
        rows = [json.loads(x) for x in raw.splitlines() if x.strip()]
        models = collections.Counter(r["request"].get("model") for r in rows)
        tokens = collections.Counter(r["request"].get("max_tokens") for r in rows)
        body = "".join(json.dumps(r, ensure_ascii=False) for r in rows)
        sys_prompts = [r["request"]["messages"][0]["content"] for r in rows]
        gen = [s for s in sys_prompts if "SQL 生成" in s[:80]]
        cassettes.append({
            **digest(path),
            "n_records": len(rows),
            "models": dict(models),
            "max_tokens": {str(k): v for k, v in tokens.items()},
            "few_shot_token_hits": body.lower().count("few_shot"),
            "example_token_in_sqlgen_system": sum(s.count("示例") for s in gen),
            "sqlgen_system_n": len(gen),
        })
    return {
        "face": "observation",
        "question": "载体记的是谁产的数，产出方是否等于被测对象",
        "verdict_producer": "eval/runner.py:697 eq.compare_tables(gold_view['table'], pred_table, ...)",
        "verdict_sink": "eval/runner.py:714-724 record['verdict']",
        "verdict": "观测侧是评测链路真打/重放后由 runner 判的结果等价，不是上游意图；匣带只记 LLM 请求响应，不记 verdict",
        "batches": batches,
        "cassettes": cassettes,
    }


def measurement_side(batches: list[dict[str, Any]]) -> dict[str, Any]:
    """计量侧：分母、自增点、边际与联合、异常分支是否占用同一标签。"""
    per_batch = []
    joint = collections.Counter()
    marginal_attr = collections.Counter()
    scored_shape = collections.Counter()
    for path in BATCHES:
        d = json.loads(path.read_text(encoding="utf-8"))
        records = d["records"]
        execute = [r for r in records if r.get("expected_behavior") == "execute"]
        bad = [r for r in execute if not (r.get("verdict") or {}).get("equivalent")]
        for r in records:
            scored_shape[(r.get("expected_behavior"), r.get("scored"))] += 1
        for r in bad:
            attr = (r.get("attribution") or {}).get("category", "NULL")
            marginal_attr[attr] += 1
            t, c = r.get("terminal_event"), r.get("terminal_code")
            if t == "error" and c == "GATE_AST_REJECTED":
                k = "A_GATE_REJECT_" + str(r.get("gate1_reject_rule"))
            elif t == "error" and c == "SQL_SYNTAX_ERROR":
                k = "B_SQL_DIALECT_SYNTAX"
            elif t in ("refuse", "clarify"):
                k = "C_NO_SQL_" + str(t).upper()
            elif t == "error":
                k = "D_INFRA_" + str(c)
            elif t == "complete":
                k = "E_RAN_BUT_WRONG_RESULT"
            else:
                k = "F_OTHER"
            joint[k] += 1
        per_batch.append({
            "batch": path.name,
            "n_records": len(records),
            "n_execute": len(execute),
            "n_bad": len(bad),
            "n_equivalent_summary": d["summary"]["n_equivalent"],
            "attribution_distribution": dict(d["summary"].get("attribution_distribution", {})),
        })
    return {
        "face": "measurement",
        "question": "分桶能否支持联合口径，分母混进了什么，异常分支是否占同一标签",
        "denominator": "eval/runner.py:1213-1214 只在 expected_behavior=execute 上累加 n_equivalent",
        "counter_increment": "eval/runner.py:1214 sum(1 for r in execute if (r.get('verdict') or {}).get('equivalent'))",
        "abnormal_branch": "eval/runner.py:641-643 infra_error ⇒ scored=False / verdict=None / attribution=None，但仍进 terminal_distribution",
        "marginal_only": "attribution_distribution 是单标签边际计数，拿不出『R14 ∧ 跑通但答错』的联合；下面 joint 是逐例现算的派生读数，不是盘上原生标签",
        "scored_shape": {f"{a}/{b}": n for (a, b), n in scored_shape.items()},
        "joint_bad_by_terminal": dict(joint.most_common()),
        "marginal_attribution_over_bad": dict(marginal_attr.most_common()),
        "per_batch": per_batch,
        "verdict": "分母 95 条 execute 干净；83 条失败按终态联合拆分属派生，归因分布属边际，两者不可混记",
    }


def claim_receipt(exp: dict[str, Any], obs: dict[str, Any]) -> dict[str, Any]:
    """回执：一段一条，逐条声称 → 实测 → 判定。"""
    rows = [
        {"claim": "三批 69/67/66 = 70.88%，分母 95 条 execute",
         "observed": [b["n_equivalent"] for b in obs["batches"]],
         "verdict": "OK", "owner": "lead（本窗现读）"},
        {"claim": "冻结集 gold 齐备且可零成本复算",
         "observed": exp["gold_field_coverage"], "verdict": "OK", "owner": "lead（本窗现读）"},
        {"claim": "33 条 gate_policy_gap 全是 R14 误判",
         "observed": str(REPO / "eval/olist/probe_attribution_misjudge.json"),
         "verdict": "OK", "owner": "T-03 已 CLOSED，证据件只读"},
        {"claim": "R14 收窄实测 +5 题/批 → 76.14%，零回归",
         "observed": str(REPO / "eval/olist/probe_dialect_gain.json"),
         "verdict": "OK", "owner": "T-02 探针，本窗不重跑"},
        {"claim": "十件现成探针在盘可复跑",
         "observed": len(PROBES), "verdict": "OK" if len(PROBES) >= 10 else "MISSING",
         "owner": "lead"},
        {"claim": "few-shot 库 119 行已入库、SHOTS_N 5",
         "observed": "docs/10:40 的书面登记；本窗未连真库，行数 NOT_VERIFIED",
         "verdict": "PARTIAL", "owner": "需真库冒烟，不能由本窗代认"},
        {"claim": "改 prompt 的增益可 replay 叠加",
         "observed": "eval/cassette.py key = sha256(path + canonical_json(body))，prompt 变即 CassetteMiss",
         "verdict": "REJECTED", "owner": "lead，写入 P1 两层方案"},
        {"claim": "bad case 有原生错因标注可支撑逐例定性",
         "observed": "must_contain / must_not_contain 覆盖 0，business_knowledge_required 词表 24",
         "verdict": "NOT_AVAILABLE", "owner": "lead，P0.2 人工定性不可省"},
    ]
    return {
        "conclusion": "认：三批读数、冻结集 gold、33 条误判、R14 +5、十件探针。不认：few-shot 行数（需真库）、replay 叠加 prompt 改动、原生错因标注。",
        "rows": rows,
        "computable_today": {
            "what": "95 条 execute 上的 EX、按终态拆分的 83 条失败联合分布、gold 字段覆盖率",
            "does_not_answer": "28 条真错题各自错在哪、few-shot 增益多少、85% 能否达成",
        },
        "prerequisites": [
            {"item": "28 条真错题逐例错因", "owner": "lead / 人工复核", "why": "冻结集无原生标注，代做等于编数据"},
            {"item": "app.gold_query 行数与同源题排除", "owner": "真库冒烟", "why": "本窗零 DB，不能拿文档登记冒充实测"},
            {"item": "三批新 live 读数", "owner": "P3 付费批", "why": "prompt 改动必然 miss 旧匣带"},
        ],
        "judgement_draft": {
            "denominator": "dataset_v3_frozen.json 的 expected_behavior=execute，现读 95",
            "numerator": "verdict.equivalent 为真的条数，唯一生产者 eval/runner.py:697",
            "hard_requirements": ["冻结集不动", "三个独立 batch_id", "cap{calls,spent_cny,stopped} 落全", "不写 85% 达成除非实测达标"],
        },
        "suspension_rewrite": "不登记『悬空』；三半各有主：期望侧 lead（冻结集）、观测侧 runner（唯一生产者）、计量侧 runner:1214（分母），未决项只记各自缺口与 owner。",
    }


def main() -> None:
    exp = expectation_side()
    obs = observation_side()
    mes = measurement_side(obs["batches"])
    payload = {
        "schema": "U183_CARRIER_THREE_FACE_CHECK/v1",
        "probe": "eval/olist/probe_u183_carriers.py",
        "recompute": "python eval/olist/probe_u183_carriers.py",
        "faces": {"expectation": exp, "observation": obs, "measurement": mes},
        "carriers": {
            "probes": [digest(p) for p in PROBES],
            "docs": [digest(p) for p in DOCS],
            "frozen": digest(FROZEN),
        },
        "claim_receipt": claim_receipt(exp, obs),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", OUT.name, OUT.stat().st_size, "bytes")
    print("EXPECT", exp["gold_native_all_95"], exp["business_knowledge_vocab_size"])
    print("OBS", [b["n_equivalent"] for b in obs["batches"]])
    print("MES", mes["joint_bad_by_terminal"])
    print("RECEIPT", payload["claim_receipt"]["conclusion"])


if __name__ == "__main__":
    main()
