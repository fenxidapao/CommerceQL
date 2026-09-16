# W4 接线提示词 —— 三道闸门节点（gate1_ast / gate2_policy / gate3_cost）

> 产出：W2C｜日期：2026-09-16｜用途：阶段 4（编排收口）启动时，把本文件全文作为 W4 窗口的开工上下文之一。

---

你负责 CommerceQL 的阶段 4 编排收口（`app/graph/**` + SSE 端点）。三道闸门的**纯函数实现已交付**（W2C，`app/guard/**`），你只做节点接线，不写闸门逻辑。以下是你需要的全部接线事实：

## 1. 调用入口（不要调 GuardPort 的瘦方法，用模块函数拿完整出参）

```python
from app.guard import run_gate1, run_gate2, run_gate3   # 完整出参
from app.guard.ast_gate import Gate1Report              # 类型

# 节点 8 gate1_ast（0.1s 预算，禁 LLM）：
report: Gate1Report = run_gate1(sql_text, allowlist)
#   report.gate_result        -> GateResult（写 state.gate_results[GateNo.AST]）
#   report.rewritten_sql      -> **最终 SQL**：写回 state.sql_text，供 gate2/gate3/execute 消费
#   report.limit_injected     -> 写 state.limit_injected（07 §5.2 组 7）
#   report.applied_predicates -> 写 state.applied_predicates
#   report.warnings           -> 告警级规则（R17–R20）记录；进 gate_detail / 日志，不下发用户
# 拒绝时：report.gate_result.rule_id / reason 已带归因；发 error(GATE_AST_REJECTED)，**不触发 repair**（07 §5.3 节点 8）

# 节点 9 gate2_policy（0.1s，禁 LLM）：
from app.guard.policy_gate import run_gate2
rep = run_gate2(report.rewritten_sql, ctx, bundle)   # bundle = SemanticBundlePort（W2A 运行时）
#   rep.gate_result / rep.scope   -> 写 state.gate_results[GateNo.POLICY] / state.scope
#   rep.refuse_reason 非 None（现仅 out_of_scope）-> 发 refuse(out_of_scope)，不是 error
#   其余拒绝 -> error(GATE_POLICY_REJECTED)

# 节点 10 gate3_cost（1.0s，禁 LLM）：
from app.guard.cost_gate import run_gate3, EXPLAIN_ERROR_DEGRADE_THRESHOLD
result = run_gate3(final_sql, {
    "explain_plan": plan_json,     # 你负责跑：EXPLAIN (FORMAT JSON)，只读连接、同事务、同身份 GUC（07 §7.5）
    # "explain_error": True,       # EXPLAIN 本身报错时置位 -> guard 判 warn
})
#   PASS -> 发 stage gate_passed（三闸门全过）；WARN -> 仍执行；REJECT -> error(COST_TOO_HIGH) + suggestions[]
#   SKIPPED（无 explain_plan，SQLite 沙箱）-> gate_status 标 not_evaluated，**不得渲染成 PASS**（D6）
#   EXPLAIN 连续报错 >= EXPLAIN_ERROR_DEGRADE_THRESHOLD(3) -> 方言级降级"仅 AST+策略"并显式标注（计数器你维护）
```

## 2. allowlist 从哪来

`bundle.asset_allowlist(ctx)`（W2A 的 `SemanticBundlePort`）。预期形状定义在 `app/guard/ast_gate.py` 模块 docstring；W2A 交付前如需联调，测试夹具 `tests/unit/guard_fixtures.py::build_allowlist()` 可直接复用（从真语义包构建）。**注意**：`max_rows`（R04 注入上限）与 `bundle_version`（gate2 版本一致性）也走这个映射。

## 3. 必须保持的顺序与红线

1. **默认谓词注入 → LIMIT 归一化 → 审计** 的顺序已在 `run_gate1` 内部锁死，不要在外部再做任何 SQL 改写。
2. `sql_text` 在 gate1 后必须替换为 `report.rewritten_sql`（审计对象 = 最终 SQL）。
3. 闸门拒绝**不触发 repair**（结构性拒绝）；只有 `execute` 层的可修错误走 repair，且 repair 产出重过 gate1。
4. 告警级规则（R17–R20）**不是拒绝**：`report.warnings` 记录后查询继续；把它们渲染成拒绝 = 误杀（U-16）。
5. `gate_detail` 必须带 `rule_id`（C-02）——三个 gate 的 `GateResult.rule_id` 已填好，原样透传。
6. 用户文案直接用 `GateResult.reason`（已做不泄露处理，红队逐条断言过）；**不要**把内部 detail 拼进用户响应。

## 4. 契约缺口（U-54/U-55 提案，见 reports/w2c/RELAY.md §1）

- GuardPort 目前没有改写类出参的通道 → 阶段 4 请先按"直接调模块函数"实现；若架构窗口裁定扩端口，再切到端口。
- gate3 的 EXPLAIN 执行（连接、事务、GUC、连续失败计数、降级标注）全部在你的节点层，guard 不持连接。

## 5. 验收锚点（你的 DoD 相关部分）

- 红队集 gate 层全绿的回归入口：`backend/tests/redteam/test_redteam_guard.py`（66 条，含负向对照）。你接线后，`graph_snapshot` 测试应覆盖：gate 拒绝 → `error` 出口路径、gate2 refuse → `refuse` 出口路径、三闸门全过 → `gate_passed`。
- W2C 收尾时全量测试基线：758 passed / 3 failed（失败均在他窗在制品，见 reports/w2c/RELAY.md §4）。
