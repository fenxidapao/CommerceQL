"""契约断言：取值集基数与查找表自洽性。

归属窗口：W0（docs/08 §3.1）。对应 **阶段 0 DoD③**（"契约断言集可以是空的，但必须能跑通"）
与 **07 §4.2 断言⑤**。

为什么这里**不是**凑数的占位断言：
  pytest 对"零测试被收集"返回的退出码是 **5**，CI 把非 0 一律判失败
  （`backend/pyproject.toml` 里刻意**没有**加 `--suppress-no-test-exit-code`，
  就是为了让这个坑暴露出来，而不是被掩盖）。所以"能跑通"必须有断言承载 —— 本文件即该载体。

本文件**只读** `app.core.enums`，不 import 任何业务模块：
  它的作用是让"有人偷改取值集却不同步契约"在 CI 阶段就红掉，
  而不是等某个窗口按旧数字写死了分支才发现。
"""

from __future__ import annotations

import pytest

from app.core.enums import (
    AST_BLOCKING_RULES,
    AST_REWRITE_RULES,
    AST_RULE_SEVERITY,
    AST_WARNING_RULES,
    CONTRACT_COUNTS,
    DEFAULT_SUGGESTIONS,
    DEGRADABLE_DEPENDENCIES,
    DEPENDENCY_KIND,
    ERROR_HTTP_STATUS,
    ERROR_RETRY_TIER,
    RATE_LIMIT_BUCKET_RETRY_AFTER_S,
    READINESS_DEPENDENCIES,
    REQUIRES_SUGGESTIONS,
    RETRY_AFTER_DEFAULT_S,
    RETRY_AFTER_REQUIRED,
    RETRYABLE_BOOLEAN,
    SESSION_CONFLICT_RETRY_AFTER_S,
    SSE_STAGE_EMISSION_POINTS,
    SSE_TERMINAL_EVENTS,
    ActionTaken,
    AstRule,
    AstRuleSeverity,
    BindingLayer,
    BindingState,
    ChartPreference,
    ChartType,
    CitationType,
    ClarifyReason,
    DegradedReason,
    Dependency,
    DependencyKind,
    ErrorCode,
    FeedbackReasonCode,
    GateDecision,
    GateNo,
    GoldQueryTier,
    HealthStatus,
    LatencyKey,
    LimitType,
    Outcome,
    RateLimitBucket,
    RefuseReason,
    RetrievalMode,
    RetryableTier,
    Role,
    ScopeLevel,
    SseEvent,
    Stage,
    TaskStatus,
    TokenKey,
    validate_contract_counts,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# 1. 自检函数本身必须能跑通（DoD③ 的最小可验证载体）
# ---------------------------------------------------------------------------

def test_validate_contract_counts_passes() -> None:
    """`app/core/enums.py` 的 `validate_contract_counts()` 不得抛错。

    这是 07 §4.2 断言⑤ 的直接机器化：枚举实际基数 == `CONTRACT_COUNTS` 声明值。
    """
    validate_contract_counts()


# ---------------------------------------------------------------------------
# 2. 契约基数表 ↔ 枚举对象 的**全量映射**
# ---------------------------------------------------------------------------
# 这张表是"CONTRACT_COUNTS 里每一个键都真的有测试在盯"的证明。
# 漏登记 / 多登记都会在 test_contract_counts_keys_are_all_bound 里红掉。

_COUNT_BINDINGS: dict[str, object] = {
    "stage": Stage,
    "error_code": ErrorCode,
    "chart_type": ChartType,
    "sse_event": SseEvent,
    "sse_emission_points": SSE_STAGE_EMISSION_POINTS,
    "sse_terminal_events": SSE_TERMINAL_EVENTS,
    "outcome": Outcome,
    "task_status": TaskStatus,
    "refuse_reason": RefuseReason,
    "clarify_reason": ClarifyReason,
    "degraded_reason": DegradedReason,
    "action_taken": ActionTaken,
    "retrieval_mode": RetrievalMode,
    "feedback_reason_code": FeedbackReasonCode,
    "binding_state": BindingState,
    "binding_layer": BindingLayer,
    "role": Role,
    "scope_level": ScopeLevel,
    "gate_no": GateNo,
    "gate_decision": GateDecision,
    "chart_preference": ChartPreference,
    "citation_type": CitationType,
    "limit_type": LimitType,
    "rate_limit_bucket": RateLimitBucket,
    "latency_key": LatencyKey,
    "token_key": TokenKey,
    "health_status": HealthStatus,
    "dependency": Dependency,
    "readiness_dependencies": READINESS_DEPENDENCIES,
    "degradable_dependencies": DEGRADABLE_DEPENDENCIES,
    # ✅ U-16 销账后，`AstRule` 已成为 `enums.py` 的实体 → 本文件直接校验（不再是"登记数字"）
    "ast_rule": AstRule,
    "ast_rule_severity": AstRuleSeverity,
    # ✅ U-14 §11.7 新增的双层 Gold Query 库
    "gold_query_tier": GoldQueryTier,
}

#: 有意**不在本文件校验**的键（当前为空）。
#: 曾经装着 `ast_rule` —— 那时规则实体归 W2C，本文件只能"登记数字"（U-16 未裁定）。
#: 裁定后 `AstRule` 落进 `enums.py`，该豁免随之**销账**：现在没有豁免项了。
_UNCHECKED_IN_ENUMS: set[str] = set()


def test_contract_counts_keys_are_all_bound() -> None:
    """`CONTRACT_COUNTS` 的每个键都必须有对应的实体绑定（多一个键暴露"死配置"）。"""
    declared = set(CONTRACT_COUNTS)
    bound = set(_COUNT_BINDINGS) | _UNCHECKED_IN_ENUMS
    assert not (declared - bound), f"CONTRACT_COUNTS 有键无人校验：{sorted(declared - bound)}"
    assert not (bound - declared), f"校验表含已不存在的键：{sorted(bound - declared)}"


@pytest.mark.parametrize("key", sorted(_COUNT_BINDINGS))
def test_declared_count_matches_object(key: str) -> None:
    """逐个键比对：声明基数 == 实体实际基数。"""
    obj = _COUNT_BINDINGS[key]
    actual = len(obj)  # type: ignore[arg-type]
    assert actual == CONTRACT_COUNTS[key], (
        f"{key}: 声明={CONTRACT_COUNTS[key]} 实际={actual} → 有人改了取值集却没同步 CONTRACT_COUNTS"
    )


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("stage", 6),        # 07 §14.3 约束 8
        ("error_code", 28),  # 附录 A §A.11
        ("chart_type", 7),   # 附录 A §A.10（★ U-15：非 07 §4.2 所写的「6 值」）
    ],
)
def test_authoritative_counts(key: str, expected: int) -> None:
    """07 §4.2 断言⑤ 明文点名的 3 个数字 —— 单独钉一次，改动代价最高。"""
    assert CONTRACT_COUNTS[key] == expected


