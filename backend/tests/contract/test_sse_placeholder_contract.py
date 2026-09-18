"""§16.2 首字节占位帧（U-66）—— NFR-1.2 的**唯一执行点**在 W4 的 SSE 层。

被测契约（HANDOFF §五-6 + 07 §16.2）：

| 约束 | 断言 |
|---|---|
| 判定阈值 = 1.6s（照 `normalize_intent` 分配，**不是旧值 1.2s**） | 常量 `PLACEHOLDER_AFTER_S == 1.6` |
| 1.6s 内无任何 stage 帧 → 推一次 `stage=intent` 占位 | 慢图（0.3s planner + 0.05s 阈值）出现占位帧 |
| **单次**：占位只发一帧 | 慢图里 stage 帧总数 == 占位数 |
| **不发结论**：载荷只有 `elapsed_ms`（+push 注入的 `stage` 键） | 占位帧 data 键集 ⊆ `{stage, elapsed_ms}` |
| **不回退**：真实 stage 帧照常发，占位不收回 | 快路径（refuse）转录里真帧在前、无占位 |
| 真值已到（已有 stage 帧）→ **不覆盖** | 快路径 stage 帧 == 1（真帧） |
| 图已结束 → 不发占位 | 哨兵收尾的正常流中占位不出现于终态之后 |

同步用例 + `asyncio.run`（不写 `async def test_`，见 `tests/contract/` 顶部惯例说明）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.api.runner import PLACEHOLDER_AFTER_S, RunRequest, SseRunner
from app.api.state_store import RedisStateStore
from app.core.enums import SseEvent
from app.graph.build import build_graph
from tests.contract.test_api_runner_contract import (
    _IDENTITY,
    _DepsHolder,
    _parse,
)
from tests.unit._redis_fake import FakeRedis

# ============================================================================
# 占位帧的三条语义（单次 / 不发结论 / 不回退）
# ============================================================================


def _collect(
    runner: SseRunner, *, question: str = "上个月卖得怎么样"
) -> list[tuple[str, dict[str, Any]]]:
    req = RunRequest(identity=_IDENTITY, question=question)

    async def _run() -> list[bytes]:
        return [frame async for frame in runner.stream(req)]

    return [_parse(frame) for frame in asyncio.run(_run())]


def _placeholder_runner(holder: _DepsHolder, *, placeholder_after_s: float) -> SseRunner:
    """占位阈值压小（0.05s）、心跳与取消轮询拉大 —— 让 tick 分支**只**服务占位判定。"""
    return SseRunner(
        graph=build_graph(),
        store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
        new_deps=holder,
        heartbeat_s=10.0,
        cancel_poll_s=10.0,
        placeholder_after_s=placeholder_after_s,
    )


class TestPlaceholderContract:
    def test_threshold_is_the_u66_value_not_the_old_1_2s(self) -> None:
        """🔴 判定值 = 1.6s（§16.2 订正原文）。改它必须同步 07 §16.2 / HANDOFF §五-6。"""
        assert PLACEHOLDER_AFTER_S == 1.6

    def test_slow_graph_gets_exactly_one_placeholder_before_any_conclusion(self) -> None:
        """慢图：0.3s 的 planner + 0.05s 阈值 ⇒ 恰一帧 `stage=intent` 占位，先于终态。"""
        runner = _placeholder_runner(_DepsHolder("slow"), placeholder_after_s=0.05)
        frames = _collect(runner)

        stage_frames = [f for f in frames if f[0] == SseEvent.STAGE.value]
        assert stage_frames, "1.6s 阈值内图未完成 ⇒ 必须有占位帧（NFR-1.2 唯一执行点）"
        placeholders = [f for f in stage_frames if f[1].get("stage") == "intent"]
        assert placeholders, f"占位必须是 stage=intent：{stage_frames}"
        assert len(placeholders) == 1, f"占位**单次**：{len(placeholders)} 帧"

        first = placeholders[0][1]
        # `terminal` 由 `push` 对所有帧统一注入；结论字段的判据 = 除这三个公共键外无他。
        assert set(first) <= {"stage", "elapsed_ms", "terminal"}, f"占位**不发结论**：{first}"
        assert first["terminal"] is False
        assert isinstance(first["elapsed_ms"], int) and first["elapsed_ms"] >= 0

        # 占位在终态之前（首字节可见变化的意义就是"在结果前"）。
        terminals = [i for i, (_, d) in enumerate(frames) if d["terminal"] is True]
        assert terminals
        assert frames.index(placeholders[0]) < min(terminals)

    def test_fast_path_sends_real_stage_and_no_placeholder(self) -> None:
        """快路径（refuse 早退）：真 `stage=intent` 先到 ⇒ **不覆盖**、无占位、真值只一帧。"""
        runner = _placeholder_runner(_DepsHolder("refuse_intent"), placeholder_after_s=0.05)
        frames = _collect(runner)

        stage_frames = [f for f in frames if f[0] == SseEvent.STAGE.value]
        assert stage_frames, "快路径应有真实的 stage=intent 帧"
        assert len(stage_frames) == 1, f"真值已到，占位不得出现：{stage_frames}"
        assert stage_frames[0][1]["stage"] == "intent"

    def test_placeholder_after_s_defaults_to_contract_value(self) -> None:
        """生产装配不传参 —— 契约值只有 `PLACEHOLDER_AFTER_S` 一份来源。"""
        runner = SseRunner(
            graph=build_graph(),
            store=RedisStateStore(FakeRedis()),  # type: ignore[arg-type]
            new_deps=_DepsHolder("refuse_intent"),
        )
        assert runner._placeholder_after_s == PLACEHOLDER_AFTER_S
