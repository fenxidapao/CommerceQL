"""W80-4：红队尾部分类（零执行；不改用例、不改产品）。

把 W80 红队产物里 **21 条非 G-3 断言失败**（10 个用例）逐条归到三桶，并按
「设计如此／已知限制／潜在缺陷」写性质。目的不是把失败洗成通过，而是让最终交付
能回答"这 21 条到底是什么"：

* 终态形状 7 用例／17 断言：gate1 先拦（R07/R14）⇒ 在线按设计映射成
  `error(GATE_AST_REJECTED)`，用例期望 `refuse` ⇒ **用例前提 vs 实现约定**；没有放行。
* 截断 2 用例／2 断言：改写后 LIMIT 10000 = `EXEC_MAX_ROWS`；沙箱结果恰 10000 行 /
  2000 组 ⇒ `truncated=False` 对沙箱数据正确；且 P0 不传 `effective_limit`
  （N-06 / FR-8.9）⇒ 退化口径不可能在"注入 LIMIT < max_rows"时置真。**已知限制**。
* 可执行前提 1 用例／2 断言：题面显式引用 `tenant_id`（deny 列）⇒ gate1 R07 拒绝，
  用例却假设能跑到 DB 拿 0 行。**用例前提与语义包不相容（W1A）**，不是缺陷、不是放行。

产物：`eval/results_w80_redteam_tail.json`
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Mapping
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

REDTEAM = os.path.join(HERE, "results_w80_redteam.json")
OUT = os.path.join(HERE, "results_w80_redteam_tail.json")

TERMINAL_BUCKET = "终态形状（refuse vs error）"
TRUNCATION_BUCKET = "截断可观测性（truncated）"
EXEC_BUCKET = "可执行前提（用例假设能跑到 DB）"

TERMINAL_ASSERTIONS = frozenset({"refuse", "outcome == refuse", "not_rendered_as_error", "not_error"})
TRUNCATION_ASSERTIONS = frozenset({"truncated_true", "truncated_false"})

CLASSIFICATION = {
    TERMINAL_BUCKET: "设计如此",
    TRUNCATION_BUCKET: "已知限制",
    EXEC_BUCKET: "已知限制",
}
SCOPE = {
    TERMINAL_BUCKET: "产品终态映射（gate1 → error）＋用例期望",
    TRUNCATION_BUCKET: "产品 P0 载体缺失（N-06/FR-8.9）＋沙箱数据规模",
    EXEC_BUCKET: "用例前提（tenant_id 是 deny 列）",
}
EXPECTED = {
    TERMINAL_BUCKET: {"assertions": 17, "cases": 7},
    TRUNCATION_BUCKET: {"assertions": 2, "cases": 2},
    EXEC_BUCKET: {"assertions": 2, "cases": 1},
}

CITATIONS = {
    TERMINAL_BUCKET: [
        {"path": "backend/app/graph/nodes/gate1_ast.py", "line": 132,
         "what": "gate1 拒绝 → error(GATE_AST_REJECTED)"},
        {"path": "backend/app/graph/nodes/error_out.py", "line": 64,
         "what": "AST 拒绝映射到 GATE_AST_REJECTED 错误码"},
        {"path": "backend/app/graph/edges.py", "line": 283,
         "what": "§5.4：not passed → error_out，不进 repair"},
        {"path": "eval/reporter.py", "line": 1853,
         "what": "红队失败桶原文：用例前提 vs 实现约定，不是漏拦"},
    ],
    TRUNCATION_BUCKET: [
        {"path": "backend/app/exec/executor.py", "line": 330,
         "what": "collect_cap = max_rows（effective_limit=None 时）"},
        {"path": "backend/app/exec/executor.py", "line": 364,
         "what": "more_exist = collected > collect_cap"},
        {"path": "backend/app/exec/executor.py", "line": 371,
         "what": "truncated = len == effective_limit（否则 more_exist）"},
        {"path": "backend/app/graph/nodes/execute.py", "line": 133,
         "what": "_effective_limit 恒 None（P0 载体缺失，N-06/FR-8.9）"},
        {"path": "backend/app/core/config.py", "line": 111,
         "what": "EXEC_MAX_ROWS 默认 10000"},
        {"path": "eval/reporter.py", "line": 1859,
         "what": "红队失败桶原文：effective_limit 载体缺失 ⇒ truncated 无从置真"},
    ],
    EXEC_BUCKET: [
        {"path": "backend/app/guard/ast_gate.py", "line": 946,
         "what": "裸写 deny 列归 R07（tenant_id 是 deny 列）"},
        {"path": "backend/app/graph/nodes/gate1_ast.py", "line": 132,
         "what": "gate1 拒绝 → error(GATE_AST_REJECTED)"},
        {"path": "eval/reporter.py", "line": 1861,
         "what": "红队失败桶原文：用例前提与语义包不相容（W1A）"},
    ],
}


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bucket_of(assertions: list[str]) -> str:
    names = set(assertions)
    if names & TERMINAL_ASSERTIONS:
        return TERMINAL_BUCKET
    if names & TRUNCATION_ASSERTIONS:
        return TRUNCATION_BUCKET
    return EXEC_BUCKET


def _rationale(case: Mapping[str, Any], bucket: str) -> str:
    case_id = str(case.get("case_id"))
    facts = case.get("facts") or {}
    if bucket == TERMINAL_BUCKET:
        return (
            f"{case_id} 被 {case.get('reject_gate')} 以 {case.get('rule_id')} 拒绝"
            f"（blocked={case.get('blocked')}，leaked={case.get('leaked')}）；"
            "在线把 gate1 的 not passed 映射为 error(GATE_AST_REJECTED)"
            "（gate1_ast.py:132 → error_out.py:64），用例期望 refuse/not_rendered_as_error。"
            "属「用例前提 vs 实现约定」，不是漏拦；若产品要求攻击类统一出 refuse，"
            "需改在线终态映射——那是产品决策，本轮不改。"
        )
    if bucket == TRUNCATION_BUCKET:
        rows = case.get("row_count")
        rewritten = str(facts.get("rewritten_sql") or "")
        if rows == 10000:
            return (
                "改写后 LIMIT 10000 = EXEC_MAX_ROWS，结果恰 10000 行；"
                "fetch 以 effective_limit=None 走退化口径（collect_cap=10000，"
                "more_exist=collected>10000）⇒ 没有第 10001 行 ⇒ truncated=False 对沙箱数据正确。"
                "若 P0 按 §8.6 传入 effective_limit=10000，则 len==L 会置 true"
                "（N-06/FR-8.9 载体缺失，已知限制）。改写 SQL："
                f"{rewritten[:120]}"
            )
        return (
            f"改写后 LIMIT 10000 = EXEC_MAX_ROWS，结果 {rows} 组 < 10000 ⇒ "
            "沙箱规模下不可能截断；用例期望 true 假设生产规模数据。"
            "属沙箱数据规模＋P0 effective_limit 载体缺失（N-06/FR-8.9），已知限制。改写 SQL："
            f"{rewritten[:120]}"
        )
    return (
        f"{case_id} 的题面显式引用 tenant_id（deny 列），gate1 以 "
        f"{facts.get('gate1_rule_id')} 拒绝（{facts.get('gate1_reason')}）；"
        "用例却假设能跑到 DB、由 RLS 返 0 行。语料前提与语义包不相容（W1A），"
        "不是产品缺陷，也不是放行。"
    )


def main() -> int:
    report = _load(REDTEAM)
    failures: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    mixed: list[str] = []

    for case in report.get("results") or []:
        failed = [c for c in case.get("checks") or [] if c.get("status") == "FAIL"]
        if not failed:
            continue
        names = [str(c["assertion"]) for c in failed]
        buckets = {_bucket_of([name]) for name in names}
        if len(buckets) > 1:
            mixed.append(str(case.get("case_id")))
        bucket = _bucket_of(names)
        facts = case.get("facts") or {}
        item = {
            "case_id": case.get("case_id"),
            "expected_outcome": case.get("expected_outcome"),
            "bucket": bucket,
            "classification": CLASSIFICATION[bucket],
            "scope": SCOPE[bucket],
            "reject_gate": case.get("reject_gate"),
            "rule_id": case.get("rule_id"),
            "terminal_shape": case.get("terminal_shape"),
            "blocked": case.get("blocked"),
            "leaked": case.get("leaked"),
            "executed": case.get("executed"),
            "row_count": case.get("row_count"),
            "assertions": [
                {"assertion": c["assertion"], "detail": c["detail"]} for c in failed
            ],
            "rationale": _rationale(case, bucket),
            "citations": CITATIONS[bucket],
            "facts": {
                key: facts.get(key)
                for key in (
                    "gate1_rule_id",
                    "gate1_reason",
                    "gate1_limit_injected",
                    "rewritten_sql",
                    "truncated",
                )
                if key in facts
            },
        }
        items.append(item)
        failures.extend(
            {"case_id": case.get("case_id"), "assertion": c["assertion"]} for c in failed
        )

    counter = Counter(item["bucket"] for item in items)
    assertion_counter = Counter(item["bucket"] for item in items for _ in item["assertions"])
    buckets = [
        {
            "bucket": bucket,
            "classification": CLASSIFICATION[bucket],
            "cases": counter.get(bucket, 0),
            "assertions": assertion_counter.get(bucket, 0),
            "expected_cases": EXPECTED[bucket]["cases"],
            "expected_assertions": EXPECTED[bucket]["assertions"],
            "rationale": {
                TERMINAL_BUCKET: "gate1 先拦，按设计出 error；用例期望 refuse ⇒ 用例前提 vs 实现约定",
                TRUNCATION_BUCKET: "沙箱数据规模 + P0 effective_limit 恒 None ⇒ truncated 无法置真",
                EXEC_BUCKET: "用例假设能执行，但 tenant_id 是 deny 列 ⇒ 前提与语义包不相容",
            }[bucket],
        }
        for bucket in (TERMINAL_BUCKET, TRUNCATION_BUCKET, EXEC_BUCKET)
    ]
    shape_ok = (
        len(failures) == 21
        and len(items) == 10
        and all(
            counter.get(bucket, 0) == EXPECTED[bucket]["cases"]
            and assertion_counter.get(bucket, 0) == EXPECTED[bucket]["assertions"]
            for bucket in EXPECTED
        )
        and not mixed
    )
    classification_counts = Counter(item["classification"] for item in items)

    payload: dict[str, Any] = {
        **_bootstrap.build_stamp(),
        "task": "W80-4 红队尾部分类（21 条非 G-3 断言失败 / 10 用例；零执行；不改用例、不改产品）",
        "source": {
            "path": _relative(REDTEAM),
            "sha256": _sha256(REDTEAM),
            "git_rev": report.get("git_rev"),
            "git_dirty": report.get("git_dirty"),
            "generated_at": report.get("generated_at"),
            "total": report.get("total"),
            "expect_block": report.get("expect_block"),
            "checked": report.get("checked"),
            "leaked": report.get("leaked"),
        },
        "n_failures": len(failures),
        "n_cases": len(items),
        "buckets": buckets,
        "classification_counts": dict(classification_counts),
        "potential_defect_count": classification_counts.get("潜在缺陷", 0),
        "shape_ok": shape_ok,
        "mixed_bucket_cases": mixed,
        "items": items,
        "statement": (
            "这 21 条不影响 G-3 的「危险 SQL 放行=0」；G-3 PASS 不是成本闸门已测。"
            "不得把本件读成红队全绿，也不得据此改用例或产品代码。"
        ),
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"written: {_relative(OUT)}")
    print(f"failures={len(failures)} cases={len(items)} shape_ok={shape_ok}")
    for bucket in buckets:
        print(
            f"  {bucket['classification']:<6} {bucket['bucket']}: "
            f"{bucket['assertions']} 断言 / {bucket['cases']} 用例"
        )
    return 0 if shape_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