def test_feedback_reason_codes_match_appendix_a() -> None:
    """附录 A §A.6 的 10 个归因码：字面量必须逐字一致。

    它们是**外部契约**（客户端会把这些字符串传上来），改一个字母就是破坏性变更；
    而"归因方向"（右列映射）依赖这些取值可枚举，故不能退化成自由字符串。
    """
    assert {code.value for code in FeedbackReasonCode} == {
        "wrong_metric_definition",
        "wrong_time_range",
        "wrong_dimension",
        "missing_synonym",
        "wrong_join",
        "wrong_aggregation",
        "missing_default_filter",
        "permission_issue",
        "data_quality",
        "other",
    }


# ---------------------------------------------------------------------------
# 3. 失败面必须完整：任何一条出口路径都得有 HTTP 码与可重试级别
# ---------------------------------------------------------------------------

def test_every_error_code_has_http_status() -> None:
    missing = sorted(set(ErrorCode) - set(ERROR_HTTP_STATUS))
    assert not missing, f"错误码缺 HTTP 映射（会走出无码响应）：{missing}"


def test_every_error_code_has_retry_tier() -> None:
    missing = sorted(set(ErrorCode) - set(ERROR_RETRY_TIER))
    assert not missing, f"错误码缺可重试级别：{missing}"


def test_no_orphan_lookup_entries() -> None:
    """查找表不得含已不存在的错误码（删码忘了删表 → 死配置）。"""
    assert not sorted(set(ERROR_HTTP_STATUS) - set(ErrorCode))
    assert not sorted(set(ERROR_RETRY_TIER) - set(ErrorCode))


