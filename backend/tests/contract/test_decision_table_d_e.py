"""07 §14.2 决策表 **D 组 / E 组**（闸门与执行跳）—— 全链图级测试。

夹具：`_fullchain_deps`（理由与纪律见其模块 docstring）。
断言模板沿 A 组（`test_decision_table_contract.py`）：`run_chain` 收帧 →
`terminal_frames` 过滤 `terminal is True` → 恰 1 终态 + `outcome.status` + 审计落行。

⚠️ 与 07 字面的差异（按实现断言，登记 RELAY §九 U-88 起）：

1. **D3 走到 `error(GATE_POLICY_REJECTED)` 而非字面的 `refuse(pii_blocked)`**：
   `run_gate2` 的敏感列复核走 `_reject("G2-DENY", ...)`（无 `refuse_reason`）——
   `refuse_reason` 只给数据域越界（out_of_scope）那条。见 `policy_gate.py` docstring。
2. **D7 的 `detail.limit_type="memory"` 在 P0 无载体**：`ExecError` 未带 limit_type，
   `map_code` 的 `detail` 只给 ANALYST+（本组身份即 ANALYST，但 detail 内容为空）。
   判据码 `EXEC_RESOURCE_EXCEEDED` 与 07 一致，故只断言码。
3. **E7 / E8 不做图级新断言**：E7（客户端取消/断连）是**流层**行为（`runner.stream`
   的取消语义，见 `test_api_runner_contract.py::TestCancellation`）；E8 是 **HTTP 409**
   请求级（`TASK_NOT_CANCELLABLE`，见 `test_errors_contract.py`）。二者**不是**图内
   节点跳，跑图证明不了，故引用既有测试不留图级桩。
"""

from __future__ import annotations

from typing import Any

from app.core.enums import TaskStatus
from tests.contract._fullchain_deps import (
    GREEN_RESULT,
    GREEN_SQL,
    base_allowlist,
    exec_failure,
    make_chain,
    run_chain,
    syntax_failure,
    terminal_frames,
)

# 常用断言集：P0 边界 —— presenter 缺席 ⇒ 成功链路恒伴随一条 present_failed 降级。
_P0_PRESENT_ONLY: list[tuple[str, str]] = [("present_failed", "table_only")]

#: 触发 gate3 三态的最小 EXPLAIN 载荷（Total Cost 三档：pass < 5e4 < warn < 5e5 < reject）。
_OVER_REJECT = {"Plan": {"Total Cost": 1_000_000, "Plan Rows": 10, "Node Type": "Seq Scan"}}
_WARN_BAND = {"Plan": {"Total Cost": 100_000, "Plan Rows": 10, "Node Type": "Seq Scan"}}


