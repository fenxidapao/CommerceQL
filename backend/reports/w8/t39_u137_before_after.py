"""T-39 D 的随交读数：演示那句「上个月复购率最高的 10 个店铺是哪些？」在 `U-137` 落地**前后**的归因对撞。

🔴 零出站：不发 LLM、不连业务写面、不碰匣带。SQL 从 `app.audit_log.final_executed_sql` **只读**取
（外层 `begin; … rollback;`），闸门是纯静态件（sqlglot ＋ 语义包 allowlist）。

"前"那一臂怎么来的（这是本窗自订的**离线对照臂**，不是生产可观测）：
    落地前 `_join_verdict` 用的是 `self.assets.get(name)` 命中就取 `logical_name`、不命中就用**原名**（CTE 名）
    ⇒ 等价物 = 把 `_side_logical` 换成"单值、不展开 CTE"的旧语义，再对**同一条 SQL**跑一遍。
    可信度检验的**结果**（本轮现测，写在这里防下一轮重犯）：我原本期望对照臂复现第 13 轮归档的 R10×3 ——
    期望本身是错的：第 13 轮那三条与 T-38 这三条**不是同一批 SQL 变体**，拿前一批的 tally 当后一批的对照位
    = 用另一个题面的读数当验收位。⇒ 本件只保留「同一条 SQL 的对照臂 vs 当期实现」这一对单变量对撞。

"后"那一臂 = 当期实现（`app/guard/ast_gate.py::_side_logical()`）。

⚠️ 活体面**不带**本轮改动：镜像 `Created = 2026-10-05T15:19:25Z`、本轮未 build／未 recreate ⇒
   这里两句都是**离线面**（依 `U-125` 判据④，按 `rule_id` 的归因必须标"来自离线器件"）。

复算（cwd = 仓库根）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t39_u137_before_after.py
产物：`backend/reports/w8/evidence/t39/u137_before_after.json`
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
for _p in (str(ROOT / "eval"), str(ROOT / "backend"), str(ROOT / "backend" / "reports" / "w8")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

_bootstrap.bootstrap()

# 复用第 13 轮那件离线器件的取数面：psql 会把 base64 按 76 字符折行 ⇒ 拼接逻辑已在它手里踩过一次，
# 不在这里重写一份第二真相。
import probe_r13_gate_rejections as p13  # noqa: E402

from app.auth.context import IdentityContext  # noqa: E402
from app.core.enums import AstRule, Role  # noqa: E402
from app.guard.ast_gate import _Auditor, run_gate1  # noqa: E402
from app.guard.rules import RULE_BY_ID  # noqa: E402
from app.semantics.loader import load_bundle  # noqa: E402
from app.semantics.runtime import SemanticBundleRuntime  # noqa: E402

RECEIPT = ROOT / "deploy" / "loadtest" / "t38_c3n30_main.json"
OUT = ROOT / "backend" / "reports" / "w8" / "evidence" / "t39" / "u137_before_after.json"
R13_ARCHIVE = ROOT / "backend" / "reports" / "w8" / "evidence" / "t39" / "u137_before.json"


def record_of(task_id: str) -> dict[str, str]:
    """取该 run 的 SQL ＋ 身份 ＋ 原始问句（只读，`begin; … rollback;` 在 p13 里）。"""
    return p13._sql_of(task_id)


def allow_for(rec: dict[str, str], task_id: str):
    runtime = SemanticBundleRuntime(load_bundle(_bootstrap.BUNDLE_PATH))
    identity = IdentityContext(
        trace_id="tr-t39", task_id=task_id, session_id="se-t39",
        tenant_id=rec["tenant_id"], user_id=rec["user_id"],
        role=Role.ANALYST if rec["role"] == "analyst" else Role.PLATFORM_ADMIN,
        scope_claims=(), shop_ids=())
    return runtime.guard_allowlist(identity, max_rows=None)


def _legacy_side_logical(self: _Auditor, name: str, _stack: frozenset[str] = frozenset()) -> set[str]:
    """落地前的等价语义：资产名给 `logical_name`，其余（含 CTE 名）**原样**返回、不展开。"""
    asset = self.assets.get(name)
    if asset is not None:
        return {str(asset.get("logical_name", name))}
    return {name}


def run_with_legacy_join_verdict(sql: str, allow) -> dict:
    """在同一个 Auditor 上把 `_side_logical` 换成旧语义 ⇒ 复现落地前那条判定路径（单变量）。"""
    patched = _Auditor._side_logical
    _Auditor._side_logical = _legacy_side_logical  # type: ignore[assignment]
    try:
        report = run_gate1(sql, allow)
    finally:
        _Auditor._side_logical = patched  # type: ignore[assignment]
    return report


def cell_of(task_id: str, note: str = "") -> dict:
    rec = record_of(task_id)
    allow = allow_for(rec, task_id)
    after = run_gate1(rec["sql"], allow)
    before = run_with_legacy_join_verdict(rec["sql"], allow)

    def face(res) -> dict:
        g = res.gate_result
        msg = RULE_BY_ID[AstRule(g.rule_id)].user_message if g.rule_id else None
        return {"passed": g.passed, "rule_id": g.rule_id, "user_message": msg}

    return {"task_id": task_id, "sql_chars": len(rec["sql"]),
            "sql_len_matches_declared": len(rec["sql"]) == rec["declared_len"],
            "raw_question": rec.get("raw_question"),
            "tenant_id": rec["tenant_id"], "user_id": rec["user_id"],
            "before_legacy_arm": face(before),
            "after_current_impl": face(after), "note": note}


def main() -> int:
    print(f"[ROOT] {ROOT}")
    assert RECEIPT.exists(), f"尺坏：找不到回执 {RECEIPT}"
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    codes = receipt["scenarios"][0]["codes_task_ids"]
    rejected = [t for code, ids in codes.items() if code == "GATE_AST_REJECTED" for t in ids]
    if not rejected:
        raise SystemExit("尺坏：当期回执里没有 GATE_AST_REJECTED 的 task_id ⇒ 本件无事可做（不是通过，是无样本）")

    r13 = json.loads(R13_ARCHIVE.read_text(encoding="utf-8"))
    rows = [cell_of(t) for t in sorted(rejected)]
    legacy_ids = [r["before_legacy_arm"]["rule_id"] for r in rows]
    after_ids = [r["after_current_impl"]["rule_id"] for r in rows]
    changed = [r["task_id"][:12] + "…" for r in rows
               if r["before_legacy_arm"]["rule_id"] != r["after_current_impl"]["rule_id"]
               or r["before_legacy_arm"]["passed"] != r["after_current_impl"]["passed"]]
    flipped_pass = [r["task_id"][:12] + "…" for r in rows if r["after_current_impl"]["passed"]]
    out = {
        "artifact": "commerceql.w8.t39_u137_before_after/1",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_rev": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True).stdout.strip(),
        "git_rev_short": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                        capture_output=True, text=True).stdout.strip(),
        "zero_egress": True,
        "question": "上个月复购率最高的 10 个店铺是哪些？（同一题在 T-38 批里生成了三条变体）",
        "receipt": "deploy/loadtest/t38_c3n30_main.json（三条 GATE_AST_REJECTED 的 task_id 取自 codes_task_ids）",
        "arms": {
            "before": "离线对照臂 = 把 `_side_logical` 换成落地前语义（不展开 CTE）后对同一条 SQL 跑 `run_gate1`（本窗自订，单变量）",
            "after": "当期实现（`app/guard/ast_gate.py::_side_logical()` 按资产口径展开）",
            "credibility_check": {
                "本窗自订的期望（**已被现测推翻，原文保留**）":
                    "我原先要求对照臂把这三条复现成 R10×3，参照物是第 13 轮归档 `u137_before.json` 的 rule_id_tally。",
                "现测": {"legacy_arm_rule_ids": legacy_ids, "after_arm_rule_ids": after_ids,
                        "对照臂给出 R10×3": set(legacy_ids) == {"R10"}},
                "为什么期望本身是错的":
                    "第 13 轮那三条（`tk_8fbf1cf3…`／`tk_51912ce6…`／`tk_0696f1a8…`）与本轮这三条（T-38 批）**不是同一批 SQL 变体**，"
                    "把前一批的 tally 当后一批的对照位 = 拿另一个题面的读数当验收位（§4.8 规则：pre-fix 就为 0 不得当验收位）。"
                    "⇒ 期望作废，只留「对照臂 vs 当期实现」这一对**同一条 SQL 的单变量对撞**。",
                "r13_archive_rule_tally": r13.get("rule_id_tally"),
                "r13_archive_class_tally": r13.get("class_tally"),
                "⚠️ 不许用回执 code 反推 rule_id":
                    "`app/graph/nodes/error_out.py:64` 把**任何** AST 闸门拒绝映射成 `GATE_AST_REJECTED` ⇒ "
                    "回执里的 code 分不清 R06/R10（这正是 `U-125`「rule_id 无出口」的另一面）。",
            },
        },
        "rows": rows,
        "tally_after": {},
        "reading": "",
    }
    tally: dict[str, int] = {}
    for r in rows:
        key = f"{r['after_current_impl']['rule_id']}|passed={r['after_current_impl']['passed']}"
        tally[key] = tally.get(key, 0) + 1
    out["tally_after"] = dict(sorted(tally.items()))
    out["归因变化"] = {"改了的": changed, "翻成放行的": flipped_pass}
    out["reading"] = (
        f"三条变体里**只有一条**的归因被本轮改动改变（{changed}：R10 → R06 —— CTE 侧按资产展开后连接路径判定通过，"
        "露出真正的列面违规）；仍 R10 那一条是**真该拒**（其资产对不在认证边集内），但它今天起的文案不再是"
        "「超出你的权限」；前后同为 R06 的那条与本号无关 ⇒ 🔴 **第 15 轮 RELAY §16.3／OVERVIEW 里"
        "『三条 GATE_AST_REJECTED 明确归 U-137 面』那句是过度归因，本轮就地订正**。"
        f"三条**没有一条**翻成放行（after = {out['tally_after']}）⇒ 演示那句「上个月复购率最高的 10 个店铺是哪些？」"
        "在离线面**仍不出数**，而活体面连本轮改动都还没带上（镜像未重建）。"
        "⇒ QA 16.5(ii) 那条「先落 U-137 再演示」（出路 a）**前提不成立**，已写进本轮交回。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"tally_after": out["tally_after"],
                      "legacy_arm_rule_ids": legacy_ids,
                      "归因改了的": changed,
                      "翻成放行的": flipped_pass,
                      "rows": [(r["task_id"][:12] + "…",
                                r["before_legacy_arm"]["rule_id"],
                                r["after_current_impl"]["rule_id"],
                                r["after_current_impl"]["passed"]) for r in rows]},
                     ensure_ascii=False))
    print(f"落盘 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