# ---------------------------------------------------------------------------
# 4. retryable / Retry-After / suggestions 的**三级不对称**（★ U-17 已销账）
# ---------------------------------------------------------------------------
# ⚠️ **本节在本会话被重写过**。第一版写的是 07 初版的语义：
#   ❌ NONE     ⇒ 绝不带 Retry-After；
#   ✅ YES      ⇒ 必须带；
#   ⭕ REPHRASE ⇒ **必须带** Retry-After 且必须给 suggestions[]。
# 其中 ⭕ 那条是**假承诺**：Retry-After 的含义是"等这么久，同一请求再发一次会有不同结果"，
# 而 ⭕ 的定义恰恰是"原样重试必然失败"。两者并列 = 用倒计时把用户骗进必然失败的重试，
# 且前端会按 06 §4.12 把它渲染成"稍后自动重试"。
# U-17 裁定后的正确形态：
#   ✅ ⇒ 必须带 Retry-After（**且必须有值**）
#   ⭕ ⇒ **不得**带 Retry-After；**必须**给 suggestions[]
#   ❌ ⇒ 两者皆无
# 这组不变式不靠评审看 —— 下方逐条断言，且 `api.errors.HttpErrorMapping.validate()`
# 在运行期重复同一组判据（两处一致才叫"钉死"）。

def test_retry_after_only_on_yes_tier() -> None:
    """Retry-After ⟺ ✅。**这是 U-17 的核心修正**。"""
    drift = sorted(
        code
        for code, tier in ERROR_RETRY_TIER.items()
        if RETRY_AFTER_REQUIRED[code] is not (tier is RetryableTier.YES)
    )
    assert not drift, (
        f"Retry-After 要求与 ✅ 档脱钩：{drift} —— "
        f"⭕ 带 Retry-After 是假承诺（U-17），❌ 带则诱导越权试探式的重试"
    )


def test_non_retryable_never_requires_retry_after() -> None:
    offenders = sorted(
        code
        for code, tier in ERROR_RETRY_TIER.items()
        if tier is RetryableTier.NONE and RETRY_AFTER_REQUIRED.get(code, False)
    )
    assert not offenders, f"❌ 不可重试码却要求 Retry-After（自相矛盾）：{offenders}"


def test_rephrase_must_not_carry_retry_after() -> None:
    """⭕ **不得**带 Retry-After —— 本测试就是为"防有人改回去"而存在的。"""
    offenders = sorted(
        code for code, tier in ERROR_RETRY_TIER.items() if tier is RetryableTier.REPHRASE and RETRY_AFTER_REQUIRED[code]
    )
    assert not offenders, f"⭕ 档被要求带 Retry-After（假承诺，U-17）：{offenders}"


def test_every_yes_code_has_a_concrete_retry_after_value() -> None:
    """'必须带' 与 '没有值' 同时成立 = 逼实现者发明数字（U-22）。

    附录 A 只给了两个码的明文值（`RATE_LIMITED` 按桶、`SESSION_CONFLICT`=3），
    其余 ✅ 码由 W0 落**保守缺省值**并登记 U-22；本测试保证"缺省值一定存在"。
    """
    missing = sorted(code for code, req in RETRY_AFTER_REQUIRED.items() if req and code not in RETRY_AFTER_DEFAULT_S)
    assert not missing, f"✅ 码没有 Retry-After 取值 → 实现者只能发明一个数字（U-22）：{missing}"


def test_retryable_boolean_matches_tier() -> None:
    """`retryable` 布尔只对 ✅ YES 为真 —— ⭕ REPHRASE 原样重试必然再失败，故为 false。"""
    drift = sorted(
        code for code, tier in ERROR_RETRY_TIER.items() if RETRYABLE_BOOLEAN[code] is not (tier is RetryableTier.YES)
    )
    assert not drift, f"retryable 投影与级别表不一致：{drift}"


def test_suggestions_required_iff_rephrase() -> None:
    """07 §14.4：⭕ 必须给"怎么改"（只给倒计时不给改法 = 诱导无效操作）。"""
    drift = sorted(
        code
        for code, tier in ERROR_RETRY_TIER.items()
        if REQUIRES_SUGGESTIONS[code] is not (tier is RetryableTier.REPHRASE)
    )
    assert not drift, f"suggestions 要求与 REPHRASE 级别脱钩：{drift}"


