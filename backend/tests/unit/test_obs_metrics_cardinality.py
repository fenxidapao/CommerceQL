"""`app/obs/metrics.py` 的**基数不变式**与"补 0 / 不补 0"语义（07 §15.3 三条纪律）。

归属窗口：W7。

## 为什么单独一个文件
基数闸门（纪律 ②）的失效方向是**静默少一条序列**，而不是抛错：
`_Metric._admits()` 在"某个标签的第 N+1 个不同取值"到达时丢弃写入，只往
`metric_label_overflow_total` 记一笔。看板上看不到任何异常 —— 曲线只是"从来没有过"。
2026-09-18 的观测链路审计就抓到一处：`rule_id` 的上界写 20，而它的**域**是
`"" + R01…R20` = 21 个不同取值（空值在标签里是有语义的，见 `EMPTY_LABEL_VALUE`）。
后果不是"某一类拒绝统计不到"，而是"**哪一类统计不到取决于到达顺序**" ——
这种"随机丢"比"稳定丢"难查一个数量级，所以这里要的是**全局不变式**，不是逐例补丁。

## 本文件同时钉住的那个语义（文档反复踩到的地方）
注册表对"从未观测"的族有两种**不同**的导出行为，二者都用过"未接线"这一个词，
于是告警规则与看板把两种情况写成了同一种：
· 标签全集已知（域由枚举给全）→ **补 0 输出**（序列恒在，值为 0）；
· 既无全集又从未观测 → **整族不输出**。
差别是实际后果：前者的 `rate()` 会算出一个真实的 0（告警条件可能**恒真**），
后者是 no-data（条件根本不评估）。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest

from app.obs import metrics


def _all_specs() -> list[metrics._MetricSpec]:
    return [metric.spec for metric in metrics._REGISTRY.values()]


def test_every_declared_domain_fits_its_cardinality_cap() -> None:
    """★ 主不变式：任何一个标签的**声明域**都不得大于它的**上界**。

    域 > 上界 ⇒ 上界必然会在某个到达顺序下咬掉一个合法取值（且咬掉哪个不确定）。
    这类缺陷不可能靠"看着顺眼"发现，只能靠把两者放在一起比。
    """
    offenders: list[str] = []
    for spec in _all_specs():
        for label in spec.labels:
            cap = metrics.BOUNDED_ALLOWED_LABELS.get(label)
            domain = spec.domains.get(label)
            if cap is None:
                offenders.append(f"{spec.name}.{label}: 标签名没有声明基数上界")
                continue
            if domain is not None and len(domain) > cap:
                offenders.append(
                    f"{spec.name}.{label}: 域有 {len(domain)} 个取值 > 上界 {cap}"
                    f"（合法值会被静默丢弃，丢哪个取决于到达顺序）"
                )
    assert not offenders, "\n".join(offenders)


def test_every_metric_declares_only_registered_label_keys() -> None:
    """纪律 ② 的另一半：标签名必须在上界表里，否则闸门**根本没有上界**可言。"""
    for spec in _all_specs():
        for label in spec.labels:
            assert label in metrics.BOUNDED_ALLOWED_LABELS, (
                f"{spec.name} 用了未登记上界的标签 {label!r} —— `_admits()` 对它不设防"
            )


def test_forbidden_unbounded_labels_are_never_used() -> None:
    """纪律 ①：`user_id`/`task_id`/`session_id` 一类**永不得**成为标签（基数爆炸）。

    注册时构造即抛的那条路（`_MetricSpec` 校验）在这里再断言一次，是为了让
    "有人绕过注册直接改 `BOUNDED_ALLOWED_LABELS` 塞进 `tenant`"也留痕。
    """
    for spec in _all_specs():
        assert not (set(spec.labels) & set(metrics.UNBOUNDED_FORBIDDEN_LABELS)), spec.name


def test_observed_value_beyond_cap_is_dropped_and_counted() -> None:
    """上界**真的在拦**：第 N+1 个合法但超界的取值必须丢弃 + 计 overflow。

    为什么用 `llm_upstream_concurrency`（标签 `model`，上界 2、域缺席）：
    它是"域不限制、只靠上界"的那一类，正好单独验证闸门 ② 不依赖闸门 ③。
    """
    metrics.reset_for_tests()
    gauge = metrics._REGISTRY["llm_upstream_concurrency"]
    gauge.set_value(1.0, model="flash")
    gauge.set_value(2.0, model="pro")
    gauge.set_value(3.0, model="third-model-should-not-fit")

    assert gauge.value(model="flash") == 1.0
    assert gauge.value(model="pro") == 2.0
    text = metrics.render_prometheus_text()
    assert 'llm_upstream_concurrency{model="third-model-should-not-fit"}' not in text
    assert metrics.METRIC_LABEL_OVERFLOW_TOTAL.value(metric="llm_upstream_concurrency") == 1.0


def test_full_domain_families_export_zero_series_while_unobserved() -> None:
    """**补 0** 那一支：域已知 ⇒ 未观测也输出，值为 0。

    钉住它是为了止住一类反复出现的错误结论："序列恒 0 = 没接线 = 告警不会响"。
    恰恰相反 —— 恒 0 会让 `== 0` 型条件在**健康系统里持续为真**。
    """
    metrics.reset_for_tests()
    text = metrics.render_prometheus_text()
    assert 'query_outcome_total{outcome="refuse"} 0' in text, (
        "Outcome 五值是已知全集 ⇒ 未观测也必须出现 0 序列（否则看板要处理'序列缺席'）"
    )


def test_unknown_domain_families_are_absent_until_observed() -> None:
    """**不补 0** 那一支：既无全集又未观测 ⇒ 整族不输出（宁缺不假）。"""
    metrics.reset_for_tests()
    text = metrics.render_prometheus_text()
    # prompt_version 的取值来自运行期，注册表无从预枚举
    assert "# TYPE llm_json_parse_failure_total" not in text, (
        "该族无声明域且未观测，输出 0 等于宣称'采到了、值为 0'"
    )
    metrics.observe_json_parse_failure("p_2026_09")
    assert 'llm_json_parse_failure_total{prompt_version="p_2026_09"} 1' in (
        metrics.render_prometheus_text()
    )


def test_http_status_label_carries_status_classes_not_codes() -> None:
    """`status` 落的是**状态类**（`2xx`…`5xx`），不是三位数字。

    为什么重要：告警侧曾按 `status="429"` 写条件（附录 A 的 429 只表示配额，
    且它在 `http_requests_total` 上根本没有那个取值），那样一条规则永远不成立。
    `status` **没有声明域**（只有上界 10），所以只能这样断言行为。
    """
    metrics.reset_for_tests()
    metrics.record_http_request("/api/v1/query", 429, 0.1)
    metrics.record_http_request("/api/v1/query", 503, 0.1)
    text = metrics.render_prometheus_text()
    assert 'http_requests_total{endpoint="/api/v1/query",status="4xx"} 1' in text
    assert 'status="429"' not in text, "状态码原值进了标签 ⇒ 基数会随错误码漂移（§15.3 纪律②）"
    assert 'status="5xx"' in text


@pytest.mark.parametrize("spec", _all_specs(), ids=lambda s: s.name)
def test_help_text_is_not_empty_and_name_has_its_type_suffix(spec: metrics._MetricSpec) -> None:
    """命名口径（本文件顶部"改名/加名的唯一迁移点"那段）：名字后缀与类型一致。

    只断言**有 help** 与**后缀形态**两件事：前者保证导出面可读，后者保证
    PromQL 里 `rate()`/`histogram_quantile()` 的用法规约上成立（counter 才 `rate`）。
    """
    assert spec.help.strip(), spec.name
    if spec.name.endswith("_total"):
        assert spec.kind == metrics.COUNTER, f"{spec.name}: `_total` 后缀只能给 counter"


# ---------------------------------------------------------------------------
# ★ U-105（架构裁定 2026-09-20）：**封闭集**的越界处置与开放集**相反**
#
# 本文件上面钉的那套是"丢弃 + 计溢出"（开放集，如 `rule_id`）—— 脏数据不该打挂请求。
# 但 `assertion` 的取值域由代码里的 `ASSERTION_NAMES` 决定：出现第 5 个名字**只能是代码错误**，
# 此时"丢弃"的失效方式是把"少了一个分支"伪装成"这类断言从没红过"，而这条指标存在的目的
# 恰恰是让"带着未就绪前置条件跑起来"可见 ⇒ 必须当场抛。
# ---------------------------------------------------------------------------

_THROWAWAY = "test_closed_probe_state"


@contextlib.contextmanager
def _throwaway_closed_metric() -> Iterator[metrics._Metric]:
    """注册一个**仅测试用**的 closed 指标，用完从注册表摘掉（不污染全局导出面）。"""
    spec = metrics._MetricSpec(
        _THROWAWAY,
        metrics.GAUGE,
        help_text="仅测试用：验证封闭集的越界处置",
        labels=("assertion", "assertion_status"),
        closed=("assertion", "assertion_status"),
    )
    metric = metrics.register_metric(spec)
    try:
        yield metric
    finally:
        metrics._REGISTRY.pop(_THROWAWAY, None)


def test_closed_label_without_bound_domain_raises() -> None:
    """域未绑定 ⇒ **抛**，而不是"整族安静地不输出"。

    这条是 `bind_domain` 注入形态的代价：绑定动作丢了（或 lifespan 没跑到那一段），
    现象必须是启动当场红，而不是"看板上永远没有启动校验这一屏"。
    """
    metrics.reset_for_tests()
    with _throwaway_closed_metric() as gauge, pytest.raises(ValueError, match="尚未绑定"):
        gauge.set_value(1.0, assertion="analytics_dsn_is_read_only", assertion_status="pass")
    assert metrics.METRIC_LABEL_OVERFLOW_TOTAL.value(metric=_THROWAWAY) in (None, 0.0), (
        "封闭集越界走了'丢弃 + 计溢出'那条路 ⇒ 与 U-105 的 fail-fast 裁定相反"
    )


def test_closed_label_out_of_domain_raises_not_dropped() -> None:
    metrics.reset_for_tests()
    with _throwaway_closed_metric() as gauge:
        gauge.spec.bind_domain("assertion", ("a", "b"))
        gauge.spec.bind_domain("assertion_status", ("pass", "pending", "fail"))
        with pytest.raises(ValueError, match="域外取值"):
            gauge.set_value(1.0, assertion="c", assertion_status="pass")
        # 正向对照：域内的写入照常生效 ⇒ 上面那次抛不是"整个指标写不进"
        gauge.set_value(1.0, assertion="a", assertion_status="pending")
        assert gauge.value(assertion="a", assertion_status="pending") == 1.0


def test_closed_domain_binding_rejects_oversized_and_conflicting() -> None:
    """绑定动作自己也要 fail-fast：**超过** `BOUNDED_ALLOWED_LABELS["assertion"]` 必须抛。

    ⚠️ 这一条把"上界"与"源枚举"绑成一件事：W1B 真加断言名时，抛出的信息会直接指向
    `BOUNDED_ALLOWED_LABELS["assertion"]`，逼着改的人**带着裁定出处**去动上界，而不是顺手放宽。
    ⚠️ 域的大小**从字典读、不写字面量**：09-21 因为这里抄死了"上界是 4"，U-111 把上界抬到 5
    之后本用例假红了一次（`DID NOT RAISE`）—— 用例自己犯了它要防的那个错。
    """
    metrics.reset_for_tests()
    cap = metrics.BOUNDED_ALLOWED_LABELS["assertion"]
    with _throwaway_closed_metric() as gauge:
        # 正向对照：恰好等于上界要放行 ⇒ 下面那次抛的是"超限"，不是"任何长域都抛"
        assert gauge.spec.bind_domain("assertion", tuple(f"a{i}" for i in range(cap)))
        with pytest.raises(ValueError, match="超过基数上界"):
            gauge.spec.bind_domain("assertion", tuple(f"a{i}" for i in range(cap + 1)))
    with _throwaway_closed_metric() as gauge:   # 另起一个：上面那个已经绑掉域了
        gauge.spec.bind_domain("assertion", ("a", "b"))
        with pytest.raises(ValueError, match="不允许二次绑定"):
            gauge.spec.bind_domain("assertion", ("a", "b", "c"))
        # 同域重复绑定**放行**（幂等）：测试与 lifespan 可能各绑一次，值同源时不该炸
        assert gauge.spec.bind_domain("assertion", ("a", "b")) == ("a", "b")


def test_startup_assertion_metric_exports_full_closed_grid() -> None:
    """真实指标：域从 **repo 的源枚举**导出 ⇒ 未观测也补 0，序列数 = 4 × 3 = 12。

    刻意不硬编码 12 之外的东西：断言名与状态值都从源读，这样 W1B 改名/加名时
    这条用例只会因"上界与源不一致"而红（那是真信号），不会因为抄名漂移而假绿。
    """
    from app.repo.startup_assertions import ASSERTION_NAMES, AssertionStatus

    metrics.reset_for_tests()
    names, statuses = metrics.bind_startup_assertion_domains(
        ASSERTION_NAMES, tuple(item.value for item in AssertionStatus)
    )
    assert names == tuple(ASSERTION_NAMES), "域必须逐字来自 ASSERTION_NAMES（禁手抄的那条裁定）"
    assert metrics.BOUNDED_ALLOWED_LABELS["assertion"] >= len(names)
    text = metrics.render_prometheus_text()
    for name in names:
        for status in statuses:
            assert f'startup_assertion_state{{assertion="{name}",assertion_status="{status}"}}' in text, (
                f"封闭集已绑定 ⇒ ({name},{status}) 这一行缺失就不是'还没采到'，而是导出漏了"
            )
    assert text.count("# TYPE startup_assertion_state ") == 1
    assert sum(1 for line in text.splitlines() if line.startswith("startup_assertion_state{")) == (
        len(names) * len(statuses)
    )
    # 记一条 pass 后：同一断言的另两行仍必须是 0（"只有一行是 1" 这个口径得由导出面撑住）
    metrics.observe_startup_assertion(names[0], "pass")
    text = metrics.render_prometheus_text()
    assert f'startup_assertion_state{{assertion="{names[0]}",assertion_status="pass"}} 1' in text
    assert f'startup_assertion_state{{assertion="{names[0]}",assertion_status="fail"}} 0' in text
