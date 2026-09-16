"""缓存键契约断言（07 §11.1 / §11.2 / §11.5）。

归属窗口：W0（docs/08 §3.1 的 `app/cache/keys.py`）。

**为什么键要专门一个测试文件**：07 §11.2 规则 1 的失效方式**不报错** ——
少一个 `tenant_id` 的键照样能读写、照样命中、照样返回数据，只是命中的是**别人的**数据。
唯一能拦住它的是构造器级断言 + 这里的不变式。

本文件的第二项职责：把"**哪些键被允许不带租户**"钉成一份**显式清单**。
`TENANTLESS_BUILDERS` 的三条理由各不相同（全局指针 / 规则 8 唯一豁免 / 规则 1 不适用），
新增一个无租户键**必须**先在这里登记 —— 否则本测试红。
"""

from __future__ import annotations

import inspect

import pytest

from app.cache import keys

pytestmark = pytest.mark.contract

_TENANT = "t_acme"
_BUNDLE = "v1"
_OTHER_TENANT = "t_globex"

#: 期望的"无租户键"清单，作为**变量**而非字面量参与比较：
#: 直接和字面量比会被 ruff 的 SIM300（Yoda condition）判为可疑写法，
#: 而且这里的意图本来就是"清单是一份可评审的常量"，独立成常量更直白。
_EXPECTED_TENANTLESS: frozenset[str] = frozenset({"active_version", "embedding", "event_buffer"})

#: `keys.py` 中**不是键构造函数**的公共工具（不参与"必须收 tenant_id"的检查）。
_NOT_KEY_BUILDERS: frozenset[str] = frozenset({"sha256_text", "jittered_ttl", "user_scope_hash"})


# ---------------------------------------------------------------------------
# 1. 无租户键的**显式登记清单**（规则 1 / 规则 8）
# ---------------------------------------------------------------------------

def test_tenantless_set_matches_documented_exemptions() -> None:
    """`TENANTLESS_BUILDERS` 必须恰是那三个有理由的键，一个不多一个不少。"""
    assert keys.TENANTLESS_BUILDERS == _EXPECTED_TENANTLESS, (
        "无租户键清单被改动 —— 每一个都必须在 07 §11.2 有明确依据（规则 1 的判据或规则 8 的豁免）"
    )


def test_all_public_builders_are_registered() -> None:
    """`__all__` 里的构造函数 == `ALL_BUILDERS`，防止"新加了键却没进清单"。"""
    declared = {
        name
        for name in keys.__all__
        if callable(getattr(keys, name)) and name not in _NOT_KEY_BUILDERS
    }
    assert declared == keys.ALL_BUILDERS, (
        "有构造函数未登记进 ALL_BUILDERS（新增无租户键会因此逃过检查）"
    )


@pytest.mark.parametrize("name", sorted(keys.ALL_BUILDERS - keys.TENANTLESS_BUILDERS))
def test_every_tenant_scoped_builder_has_a_tenant_param(name: str) -> None:
    """除登记过的豁免键外，**每个**键构造函数都必须收 `tenant_id`。

    用签名反射而不是"读代码"——读代码看不出"参数名叫 tenant 但被忽略了"。
    """
    signature = inspect.signature(getattr(keys, name))
    assert "tenant_id" in signature.parameters, f"{name} 缺 tenant_id 参数（N-10，致命）"


@pytest.mark.parametrize("name", sorted(keys.TENANTLESS_BUILDERS))
def test_tenantless_builder_has_no_tenant_param(name: str) -> None:
    """反向守卫：登记为无租户的键**不得**偷偷收 tenant_id（列表与实现必须一致）。"""
    signature = inspect.signature(getattr(keys, name))
    assert "tenant_id" not in signature.parameters, f"{name} 已收租户参数，应从 TENANTLESS_BUILDERS 移除并更新理由"


# ---------------------------------------------------------------------------
# 2. 逐个键的格式（与 07 §11.1 的表逐行对齐）
# ---------------------------------------------------------------------------

def test_semantic_retrieval_key_format() -> None:
    key = keys.semantic_retrieval(_TENANT, _BUNDLE, "上个月销售额")
    assert key.startswith(f"sem:retr:{_TENANT}:{_BUNDLE}:")
    # 自由文本必须摘要后入键（规则 6）
    assert "上个月" not in key
    assert key.endswith(keys.sha256_text("上个月销售额"))