def test_every_rephrase_code_has_default_suggestions() -> None:
    """⭕ 的 suggestions 是硬约束，故**必须**有缺省值，否则默认路径产出的对象不合法。"""
    missing = sorted(code for code in ErrorCode if REQUIRES_SUGGESTIONS[code] and code not in DEFAULT_SUGGESTIONS)
    assert not missing, f"⭕ 码缺省 suggestions 未定义：{missing}"


def test_default_suggestions_are_actionable_phrases() -> None:
    """suggestions 必须是**可执行的改法**，不是"请稍后重试"这类空话。"""
    banned = ("稍后重试", "请重试", "重试")
    for code, items in DEFAULT_SUGGESTIONS.items():
        assert items, f"{code} 的缺省 suggestions 不得为空"
        for item in items:
            assert not any(b == item for b in banned), f"{code} 的 suggestion 是空话：{item!r}"


def test_internal_tier_follows_appendix_a_u21() -> None:
    """**U-21**：`INTERNAL` 的档位在 07 §14.4（✅）与附录 A §A.11（⭕）之间冲突。

    契约优先级「附录 A > 07」（08 §0.1）→ 取 ⭕。
    本测试同时把"另一条路走不通"钉下来：若有人改判为 ✅，**必须同时给 Retry-After 值**，
    否则 `test_every_yes_code_has_a_concrete_retry_after_value` 会红。
    """
    assert ERROR_RETRY_TIER[ErrorCode.INTERNAL] is RetryableTier.REPHRASE, (
        "U-21：INTERNAL 按附录 A §A.11 应为 ⭕（不带 Retry-After、必须给 suggestions）"
    )
    assert RETRY_AFTER_REQUIRED[ErrorCode.INTERNAL] is False
    assert REQUIRES_SUGGESTIONS[ErrorCode.INTERNAL] is True


# ---------------------------------------------------------------------------
# 5. AST 规则表：20 条 + **阻断/改写/告警三级**（★ U-16 已销账）
# ---------------------------------------------------------------------------
# U-16 的关键不是"从 16 条加到 20 条"，而是**R17–R20 不是阻断级**。
# 把它们写成拒绝 = 误杀正常查询（架构窗口原话："属实现缺陷"）。
# 所以本节的断言方向与第 3 节**相反**：不是"必须拒绝"，而是"必须不被拒绝"。

def test_ast_rule_count_is_20() -> None:
    assert len(AstRule) == 20, "AST 规则必须是 R01–R20（07 v0.6 §7.2）"


def test_ast_rule_ids_are_contiguous_r01_to_r20() -> None:
    """编号连续 —— 跳号会让"红队集逐条覆盖"无法用程序核对。"""
    expected = {f"R{i:02d}" for i in range(1, 21)}
    actual = {rule.value for rule in AstRule}
    assert actual == expected, f"规则编号不连续：缺 {sorted(expected - actual)} 多 {sorted(actual - expected)}"


def test_ast_severity_covers_every_rule() -> None:
    missing = sorted(set(AstRule) - set(AST_RULE_SEVERITY))
    assert not missing, f"以下规则没有处置级别（实现者只能自己猜）：{missing}"


def test_ast_rule_sets_partition_the_table() -> None:
    """三个级别集合必须**恰好划分**规则全集（不重不漏）。"""
    union = AST_BLOCKING_RULES | AST_WARNING_RULES | AST_REWRITE_RULES
    assert union == set(AstRule), "三级集合没有恰好覆盖规则全集"
    assert not (AST_BLOCKING_RULES & AST_WARNING_RULES)
    assert not (AST_BLOCKING_RULES & AST_REWRITE_RULES)
    assert not (AST_WARNING_RULES & AST_REWRITE_RULES)


def test_ast_warn_rules_are_exactly_r17_to_r20() -> None:
    """★ **本测试是 U-16 的"改它必须显式推翻"机制**。

    R17–R20 是**告警级**：命中后必须"产生告警且查询继续"。
    若有人把这四条改成阻断级（或新增一条阻断规则混进来），本测试红。
    """
    assert {r.value for r in AST_WARNING_RULES} == {"R17", "R18", "R19", "R20"}, (
        "R17–R20 必须是告警级（记录后继续）；写成拒绝会误杀正常查询（U-16）"
    )
    for rule in AST_WARNING_RULES:
        assert AST_RULE_SEVERITY[rule] is AstRuleSeverity.WARN


