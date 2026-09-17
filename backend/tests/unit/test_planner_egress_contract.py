"""载荷穿越**真网关**的联调单测（W3B，N-01：离线，假上游）。

## 为什么必须有这个文件（而不是只测假端口）

前面几个文件用的是**假 `LLMPort`**，它只能证明"我把什么交给了端口"。
但 W3B 的载荷终究要经过 **W3A 的真网关**：那里有三道出站防线、`EgressPayload` 的
严格白名单、prompt 资产的渲染（`string.Template`）。**任何一环不匹配，线上就是 500 或
400**，而假端口一条都发现不了。

本文件把两者串起来，只断言一件事：

    **W3B 构造的载荷，能被真网关原样消化，且线缆上的字节里没有 SQL。**

## 与 `test_llm_gateway.py` 的分工

那边是 W3A 的 DoD③（网关自身的降级链、白名单、成本）。这里**不重复**那些，
只用真网关当"校验器"，证明**跨窗口的接缝**是通的：

| 接缝 | 断言 |
|---|---|
| 载荷键集 ↔ 白名单 | `EgressPayload.from_mapping` 不抛（由网关内部触发） |
| 载荷变量 ↔ 资产占位符 | `render_messages` 不因缺变量抛（网关内部触发） |
| task 名 ↔ 路由表 | `normalize_intent` → flash/不思考；`gen_sql_complex` → pro/思考 |
| `prompt_version` ↔ 资产名 | N-19 必录字段真的有值且与资产一致 |
| `sql_text` ↔ N-17 | 线缆字节里搜不到；且**注入即抛**（负向对照） |
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import FrozenClock
from app.core.contracts import IdentityContext
from app.core.enums import Role
from app.llm import LlmGateway
from app.llm.budget import BudgetGuard, InMemoryCostLedgerSink
from app.llm.client import ChatClient
from app.llm.egress_guard import ALLOWED_WIRE_KEYS
from app.llm.errors import LlmEgressViolation
from app.llm.prompts.loader import load_prompt, render_messages
from app.llm.router import ModelKey
from app.planner.engine import PlannerEngine
from app.planner.payloads import (
    PromptContext,
    gen_sql_payload,
    normalize_intent_payload,
    repair_payload,
)
from app.planner.schemas import Plan
from app.semantics import SemanticBundleRuntime, load_bundle
from tests.unit._llm_fake_upstream import FakeUpstream, json_ok

REAL_BUNDLE = Path(__file__).resolve().parents[3] / "semantic" / "bundle_2026.09.14.1.yaml"

#: 与 W3A 测试同款的真实模型 ID（避免断言落在"未知模型走最贵档"的兜底路径上）。
_MODEL_NAMES = {"fast": "deepseek-flash", "strong": "deepseek-v4-pro"}
_NOW = datetime(2026, 9, 17, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
_QUESTION = "上月华东区销售额"

#: 一个只可能来自 **SQL 子句组合**的标记 —— 用它做"线缆里没有 SQL"的搜索键。
#:
#: ⚠️ 初版用 `"order_paid"` 作标记，**被自己的测试否掉了**：那是语义包里的**物理资产名**，
#: 它**合法地**出现在 `semantic_summary` 里（模型必须知道表名）。用它当标记，
#: 任何实现都会红 —— 那是个假阳性，不是安全发现。
#: ⇒ 标记必须取"只有 `… FROM … GROUP BY …` 这种子句组合才会出现"的片段。
_SQL_PROBE = "sum(amount) FROM order_paid GROUP BY region"


@pytest.fixture(scope="module")
def runtime() -> SemanticBundleRuntime:
    return SemanticBundleRuntime(load_bundle(REAL_BUNDLE))


@pytest.fixture(scope="module")
def clock(runtime: SemanticBundleRuntime) -> FrozenClock:
    return FrozenClock(_now=_NOW, _semantics=runtime.time_semantics())


def _ctx() -> IdentityContext:
    return IdentityContext(
        trace_id="tr", task_id="tk", session_id="ss", tenant_id="t1", user_id="u1", role=Role.ANALYST
    )


def _real_gateway(upstream: FakeUpstream, *, max_retries: int = 0) -> LlmGateway:
    """装配"上游全假、其余全真"的网关（真白名单 + 真 prompt 资产 + 真路由表）。"""
    client = ChatClient(
        base_url="https://upstream.test",
        api_key="sk-test-not-a-real-key",
        model_names=_MODEL_NAMES,
        max_concurrency=50,
        semaphore_flash=8,
        semaphore_pro=2,
        max_retries=max_retries,
        circuit_fails=999,  # 熔断归 W3A 测；这里不让它干扰
        circuit_open_s=30.0,
        transport=upstream.transport,
    )
    return LlmGateway(
        client=client,
        model_names={ModelKey.FAST: _MODEL_NAMES["fast"], ModelKey.STRONG: _MODEL_NAMES["strong"]},
        budget=BudgetGuard(
            global_daily_budget_cny=Decimal("1000"), alert_ratio=0.8, sink=InMemoryCostLedgerSink()
        ),
        now_fn=lambda: _NOW,
    )


def _normalize_intent_response(**over: Any) -> str:
    body = {
        "normalized_question": _QUESTION,
        "time_expression": "上月",
        "unmapped_terms": [],
        "intent": "query",
        "reason_code": None,
        "confidence": 0.9,
        "clarify_hint": None,
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


# ============================================================================
# 一、跨窗口接缝：载荷 → 真网关 → 线缆
# ============================================================================

class TestPayloadSurvivesTheRealGateway:
    @pytest.mark.asyncio
    async def test_planner_payload_passes_all_three_egress_defences(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """一次 `understand` 全程走真网关：白名单、变量渲染、路由表、N-19 全过。"""
        upstream = FakeUpstream(lambda i, req: json_ok(content=_normalize_intent_response()))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)

        outcome = await engine.understand(_ctx(), _QUESTION, history=["上一轮问题"])

        # ① 恰好一个请求（合并档的价值：省掉一次往返）
        assert upstream.sent == 1
        # ② 出站键**只有**登记过的那些
        wire = upstream.calls[0]
        assert set(wire) <= ALLOWED_WIRE_KEYS
        # ③ 路由表真的生效（task 名与 W3A 的路由表对齐）
        assert wire["model"] == "deepseek-flash"
        assert wire["thinking"] == {"type": "disabled"}
        assert wire["response_format"] == {"type": "json_object"}  # 资产/schema 让 json 字样成立
        # ④ N-19：`prompt_version` 是**真资产名**
        assert outcome.meta.prompt_version == "normalize_intent_v1"
        assert wire["messages"][0]["role"] == "system"
        # ⑤ 语义摘要真的进了**稳定前缀**（system 段），问题在 user 段
        assert "## 认证资产" in wire["messages"][0]["content"]
        assert _QUESTION in wire["messages"][1]["content"]
        assert "上一轮问题" in wire["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_no_sql_marker_appears_anywhere_on_the_wire(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """N-17 的线缆级断言：整份请求体里搜不到任何 SQL 片段。"""
        upstream = FakeUpstream(lambda i, req: json_ok(content=_normalize_intent_response()))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)
        await engine.understand(
            _ctx(),
            _QUESTION,
            history=["之前问过", f"SELECT region, {_SQL_PROBE} LIMIT 10", "再问一次"],
        )
        blob = json.dumps(upstream.calls, ensure_ascii=False)
        assert _SQL_PROBE not in blob          # 历史里的整条 SQL 被裁掉
        assert "generated_sql" not in blob      # 也没有 SQL 相关键名
        # 对照：合法内容确实出站了（否则"没搜到"可能只是因为整份载荷是空的）
        assert _QUESTION in blob and "## 认证资产" in blob

    @pytest.mark.asyncio
    async def test_known_limit_a_sql_fragment_without_select_is_not_detected(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """🔴 **已知限制**（把边界钉成断言，而不是假装覆盖完整）。

        `_SQL_STATEMENT_RE` 要求的是**子句组合**（`SELECT…FROM` / `INSERT INTO` / …），
        这个取舍是 W3A 明确写下的："否则会把 `select 前十个 SKU` 这种正常中文问句误杀"。
        代价就是本条：一条**没有 `SELECT` 开头**的 SQL 片段（如 `sum(amount) FROM t GROUP BY c`）
        既不被 `sanitize_history` 丢弃，也不被网关的 `error_digest`/`history_questions`
        扫描拦下，会随历史一起出站。

        为什么仍然这样定：把检测器放宽到"任何 `FROM …` 就算 SQL"，会开始误杀
        "帮我看看 FROM 到 TO 的转化率"这类真实问题，而误杀的代价（正常业务问不了）
        高于本条残留的代价（用户自己粘的半截语句被送出去 —— 那本来就是他自己的话）。
        ⇒ 记为**跨窗口共享的已知边界**（`RELAY.md §给 W3A` 引 W3A 的同一处取舍），
        任何一侧要收紧都必须两侧同时改，否则会出现"一处拦一处放"的不一致。
        """
        fragment = f"帮我改写成 {_SQL_PROBE}"  # 注意：没有 SELECT
        upstream = FakeUpstream(lambda i, req: json_ok(content=_normalize_intent_response()))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)
        await engine.understand(_ctx(), _QUESTION, history=["之前问过", fragment])

        blob = json.dumps(upstream.calls, ensure_ascii=False)
        assert _SQL_PROBE in blob  # ← 这条是**限制本身**，不是期望行为
        assert upstream.sent == 1  # 也没有因此拦下请求（检测层只打标、不拒绝）

    @pytest.mark.asyncio
    async def test_gen_sql_payload_renders_the_plan_without_sql(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`gen_sql` 的计划块走 `constraints` 槽，且计划结构里本就没有 SQL。"""
        sql_body = json.dumps(
            {
                "candidates": [
                    {
                        "sql_text": f"SELECT region, {_SQL_PROBE} LIMIT 10",
                        "params": {},
                        "rationale": "按大区聚合",
                        "confidence": 0.8,
                    }
                ],
                "blocking_issues": [],
            },
            ensure_ascii=False,
        )
        upstream = FakeUpstream(lambda i, req: json_ok(content=sql_body))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)

        plan = Plan.model_validate(
            json.loads(
                json.dumps(
                    {
                        "metrics": [{"name": "gmv", "caliber": "sum(amount)"}],
                        "dimensions": ["region"],
                        "filters": [],
                        "grain": "day",
                        "time_range": {"start": None, "end": None},
                        "order_by": [],
                        "limit": 10,
                        "assets": [{"asset": "v_order_paid", "join_key": None}],
                        "output_columns": ["region", "gmv"],
                        "blocking_issues": [],
                    }
                )
            )
        )
        outcome = await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=plan, candidates=1
        )

        wire = upstream.calls[0]
        assert set(wire) <= ALLOWED_WIRE_KEYS
        assert wire["model"] == "deepseek-flash"
        # 出站的是**计划**（`[已审查的查询计划]` 段），不是 SQL
        assert "[已审查的查询计划]" in wire["messages"][1]["content"]
        assert _SQL_PROBE not in json.dumps(wire, ensure_ascii=False)
        # 而**回来的** SQL 正常进入了产出（出站受限 ≠ 结果受限）
        assert outcome.primary is not None
        assert _SQL_PROBE in outcome.primary.sql_text

    @pytest.mark.asyncio
    async def test_complex_task_hits_the_thinking_route(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """`gen_sql_complex` → strong 档 + **开思考**（PRD §12.2：唯一走思考的档）。"""
        body = json.dumps(
            {
                "candidates": [
                    {"sql_text": "SELECT 1", "params": {}, "rationale": "r", "confidence": 0.8}
                ],
                "blocking_issues": [],
            },
            ensure_ascii=False,
        )
        upstream = FakeUpstream(lambda i, req: json_ok(content=body))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)
        plan = Plan.model_validate(
            json.loads(
                json.dumps(
                    {
                        "metrics": [{"name": "gmv", "caliber": "c"}],
                        "dimensions": [],
                        "filters": [],
                        "grain": None,
                        "time_range": {"start": None, "end": None},
                        "order_by": [],
                        "limit": 5,
                        "assets": [],
                        "output_columns": [],
                        "blocking_issues": [],
                    }
                )
            )
        )
        await engine.sql_for(
            _ctx(), normalized_question=_QUESTION, plan=plan, candidates=1, complex_query=True
        )
        wire = upstream.calls[0]
        assert wire["model"] == "deepseek-v4-pro"
        assert wire["thinking"] == {"type": "enabled"}

    @pytest.mark.asyncio
    async def test_repair_payload_reaches_the_wire_without_the_failed_sql(
        self, runtime: SemanticBundleRuntime, clock: FrozenClock
    ) -> None:
        """节点 16：纠错的线缆上只有**脱敏摘要**，没有失败的那条 SQL。"""
        body = json.dumps(
            {
                "candidates": [
                    {"sql_text": "SELECT 1", "params": {}, "rationale": "r", "confidence": 0.8}
                ],
                "blocking_issues": [],
                "repairable": True,
            },
            ensure_ascii=False,
        )
        upstream = FakeUpstream(lambda i, req: json_ok(content=body))
        engine = PlannerEngine(llm=_real_gateway(upstream), semantics=runtime, clock=clock)
        plan = Plan.model_validate(
            json.loads(
                json.dumps(
                    {
                        "metrics": [{"name": "gmv", "caliber": "c"}],
                        "dimensions": [],
                        "filters": [],
                        "time_range": {"start": None, "end": None},
                        "order_by": [],
                        "limit": 5,
                        "assets": [],
                        "output_columns": [],
                        "blocking_issues": [],
                    }
                )
            )
        )
        await engine.repair_sql(
            _ctx(),
            normalized_question=_QUESTION,
            plan=plan,
            error_digest="- 列 `region_name` 不存在（提示：大区列在 region 资产上）",
        )
        wire = upstream.calls[0]
        assert wire["model"] == "deepseek-flash"
        assert "region_name" in wire["messages"][1]["content"]
        assert _SQL_PROBE not in json.dumps(wire, ensure_ascii=False)


