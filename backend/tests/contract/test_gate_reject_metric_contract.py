"""`U-125` ① 的锁：闸门拒绝计数**只在节点侧**、且带得出 `rule_id`（07 §14.5 的分组判据）。

三条判据各钉一处，缺一条就退化：

| 判据 | 钉在哪 | 缺了会怎样 |
|---|---|---|
| **①** 本文件 | `app/graph/nodes/_shared.py::gate_update`（三闸共用收敛点）计数 | 全族恒 0（② 已把反推路径摘掉） |
| **②** | `tests/unit/test_obs_instrumentation.py`（终止帧**不再**计数） | 与节点侧**双计** |
| **③** | `tests/unit/test_obs_gate_rule_vocabulary.py`（取值域覆盖三闸字母表） | gate2/gate3 的号被"丢弃 + 计溢出" |

读数一律用**增量**而非绝对值：指标是进程级注册表，同一次 pytest 里别的用例也会计数。
"""

from __future__ import annotations

from app.core.contracts import GateResult
from app.core.enums import AstRule, GateDecision, GateNo
from app.graph.nodes._shared import gate_update
from app.obs import metrics


def _count(gate_no: GateNo, rule_id: str) -> float:
    return metrics.GATE_REJECT_TOTAL.value(gate_no=str(int(gate_no)), rule_id=rule_id)


def _reject(gate_no: GateNo, rule_id: str | None) -> None:
    gate_update({}, gate_no, GateResult(gate_no, False, GateDecision.REJECT, rule_id=rule_id))


def test_rejection_is_counted_with_its_own_rule_id() -> None:
    """gate2 的 `G2-*` 必须落在自己那条序列上（旧形态只会落 `rule_id=""`）。"""
    before = _count(GateNo.POLICY, "G2-ASSET")
    _reject(GateNo.POLICY, "G2-ASSET")
    assert _count(GateNo.POLICY, "G2-ASSET") == before + 1


def test_gate1_rejection_uses_ast_rule_vocabulary() -> None:
    """gate1 用 `AstRule` 的字面值（与 ③ 的取值域同源，不改写、不归并成空值）。"""
    rule = AstRule.R05_TABLE_ALLOWLIST.value
    before = _count(GateNo.AST, rule)
    _reject(GateNo.AST, rule)
    assert _count(GateNo.AST, rule) == before + 1


def test_three_gates_do_not_share_one_label() -> None:
    """三道闸各记各的 `gate_no`：合并成一格就没法按闸门分组了。"""
    before = {gate: _count(gate, "G2-DENY") for gate in GateNo}
    _reject(GateNo.POLICY, "G2-DENY")
    assert _count(GateNo.POLICY, "G2-DENY") == before[GateNo.POLICY] + 1
    for gate in (GateNo.AST, GateNo.COST):
        assert _count(gate, "G2-DENY") == before[gate]


def test_pass_is_not_counted() -> None:
    """通过/`warn`/`skipped` 都不算拒绝 —— 只有 `passed is False` 进这一族。"""
    total_before = metrics.GATE_REJECT_TOTAL.total()
    gate_update({}, GateNo.COST, GateResult(GateNo.COST, True, GateDecision.WARN, rule_id=None))
    assert metrics.GATE_REJECT_TOTAL.total() == total_before


def test_missing_rule_id_lands_on_empty_label_not_dropped() -> None:
    """载体真没给规则号时才落空值序列（那是"未知"，不是"反推不出来"）。"""
    before_empty = _count(GateNo.AST, metrics.EMPTY_LABEL_VALUE)
    before_total = metrics.GATE_REJECT_TOTAL.total()
    _reject(GateNo.AST, None)
    assert _count(GateNo.AST, metrics.EMPTY_LABEL_VALUE) == before_empty + 1
    assert metrics.GATE_REJECT_TOTAL.total() == before_total + 1