def test_limit_injection_and_comment_strip_are_rewrites_not_blocks() -> None:
    """R04（强制 LIMIT）与 R15（剥离注释后重解析）是**改写**，不是拒绝。

    写成拒绝会让**每一条正常查询**都失败 —— 它们命中率是 100%（正常查询本来就不带 LIMIT）。
    """
    assert AST_RULE_SEVERITY[AstRule.R04_FORCE_LIMIT] is AstRuleSeverity.REWRITE
    assert AST_RULE_SEVERITY[AstRule.R15_COMMENT_STRIP] is AstRuleSeverity.REWRITE


def test_high_risk_blocking_rules_are_blocking() -> None:
    """反向守卫：真正的高危规则**必须**是阻断级（防止有人"顺手"降级）。"""
    must_block = {
        AstRule.R01_STATEMENT_TYPE,
        AstRule.R02_MULTI_STATEMENT,
        AstRule.R03_SELECT_STAR,
        AstRule.R07_DENY_COLUMNS,
        AstRule.R08_SYSTEM_SCHEMA,
        AstRule.R09_FUNCTION_DENYLIST,
        AstRule.R11_CARTESIAN,
        AstRule.R12_RECURSIVE_CTE,
        AstRule.R14_LITERAL_POLICY,
        AstRule.R16_SEARCH_PATH,
    }
    assert must_block <= AST_BLOCKING_RULES, f"这些规则不得降级为非阻断：{sorted(r.value for r in must_block - AST_BLOCKING_RULES)}"


# ---------------------------------------------------------------------------
# 6. 会话串行冲突：409 而不是 429（U-14 家族的一致性守卫）
# ---------------------------------------------------------------------------

def test_session_conflict_is_409_not_429() -> None:
    assert ERROR_HTTP_STATUS[ErrorCode.SESSION_CONFLICT] == 409, (
        "会话串行冲突必须是 409：它是状态冲突，不是配额问题（附录 A v1.4 §A.11）"
    )


def test_session_conflict_suggestion_is_short() -> None:
    """409 的 Retry-After 是"建议值"，语义是"等锁释放"，不是限流倒计时。

    取值刻意很短（秒级）—— 会话锁的等待上限受 07 §9.3 约束（≤10s）。
    """
    assert isinstance(SESSION_CONFLICT_RETRY_AFTER_S, int)
    assert 0 < SESSION_CONFLICT_RETRY_AFTER_S <= 10


def test_rate_limited_retry_after_matches_appendix_bucket() -> None:
    """`RATE_LIMITED` 的缺省值必须等于 §A.0.6 的查询类桶值 —— 同一数值不得有两处字面量。"""
    assert RETRY_AFTER_DEFAULT_S[ErrorCode.RATE_LIMITED] == RATE_LIMIT_BUCKET_RETRY_AFTER_S[RateLimitBucket.QUERY]


def test_rate_limited_is_429_with_retry_after() -> None:
    assert ERROR_HTTP_STATUS[ErrorCode.RATE_LIMITED] == 429
    assert RETRY_AFTER_REQUIRED[ErrorCode.RATE_LIMITED] is True


def test_gold_query_tiers_are_two_and_distinct() -> None:
    """U-14 牵出的 §11.7：Gold Query 必须分**全局认证库**与**租户私有库**两层。

    合成一层 = 把"进全局库需额外审批"这道闸门从类型层面删掉。
    """
    assert len(GoldQueryTier) == 2
    assert GoldQueryTier.GLOBAL_CERTIFIED is not GoldQueryTier.TENANT_PRIVATE


# ---------------------------------------------------------------------------
# 7. SSE 帧契约（附录 A §A.7）
# ---------------------------------------------------------------------------

def test_terminal_events_are_known_sse_events() -> None:
    unknown = sorted(SSE_TERMINAL_EVENTS - set(SseEvent))
    assert not unknown, f"终止事件含未知类型：{unknown}"


def test_terminal_events_are_exactly_four() -> None:
    assert len(SSE_TERMINAL_EVENTS) == 4
    assert set(SSE_TERMINAL_EVENTS) == {
        SseEvent.COMPLETE,
        SseEvent.CLARIFY,
        SseEvent.REFUSE,
        SseEvent.ERROR,
    }