def _reasons(frames: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    """全部 degraded 帧的 `(reason, action_taken)`（按发生序）。"""
    return [(d["reason"], d["action_taken"]) for e, d in frames if e == "degraded"]


def _stages(frames: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """全部 `stage` 帧的 `stage` 值（按发生序）。"""
    # `stage` 帧必有 `stage` 键（`encode` 校验，缺失即抛错）⇒ 直接索引而非 `.get`。
    return [str(d["stage"]) for e, d in frames if e == "stage"]


class TestGroupD:
    """D 组：三道闸门（07 §14.2 L2661–L2667）。"""

    def test_d1_ast_reject_multi_statement(self) -> None:
        """D1 闸门一 AST 拒绝（R02 多语句）→ `error(GATE_AST_REJECTED)`。"""
        chain = make_chain(sql="SELECT 1; SELECT 2")
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "GATE_AST_REJECTED"
        assert outcome.status is TaskStatus.FAILED
        # 结构性拒绝不进 repair、不给数据（07 §5.4 明文）。
        assert all(e != "data" for e, _ in frames)
        assert chain.planner.repair_calls == 0
        assert chain.audit.pre[0]["outcome"] == "failed"

    def test_d2_policy_version_mismatch(self) -> None:
        """D2 闸门二 策略版本不一致 → `error(GATE_POLICY_REJECTED)`。"""
        chain = make_chain(
            allowlists=({**base_allowlist(), "bundle_version": "stale-v"},),
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "GATE_POLICY_REJECTED"
        assert outcome.status is TaskStatus.FAILED
        assert all(e != "data" for e, _ in frames)

    def test_d3_policy_sensitive_column(self) -> None:
        """D3 闸门二 命中敏感列（二次复核）→ `error(GATE_POLICY_REJECTED)`。

        ⚠️ 差异登记：07 字面 `refuse(pii_blocked)`，实现走 `_reject("G2-DENY")`
        （`run_gate2` 的 `refuse_reason` 只给越界域那条）⇒ error（模块 docstring 差异 1）。
        两跳 allowlist：gate1 干净（deny 空，让 R07 放行）、gate2 带 deny 命中复核。
        """
        chain = make_chain(
            allowlists=(
                base_allowlist(),
                {**base_allowlist(), "deny_columns": ["order_paid.buyer_phone"]},
            ),
            sql=(  # 引用 buyer_phone（logical=order_paid），gate2 复核命中 deny。
                "SELECT order_id, buyer_phone FROM fact_orders "
                "WHERE region_code = 440000 LIMIT 100"
            ),
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "GATE_POLICY_REJECTED"
        assert outcome.status is TaskStatus.FAILED
        assert all(e != "data" for e, _ in frames)

    def test_d4_cost_reject(self) -> None:
        """D4 闸门三 成本/规模拒绝 → `error(COST_TOO_HIGH)`（预执行，未跑）。"""
        chain = make_chain(explain_payload=_OVER_REJECT)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        # ⚠️ 不断言 `message`：`map_code` 的 `message` 是入参，runner `_extras` 未传
        # （文案归 06 UI/UX），当前为空——这是文案接线缺口，非码级判据。
        assert terminals[0][1]["code"] == "COST_TOO_HIGH"
        assert outcome.status is TaskStatus.FAILED
        # 预执行拒绝：没有跑到 execute（fetch 未发生）、不给数据。
        assert chain.executor.fetch_calls == 0
        assert all(e != "data" for e, _ in frames)

    def test_d5_cost_warn_still_executes(self) -> None:
        """D5 闸门三 `warn` → **仍执行**（无错误事件），且不报告为通过。

        判据：`decision=WARN` 非 `PASS` ⇒ `events._all_gates_clean_pass` False ⇒
        不发 `stage=gate_passed`，但仍发 `stage=executing`（07 §14.2 D5）。
        """
        chain = make_chain(explain_payload=_WARN_BAND)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        assert all(e != "error" for e, _ in frames)
        assert any(e == "data" for e, _ in frames)
        # warn 不得报告为通过，但仍执行。
        assert "gate_passed" not in _stages(frames)
        assert "executing" in _stages(frames)
        assert chain.executor.fetch_calls == 1

    def test_d6_cost_skipped_still_executes(self) -> None:
        """D6 闸门三 被跳过（SQLite 沙箱无 EXPLAIN JSON）→ 仍执行、不报告为通过。"""
        chain = make_chain(explain_payload=None)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        assert all(e != "error" for e, _ in frames)
        assert any(e == "data" for e, _ in frames)
        assert "gate_passed" not in _stages(frames)
        assert "executing" in _stages(frames)
        assert chain.executor.fetch_calls == 1

    def test_d7_exec_resource_exceeded(self) -> None:
        """D7 执行期资源上限超限 → `error(EXEC_RESOURCE_EXCEEDED)`（已开始执行）。"""
        chain = make_chain(fetches=(exec_failure("resource_exceeded"),))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "EXEC_RESOURCE_EXCEEDED"
        assert outcome.status is TaskStatus.FAILED
        # 资源超限不可修（不进 repair）—— 与 timeout 同判据。
        assert chain.executor.fetch_calls == 1
        assert chain.planner.repair_calls == 0
        assert all(e != "data" for e, _ in frames)


class TestGroupE:
    """E 组：执行类（07 §14.2 L2673–L2680）。"""

    def test_e1_repairable_error_goes_to_repair(self) -> None:
        """E1 执行失败且可修且 `repair_round<2` → 无事件进 repair，修复后成功。"""
        chain = make_chain(
            fetches=(syntax_failure(), GREEN_RESULT),
            repair_sqls=(GREEN_SQL,),
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 进 repair 是内部重试（§14.2 E1 明文"无事件"）：无 error 帧。
        assert all(e != "error" for e, _ in frames)
        assert _reasons(frames) == _P0_PRESENT_ONLY
        assert chain.executor.fetch_calls == 2
        assert chain.planner.repair_calls == 1
        assert any(e == "data" for e, _ in frames)

    def test_e2_repair_exhausted(self) -> None:
        """E2 纠错 2 轮仍失败 → `error(SQL_SYNTAX_ERROR)`（含"已尝试 N 次"语义）。"""
        chain = make_chain(
            fetches=(syntax_failure(), syntax_failure(), syntax_failure()),
            repair_sqls=(GREEN_SQL, GREEN_SQL),
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "SQL_SYNTAX_ERROR"
        assert outcome.status is TaskStatus.FAILED
        # 三次执行（首跳 + 两次修复后）+ 两次 repair，然后超限收口。
        assert chain.executor.fetch_calls == 3
        assert chain.planner.repair_calls == 2
        assert all(e != "data" for e, _ in frames)

    def test_e3_exec_timeout(self) -> None:
        """E3 执行超时（57014）→ `error(EXEC_TIMEOUT)`（不可修，不进 repair）。"""
        chain = make_chain(fetches=(exec_failure("timeout"),))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "EXEC_TIMEOUT"
        assert outcome.status is TaskStatus.FAILED
        assert chain.executor.fetch_calls == 1
        assert chain.planner.repair_calls == 0

    def test_e4_db_unavailable(self) -> None:
        """E4 DB 不可达 → `error(DB_UNAVAILABLE)`。"""
        chain = make_chain(fetches=(exec_failure("db_unavailable"),))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "DB_UNAVAILABLE"
        assert outcome.status is TaskStatus.FAILED
        assert chain.planner.repair_calls == 0

    def test_e5_permission_refuses_out_of_scope(self) -> None:
        """E5 库权限不足（42501，L3 兜底命中）→ `refuse(out_of_scope)`（产品结论）。"""
        chain = make_chain(fetches=(exec_failure("permission"),))
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "refuse"
        assert terminals[0][1]["reason"] == "out_of_scope"
        assert outcome.status is TaskStatus.REFUSE
        # 产品级拒答走 refuse，不是 error（07 §7.6.1）。
        assert all(e != "error" for e, _ in frames)
        assert all(e != "data" for e, _ in frames)
        assert chain.planner.repair_calls == 0
        assert chain.audit.pre[0]["outcome"] == "refuse"

    def test_e6_mask_fail_closed(self) -> None:
        """E6 脱敏失败 → `error(INTERNAL)`，fail-closed **不下发任何行**。"""
        chain = make_chain(mask_fail=True)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "error"
        assert terminals[0][1]["code"] == "INTERNAL"
        assert outcome.status is TaskStatus.FAILED
        # fail-closed：终态 error 且绝无 data 帧（N-05 / §14.3 约束 6）。
        assert all(e != "data" for e, _ in frames)
        assert chain.audit.pre[0]["outcome"] == "failed"

    # E7（客户端取消/断连）与 E8（cancel 但任务已结束）不做图级桩：
    # 前者是 `runner.stream` 的流层取消语义（test_api_runner_contract.py::TestCancellation），
    # 后者是 HTTP 409 `TASK_NOT_CANCELLABLE`（test_errors_contract.py）——
    # 两者都不在图内节点跳的可观测面上（模块 docstring 差异 3）。
