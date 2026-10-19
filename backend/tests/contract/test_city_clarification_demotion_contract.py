"""W60：明确店铺城市题面经 normalize 后必须进入执行链。"""
from __future__ import annotations

from app.graph.context import GraphDeps
from app.planner.schemas import IntentKind
from tests.contract._fullchain_deps import FullChainPlanner, FullChainSemantics, ScriptRetrieval, _green_understand
from tests.contract.test_api_runner_contract import _IDENTITY


class _CityPlanner(FullChainPlanner):
    """模拟 live 匣带的误澄清；只替换 understand 的返回。"""

    async def understand(self, identity, question, history=()):
        from dataclasses import replace
        return replace(
            _green_understand(question),
            intent=IntentKind.CLARIFY,
            reason_code="ambiguous_dimension_city",
            clarify_hint="城市存在歧义",
        )


def test_explicit_city_question_reaches_plan_not_clarify():
    deps = GraphDeps(
        llm=object(),
        planner=_CityPlanner(),
        retrieval=ScriptRetrieval(),
        semantics=FullChainSemantics(),
        binding=None,
        executor=None,
        mask=None,
        audit=None,
        clock=object(),
    )
    state = {
        "raw_question": "各城市的店铺数分别是多少？",
        "tenant_id": _IDENTITY.tenant_id,
        "user_id": _IDENTITY.user_id,
        "role": _IDENTITY.role,
        "trace_id": "tr-city",
        "task_id": "tk-city",
        "session_id": "se-city",
        "history_questions": (),
        "options": {},
        "scope_claims": (),
        "shop_ids": (),
    }
    # FullChainSemantics 没有 semantic_summary/blacklist；本契约只测 normalize 路由。
    deps = type(deps)(
        llm=deps.llm, planner=deps.planner, retrieval=deps.retrieval, semantics=None,
        binding=None, executor=None, mask=None, audit=None, clock=deps.clock,
    )
    # 只验证 normalize 产出，不执行完整依赖图。
    import asyncio
    from app.graph.context import RunContext, set_run_context, clear_run_context

    async def _call():
        token = set_run_context(RunContext(deps))
        try:
            from app.graph.nodes.normalize import normalize
            return await normalize(state)
        finally:
            clear_run_context(token)

    # 该契约只要求 normalize 的意图；路由由 test_edges_contract 覆盖。
    got = asyncio.run(_call())
    assert got["intent"] == IntentKind.EXECUTABLE.value
    assert got["intent_detail"]["reason_code"] == "shop_city_unambiguous"
