"""07 §14.2 决策表 **B 组 / C 组**（链接-绑定-计划-SQL 生成跳）—— 全链图级测试。

夹具：`_fullchain_deps`（自建全链 deps 的理由与设计纪律见其模块 docstring）。
断言模板沿 A 组（`test_decision_table_contract.py`）：`run_chain` 收帧 →
`terminal_frames` 过滤 `terminal is True` → 恰 1 终态 + `outcome.status` + 审计落行。

⚠️ 与 07 字面的**三处差异**（按实现断言，登记 RELAY §九 U-88 起）：

1. B2/B3 的 07 字面 `reason=ambiguity`，实现字面量是 `ambiguous_field_binding`
   （附录 A §A.1.4 示例；`clarify_out.py` docstring §二 已登记）；
2. **C1+C2 在实现里是同一条路径**（plan 失败 = 一次 `degraded` + 一次 `refuse`，
   没有独立的"模板未命中"跳）⇒ 合并为一个用例；
3. B6 的 `disclosure` **不进 SSE 帧**（帧只带 `reason/action_taken`，C-08），
   在 `audit.supp[0]["degradations"]` 的 `detail.binding_disclosure` 可见
   （`context.report_degraded` 的既有口径）⇒ 断言落审计侧。
"""

from __future__ import annotations

import json
from typing import Any

from app.binding import MAX_CLARIFY_OPTIONS
from app.core.contracts import CandidateRef
from app.core.enums import (
    ActionTaken,
    BindingState,
    DegradedReason,
    RetrievalMode,
    TaskStatus,
)
from app.planner.errors import PlanUnavailable
from tests.contract._fullchain_deps import (
    BUNDLE_VERSION,
    GREEN_RESULT,
    GREEN_SQL,
    make_chain,
    run_chain,
    syntax_failure,
    terminal_frames,
)

# 常用断言集：P0 边界 —— presenter 缺席 ⇒ 成功链路**恒**伴随一条 present_failed 降级。
_P0_PRESENT_ONLY: list[tuple[str, str]] = [("present_failed", "table_only")]