def test_emission_points_declare_only_legal_stages() -> None:
    """`data_ready` / `complete` 这类**事件名伪装成 stage** 的病害复发守卫。

    07 §4.1 禁令三记录过真实事故：`stage` 出现过非法值 `data_ready` / `complete`。
    """
    illegal = [
        (evt, stage) for evt, stage in SSE_STAGE_EMISSION_POINTS if stage is not None and stage not in Stage
    ]
    assert not illegal, f"发射点含非法 stage：{illegal}"


def test_emission_points_cover_every_sse_event() -> None:
    declared = {evt for evt, _ in SSE_STAGE_EMISSION_POINTS}
    missing = sorted(set(SseEvent) - declared)
    assert not missing, f"以下 SSE 事件没有发射点（永远发不出来）：{missing}"


def test_emission_points_have_no_duplicates() -> None:
    pairs = [(evt, stage) for evt, stage in SSE_STAGE_EMISSION_POINTS]
    assert len(pairs) == len(set(pairs)), "发射点表存在重复项 → 基数虚高"


def test_only_stage_event_carries_a_stage() -> None:
    """只有 `stage` 事件允许带 stage 值；其余事件带 stage 会让前端状态机错乱。"""
    wrong = [
        evt
        for evt, stage in SSE_STAGE_EMISSION_POINTS
        if stage is not None and evt is not SseEvent.STAGE
    ]
    assert not wrong, f"非 stage 事件却携带 stage：{wrong}"


def test_stage_event_always_carries_a_stage() -> None:
    assert all(stage is not None for evt, stage in SSE_STAGE_EMISSION_POINTS if evt is SseEvent.STAGE)


# ---------------------------------------------------------------------------
# 7. 三探针依赖分类（N-21：软依赖**不得**进 readiness）
# ---------------------------------------------------------------------------

def test_readiness_contains_only_hard_dependencies() -> None:
    wrong = sorted(d for d in READINESS_DEPENDENCIES if DEPENDENCY_KIND[d] is not DependencyKind.HARD)
    assert not wrong, (
        f"/healthz/ready 含软依赖 {wrong} → 违反 N-21：软依赖失败只许降级，不得让 ready 变 503"
    )


def test_soft_dependencies_are_degradable_not_readiness() -> None:
    assert Dependency.LLM in DEGRADABLE_DEPENDENCIES
    assert Dependency.EMBEDDING in DEGRADABLE_DEPENDENCIES
    assert Dependency.LLM not in READINESS_DEPENDENCIES
    assert Dependency.EMBEDDING not in READINESS_DEPENDENCIES


def test_hard_and_degradable_partition_all_dependencies() -> None:
    """硬依赖 ∪ 可降级依赖 == 全部依赖，且不相交（防"某个依赖无人负责"）。"""
    assert set(Dependency) == READINESS_DEPENDENCIES | DEGRADABLE_DEPENDENCIES
    assert not (READINESS_DEPENDENCIES & DEGRADABLE_DEPENDENCIES)


def test_every_dependency_has_kind() -> None:
    assert set(DEPENDENCY_KIND) == set(Dependency)


def test_stage0_expects_four_hard_two_soft() -> None:
    """阶段 0 的 `/ready`=503 正是"4 个硬依赖全未接"的体现；此处把 4 / 2 钉住。"""
    assert len(READINESS_DEPENDENCIES) == 4
    assert len(DEGRADABLE_DEPENDENCIES) == 2


# ---------------------------------------------------------------------------
# 8. 限流桶 → Retry-After 建议值
# ---------------------------------------------------------------------------

def test_rate_limit_buckets_all_have_retry_after_hint() -> None:
    missing = sorted(set(RateLimitBucket) - set(RATE_LIMIT_BUCKET_RETRY_AFTER_S))
    assert not missing, f"限流桶缺 Retry-After 建议值：{missing}"


def test_rate_limit_retry_after_is_positive_when_present() -> None:
    bad = sorted(
        bucket
        for bucket, seconds in RATE_LIMIT_BUCKET_RETRY_AFTER_S.items()
        if seconds is not None and seconds <= 0
    )
    assert not bad, f"限流桶 Retry-After 必须为正整数或 None：{bad}"
