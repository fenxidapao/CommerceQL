"""P0-A-4：上游失败必须**可判根因**（`terminal.error_detail`）—— 离线契约测试。

**为什么值得钉住**（实测，不是推测）：第 41–43 轮里 `LLM_UPSTREAM_ERROR` 这个码
把两种完全不同的事压成一个 ——「上游服务端过载」与「本地匣带把响应解码搞坏」。
`_shared.llm_error_update` 当时只取 `default_code`、**丢掉 `exc.detail`**，
于是产物里唯一的线索是 `code`，排查只能靠猜 —— **实测连猜三轮都猜错**。
本文件钉三件事：① 有 detail 就要落进终态；② 无 detail 时**不编空键**；
③ `LlmRefused` 是产品结论，**不得**被塞进 error 通道。

⚠️ 装配：`llm_error_update` 会经 `terminal_update()` → `metering_update()` 读 `RunContext`
⇒ 必须先 `set_run_context(...)`（不设时节点 fail-fast 抛 `RuntimeError`，那是刻意的）。
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.api import sse
from app.core.enums import ErrorCode, Outcome
from app.graph.context import clear_run_context, set_run_context
from app.graph.events import EventRecorder
from app.graph.nodes._shared import llm_error_update
from app.llm.errors import LlmRefused, LlmTimeout, LlmUpstreamError
from tests.contract.test_api_runner_contract import _make_deps

_STATE: dict[str, Any] = {"terminal": None}


@pytest.fixture
def ctx() -> Iterator[None]:
    """带 recorder 的 `RunContext`（与 `tests/contract/test_graph_timeout_contract.py:60-65` 同形）。"""
    context = _make_ctx()
    token = set_run_context(context)
    try:
        yield None
    finally:
        clear_run_context(token)


def _make_ctx():
    from app.graph.context import RunContext

    return RunContext(_make_deps("refuse_intent"), recorder=EventRecorder(encoder=sse.encode))


def test_upstream_error_detail_is_kept_in_terminal(ctx: None) -> None:
    """★ 正例：`LlmUpstreamError.detail` **必须**出现在 `terminal["error_detail"]` 里。

    样本就是第 43 轮 spy 逐字捕到的那两个键（`app/llm/client.py:346-350` 的抛点形态）。
    """
    exc = LlmUpstreamError("上游连接失败", detail={"model": "deepseek-flash", "kind": "DecodingError"})
    update = llm_error_update(dict(_STATE), exc, stage="normalize")
    terminal = update["terminal"]
    assert terminal["event"] == "error"
    assert terminal["code"] == ErrorCode.LLM_UPSTREAM_ERROR.value
    assert update["outcome"] == Outcome.FAILED
    assert terminal["error_detail"] == {"model": "deepseek-flash", "kind": "DecodingError"}, (
        "detail 被丢弃 ⇒ 产物里无法区分'上游抖/超时'与'响应解码失败'（正是第 41–43 轮的根因）"
    )


def test_timeout_detail_is_kept(ctx: None) -> None:
    """正例：超时也要留下可判根因的量（`remaining_s` 是判定"是不是 deadline 耗尽"的唯一依据）。"""
    exc = LlmTimeout("上游调用超时", detail={"model": "deepseek-v4.1-flash", "remaining_s": 0.0})
    terminal = llm_error_update(dict(_STATE), exc, stage="plan")["terminal"]
    assert terminal["error_detail"] == {"model": "deepseek-v4.1-flash", "remaining_s": 0.0}


def test_no_detail_means_no_key(ctx: None) -> None:
    """反例：**不编空键** —— `detail` 为空时不得产出 `error_detail: {}`。

    否则"本次终态没有这项信息"与"这次真的没有根因"会在产物里长得一样，
    下一个人会把空字典当成"查过了、确实没有"。
    """
    exc = LlmUpstreamError("上游连接失败")
    terminal = llm_error_update(dict(_STATE), exc, stage="gen_sql")["terminal"]
    assert "error_detail" not in terminal, f"空 detail 不该落键：{terminal}"


def test_detail_is_copied_not_aliased(ctx: None) -> None:
    """反例：终态里的 detail 必须是**副本** —— 否则调用方事后改那个 dict 会改写历史终态。"""
    payload = {"model": "m", "kind": "K"}
    exc = LlmUpstreamError("上游连接失败", detail=payload)
    terminal = llm_error_update(dict(_STATE), exc, stage="normalize")["terminal"]
    payload["kind"] = "MUTATED"
    assert terminal["error_detail"]["kind"] == "K", "终态与异常对象共享了同一个 dict"


def test_llm_refused_stays_a_product_verdict(ctx: None) -> None:
    """反例：`LlmRefused` 是**产品结论**（模板层无命中）⇒ 走 refuse，**不得**进 error 通道、
    更不得被塞 `error_detail`（它的 `default_code is None`，走兜底会被折成 500 INTERNAL）。
    """
    exc = LlmRefused("模型拒绝：模板层无命中")
    update = llm_error_update(dict(_STATE), exc, stage="normalize")
    terminal = update["terminal"]
    assert terminal["event"] == "refuse"
    assert update["outcome"] == Outcome.REFUSE
    assert "code" not in terminal and "error_detail" not in terminal


def test_non_mapping_detail_is_ignored(ctx: None) -> None:
    """反例：`detail` 被外力改成非映射时**静默不带**（不崩、也不把标量塞进 jsonb 列）。

    ⚠️ 样本必须**事后改属性**：`LlmError.__init__` 自己就做 `dict(detail or {})`
    ⇒ 构造期传标量会先在那里抛，测不到本函数的守卫。
    """
    exc = LlmUpstreamError("上游连接失败")
    exc.detail = "not-a-mapping"  # type: ignore[assignment]
    terminal = llm_error_update(dict(_STATE), exc, stage="normalize")["terminal"]
    assert "error_detail" not in terminal
    assert terminal["code"] == ErrorCode.LLM_UPSTREAM_ERROR.value
