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
