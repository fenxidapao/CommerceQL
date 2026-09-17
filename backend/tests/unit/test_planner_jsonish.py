"""JSON 提取与校验摘要单测（W3B，N-01：离线、无网络、无 LLM）。

## 这个文件要钉住的两件事

1. **提取的鲁棒性**：模型输出里的 JSON 常被围栏包裹、前后带解释文字、甚至带着未闭合的括号。
   提取器必须"能取就取、取不到就**说清为什么**"，而不是抛一个裸 `JSONDecodeError`。
2. **摘要的**不**泄露性**（N-17 / §10.5 ⑤）：
   `validation_digest` 的产物会进 prompt 的 `$error_digest` 槽，也会进 SSE 的 `detail`。
   它**只能**含 `loc` / `type` / `msg` —— Pydantic 的 `ValidationError` 里还有一个
   `input` 字段，那里装的是**模型刚吐出来的原始值**（可能就是一条 SQL）。
   把它带出去 = 亲手把 SQL 回灌 prompt。

## 负向对照（本文件的纪律）

"摘要不含 SQL"这类断言，若夹具里**根本没有** SQL，那它必然通过 —— 那是**空断言**。
所以下面的用例显式构造一个"输入里真的有 SQL"的失败现场，先证明**注入即红**，
再证明正常路径**是绿的**。见 `test_sql_in_input_is_dropped_...` 一组。
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.planner.jsonish import (
    JsonAttempt,
    extract_json_object,
    first_json_object,
    validation_digest,
)

#: `validation_digest` 的 `limit` 是**必填**关键字参数（有意为之：由调用方决定"多长算摘要"）。
_DIGEST_LIMIT = 1000


class _Strict(BaseModel):
    """与 `planner.schemas` 同配置的极小模型（严格 + 冻结）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sql: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


# ============================================================================
# 一、平衡括号扫描
# ============================================================================

class TestFirstJsonObject:
    def test_plain_object(self) -> None:
        text, reason = first_json_object('{"a": 1}')
        assert reason is None
        assert text is not None and json.loads(text) == {"a": 1}

    def test_fenced_object_is_unwrapped(self) -> None:
        """```json 围栏是**格式噪声**不是内容错误 —— 剥掉即可，不该浪费一次修复重试。"""
        text, reason = first_json_object('```json\n{"sql": "SELECT 1"}\n```')
        assert reason is None
        assert text is not None and json.loads(text) == {"sql": "SELECT 1"}

    def test_explanatory_prose_around_object(self) -> None:
        raw = '好的，分析如下：\n{"sql": "SELECT 1"}\n希望对你有帮助。'
        text, reason = first_json_object(raw)
        assert reason is None
        assert text is not None and json.loads(text) == {"sql": "SELECT 1"}

    def test_braces_inside_string_do_not_break_balance(self) -> None:
        """字符串里的 `{` `}` 不参与配对 —— 贪婪正则会在这里断掉。"""
        raw = '{"sql": "SELECT json_build_object(\'a\', \'{\') AS x"}'
        text, reason = first_json_object(raw)
        assert reason is None
        assert text is not None and json.loads(text) == json.loads(raw)

    def test_escaped_quote_inside_string(self) -> None:
        raw = '{"sql": "SELECT \'a\\\\\'b\' AS x"}'
        text, reason = first_json_object(raw)
        assert reason is None
        assert text is not None and json.loads(text) == json.loads(raw)

    def test_unclosed_object_reports_reason_without_raising(self) -> None:
        text, reason = first_json_object('{"sql": "SELECT 1"')
        assert text is None
        assert reason  # 必须给得出理由，否则修复轮次无从下手

    def test_no_brace_at_all_reports_reason(self) -> None:
        text, reason = first_json_object("我不知道该怎么回答")
        assert text is None
        assert reason

    @pytest.mark.parametrize("blank", ["", "   ", "\n\n"])
    def test_blank_input(self, blank: str) -> None:
        text, reason = first_json_object(blank)
        assert text is None and reason


# ============================================================================
# 二、提取为 Mapping
# ============================================================================

class TestExtractJsonObject:
    def test_returns_mapping(self) -> None:
        obj, reason = extract_json_object('{"a": 1}')
        assert reason is None and obj == {"a": 1}

    def test_non_mapping_json_is_rejected(self) -> None:
        """`[1,2,3]` 是合法 JSON 但不是我们要的形状 —— 必须报错而不是当成空 dict。"""
        obj, reason = extract_json_object("[1, 2, 3]")
        assert obj is None and reason

    def test_string_json_is_rejected(self) -> None:
        obj, reason = extract_json_object('"just a string"')
        assert obj is None and reason


