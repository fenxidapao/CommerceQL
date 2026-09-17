"""T1 出站脱敏（N-12）单测 —— **白名单而非黑名单**。

覆盖 DoD③ 的**构造侧**：出站载荷只能由受控数据类构造，未登记字段无法被表示。
"录制 outbound payload 里不含任何明细键名与值"的**端到端**版本在
`test_llm_gateway.py::TestOutboundAttachment`（那里走真实 HTTP 传输层录制原始字节）。

## 负向对照（本仓库的硬纪律）

`TestNegativeControl` 用「注入 → 必红 → 还原 → 必绿」证明这些断言**真的会拦**，
而且断言红的**确实是目标那条**（比对异常类型 + 消息特征，而不只是"抛了个异常"）。
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from app.llm.egress_guard import (
    ALLOWED_WIRE_KEYS,
    EXTERNALLY_SOURCED_FIELDS,
    MAX_RAW_QUESTION_CHARS,
    EgressPayload,
    assert_no_forbidden_keys,
    build_wire_request,
    normalize_key,
)
from app.llm.errors import LlmEgressViolation


def _payload(**over: object) -> EgressPayload:
    base: dict[str, object] = {
        "raw_question": "统计华东区上月销售额前十的 SKU",
        "semantic_summary": "表 fact_sales(sku_id, order_id, amount, dt)",
        "dialect_note": "目标方言：PostgreSQL 16。金额单位为元。",
        "output_schema": '{"type":"object","properties":{"sql":{"type":"string"}}}',
        "bundle_version": "2026.09.14.1",
    }
    base.update(over)
    return EgressPayload(**base)  # type: ignore[arg-type]


def _wire(**over: object) -> dict[str, object]:
    return build_wire_request(
        _payload(**over),
        model="deepseek-flash",
        system_text="你是 CommerceQL 组件，只输出 JSON 对象。",
        user_text="[问题]\n统计上月销售额",
        max_tokens=512,
        temperature=0.0,
        thinking=False,
    )


class TestWhitelist:
    def test_registered_field_set_is_exactly_this(self) -> None:
        """字段集快照 —— 新增字段必须**同时**改本断言与 07 §10.5，漏改即 CI 红。"""
        assert set(EgressPayload.from_mapping({"raw_question": "q"}).as_dict()) == {
            "raw_question",
            "semantic_summary",
            "dialect_note",
            "output_schema",
            "few_shots",
            "constraints",
            "error_digest",
            "candidates",
            "history_questions",
            "bundle_version",
            "user_scope",
        }

    def test_unknown_key_is_rejected_not_dropped(self) -> None:
        """🔴 未知键**必须抛错**而不是静默丢弃 —— 丢弃等于让调用方以为参数生效了。"""
        with pytest.raises(LlmEgressViolation) as ei:
            EgressPayload.from_mapping({"raw_question": "q", "trace_id": "abc"})
        assert "未登记" in ei.value.message
        assert ei.value.detail["unknown_keys"] == ["trace_id"]

    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(LlmEgressViolation):
            EgressPayload.from_mapping(["raw_question"])  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bad_key",
        ["rows", "result_set", "resultSet", "sample_json", "deny_columns",
         "raw_error", "sql_text", "generated_sql", "tenant_id", "otherTenant", "row_count"],
    )
    def test_forbidden_key_names_are_rejected(self, bad_key: str) -> None:
        """键级扫描：归一化后比较，`result_set` 与 `resultSet` 同罪。"""
        with pytest.raises(LlmEgressViolation):
            assert_no_forbidden_keys({"messages": [{bad_key: "x"}]})

    def test_forbidden_keys_are_found_recursively(self) -> None:
        with pytest.raises(LlmEgressViolation) as ei:
            assert_no_forbidden_keys({"messages": [{"meta": {"nested": {"rows": [1, 2]}}}]})
        assert "rows" in str(ei.value.detail["path"])

    def test_error_message_never_carries_the_value(self) -> None:
        """🔴 报错只给**键名与路径**：脱敏模块自己的报错也是泄露通道。"""
        secret = "13800138000"
        with pytest.raises(LlmEgressViolation) as ei:
            assert_no_forbidden_keys({"sample_json": secret})
        assert secret not in str(ei.value.detail)

    def test_key_normalization(self) -> None:
        assert normalize_key("Result_Set") == "resultset"
        assert normalize_key("row-count") == "rowcount"


class TestValueLevelScan:
    def test_sql_in_raw_question_is_ALLOWED(self) -> None:
        """用户自己贴一句 SQL 提问是**合法用法**（§10.5 ① 允许归一化后的用户问题）。

        拦它 = 拦正常业务。这条断言存在的意义是防止后人"顺手加个 SQL 黑名单"。
        """
        p = _payload(raw_question="SELECT sku_id FROM fact_sales WHERE dt > '2026-08-01' 是什么意思？")
        assert "SELECT" in p.raw_question

    def test_sql_in_history_is_REJECTED(self) -> None:
        """§10.5 ⑥：会话历史里的 **SQL 与结果**禁止出站（N-17 同源）。"""
        with pytest.raises(LlmEgressViolation) as ei:
            _payload(history_questions=["上月销售额多少", "SELECT sum(amount) FROM fact_sales"])
        assert "N-17" in ei.value.message

    def test_sql_in_error_digest_is_REJECTED(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(error_digest="syntax error near SELECT a, b FROM t")

    def test_benign_select_word_in_chinese_question_is_not_flagged(self) -> None:
        """"SQL **语句**特征"要求子句组合，不是"出现 SELECT 这个词" —— 防误杀。"""
        p = _payload(raw_question="select 前十个 SKU 的销量（这是英文混写的口语问法）")
        assert p.raw_question

    def test_tabular_rows_are_REJECTED(self) -> None:
        dumped = "统计一下\n1001, sku-a, 120.5, 2026-08-01\n1002, sku-b, 88.0, 2026-08-02\n1003, sku-c, 9.9, 2026-08-03"
        with pytest.raises(LlmEgressViolation) as ei:
            _payload(raw_question=dumped)
        assert "结果集形态" in ei.value.message

    def test_container_value_is_REJECTED(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(semantic_summary=[{"a": 1}])

    def test_length_caps(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(raw_question="x" * (MAX_RAW_QUESTION_CHARS + 1))

    def test_candidates_caps(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(candidates=("col_" + "y" * 200,))

    def test_empty_question_is_REJECTED(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(raw_question="   ")

    def test_externally_sourced_fields_are_the_expected_three_plus_candidates(self) -> None:
        """形态扫描只作用于外部来源字段 —— 自产稳定文本合法地含 SQL 关键词。"""
        scanned = EXTERNALLY_SOURCED_FIELDS
        assert scanned == {"raw_question", "history_questions", "error_digest"}

    def test_own_prompt_text_may_contain_sql_keywords(self) -> None:
        """`dialect_note` 里出现 "SELECT" 是**必然**的，不得误杀。

        ⚠️ 这条断言同时说明**边界在哪**：形态扫描只作用于 `EXTERNALLY_SOURCED_FIELDS`，
        而方言说明/JSON Schema 是自产稳定文本 —— 对它们做 SQL 扫描等于每天误杀自己。
        """
        w = build_wire_request(
            _payload(dialect_note="使用 SELECT 而非 SELECT ALL；禁止 INSERT/UPDATE。"),
            model="deepseek-flash",
            system_text="[方言说明]\n使用 SELECT 而非 SELECT ALL；禁止 INSERT/UPDATE。\n[输出]\nJSON",
            user_text="[问题]\n统计上月销售额",
            max_tokens=512,
            temperature=0.0,
            thinking=False,
        )
        assert "SELECT" in w["messages"][0]["content"]


class TestWireRequest:
    def test_only_registered_wire_keys(self) -> None:
        assert set(_wire()) <= ALLOWED_WIRE_KEYS

    def test_thinking_flag_uses_the_only_working_form(self) -> None:
        """🔴 实测（2026-09-17）：关闭思考的唯一有效写法是 `{"type":"disabled"}`。

        `thinking: false` 会被上游 400；`enable_thinking: false` / `chat_template_kwargs`
        会被**静默忽略**（仍产 reasoning token）。所以这里钉死**形状**。
        """
        assert _wire()["thinking"] == {"type": "disabled"}
        assert build_wire_request(
            _payload(), model="deepseek-v4-pro", system_text="s JSON", user_text="u",
            max_tokens=1, temperature=0.0, thinking=True,
        )["thinking"] == {"type": "enabled"}

    def test_json_output_requires_the_word_json(self) -> None:
        """🔴 实测：`response_format=json_object` 要求消息里有 "json" 字样，否则上游 400。"""
        with pytest.raises(LlmEgressViolation) as ei:
            build_wire_request(
                _payload(), model="deepseek-flash", system_text="你是助手。", user_text="问题",
                max_tokens=16, temperature=0.0, thinking=False, json_output=True,
            )
        assert "json" in ei.value.message.lower()

    def test_user_scope_rides_the_api_field_not_the_prompt(self) -> None:
        """冲突 A 的裁定：`user_id` 只以**哈希**出现在 HTTP `user` 参数，不进 messages。"""
        w = build_wire_request(
            _payload(user_scope="0123456789abcdef"),
            model="deepseek-flash", system_text="s JSON", user_text="u",
            max_tokens=8, temperature=0.0, thinking=False,
        )
        assert w["user"] == "0123456789abcdef"
        assert "0123456789abcdef" not in w["messages"][0]["content"]
        assert "0123456789abcdef" not in w["messages"][1]["content"]

    def test_plaintext_user_id_is_rejected(self) -> None:
        with pytest.raises(LlmEgressViolation):
            _payload(user_scope="user-42")

    def test_deny_columns_are_the_last_line_of_defence(self) -> None:
        """§10.5 ④：`deny_columns` 列名绝不出现 —— 语义层过滤失效时网关复核。

        负向对照：**同一份内容**在不传 `deny_columns` 时正常通过（说明拦的是 deny 规则，
        而不是"看到列名就拦"这种会把合法列名一起杀掉的粗暴实现）。
        """
        dirty = _payload(semantic_summary="表 users(phone_number, id_card)")
        kwargs = {
            "model": "deepseek-flash", "system_text": "系统 JSON", "user_text": "问题",
            "max_tokens": 8, "temperature": 0.0, "thinking": False,
        }
        # 对照（绿）：内容本身合法，只是恰好含一个敏感列名 —— 不传 deny 就不该拦
        assert build_wire_request(dirty, **kwargs)["model"] == "deepseek-flash"  # type: ignore[arg-type]
        # 注入 deny 规则（红）
        with pytest.raises(LlmEgressViolation) as ei:
            build_wire_request(dirty, deny_columns=("phone_number",), **kwargs)  # type: ignore[arg-type]
        assert ei.value.detail["deny_columns_hit"] == ["phone_number"]

    def test_empty_model_rejected(self) -> None:
        with pytest.raises(LlmEgressViolation):
            build_wire_request(
                _payload(), model="", system_text="s JSON", user_text="u",
                max_tokens=8, temperature=0.0, thinking=False,
            )


class TestNegativeControl:
    """DoD③ 的构造侧负向对照：**注入 → 必红 → 还原 → 必绿**。"""

    INJECTED: ClassVar[dict[str, Any]] = {
        "raw_question": "上月销售额",
        "result_set": {"columns": ["amount"], "rows": [[1]]},
    }

    def test_injection_goes_red_on_the_target_assertion(self) -> None:
        with pytest.raises(LlmEgressViolation) as ei:
            EgressPayload.from_mapping(self.INJECTED)
        # 必须红的**是目标那条**（未知键），而不是恰好别的异常
        assert "未登记" in ei.value.message
        assert "result_set" in ei.value.detail["unknown_keys"]
        # 值绝不进报错信息
        assert "amount" not in str(ei.value.detail)

    def test_restore_goes_green(self) -> None:
        p = EgressPayload.from_mapping({"raw_question": "上月销售额"})
        assert p.raw_question == "上月销售额"

    def test_injection_of_a_registered_key_with_dirty_value_also_goes_red(self) -> None:
        """绕过数据类直接拼 dict 也拦得住（防线 2 的用途）。"""
        with pytest.raises(LlmEgressViolation):
            assert_no_forbidden_keys({"messages": [{"role": "user", "content": "q"}], "rows": [[1]]})
