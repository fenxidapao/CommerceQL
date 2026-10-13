"""T-51 段 1 诊断采集（**live L4**）—— 只读冻结集，只出站 `l4_score`。

⚠️ 本件**不写** `app.cost_ledger`：`build_gateway` 未传 `ledger` ⇒ 走
`InMemoryCostLedgerSink`（`app/llm/__init__.py:617`）。花费从 `ScoreOutcome.cost_cny` 逐笔累加自报。

用法（cwd = `CommerceQL`，需 `.venv`）：
    .venv\\Scripts\\python.exe backend/reports/w8/t51_collect.py [--smoke] [--out-dir DIR]

候选表纪律：只登记**语义包里有真实竞争绑定对**的题（机器可复算），其余题**拒绝出站**
（它们不是"两个绑定竞争"，构造候选 = 伪造输入）。理由与分类见 `t51_scope.json`。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from decimal import Decimal

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]                     # CommerceQL/
BACKEND = ROOT / "backend"
EVAL = ROOT / "eval"
REPEATS = 3

#: 真实竞争绑定对（来源 = `semantic/bundle_2026.09.14.1.yaml` 的 `field_bindings.城市.candidates`，
#: 冻结集 `C-CITY-01` 自带同一对 ⇒ **不是本件编的**）。
CITY_PAIR = ("order_paid.receiver_city", "shop.city")
PAIRED_CASES = {
    "C-CITY-01": CITY_PAIR,
    "C-CITY-02": CITY_PAIR,
    "C-CITY-03": CITY_PAIR,
    "C-CITY-04": CITY_PAIR,
}


def _load_env() -> int:
    """把 `deploy/.env` 灌进 `os.environ`（**不打印任何值**）。返回灌入条数。"""
    path = ROOT / "deploy" / ".env"
    if not path.exists():
        return 0
    n = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n


def _dataset_cases() -> list[dict]:
    data = json.loads((EVAL / "dataset_v1_frozen.json").read_text(encoding="utf-8"))
    return data["cases"]


async def _collect(cases: list[dict], *, smoke: bool) -> dict:
    sys.path.insert(0, str(EVAL))
    sys.path.insert(0, str(BACKEND))
    import _bootstrap

    _bootstrap.bootstrap()

    from app.binding import ScoreSample, assess_stability, score_l4, sweep
    from app.core.config import get_settings
    from app.llm import build_gateway

    settings = get_settings()
    gateway = build_gateway(settings)
    epsilon = float(getattr(settings, "BINDING_TAU_EPSILON", 0.02))
    bundle_version = getattr(settings, "SEMANTIC_BUNDLE_VERSION", "") or ""

    samples: list[ScoreSample] = []
    raw_rows: list[dict] = []
    spend = Decimal(0)
    failures: list[dict] = []
    todo = [c for c in cases if c["case_id"] in PAIRED_CASES]
    if smoke:
        todo = todo[:1]

    for case in todo:
        cid = case["case_id"]
        cands = PAIRED_CASES[cid]
        question = case["question"]
        repeats: list[tuple[float, ...]] = []
        for k in range(REPEATS):
            outcome = await score_l4(
                port=gateway, question=question, candidates=list(cands),
                bundle_version=bundle_version,
            )
            if outcome.cost_cny is not None:
                spend += Decimal(outcome.cost_cny)
            if not outcome.ok:
                failures.append({"case_id": cid, "attempt": k + 1, "reason": outcome.reason})
                continue
            by_id = {s.candidate_id: s.value for s in outcome.scores}
            repeats.append(tuple(float(by_id[c]) for c in cands))
        if len(repeats) < REPEATS:
            failures.append({"case_id": cid, "attempt": "final", "reason": f"只有 {len(repeats)} 次可用"})
            continue
        sample = ScoreSample(
            sample_id=cid, candidate_ids=tuple(cands),
            repeats=tuple(repeats), gold_candidate_id=None,
        )
        samples.append(sample)
        raw_rows.append({
            "case_id": cid, "question": question, "candidate_ids": list(cands),
            "repeats": [list(r) for r in repeats], "gold_candidate_id": None,
            "gaps": [sample.gap(i) for i in range(len(sample.repeats))],
        })

    await gateway.aclose()

    stability = assess_stability(samples) if samples else None
    points = sweep(samples, epsilon=epsilon) if samples else ()
    return {
        "scope": {
            "run": "T-51 段1 诊断（city 族子集）",
            "paired_cases": sorted(PAIRED_CASES),
            "n_samples": len(samples),
            "repeats": REPEATS,
            "epsilon": epsilon,
            "note": "只覆盖 city_ambiguity 一族（语义包内唯一有真实竞争绑定对的族）",
        },
        "samples": raw_rows,
        "failures": failures,
        "spend_cny": str(spend),
        "stability": None if stability is None else {
            "verdict": str(stability.verdict),
            "max_gap_std": stability.max_gap_std,
            "min_kendall": stability.min_kendall,
            "repeats": stability.repeats,
            "per_sample": [
                {"sample_id": s.sample_id, "gaps": list(s.gaps),
                 "gap_std": s.gap_std, "kendalls": list(s.kendalls)}
                for s in stability.samples
            ],
        },
        "curve": [
            {"tau": p.tau, "binding_accuracy": p.binding_accuracy,
             "should_clarify_but_did_not": p.should_clarify_but_did_not,
             "clarify_rate": p.clarify_rate, "decided": p.decided,
             "should_clarify_total": p.should_clarify_total}
            for p in points
        ],
    }


def _classify(cases: list[dict]) -> dict:
    """零调用：把 18 条按"歧义发生的层"分类 ⇒ 哪些才有真实绑定竞争对。"""
    def kind(bkr: list[str]) -> str:
        tags = set(bkr)
        if "fuzzy:city_ambiguity" in tags:
            return "绑定竞争（L4 候选空间内）"
        if "fuzzy:relative_time" in tags:
            return "时间窗未定（不在 L4 候选空间）"
        if "fuzzy:region_undefined" in tags:
            return "值域未定义（不在 L4 候选空间）"
        if "fuzzy:open_ended" in tags:
            return "开放式问法（不在 L4 候选空间）"
        if "fuzzy:metric" in tags or any(t.startswith("metric:") for t in tags) and "fuzzy:refund" in tags:
            return "指标口径未定（不在 L4 候选空间）"
        return "其它"

    rows = []
    for c in cases:
        ce = c.get("clarify_expected")
        if not ce:
            continue
        bkr = list(c.get("business_knowledge_required") or ())
        rows.append({
            "case_id": c["case_id"], "question": c["question"],
            "bkr": bkr, "kind": kind(bkr),
            "has_real_pair": c["case_id"] in PAIRED_CASES,
            "why": ce.get("reason"),
        })
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"n_clarify": len(rows), "by_kind": counts, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out-dir", default=str(HERE.parent))
    args = ap.parse_args()

    loaded = _load_env()
    cases = _dataset_cases()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scope = _classify(cases)
    scope["env_keys_loaded"] = loaded
    scope["candidate_policy"] = (
        "只对语义包内有真实竞争绑定对的题出站；其余题拒绝构造候选（构造 = 伪造输入）"
    )
    (out_dir / "t51_scope.json").write_text(
        json.dumps(scope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[scope] n_clarify={scope['n_clarify']} by_kind={scope['by_kind']}")
    print(f"[scope] real_pair cases = {sorted(PAIRED_CASES)}  env_keys_loaded={loaded}")

    result = asyncio.run(_collect(cases, smoke=args.smoke))
    name = "t51_stage1_city_only_smoke.json" if args.smoke else "t51_stage1_city_only.json"
    (out_dir / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    st = result["stability"]
    print(f"[run] n_samples={result['scope']['n_samples']} spend_cny={result['spend_cny']} "
          f"failures={len(result['failures'])}")
    if st:
        print(f"[stability] verdict={st['verdict']} max_gap_std={st['max_gap_std']:.4f} "
              f"min_kendall={st['min_kendall']:.4f}")
        for s in st["per_sample"]:
            print(f"   {s['sample_id']}: gaps={[round(g,4) for g in s['gaps']]} "
                  f"gap_std={s['gap_std']:.4f} kendalls={[round(k,3) for k in s['kendalls']]}")
    print(f"[curve] {len(result['curve'])} points -> {out_dir / name}")


if __name__ == "__main__":
    main()