"""07 §14.2 决策表 **F 组 / G 组**（LLM/呈现与审计/开关跳）—— 全链图级测试。

夹具：`_fullchain_deps`（理由与纪律见其模块 docstring）。
断言模板沿 A 组：`run_chain` 收帧 → `terminal_frames` 过滤终态 → 恰 1 终态 +
`outcome.status` + 审计落行。

⚠️ 与 07 字面的差异（按实现断言，登记 RELAY §九 U-88 起）：

1. **F1 无弱模型降级档**：`LlmTimeout` / `LlmCircuitOpen` 在图内可测面（脚本件直抛，
   不经过 `app.llm` 网关降级链）→ `llm_error_update` 按 `default_code="INTERNAL"`
   折成 `error(INTERNAL)`，而非 07 字面的 `degraded + switched_to_weak_model`。
2. **F4 `present` 失败**在图内是**恒触发**（P0 边界：presenter 缺席 ⇒ 成功链恒带
   `degraded(present_failed/table_only)`），与 `TestFullchainGreenBaseline` 同一现象。
3. **F5 不可达**：`GateResult` 缺预估延迟载体 ⇒ 转异步分支恒不可达（引用
   `test_edges_contract.py::test_async_switch_is_unreachable_until_carrier_lands`）。
4. **F6 会话历史恒空**：`GraphState` 无历史字段（`normalize` docstring §三已登记），
   裁剪无从发生 ⇒ 无任何事件，纯登记。
5. **G3 缺载体**：kill switch 需意图节点读全局开关，P0 无该开关（引用
   `test_edges_contract.py::test_route_after_intent_respects_terminal_set_by_node`
   钉住"节点已设终态按终态出口"的**路由**面，但触发面在图内无载体）。
6. **G4 缺载体**：`recursion_limit=25` 超出需构造 ≥25 步循环，正常链无法触达，
   图级不可测 ⇒ 纯登记（`GRAPH_RECURSION_LIMIT` 常量见 `build.py`）。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import TaskStatus
from app.llm.errors import (
    LlmConcurrencyExceeded,
    LlmTimeout,
    LlmUpstreamError,
)
from tests.contract._fullchain_deps import (
    make_chain,
    run_chain,
    terminal_frames,
)

# P0 边界：presenter 缺席 ⇒ 成功链路恒伴随 present_failed 降级。
_P0_PRESENT_ONLY: list[tuple[str, str]] = [("present_failed", "table_only")]


def _reasons(frames: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    """全部 degraded 帧的 `(reason, action_taken)`（按发生序）。"""
    return [(d["reason"], d["action_taken"]) for e, d in frames if e == "degraded"]


class TestGroupF:
    """F 组：LLM 与呈现类（07 §14.2 L2698–L2703）。"""

    def test_f1_llm_timeout_becomes_internal(self) -> None:
        """F1 LLM 超时 → `error(INTERNAL)`（图内可测面无降级链，差异 1）。

        ⚠️ 07 字面 `degraded + switched_to_weak_model`；脚本件直抛时网关降级链不在
        图内，`default_code="INTERNAL"` 折成 error（登记 RELAY §九）。
        """
        chain = make_chain(understand_error=LlmTimeout("单次调用超时"))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "INTERNAL"
        assert outcome.status is TaskStatus.FAILED
        assert _reasons(frames) == []
        assert all(e != "data" for e, _ in frames)

    def test_f2_llm_concurrency_exceeded(self) -> None:
        """F2 LLM 429 并发超限 → `error(LLM_CONCURRENCY_EXCEEDED)`（不降级）。"""
        chain = make_chain(understand_error=LlmConcurrencyExceeded("上游 429 退避耗尽"))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "LLM_CONCURRENCY_EXCEEDED"
        assert outcome.status is TaskStatus.FAILED

    def test_f3_llm_upstream_error(self) -> None:
        """F3 LLM 5xx → `error(LLM_UPSTREAM_ERROR)`（不降级）。"""
        chain = make_chain(understand_error=LlmUpstreamError("上游 5xx", detail={"status": 503}))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "LLM_UPSTREAM_ERROR"
        assert outcome.status is TaskStatus.FAILED

    def test_f4_present_failed_still_succeeds_with_table(self) -> None:
        """F4 `present` 失败 → `degraded(present_failed/table_only)`，表格仍有效（success）。"""
        chain = make_chain()
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 唯一降级是 P0 恒在的 present_failed，无 error 帧，data 帧在（表格仍有效）。
        assert _reasons(frames) == _P0_PRESENT_ONLY
        assert all(e != "error" for e, _ in frames)
        assert any(e == "data" for e, _ in frames)

    # F5（预估延迟超阈值转异步）与 F6（会话历史裁剪）均无图级可观测面：
    # 前者缺预估延迟载体（test_edges_contract.py::test_async_switch_is_unreachable_until_carrier_lands），
    # 后者 GraphState 无历史字段、裁剪无从发生（normalize docstring §三已登记）。


class TestGroupG:
    """G 组：审计与开关类（07 §14.2 L2709–L2712）。"""

    def test_g1_audit_pre_fail_closed(self) -> None:
        """G1 审计段 1 写入失败 → `error(INTERNAL)`，fail-closed 不下发数据（N-09）。"""
        chain = make_chain(audit_pre_fail=True)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "INTERNAL"
        assert outcome.status is TaskStatus.FAILED
        # fail-closed：段 1 未落库，且 data 帧绝不下发。
        assert chain.audit.pre == []
        assert all(e != "data" for e, _ in frames)

    def test_g2_audit_supp_fail_non_blocking(self) -> None:
        """G2 审计段 2 写入失败 → 告警不阻断，仍 `complete`（success）。"""
        chain = make_chain(audit_supp_fail=True)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 段 1 正常落库；段 2 失败不阻断（supp 为空但终态仍是 success）。
        assert all(e != "error" for e, _ in frames)
        assert len(chain.audit.pre) == 1
        assert chain.audit.supp == []
        assert any(e == "data" for e, _ in frames)

    # G3（kill switch 全局禁用开关）与 G4（recursion_limit 超限）均缺载体，不做图级桩：
    # G3 触发面需意图节点读全局开关（P0 无），路由面已被
    # `test_edges_contract.py::test_route_after_intent_respects_terminal_set_by_node` 钉住；
    # G4 需构造 ≥25 步循环，正常链无法触达（`GRAPH_RECURSION_LIMIT` 见 `build.py`）。
