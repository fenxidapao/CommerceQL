"""U-125 ③ 的哨兵：`gate_reject_total{rule_id}` 的取值域 ⟷ 闸门源码里的规则号字面量。

**为什么要一条测试而不是一段注释**：gate2/gate3 的规则号在 `app/guard/` 里是**裸字面量**
（没有枚举），而指标侧的域是 `metrics.py` 里手抄的一份 ⇒ 两处各写一遍、漂移无感 ——
这正是本项目一周内烧过三次的那件事（U-122 判据②、W0 的夹具 DSN 哨兵都是同一味药）。
本测试用**源码扫描**钉住相等：W2C 新增一个 `G2-*` 而没同步指标侧 ⇒ 这里当场红，
而不是等到看板上"闸门拦了 500 次、一次都没有规则号"才发现。

⚠️ 收敛方向（本测试刻意不实现）：若这几号升成 `app.core.enums` 的成员，`POLICY_RULE_IDS`/`COST_RULE_IDS`
应当**删除**、改回 `_enum_values(...)` 派生，本文件随之作废（届时删掉并在 U-125 留痕）。
"""

from __future__ import annotations

import ast
import os
import re

import pytest

from app.obs import metrics

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: (源码相对路径, 该文件属于哪一闸, 指标侧对应的声明)
_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (os.path.join("app", "guard", "policy_gate.py"), "gate2", metrics.POLICY_RULE_IDS),
    (os.path.join("app", "guard", "cost_gate.py"), "gate3", metrics.COST_RULE_IDS),
)


@pytest.fixture(autouse=True)
def _clean_registry() -> object:
    """每个用例前后都清注册表 ⇒ 本文件的计数断言不依赖其它用例留下的序列。"""
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


def _rule_id_literals(rel: str) -> set[str]:
    """收集该模块里所有形如 `G2-*` / `G3-*` 的字符串常量。

    ⚠️ **为什么不盯 `rule_id=<字面量>` 这一种形状**（本测试第一版就是这么写的）：
    `policy_gate.py` 里只有 `G2-DOMAIN` 走关键字实参，另外三个走 `_reject("G2-ASSET", reason, scope)`
    的**位置实参** ⇒ 只扫关键字会漏三个，而这恰好是最坏的一种失败 —— **测试看起来是绿的**。
    漏扫比误报危险，所以退到"按号的形状收集"：`^G[23]-[A-Z]+$`。
    代价：闸门源码的**文案**里若出现同形字符串会被一起收进来 ⇒ 那条会在上面的相等断言里红，
    而不是静默漏掉。gate1 不在本函数职责内（它有 `AstRule` 枚举，指标侧由 `_enum_values` 派生）。
    """
    pattern = re.compile(r"^G[23]-[A-Z]+$")
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and pattern.match(node.value)
    }


@pytest.mark.parametrize("rel,gate,declared", _SOURCES, ids=["gate2", "gate3"])
def test_source_rule_id_literals_equal_the_declared_domain(
    rel: str, gate: str, declared: tuple[str, ...]
) -> None:
    seen = _rule_id_literals(rel)
    assert seen, f"{rel} 里一个 rule_id 字面量都没扫到 ⇒ 扫描方式过期了，本测试正在**假绿**"
    assert seen == set(declared), (
        f"{gate} 的规则号漂移：源码 {sorted(seen)} vs 指标侧 {sorted(declared)} ⇒ "
        "少的那个会被域校验丢弃，看板曲线上这一格静默归零"
    )


def test_domain_covers_three_gates_plus_empty_and_fits_the_ceiling() -> None:
    """域 = 空值 + gate1 全字母表 + gate2 + gate3，且**基数上界装得下**。

    上界写小的后果不是报错，而是"第 N+1 个合法取值被静默丢弃 + 记一次 overflow"，
    且丢哪个取决于到达顺序（`metrics.py` 里那条 20→21 的旧注释写的就是同一件事）。
    """
    domain = metrics.GATE_REJECT_TOTAL.spec.domains["rule_id"]
    assert domain == metrics.GATE_REJECT_RULE_IDS
    assert "" in domain, "空值 = '载体本轮未给规则号'，是有语义的取值，必须在域里"
    assert set(metrics.POLICY_RULE_IDS) <= set(domain)
    assert set(metrics.COST_RULE_IDS) <= set(domain)
    assert len(set(domain)) <= metrics.BOUNDED_ALLOWED_LABELS["rule_id"], (
        f"域宽 {len(set(domain))} > 上界 {metrics.BOUNDED_ALLOWED_LABELS['rule_id']} ⇒ 随机洞"
    )


def test_gate2_rule_id_is_not_blanked_into_the_empty_series() -> None:
    """正向对照（旧写法在这条上会红）：`G2-DENY` 进来，就必须落在自己那条序列上。

    旧实现 `observe_gate_reject_from_payload` 用 `AstRule(rule_id)` 试转换、`ValueError` 即置
    `None` ⇒ 三闸的号全被折进 `rule_id=""`，看板上读成"闸门拦过、但没有规则号"。
    """
    assert metrics.observe_gate_reject_from_payload(2, "G2-DENY") is True
    assert metrics.GATE_REJECT_TOTAL.value(gate_no="2", rule_id="G2-DENY") == 1
    assert metrics.GATE_REJECT_TOTAL.value(gate_no="2", rule_id="") == 0, (
        "空值序列被顺带 +1 ⇒ 本项要消灭的正是这个混淆"
    )


def test_out_of_domain_rule_id_is_dropped_and_counted_as_overflow() -> None:
    """脏值不得冒充"载体没给"：返回 False、不落序列、但溢出计数要 +1（越界必须可观测）。"""
    assert metrics.observe_gate_reject_from_payload(1, "NOT_A_REAL_RULE") is False
    assert metrics.GATE_REJECT_TOTAL.value(gate_no="1", rule_id="NOT_A_REAL_RULE") == 0
    assert metrics.GATE_REJECT_TOTAL.value(gate_no="1", rule_id="") == 0, (
        "域外值被计入空值序列 ⇒ '载体没给'与'取值不合法'两件事又被并成一件"
    )
    assert metrics.METRIC_LABEL_OVERFLOW_TOTAL.value(metric="gate_reject_total") == 1