def test_few_shot_key_contains_tenant_and_bundle() -> None:
    """★ **U-14 的核心修正点**：`sem:fs` 曾**故意**不带租户，裁定后必须带。

    不带租户的后果不是报错，而是：租户 A 的 bad case 修正被租户 B 的 few-shot 检索召回
    （07 §11.2 规则 9 —— few-shot 内容来源含 `gold_query`，而它来自用户反馈 = 租户数据）。
    """
    key = keys.semantic_few_shot(_TENANT, _BUNDLE, "trade")
    assert key == f"sem:fs:{_TENANT}:{_BUNDLE}:trade"
    assert keys.semantic_few_shot(_OTHER_TENANT, _BUNDLE, "trade") != key


def test_embedding_key_is_tenant_free_and_hash_only() -> None:
    """★ `emb:` 是 **§11.2 规则 8 的唯一显式豁免** —— 加租户是纯损失。

    它满足豁免三条：输入全部来自已发布语义包 / 不含租户级内容 / 在 §11.1 表显式列出。
    加租户会让同一段公共定义的向量被重复计算 N 次（N = 租户数）。
    """
    key = keys.embedding("bge-m3", 1024, "orders 表：订单主表")
    assert key == f"emb:bge-m3:1024:{keys.sha256_text('orders 表：订单主表')}"
    assert _TENANT not in key


def test_embedding_key_separates_by_model_and_dim() -> None:
    """换模型/维度必须**自然失效**（§11.3），否则会用旧模型的向量冒充新模型的（静默错误）。"""
    a = keys.embedding("bge-m3", 1024, "x")
    b = keys.embedding("bge-m3", 768, "x")
    c = keys.embedding("text-embedding-3", 1024, "x")
    assert len({a, b, c}) == 3


def test_event_buffer_key_has_no_tenant_but_result_set_does() -> None:
    """`evt:` 与 `result:` 的**差别是有意的**，本测试防止有人"顺手统一"。

    事件缓冲只放 SSE 帧（键内容与命中与否都不反映租户数据 → 规则 1 不适用，登记 U-21）；
    结果集放**真结果行**（含业务明细）→ 必须带租户。
    """
    assert keys.event_buffer("task-1") == "evt:task-1"
    assert keys.result_set(_TENANT, "task-1") == f"result:{_TENANT}:task-1"


def test_session_and_rate_limit_keys_hash_user_id() -> None:
    """规则 4：键中**不得出现明文 `user_id`**（Redis `KEYS` 与监控面板会暴露它）。"""
    user_id = "u_林琪荣_12345"
    for key in (
        keys.session_lock(_TENANT, user_id, "sess-1"),
        keys.rate_limit("query", _TENANT, user_id),
    ):
        assert user_id not in key
        assert keys.user_scope_hash(user_id) in key


def test_rate_limit_key_contains_tenant() -> None:
    """§9.2 末行明确要求限流键含租户 —— 否则两个租户共用一个计数器（配额互相挤占）。"""
    assert _TENANT in keys.rate_limit("query", _TENANT, "u1")


def test_rate_limit_tenant_key_format() -> None:
    """U-38：租户合计维度键 = `rl:t:{bucket}:{tenant}`（07 §9.2 的 100/1200/300/min 承载位）。"""
    assert keys.rate_limit_tenant("query", _TENANT) == f"rl:t:query:{_TENANT}"


