"""T2 prompt 资产单测 —— **DoD④ 前缀缓存布局** 与 **DoD⑤ `prompt_version` 必录**。

07 §10.3 的四条硬规则在这里被机器化：

| 规则 | 本文件的断言 |
|---|---|
| 1 稳定内容必须前置 | `TestPrefixStability`：同一 payload 不同问题 → 前缀哈希**必须相同** |
| 2 前缀禁请求级变量 | `TestPrefixRules`：注入 `$trace_id` → 加载**失败**（不是渲染时才发现） |
| 3 前缀禁会话历史 | 同上（`history_block` 不在 `STABLE_PREFIX_VARS`），并断言前缀文本不含历史问题 |
| 4 命中率埋点 | 数据源是上游 `usage.prompt_cache_hit_tokens` → 见 `test_llm_client.py` 与 `test_llm_budget.py` |

另有一条**容易被忘掉但代价很高**的断言：每份资产的 system 段必须出现 "json" 字样 ——
否则 `response_format=json_object` 会被上游 400（实测）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.egress_guard import EgressPayload
from app.llm.errors import LlmPromptError
from app.llm.prompts import (
    FORBIDDEN_PREFIX_VARS,
    PROMPTS_DIR,
    STABLE_PREFIX_VARS,
    available_versions,
    load_prompt,
    prefix_hash,
    render_messages,
)
from app.llm.prompts import loader as loader_mod
from app.llm.router import LlmTask

ALL_TASKS = list(LlmTask)


def _payload(**over: object) -> EgressPayload:
    base: dict[str, object] = {
        "raw_question": "统计华东区上月销售额前十的 SKU",
        "semantic_summary": "表 fact_sales(sku_id, order_id, amount, dt)；指标：销售额=sum(amount)",
        "dialect_note": "PostgreSQL 16 + pgvector。金额单位：元。",
        "output_schema": '{"type":"object","properties":{"sql":{"type":"string"}}}',
        "bundle_version": "2026.09.14.1",
    }
    base.update(over)
    return EgressPayload(**base)  # type: ignore[arg-type]


class TestAssetsExist:
    def test_every_task_has_an_asset(self) -> None:
        """路由表的每个 task 都必须有资产 —— 否则运行到那一步才 `LlmPromptError`。"""
        for task in ALL_TASKS:
            asset = load_prompt(task.value)
            assert asset.version.startswith(f"{task.value}_v"), asset.version

    def test_asset_files_follow_the_07_naming_rule(self) -> None:
        """07 §10.3 的 `{name}_v{n}.txt` —— 文件名就是版本号，不能再有第二处版本常量。"""
        files = {p.name for p in PROMPTS_DIR.glob("*.txt")}
        for task in ALL_TASKS:
            assert f"{task.value}_v1.txt" in files

    def test_version_equals_file_stem(self) -> None:
        assert load_prompt("gen_sql").version == "gen_sql_v1"

    def test_content_hash_is_recorded(self) -> None:
        """07 §10.3："版本号与**文件内容哈希**一并记录"。

        它的作用是定位"改了文件却没升版本号"：版本没变而哈希变了 ⇒ 有人漏了升版。
        """
        assert len(load_prompt("plan").content_hash) == 16

    def test_available_versions_lists_disk_truth(self) -> None:
        assert available_versions("plan") == [1]
        assert available_versions("nope") == []

    def test_missing_asset_fails_fast(self) -> None:
        with pytest.raises(LlmPromptError) as ei:
            load_prompt("does_not_exist")
        assert "找不到" in ei.value.message

    def test_missing_version_fails_fast(self) -> None:
        with pytest.raises(LlmPromptError):
            load_prompt("plan", version=99)


class TestPrefixRules:
    """07 §10.3 规则 1 / 2 / 3。"""

    def test_prefix_vars_are_all_declared_stable(self) -> None:
        for task in ALL_TASKS:
            asset = load_prompt(task.value)
            assert asset.prefix_vars <= STABLE_PREFIX_VARS, task.value
            assert asset.prefix_vars & FORBIDDEN_PREFIX_VARS == set(), task.value

    def test_history_is_not_a_prefix_variable(self) -> None:
        """规则 3：会话历史**必须**落在变化后缀，否则前缀随会话变化、缓存全失效。"""
        assert "history_block" not in STABLE_PREFIX_VARS
        assert "history_block" in FORBIDDEN_PREFIX_VARS
        asset = load_prompt("normalize")
        assert "history_block" not in asset.prefix_vars

    def test_injecting_a_request_level_var_into_system_makes_loading_FAIL(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """规则 2 的**注入对照**：往 system 段加 `$trace_id` → 加载期就红。

        为什么必须在**加载期**拦：这类改动只让缓存命中率掉、不产生任何错误，
        等命中率指标掉下来时成本已经涨了。
        """
        (tmp_path / "normalize_v1.txt").write_text(
            "=== SYSTEM ===\n角色：$trace_id\nJSON\n=== USER ===\n$question\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(loader_mod, "PROMPTS_DIR", tmp_path)
        load_prompt.cache_clear()
        try:
            with pytest.raises(LlmPromptError) as ei:
                load_prompt("normalize")
            assert "trace_id" in ei.value.detail["illegal_vars"]
            assert "规则" in ei.value.message
        finally:
            load_prompt.cache_clear()

    def test_prefix_never_contains_history_or_question_text(self) -> None:
        """前缀文本里不得出现本次请求的问题与历史（规则 1/2/3 的**文本级**复核）。"""
        p = _payload(
            raw_question="这个问题绝不能出现在前缀里",
            history_questions=["历史问题也不许出现在前缀里"],
        )
        for task in ALL_TASKS:
            messages, _ = render_messages(load_prompt(task.value), p)
            prefix = messages[0]["content"]
            assert p.raw_question not in prefix, task.value
            assert "历史问题也不许出现在前缀里" not in prefix, task.value

    def test_prefix_makes_json_output_possible(self) -> None:
        """🔴 实测约束：`response_format=json_object` 要求消息里有 "json" 字样。

        让它在**资产层**成立（而不是靠调用方记得传），否则每份新资产都可能踩一次 400。
        """
        for task in ALL_TASKS:
            asset = load_prompt(task.value)
            sys_text = asset.system_template.template
            assert "json" in sys_text.lower(), task.value


class TestPrefixStability:
    """DoD④ 的核心：**稳定内容前置**。"""

    def test_different_questions_share_the_same_prefix(self) -> None:
        a = _payload(raw_question="问题甲")
        b = _payload(raw_question="完全不同的问题乙", few_shots=(("q", "select 1"),))
        for task in ALL_TASKS:
            asset = load_prompt(task.value)
            assert prefix_hash(asset, a) == prefix_hash(asset, b), task.value

    def test_bundle_version_change_does_change_the_prefix(self) -> None:
        """⚠️ 反向断言：前缀**该**随 `bundle_version` 变化（这是特性，不是缺陷）。

        没有这条，"前缀恒定"可以用"把语义包摘要从前缀删掉"来作弊 ——
        那样命中率是 100%，但模型看不到语义包，答案会崩。
        """
        a = _payload(bundle_version="v1")
        b = _payload(bundle_version="v2")
        assert prefix_hash(load_prompt("plan"), a) != prefix_hash(load_prompt("plan"), b)

    def test_semantic_summary_actually_lands_in_the_prefix(self) -> None:
        p = _payload(semantic_summary="UNIQUE_MARKER_表fact_sales")
        messages, _ = render_messages(load_prompt("plan"), p)
        assert "UNIQUE_MARKER_表fact_sales" in messages[0]["content"]


class TestPromptVersion:
    """DoD⑤ / N-19：`prompt_version` 必录。"""

    def test_render_returns_the_version(self) -> None:
        _, version = render_messages(load_prompt("gen_sql"), _payload())
        assert version == "gen_sql_v1"

    def test_two_roles_only(self) -> None:
        messages, _ = render_messages(load_prompt("plan"), _payload())
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_bump_version_by_adding_a_new_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """升版 = 加文件，不写代码 —— 这是"版本化 prompt"的可用性判据。"""
        (tmp_path / "plan_v1.txt").write_text("=== SYSTEM ===\n旧 JSON\n=== USER ===\n$question\n", encoding="utf-8")
        (tmp_path / "plan_v2.txt").write_text("=== SYSTEM ===\n新 JSON\n=== USER ===\n$question\n", encoding="utf-8")
        monkeypatch.setattr(loader_mod, "PROMPTS_DIR", tmp_path)
        load_prompt.cache_clear()
        try:
            assert available_versions("plan") == [1, 2]
            assert load_prompt("plan").version == "plan_v2"      # 默认取最高版
            assert load_prompt("plan", version=1).version == "plan_v1"
        finally:
            load_prompt.cache_clear()


class TestTemplateErrors:
    def test_missing_variable_names_the_variable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """资产与调用方不匹配时报错必须**指名**缺哪个变量（否则排查靠猜）。

        场景：某人给资产加了个 `$undeclared_var` 而 `render_messages` 不认识它。
        这在**加载期查不出来**（加载器只校验 SYSTEM 段的白名单），只在渲染期暴露 ——
        所以报错信息必须自带变量名，否则线上只能看到一句"prompt 模板替换失败"。
        """
        (tmp_path / "plan_v1.txt").write_text(
            "=== SYSTEM ===\nJSON\n=== USER ===\n$question\n$undeclared_var\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(loader_mod, "PROMPTS_DIR", tmp_path)
        load_prompt.cache_clear()
        try:
            with pytest.raises(LlmPromptError) as ei:
                render_messages(load_prompt("plan"), _payload())
            assert ei.value.detail["missing_var"] == "undeclared_var"
        finally:
            load_prompt.cache_clear()

    def test_shipped_assets_never_have_a_missing_variable(self) -> None:
        """反向对照：**随包交付的 10 份资产**在最小 payload 下必须全部渲染成功。

        没有这条，上面那条"缺变量会指名报错"可以用"所有资产都缺变量"来作弊。
        """
        for task in ALL_TASKS:
            messages, _ = render_messages(load_prompt(task.value), _payload())
            assert len(messages) == 2, task.value
            assert messages[1]["content"].strip(), task.value

    def test_bare_dollar_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`string.Template` 的已知坑：裸 `$` 会被当成不完整占位符。

        ⚠️ 本项目刻意不写 `$schema` 这类 JSON Schema 关键字，原因就在这里。
        """
        (tmp_path / "plan_v1.txt").write_text(
            "=== SYSTEM ===\n价格 $ 元\nJSON\n=== USER ===\n$question\n", encoding="utf-8"
        )
        monkeypatch.setattr(loader_mod, "PROMPTS_DIR", tmp_path)
        load_prompt.cache_clear()
        try:
            with pytest.raises(LlmPromptError) as ei:
                load_prompt("plan")
            assert "裸" in ei.value.message
        finally:
            load_prompt.cache_clear()

    def test_sections_must_be_present_in_order(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "plan_v1.txt").write_text("只有正文，没有分段标记\n", encoding="utf-8")
        monkeypatch.setattr(loader_mod, "PROMPTS_DIR", tmp_path)
        load_prompt.cache_clear()
        try:
            with pytest.raises(LlmPromptError) as ei:
                load_prompt("plan")
            assert "=== SYSTEM ===" in ei.value.message
        finally:
            load_prompt.cache_clear()