def _reasons(frames: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    """全部 degraded 帧的 `(reason, action_taken)`（按发生序）。"""
    return [(d["reason"], d["action_taken"]) for e, d in frames if e == "degraded"]


class TestFullchainGreenBaseline:
    """全链绿灯基线（B–G 组的"对照零点"）：一次可修因素都没有的完整成功链。"""

    def test_green_baseline(self) -> None:
        chain = make_chain()
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED

        # P0 边界：presenter 缺席 ⇒ 恰 1 条 degraded（present_failed / table_only）。
        assert _reasons(frames) == _P0_PRESENT_ONLY

        # 表格直出：data 帧在，chart/insight 帧无（present 未产出）。
        assert any(e == "data" for e, _ in frames)
        assert all(e not in ("chart", "insight") for e, _ in frames)

        # 两段审计都落行；计数器钉住"全链单趟"（无 repair 重试）。
        assert len(chain.audit.pre) == 1
        assert chain.audit.pre[0]["outcome"] == "success"
        assert len(chain.audit.supp) == 1
        assert chain.executor.fetch_calls == 1
        assert chain.planner.repair_calls == 0


class TestGroupB:
    """B 组：链接与绑定跳（07 §14.2 L2642–L2653）。"""

    def test_b1_empty_recall_refuses(self) -> None:
        """B1 召回为空 → `refuse(no_data_asset)`，无降级、无 data 帧。"""
        chain = make_chain(retrieval_candidates=())
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "refuse"
        assert terminals[0][1]["reason"] == "no_data_asset"
        assert outcome.status is TaskStatus.REFUSE
        assert all(e != "data" for e, _ in frames)
        assert _reasons(frames) == []
        assert len(chain.audit.pre) == 1
        assert chain.audit.pre[0]["outcome"] == "refuse"
        # 文案回归钉：`message`/`suggestions` 经 `_extras` 侧信道到帧（T9② 修复的
        # 静默缺陷 —— LangGraph updates 过滤增量顶层键，出口节点直写永远到不了帧）。
        assert terminals[0][1]["message"]
        assert terminals[0][1]["suggestions"]

    def test_b2_binding_ambiguity_clarifies(self) -> None:
        """B2 同粒度不同语义歧义（L4）→ `clarify` + `options[]`。

        ⚠️ 07 写 `reason=ambiguity`，实现字面量 `ambiguous_field_binding`（模块 docstring 差异 1）。
        """
        chain = make_chain(
            binding_state=BindingState.AMBIGUOUS,
            binding_options=(
                CandidateRef(asset_id="order_paid.buyer_phone", score=0.8),
                CandidateRef(asset_id="order_paid.buyer_name", score=0.7),
            ),
            binding_clarify_prompt="您问的「买家信息」指哪个字段？",
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "clarify"
        assert outcome.status is TaskStatus.CLARIFY

        # 附录 A §A.1.4：clarify 载荷**顶层平铺**（clarify_id/question/options/reason）。
        clarify = terminals[0][1]
        assert clarify["reason"] == "ambiguous_field_binding"
        assert clarify["question"] == "您问的「买家信息」指哪个字段？"
        assert [opt["value"] for opt in clarify["options"]] == [
            "order_paid.buyer_phone",
            "order_paid.buyer_name",
        ]
        # 选项形状：三者同值（label 无来源，`clarify_out` 已登记）。
        assert all(
            opt["label"] == opt["value"] == opt["asset"] for opt in clarify["options"]
        )
        assert all(e != "data" for e, _ in frames)
        assert len(chain.audit.pre) == 1
        assert chain.audit.pre[0]["outcome"] == "clarify"

    def test_b3_too_many_candidates_clarifies_capped(self) -> None:
        """B3 精筛后候选仍过多 → 同 B2 的 `clarify`，选项截断到 `MAX_CLARIFY_OPTIONS`(=4)。"""
        six = tuple(
            CandidateRef(asset_id=f"order_paid.col_{i}", score=0.9 - i * 0.05)
            for i in range(6)
        )
        chain = make_chain(
            binding_state=BindingState.AMBIGUOUS,
            binding_options=six,
            binding_clarify_prompt="候选字段较多，请选择：",
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "clarify"
        assert outcome.status is TaskStatus.CLARIFY

        clarify = terminals[0][1]
        assert clarify["reason"] == "ambiguous_field_binding"
        assert len(clarify["options"]) == MAX_CLARIFY_OPTIONS
        # 截断保序（前 4 个，不是采样）。
        assert [opt["value"] for opt in clarify["options"]] == [
            f"order_paid.col_{i}" for i in range(MAX_CLARIFY_OPTIONS)
        ]

    def test_b4_unresolved_refuses(self) -> None:
        """B4 unresolved → `refuse(no_data_asset)`。"""
        chain = make_chain(binding_state=BindingState.UNRESOLVED)
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "refuse"
        assert terminals[0][1]["reason"] == "no_data_asset"
        assert outcome.status is TaskStatus.REFUSE
        assert all(e != "data" for e, _ in frames)
        assert _reasons(frames) == []
        assert chain.audit.pre[0]["outcome"] == "refuse"

    def test_b5_embedding_down_sparse_only_still_succeeds(self) -> None:
        """B5 稠密检索不可用 → `degraded(embedding_unavailable/sparse_only)`，最终仍 success。"""
        chain = make_chain(
            retrieval_mode=RetrievalMode.SPARSE_ONLY,
            retrieval_degraded_reason=DegradedReason.EMBEDDING_UNAVAILABLE,
            retrieval_action_taken=ActionTaken.SPARSE_ONLY,
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 两条降级按发生序：链接跳的 embedding + P0 恒在的 present。
        assert _reasons(frames) == [
            ("embedding_unavailable", "sparse_only"),
            ("present_failed", "table_only"),
        ]
        assert any(e == "data" for e, _ in frames)

    def test_b6_resolved_default_succeeds_with_disclosure(self) -> None:
        """B6 resolved_default → 无异常事件、success、meta 齐全、口径标注落审计。

        ⚠️ `disclosure` 不进 SSE 帧（模块 docstring 差异 3）⇒ 断言 `audit.supp`。
        """
        chain = make_chain(
            binding_state=BindingState.RESOLVED_DEFAULT,
            binding_disclosure="已按「实付金额」口径计算",
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 无异常事件：唯一降级是 P0 恒在的 present_failed。
        assert _reasons(frames) == _P0_PRESENT_ONLY

        # meta 帧（C-05 七键；`terminal` 键由 `sse.encode` 对**每帧**恒注入 ——
        # meta 不是终止事件，终态帧是紧随其后的 `complete`，此处恒为 False）。
        metas = [d for e, d in frames if e == "meta"]
        assert len(metas) == 1
        assert metas[0]["terminal"] is False
        assert set(metas[0]) == {
            "bundle_version",
            "cost_cny",
            "tokens",
            "latency_ms",
            "trace_id",
            "scope",
            "retrieval_mode",
            "terminal",
        }
        assert metas[0]["bundle_version"] == BUNDLE_VERSION

        # 口径标注（07 表 B6"结论必须标注已按 X 口径"）：在 supp 的降级 detail 里。
        assert len(chain.audit.supp) == 1
        notes = [json.loads(item) for item in chain.audit.supp[0]["degradations"]]
        present = next(n for n in notes if n["reason"] == "present_failed")
        assert present["detail"]["binding_disclosure"] == "已按「实付金额」口径计算"


class TestGroupC:
    """C 组：计划与 SQL 生成跳（07 §14.2 L2654–L2662）。"""

    def test_c1_c2_plan_json_exhausted_refuses_with_degraded(self) -> None:
        """C1+C2 plan JSON 修复 1 次后仍失败（模板层无命中）→ 一次 `degraded` + `refuse`。

        ⚠️ 实现把 C1/C2 合并为同一条路径（模块 docstring 差异 2）：
        `plan` 失败 = `degraded(plan_generation_failed/template_only)` + `refuse(no_data_asset)`。
        """
        chain = make_chain(
            plan_error=PlanUnavailable("plan JSON 修复 1 次后仍失败", attempts=2)
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "refuse"
        assert terminals[0][1]["reason"] == "no_data_asset"
        assert outcome.status is TaskStatus.REFUSE
        assert _reasons(frames) == [("plan_generation_failed", "template_only")]
        assert all(e != "data" for e, _ in frames)
        assert chain.audit.pre[0]["outcome"] == "refuse"

    def test_c3_first_syntax_error_repairs_without_events(self) -> None:
        """C3 SQL 生成后执行期语法错（首次）→ 无事件进 repair，修复后成功。"""
        chain = make_chain(
            fetches=(syntax_failure(), GREEN_RESULT),
            repair_sqls=(GREEN_SQL,),
        )
        frames, outcome = run_chain(chain)

        terminals = terminal_frames(frames)
        assert len(terminals) == 1
        assert terminals[0][0] == "complete"
        assert outcome.status is TaskStatus.SUCCEEDED
        # 无异常事件：error 帧无；唯一降级是 P0 恒在的 present_failed。
        assert all(e != "error" for e, _ in frames)
        assert _reasons(frames) == _P0_PRESENT_ONLY
        # 修复链路的计数器：fetch 2 次（首败 + 修复后）、repair 1 次。
        assert chain.executor.fetch_calls == 2
        assert chain.planner.repair_calls == 1
        assert any(e == "data" for e, _ in frames)
