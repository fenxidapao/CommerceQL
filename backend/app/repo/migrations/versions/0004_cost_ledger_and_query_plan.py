"""0004 —— 运行时表补建：`cost_ledger`（成本账本）+ `query_plan`（计划与绑定诊断）

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17

归属窗口：W1B（docs/08 §4.1：`app/repo/**` + migrations）。

**派单来源**：W3-INT 统一转述件 `reports/w3-int/RELAY.md §给 W1B`（两张表在迁移
0001–0003 中零命中，已由收口窗口复核）。两张表都是 07 §12.3 的既定契约：

- `cost_ledger`（§12.3:2299）：列**逐列对齐** `app/llm/budget.py::CostEntry`
  （W3A 的 Q1 裁定 = sink 注入点先行、表由 W1B 建）。表不建 = 预算熔断在
  重启面前永远失效（W3A 内存 sink 的已知限制）。
- `query_plan`（§12.3:2292 + §6.8.3:1540）：W3C DoD① 的硬前置 + W4 写计划的前提。
  ⚠️ `binding_layer` 列**不在 §12.3 的表行里**，但 §6.8.3（硬约束 5）明文要求
  「`query_plan.binding_layer` 落库（与 `binding_state` 同源）」—— 两处合起来
  就是本迁移的列集（W3-INT 转述件同此口径）。

**离线护栏**：`tests/unit/test_migration_0004_runtime_contract.py` 做两组
"防两份真相"比对 —— CostEntry 字段 ↔ 本迁移 `cost_ledger` 列、
`BindingState`/`BindingLayer` 字面值 ↔ CHECK 约束字面。**改任何一边，单测当场红。**

**刻意不做（如实登记）**：

| # | 事项 | 理由与去处 |
|---|---|---|
| 1 | **保留期清理**（cost_ledger 13 个月 / query_plan 90 天） | 保留期是**运维动作不是 DDL**：07 §12.3 的"保留"列从未对应过迁移内机制，删除走属主身份的定期清理（W7 部署侧 / runbook）。这也是不给 `app_rw` DELETE 的原因 —— 清理不该用业务账号跑 |
| 2 | `app_ro` 的任何 GRANT | 两张表都不在业务查询路径上（业务 SQL 只碰 `v_*` 视图，N-02）；07 未要求只读侧可见。若 W6/评测将来要读，另行授权（注册到 RELAY） |
| 3 | `app_rw` 的 UPDATE/DELETE | **账本行不可改**（成本对账的前提）与**计划行一次写入**（诊断口径不被事后改写）都是表语义的一部分；用权限层钉死，比"靠代码自觉"多一道真实防线（同 audit_log 第①层的取向） |
| 4 | `plan_json` 的 `schema_version` DB 侧校验 | §12.3 只说"含 `schema_version`"——结构校验归写入方（W4），jsonb 里塞什么由应用层断言，DB 不猜结构 |
| 5 | downgrade | 07 §12.6：只写 up，不写 down（同 0001/0002/0003） |
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# ============================================================================
# 取值集字面值 —— 唯一来源是 `app/core/enums.py`（W0 所有）。
# ⚠️ 这里**刻意写死字面值而不是 import**：迁移文件会被独立于应用代码执行
# （alembic 子进程），且 enums 属 W0、可能被并行修改 —— 迁移要的是**落库那一刻**
# 的冻结快照。两处漂移由离线契约单测当场抓（它两边都读、逐字比对）。
# ============================================================================

_BINDING_STATES = ("resolved_unique", "resolved_default", "ambiguous", "unresolved")
_BINDING_LAYERS = ("L1", "L2", "L3", "L4")

#: `cost_cny` 的精度。`compute_cost()` 以 `Decimal("0.000001")` ROUND_HALF_UP 量化
#: （W3A `budget.py`），NUMERIC(14,6) 恰好无损容纳该量化结果
#: （整数部分 8 位 = 单行最大 ¥99,999,999.999999，对"一次调用的成本"是充裕上界）。
_COST_PRECISION = "NUMERIC(14, 6)"

# ============================================================================
# DDL 提为模块级常量：离线契约单测直接 import 解析（"CostEntry ↔ 列"、"enums ↔ CHECK"
# 两份真相的比对点在这里），不在测试里对 upgrade() 源码做脆弱的文本手术。
# ============================================================================

_DDL_COST_LEDGER = f"""
        CREATE TABLE IF NOT EXISTS app.cost_ledger (
            entry_id         text    PRIMARY KEY,
            task_id          text    NOT NULL,
            tenant_id        text    NOT NULL,
            user_id          text    NOT NULL,
            model            text    NOT NULL,
            input_tokens     bigint  NOT NULL,
            output_tokens    bigint  NOT NULL,
            cache_hit_tokens bigint  NOT NULL,
            cost_cny         {_COST_PRECISION} NOT NULL,
            is_peak          boolean NOT NULL,
            created_at       timestamptz NOT NULL
        )
        """

_LAYERS = ", ".join(repr(ly) for ly in _BINDING_LAYERS)
_STATES = ", ".join(repr(s) for s in _BINDING_STATES)

_DDL_QUERY_PLAN = f"""
        CREATE TABLE IF NOT EXISTS app.query_plan (
            task_id         text PRIMARY KEY,
            plan_json       jsonb NOT NULL,
            plan_summary    text,
            bundle_version  text NOT NULL,
            binding_state   text NOT NULL CHECK (binding_state IN ({_STATES})),
            binding_layer   text CHECK (binding_layer IN ({_LAYERS})),
            confidence      numeric
        )
        """

_IX_COST_LEDGER = (
    # 预算聚合的两条查询路径（§12.3 原文）：
    #   tenant_spent_cny(tenant_id, day) → (tenant_id, created_at)
    #   global_spent_cny(day)            → (created_at)
    "CREATE INDEX IF NOT EXISTS ix_cost_ledger_tenant_time "
    "ON app.cost_ledger (tenant_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_cost_ledger_time ON app.cost_ledger (created_at)",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. cost_ledger —— 07 §12.3:2299 逐列 + CostEntry 逐字段（契约单测锁定）
    # ------------------------------------------------------------------
    # 注意：CostEntry 还有两个**非落库**标记（tokens_estimated / price_guess），
    # W3A 在其 docstring 明写"cost_ledger 无此列"，归属运维可观测（日志）—— 不建列。
    op.execute(_DDL_COST_LEDGER)
    for stmt in _IX_COST_LEDGER:
        op.execute(stmt)

    # ------------------------------------------------------------------
    # 2. query_plan —— 07 §12.3:2292 + §6.8.3:1540（binding_layer 同源落库）
    # ------------------------------------------------------------------
    # 可空性裁定（§12.3 未写明处的 DDL 决定，注册到 DELIVERY）：
    #   plan_json      NOT NULL —— 没有计划体的"计划行"无诊断价值，写了就是脏数据；
    #   plan_summary   NULL     —— 摘要是展示层形态，允许缺失；
    #   binding_layer  NULL     —— binding_state=unresolved 等态可能没有明确判定层
    #                              （写入方 W4/W3C 决定语义，DB 不猜）；
    #   confidence     NULL     —— 澄清/未解析路径没有置信度可言。
    # binding_state 本身 NOT NULL：它是这张表存在的理由（§12.3 脚注"必须落库"）。
    op.execute(_DDL_QUERY_PLAN)

    # ------------------------------------------------------------------
    # 3. 权限（最小化，逐表 —— 同 0002 的"禁止 GRANT ALL"纪律）
    # ------------------------------------------------------------------
    # app_rw：只写只读（INSERT/SELECT）。UPDATE/DELETE 刻意不给（见文件头 #3）：
    # 熔断聚合与诊断查询只需要这两项；"账本不可改"由权限层兜底。
    op.execute("GRANT SELECT, INSERT ON app.cost_ledger TO app_rw")
    op.execute("GRANT SELECT, INSERT ON app.query_plan TO app_rw")
    # 属主（MIGRATION_DATABASE_URL 那一组）保留全部权限 —— 保留期清理用它跑。


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001/0002/0003 的裁定）。
    pass