class TestBlocks:
    """变化后缀里的四类块：few_shots / candidates / history / error_digest。

    ⚠️ 断言按 task **分派**，不强求每份资产都挂齐 —— normalize 只做问题归一化，
    给它塞 SQL few-shot 是噪声（且白占 token）。**多挂**和**漏挂**都要能被发现。
    """

    def test_history_block_renders_for_the_normalize_family(self) -> None:
        p = _payload(history_questions=["上一轮问了什么"])
        for task in ("normalize", "normalize_intent"):
            messages, _ = render_messages(load_prompt(task), p)
            assert "上一轮问了什么" in messages[1]["content"], task

    def test_few_shots_render_for_the_sql_generating_tasks(self) -> None:
        p = _payload(few_shots=(("上月销售额", "SELECT sum(amount) FROM fact_sales"),))
        for task in ("gen_sql", "gen_sql_complex"):
            messages, _ = render_messages(load_prompt(task), p)
            suffix = messages[1]["content"]
            assert "SELECT sum(amount) FROM fact_sales" in suffix, task
            assert "上月销售额" in suffix, task

    def test_candidates_render_for_the_ranking_tasks(self) -> None:
        p = _payload(candidates=("fact_sales.amount", "fact_sales.sku_id"))
        for task in ("rerank", "l4_score"):
            messages, _ = render_messages(load_prompt(task), p)
            suffix = messages[1]["content"]
            assert "fact_sales.amount" in suffix, task
            assert "fact_sales.sku_id" in suffix, task

    def test_error_digest_renders_only_for_repair(self) -> None:
        p = _payload(error_digest="ERROR: column does_not_exist does not exist")
        messages, _ = render_messages(load_prompt("repair"), p)
        assert "column does_not_exist does not exist" in messages[1]["content"]

    def test_blocks_never_leak_across_tasks(self) -> None:
        """反向对照：**没声明**这些变量的资产，块内容一个都不许出现。

        这条防的是"模板里顺手贴了一段示例 SQL，于是每次请求都带上"，属**token 泄漏**。
        """
        p = _payload(
            few_shots=(("MARKER_FS", "SELECT MARKER_FS_SQL"),),
            candidates=("MARKER_CAND",),
            history_questions=["MARKER_HIST"],
            error_digest="MARKER_ERR",
        )
        declared = {
            "normalize": {"history_block"},
            "normalize_intent": {"history_block"},
            "gen_sql": {"few_shots"},
            "gen_sql_complex": {"few_shots"},
            "rerank": {"candidates_block"},
            "l4_score": {"candidates_block"},
            "repair": {"error_digest"},
            "intent": set(),
            "plan": set(),
            "present": set(),
        }
        marker_of = {
            "few_shots": "MARKER_FS",
            "candidates_block": "MARKER_CAND",
            "history_block": "MARKER_HIST",
            "error_digest": "MARKER_ERR",
        }
        for task in ALL_TASKS:
            messages, _ = render_messages(load_prompt(task.value), p)
            text = messages[0]["content"] + messages[1]["content"]
            for block, marker in marker_of.items():
                if block in declared[task.value]:
                    assert marker in text, (task.value, block)
                else:
                    assert marker not in text, (task.value, block)

    def test_history_is_trimmed_to_last_five(self) -> None:
        p = _payload(history_questions=[f"第{i}轮" for i in range(1, 9)])
        messages, _ = render_messages(load_prompt("normalize"), p)
        suffix = messages[1]["content"]
        assert "第8轮" in suffix and "第1轮" not in suffix  # FR-10.6 的历史裁剪位置在后缀