@pytest.mark.parametrize("bucket", ["query", "read", "write", "admin"])
@pytest.mark.parametrize("user_id", ["u1", "u2", "admin@tenant"])
def test_tenant_window_key_never_equals_user_window_key(
    bucket: str, user_id: str
) -> None:
    """防撞（U-38 的全部意义）：两个维度**在任何输入下**不得产生同一个键。

    `ratelimit.py` 的滑窗脚本对 KEYS[1]（用户）/ KEYS[2]（租户）分别判定；
    若有人"启用租户维度却复用用户键"，两个判定落在同一个 ZSET 上 ——
    用户配额被当成租户配额，限流忽然变极严**且不报错**（该文件 `_window_keys`
    的 `raise` 就是防这个）。本条把"两键不可能相等"钉在键空间层面。
    """
    user_key = keys.rate_limit(bucket, _TENANT, user_id)
    tenant_key = keys.rate_limit_tenant(bucket, _TENANT)
    assert user_key != tenant_key
    # 结构性区分：租户键第 2 段是字面量 "t"；用户键第 4 段是 16 位 user_hash —— 无重合形态
    assert tenant_key.split(":")[:2] == ["rl", "t"]
    assert user_key.split(":")[3] == keys.user_scope_hash(user_id)
    # 且 PII 纪律对租户键同样成立（tenant 明文可以，user_id 不得出现）
    assert user_id not in tenant_key


def test_active_version_is_a_global_pointer() -> None:
    assert keys.active_version() == "semantic:active_version"


# ---------------------------------------------------------------------------
# 3. 构造器的硬校验（超长 / 空片段）
# ---------------------------------------------------------------------------

def test_key_length_cap_is_enforced() -> None:
    """规则 5：键长 ≤ 200。超长说明把内容塞进了键（应改哈希）。"""
    with pytest.raises(ValueError, match="超长"):
        keys.session_plan(_TENANT, "s" * (keys.KEY_MAX_LEN + 10))


def test_empty_segment_is_rejected() -> None:
    """空租户/空会话必须**当场**炸，而不是拼出一个 `sem:retr::v1:...` 的共享键。

    这是最危险的一类拼写错误：空租户的键对所有租户都相同 —— 它不像报错，
    它像"缓存命中率很高"。"""
    with pytest.raises(ValueError, match="不得为空"):
        keys.semantic_retrieval("", _BUNDLE, "q")
    with pytest.raises(ValueError, match="不得为空"):
        keys.session_plan(_TENANT, "")


# ---------------------------------------------------------------------------
# 4. TTL
# ---------------------------------------------------------------------------

def test_every_tenant_scoped_builder_has_a_default_ttl_or_is_version_driven() -> None:
    """有租户的键要么有 TTL，要么是版本指针驱动的（few-shot 属后者）。

    ⚠️ 无 TTL 且非版本驱动的键 = 永久驻留的租户数据（PII 面 + 内存泄漏）。
    """
    version_driven = {"semantic_few_shot"}
    missing = sorted(
        name
        for name in keys.ALL_BUILDERS - keys.TENANTLESS_BUILDERS - version_driven
        if name not in keys.DEFAULT_TTL_S
    )
    assert not missing, f"以下键既无 TTL 也不是版本驱动：{missing}"


def test_ttl_values_match_appendix_a_where_specified() -> None:
    """附录 A §A.13 明文给过的 TTL 不得被改：澄清 5min、幂等 24h。"""
    assert keys.DEFAULT_TTL_S["clarify_context"] == 300
    assert keys.DEFAULT_TTL_S["idempotency"] == 24 * 3600


def test_jitter_stays_within_10_percent() -> None:
    """§11.4 防雪崩：TTL 抖动幅度必须 ±10%。"""
    base = 3600
    assert keys.jittered_ttl(base, rand=0.0) == int(base * 0.9)
    assert keys.jittered_ttl(base, rand=1.0) == int(base * 1.1)


# ---------------------------------------------------------------------------
# 5. 红线：这些键**故意不存在**（§11.5）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "forbidden_name",
    ["result_cache", "query_result_cache", "negative_cache", "empty_result_cache", "permission_cache"],
)
def test_red_line_keys_are_absent(forbidden_name: str) -> None:
    """§11.5 的红线不是"暂时没做"，是"**不得**做"：

    - 结果缓存（P0 关闭，ADR-12）；
    - **负缓存**最危险：空结果可能是 RLS 行级过滤造成的，缓存它 → 另一个角色/租户
      命中"无数据"的确定结论 = **跨租户存在性泄露**；
    - 权限判定结果（角色/策略变更无法及时生效，且计算成本极低）。
    """
    assert not hasattr(keys, forbidden_name), (
        f"{forbidden_name} 是 §11.5 红线键，不得在本模块出现；"
        f"若确有必要启用（P1），须先走 ADR 与 §11.5 修订，而不是在这里加一个函数"
    )