# ============================================================================
# 三、摘要：只含 loc/type/msg，**绝不**含 input
# ============================================================================

class TestValidationDigest:
    def _failure(self, payload: dict[str, object]) -> Exception:
        with pytest.raises(Exception) as excinfo:
            _Strict.model_validate(payload)
        return excinfo.value

    def test_extra_key_is_rejected_and_digest_names_it(self) -> None:
        exc = self._failure({"sql": "SELECT 1", "confidence": 0.5, "oops": 1})
        digest = validation_digest(exc, limit=_DIGEST_LIMIT)
        assert "oops" in digest
        assert "extra_forbidden" in digest or "Extra" in digest

    def test_range_violation_digest(self) -> None:
        exc = self._failure({"sql": "SELECT 1", "confidence": 7.5})
        digest = validation_digest(exc, limit=_DIGEST_LIMIT)
        assert "confidence" in digest

    def test_digest_is_bounded(self) -> None:
        """上限必须生效：摘要里塞不进一整段原始输出。"""
        many = {f"k{i}": i for i in range(200)}
        exc = self._failure({"sql": "SELECT 1", "confidence": 0.5, **many})
        digest = validation_digest(exc, limit=200)
        assert len(digest) <= 200

    # -- 🔴 负向对照：证明"不含 SQL"这条断言**不是空断言** --------------------

    def test_sql_in_input_is_dropped_by_digest_LET_ME_SEE_THE_VALUE(self) -> None:
        """**核心负向对照**：SQL 落在 Pydantic 的 `input` 里时，摘要必须把它丢掉。

        ## 为什么第一个夹具版本是**空断言**（本用例的修订记录）

        初版把 SQL 放在 `sql` 字段上（合法），只在 `confidence` 上制造类型错误 ——
        结果是：SQL **从来没有**进入任何一条错误的 `input`（报错的是 `confidence`，
        它的 `input` 是 `"不是数字"`）。于是"摘要里没有 SQL"在任何实现下都成立，
        注入 `input` 的实验**照绿**。这就是"否定式断言必须先自证有料"的现场。

        现在两个夹具都让 SQL **真的**落在错误的 `input` 上：
        - A：多余键的值就是那条 SQL（`extra_forbidden` 的 `input` = 多余的值）；
        - B：类型错误的字段值就是那条 SQL（`string_type` 的 `input` = 那个字符串）。
        """
        sql = "SELECT sku_id, sum(amount) FROM order_paid GROUP BY 1"

        # ---- 夹具 A：多余键（extra="forbid" → input = 多余键的**值**）----
        exc_a = self._failure({"sql": "SELECT 1", "confidence": 0.5, "generated_sql": sql})
        # ① 前置证明：这条 SQL 确实出现在某个错误的 `input` 里（否则本用例无证明力）
        assert any(err.get("input") == sql for err in exc_a.errors())
        digest_a = validation_digest(exc_a, limit=_DIGEST_LIMIT)

        # ---- 夹具 B：类型错误的字段值本身是 SQL ----
        exc_b = self._failure({"sql": "SELECT 1", "confidence": sql})
        assert any(err.get("input") == sql for err in exc_b.errors())
        digest_b = validation_digest(exc_b, limit=_DIGEST_LIMIT)

        # ② 断言：两份摘要都不得出现 SQL 的任何**标志性片段**
        for digest in (digest_a, digest_b):
            assert "order_paid" not in digest
            assert "SELECT" not in digest
            assert "sku_id" not in digest
        # ③ 但定位信息必须在（否则退化成"什么都没说"）
        assert "generated_sql" in digest_a
        assert "confidence" in digest_b

    def test_digest_never_contains_the_raw_input_key(self) -> None:
        """补一条**结构性**断言：Pydantic 的 `input` 段被明确丢弃。"""
        exc = self._failure({"sql": "SELECT 1", "confidence": "x"})
        digest = validation_digest(exc, limit=_DIGEST_LIMIT)
        assert "input_value" not in digest and "input=" not in digest


# ============================================================================
# 四、JsonAttempt 的成功判定
# ============================================================================

class TestJsonAttempt:
    def test_ok_keyed_on_parsed(self) -> None:
        assert JsonAttempt(parsed=_Strict(sql="SELECT 1", confidence=1.0), error_digest=None).ok
        assert not JsonAttempt(parsed=None, error_digest="为什么不通过").ok