# ============================================================================
# 二、负向对照：白名单在这条接线里**是活的**
# ============================================================================

class TestTheGuardIsLiveOnThisWiring:
    """若网关对这些注入**不抛**，上面所有"线缆里没有 SQL"的断言都是空断言。"""

    @pytest.mark.asyncio
    async def test_injecting_sql_text_into_a_real_payload_is_rejected(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        upstream = FakeUpstream()
        gateway = _real_gateway(upstream)
        prompt_ctx = PromptContext.from_semantics(_ctx(), runtime, user_scope=None)
        payload = normalize_intent_payload(prompt_ctx, question=_QUESTION)
        payload["sql_text"] = "SELECT * FROM order_paid"  # 注入

        with pytest.raises(LlmEgressViolation):
            await gateway.call("normalize_intent", payload, "auto")
        assert upstream.sent == 0  # 一个字节都没出去

    @pytest.mark.asyncio
    async def test_injecting_sql_into_the_error_digest_is_rejected(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """摘要同样受 SQL 特征扫描（§10.5 ⑤）—— 它是要**回灌 prompt** 的。"""
        upstream = FakeUpstream()
        gateway = _real_gateway(upstream)
        prompt_ctx = PromptContext.from_semantics(_ctx(), runtime, user_scope=None)
        payload = repair_payload(
            prompt_ctx,
            question=_QUESTION,
            plan_block="[计划]",
            error_digest="上一次的 SQL 是 SELECT sku_id FROM order_paid GROUP BY 1",
        )
        with pytest.raises(LlmEgressViolation):
            await gateway.call("repair", payload, "auto")
        assert upstream.sent == 0

    @pytest.mark.asyncio
    async def test_a_question_containing_sql_is_still_allowed_out(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """反向对照：**用户自己**在问题里贴 SQL 是合法用法（§10.5 ①），不得被拦。

        没有这条对照，上面两条"注入即抛"就可能被误读成"任何 SQL 都不许出站"，
        进而有人为了"更安全"把 `raw_question` 的扫描也加严 —— 那会拦掉正常业务。
        """
        upstream = FakeUpstream(lambda i, req: json_ok(content=_normalize_intent_response()))
        gateway = _real_gateway(upstream)
        prompt_ctx = PromptContext.from_semantics(_ctx(), runtime, user_scope=None)
        payload = normalize_intent_payload(
            prompt_ctx, question="帮我看看 SELECT count(*) FROM order_paid 这个查法上月的数据对不对"
        )
        response = await gateway.call("normalize_intent", payload, "auto")
        assert upstream.sent == 1
        assert response.prompt_version == "normalize_intent_v1"


# ============================================================================
# 三、render_messages 与 W3B 载荷的**变量契约**
# ============================================================================

class TestPromptVariableContract:
    """载荷的键集与资产占位符必须对得上 —— 错一处，线上就是 `LlmPromptError`。"""

    def test_every_task_payload_renders_against_its_real_asset(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        from app.llm.egress_guard import EgressPayload

        prompt_ctx = PromptContext.from_semantics(_ctx(), runtime, user_scope=None)
        cases = {
            "normalize": normalize_intent_payload(prompt_ctx, question=_QUESTION),
            "normalize_intent": normalize_intent_payload(prompt_ctx, question=_QUESTION),
            "gen_sql": gen_sql_payload(
                prompt_ctx, question=_QUESTION, plan_block="[计划]", few_shots=[("q", "SELECT 1")]
            ),
            "repair": repair_payload(
                prompt_ctx, question=_QUESTION, plan_block="[计划]", error_digest="- 摘要"
            ),
        }
        for task, payload in cases.items():
            asset = load_prompt(task)
            messages, version = render_messages(asset, EgressPayload.from_mapping(payload))
            assert version == f"{task}_v1"
            assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
            # 07 §10.3 硬规则 1：前缀必须**跨请求稳定**（同一 bundle 版本 ⇒ 同前缀）
            assert "trace_id" not in messages[0]["content"]

    def test_asset_only_declares_stable_prefix_variables(
        self, runtime: SemanticBundleRuntime
    ) -> None:
        """W3A 的加载期校验已保证这点；这里复核我们**用的**资产没被改动到破规矩。"""
        from app.llm.prompts.loader import STABLE_PREFIX_VARS

        for task in ("normalize_intent", "gen_sql", "repair"):
            asset = load_prompt(task)
            assert asset.prefix_vars <= STABLE_PREFIX_VARS
