"""红队集 × gate 层测试（W2C；tests/redteam/ 与 W4 共建，docs/08 §4.1）。

数据源：``eval/red_team_cases_v1.json``（W1A 冻结集，content_hash 锁定）。
**DoD① 的判定基准**：block → 拒绝 + rule_id 归因 + 文案不泄露；
rewrite → 改写不拒绝；warn → 告警且继续。

**层级边界（诚实声明）**：
- 本文件只覆盖 **gate 层可判定** 的断言。expected=``refuse`` 的用例
  （跨租户 XT / 注入 INJ 组）在 gate 层的表现是"被 R07/R14 拒绝"——
  其端到端语义（refuse vs error 渲染、响应与"真无数据"不可区分）归 W4 编排与 W6 评测；
- ``execute`` / ``degraded`` 组在 gate 层只断言"gate1/gate2 放行"
  （truncated / 转异步是执行层与编排层的职责，W2D/W4）；
- gate3 沙箱跳过语义（RT-COST-003：gate_status == not_evaluated）在 gate3 单测覆盖。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.enums import GateDecision
from app.guard import ast_gate
from app.guard.ast_gate import run_gate1
from app.guard.policy_gate import run_gate2
from tests.unit.guard_fixtures import (
    REDTEAM_PATH,
    FakeSemanticBundle,
    build_allowlist,
    load_bundle_yaml,
    make_ctx,
)


@pytest.fixture(scope="module")
def allow() -> dict[str, Any]:
    return build_allowlist()


@pytest.fixture(scope="module")
def bundle(allow: dict[str, Any]) -> FakeSemanticBundle:
    return FakeSemanticBundle(allow)


@pytest.fixture(scope="module")
def cases() -> list[dict[str, Any]]:
    data = json.loads(REDTEAM_PATH.read_text(encoding="utf-8"))
    return data["cases"]


#: gate 层可完整判定 rule_id 归因的阻断规则（R01/R02/R16-002 在 run_gate1 前置检查，
#: 其归因测试在 test_guard_gate1.py —— 这里也纳入，前置检查同属 gate1）。
_BLOCK_RULE_IDS = {f"R{i:02d}" for i in range(1, 21)}


def evaluate_case(case: dict[str, Any], allow: dict[str, Any], bundle) -> str:
    """gate 层评估单条红队用例，返回实际结局：

    ``blocked:<rule_id>`` | ``blocked:gate2:<rule_id>`` | ``passed`` | ``rewritten``
    """

    r1 = run_gate1(case["attack_sql"], allow)
    if not r1.passed:
        return f"blocked:{r1.gate_result.rule_id}"
    if r1.limit_injected is not None or r1.comments_stripped:
        return "rewritten"
    rep = run_gate2(case["attack_sql"], make_ctx(), bundle)
    if not rep.gate_result.passed:
        return f"blocked:gate2:{rep.gate_result.rule_id}"
    return "passed"


# ---------------------------------------------------------------------------
# 主判定：红队集全绿（DoD①）
# ---------------------------------------------------------------------------

class TestRedTeamFrozenSet:
    def test_dataset_loaded(self, cases: list[dict[str, Any]]) -> None:
        # 冻结集完整性：66 条 / 20 规则全覆盖（W1A coverage 声明）
        assert len(cases) == 66
        covered = {r for c in cases for r in c["rule_ids"]}
        assert covered == _BLOCK_RULE_IDS

    def test_block_cases_blocked_with_rule_attribution(
        self, cases: list[dict[str, Any]], allow: dict[str, Any], bundle
    ) -> None:
        failures: list[str] = []
        for c in cases:
            if c["severity"] != "block":
                continue
            outcome = evaluate_case(c, allow, bundle)
            if not outcome.startswith("blocked"):
                failures.append(f"{c['case_id']}: expected block, got {outcome}")
                continue
            if c["rule_ids"] and outcome.split(":")[-1] not in c["rule_ids"]:
                failures.append(
                    f"{c['case_id']}: rule 归因不符 expected={c['rule_ids']} got={outcome}"
                )
        assert not failures, "阻断类用例失败：\n" + "\n".join(failures)

    def test_rewrite_cases_not_blocked(
        self, cases: list[dict[str, Any]], allow: dict[str, Any], bundle
    ) -> None:
        failures: list[str] = []
        for c in cases:
            if c["severity"] != "rewrite":
                continue
            outcome = evaluate_case(c, allow, bundle)
            # **写成拒绝即实现缺陷**（U-16 / assertion_discipline 原文）
            if outcome.startswith("blocked"):
                failures.append(f"{c['case_id']}: expected rewrite, got {outcome}")
            if c["rule_ids"] == ["R04"] and outcome != "rewritten":
                failures.append(f"{c['case_id']}: R04 必须实际发生改写, got {outcome}")
        assert not failures, "改写类用例失败：\n" + "\n".join(failures)

    def test_warn_cases_continue_with_warning(
        self, cases: list[dict[str, Any]], allow: dict[str, Any]
    ) -> None:
        failures: list[str] = []
        for c in cases:
            if c["severity"] != "warn":
                continue
            r1 = run_gate1(c["attack_sql"], allow)
            warned = {w.rule.value for w in r1.warnings}
            if not r1.passed:
                failures.append(f"{c['case_id']}: 告警级被拒绝（实现缺陷，U-16）")
            if not set(c["rule_ids"]) & warned:
                failures.append(
                    f"{c['case_id']}: 未产生规则告警 expected={c['rule_ids']} got={warned}"
                )
        assert not failures, "告警类用例失败：\n" + "\n".join(failures)

    def test_refuse_layer_cases_blocked_at_gate(
        self, cases: list[dict[str, Any]], allow: dict[str, Any], bundle
    ) -> None:
        # XT/INJ 组（expected=refuse）：gate 层底线 = 不得放行原始 SQL。
        # （refuse/error 渲染语义归 W4/W6 —— 层级边界见本文件 docstring）
        failures: list[str] = []
        for c in cases:
            if c["expected_outcome"] != "refuse":
                continue
            outcome = evaluate_case(c, allow, bundle)
            if not outcome.startswith("blocked"):
                failures.append(f"{c['case_id']}: gate 层未拦截（{outcome}）")
        assert not failures, "跨租户/注入类用例失败：\n" + "\n".join(failures)

    def test_execute_cases_pass_gates(
        self, cases: list[dict[str, Any]], allow: dict[str, Any], bundle
    ) -> None:
        # ⚠️ 已登记的冻结集内部矛盾（reports/w2c/RELAY.md，提请架构裁定）：
        # RT-LIM-003 的 SQL 含 `WHERE tenant_id = 'T_C'`，而语义包 policies.deny_columns
        # 明列 order_paid.tenant_id（"不得由模型生成"）→ gate 层按 AST-R07 拦截是
        # 契约要求（列级屏蔽优先于一切，07 §7.2）；该用例的 execute 期望与
        # deny_columns 策略二选一，W2C 选择执行契约（拒绝），等待裁定。
        waivers = {"RT-LIM-003"}
        failures: list[str] = []
        for c in cases:
            if c["expected_outcome"] not in ("execute", "degraded"):
                continue
            if c["case_id"] in waivers:
                outcome = evaluate_case(c, allow, bundle)
                assert outcome.startswith("blocked"), (
                    f"{c['case_id']} 豁免前提失效：若 gate 改为放行，需重新评估该用例"
                )
                continue
            r1 = run_gate1(c["attack_sql"], allow)
            if not r1.passed:
                failures.append(f"{c['case_id']}: 正常查询被 gate1 拒绝")
                continue
            if r1.warnings:
                failures.append(f"{c['case_id']}: no_rule_tripped 断言被警告破坏")
                continue
            rep = run_gate2(c["attack_sql"], make_ctx(), bundle)
            if not rep.gate_result.passed:
                failures.append(f"{c['case_id']}: 正常查询被 gate2 拒绝")
        assert not failures, "正常执行类用例失败：\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 不泄露表/列名（DoD②，红队逐条断言 error_text_shall_not_leak_*）
# ---------------------------------------------------------------------------

class TestNoLeakageOnReject:
    def test_reject_reasons_leak_nothing(
        self, cases: list[dict[str, Any]], allow: dict[str, Any]
    ) -> None:
        bundle_yaml = load_bundle_yaml()
        secrets: set[str] = set()
        for a in bundle_yaml["assets"]:
            secrets.add(a["physical_asset"].lower())
            secrets.add(a["logical_name"].lower())
            for col in a["columns"]:
                secrets.add(col["name"].lower())
        secrets.update({"information_schema", "pg_catalog", "pg_temp", "pg_toast"})

        failures: list[str] = []
        for c in cases:
            r1 = run_gate1(c["attack_sql"], allow)
            if r1.passed:
                continue
            reason = (r1.gate_result.reason or "").lower()
            leaked = {s for s in secrets if s in reason and len(s) > 2}
            if leaked:
                failures.append(f"{c['case_id']}: 文案泄露 {leaked} → {reason!r}")
        assert not failures, "拒绝文案泄露 schema 细节：\n" + "\n".join(failures)

    def test_rule_id_always_present_on_block(self, allow: dict[str, Any]) -> None:
        # C-02：rule_id 必进 gate_detail
        r = run_gate1("SELECT * FROM v_order_paid", allow)
        assert r.gate_result.rule_id == "R03"


# ---------------------------------------------------------------------------
# 负向对照：注入 → 必红 → 还原 → 必绿（防"护栏摆设"）
# ---------------------------------------------------------------------------

class TestNegativeControl:
    """把 _Auditor.run 打成"永不阻断"（模拟闸门失效），
    阻断类用例必须翻转 —— 否则说明断言根本不依赖被测行为（摆设护栏）。"""

    def test_disabled_audit_flips_block_cases(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cases: list[dict[str, Any]],
        allow: dict[str, Any],
        bundle,
    ) -> None:
        monkeypatch.setattr(ast_gate._Auditor, "run", lambda self, root: None)

        must_flip: list[str] = []
        for c in cases:
            if c["severity"] != "block":
                continue
            # R01/R02 与部分 R16 在 run_gate1 前置检查（审计器之外），不在本对照范围
            if set(c["rule_ids"]) & {"R01", "R02"} or "SET" in c["attack_sql"].upper():
                continue
            outcome = evaluate_case(c, allow, bundle)
            if outcome.startswith("blocked") and not outcome.startswith("blocked:gate2"):
                must_flip.append(c["case_id"])
        assert not must_flip, (
            f"负向对照失败：审计器失效后这些用例仍被 gate1 拦截（说明断言没有真正依赖审计器）：{must_flip}"
        )

    def test_restored_audit_blocks_again(
        self, cases: list[dict[str, Any]], allow: dict[str, Any], bundle
    ) -> None:
        # 还原 → 必绿：monkeypatch 恢复后原判定路径仍然成立
        r = run_gate1("SELECT * FROM v_order_paid", allow)
        assert not r.passed and r.gate_result.rule_id == "R03"

    def test_gate2_redundancy_catches_when_gate1_blind(
        self,
        monkeypatch: pytest.MonkeyPatch,
        allow: dict[str, Any],
        bundle,
    ) -> None:
        # 双保险验证：gate1 审计失效时，gate2 的资产/敏感列二次复核仍须兜底
        monkeypatch.setattr(ast_gate._Auditor, "run", lambda self, root: None)
        rep = run_gate2(
            "SELECT receiver_phone FROM v_order_paid LIMIT 10", make_ctx(), bundle
        )
        assert not rep.gate_result.passed
        assert rep.gate_result.rule_id == "G2-DENY"
