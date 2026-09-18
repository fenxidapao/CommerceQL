"""0005 —— 反馈自进化闭环的两张表：`feedback`（结果反馈）+ `gold_query`（Gold Query 库）

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

归属窗口：W1B（docs/08 §4.1：`app/repo/**` + migrations）。

**派单来源**：W0 RELAY `reports/w0/RELAY.md §9.1`（明写"U-20 / 迁移 0005 归 W1B"）
+ W4 决策点①（`POST /feedback` 的 `queued_for_review` / `corrected_sql` 无表可落）。
规格权威 = `docs/07 §12.3:2354-2355`（两行表定义）+ `docs/02 §A.6`（请求字段）+
`docs/07 §11.7`（Gold Query 的租户归属与检索规则）+ `docs/01 FR-11.1/11.2`。

**为什么现在能做**：U-20（`gold_query` 缺 `tenant_id`）在 07 v0.8 **已销账**（§12.3 + §11.7），
枚举侧 W0 已落 `c31f9b9`（`FeedbackReasonCode` 10 值 + `obs.trace` 的 `fb` 前缀）。

## 列集口径：以 §12.3 为准，两处"规范性规则要求但表行没写"的列**补齐并登记**

同 0004 的 `binding_layer` 先例（§12.3 表行没有、§6.8.3 明文要求 → 补列）：

| # | 补的列 | 依据（不同文档给出要求、§12.3 表行遗漏） | 不补的后果 |
|---|---|---|---|
| 1 | `feedback.correct_result_hint` | **§A.6 请求字段**明列 `correct_result_hint`（"用户认为正确的值"，⭕ 可选） | 端点收到该字段却无列可落 = **静默丢弃用户输入**。这比"少一个功能"更坏：响应仍 200，用户以为记下了 |
| 2 | `gold_query.bundle_version` | **§11.7 检索规则**的 SQL 明文 `AND bundle_version = :active_version` | 该规则**无法实现**（没有列可过滤）⇒ few-shot 会召回别的语义包版本产的 Gold Query |

两处不一致本身**登记为待裁定条目**（见 `reports/w1b/RELAY.md §12`，编号不擅自开）。

## 可空性裁定（§12.3 未写明处的 DDL 决定，注册到 DELIVERY —— 同 0004 的做法）

`feedback`：

| 列 | 决定 | 理由 |
|---|---|---|
| `is_correct` | NOT NULL | §A.6 必填；"用户说是/不是"是这张表唯一不可缺的信息 |
| `reason_code` | **NULL**（CHECK 仍生效） | §A.6 标 ⭕。⚠️ 可空 × 唯一键 = 见下"NULLS NOT DISTINCT" |
| `comment` / `corrected_sql` / `correct_result_hint` | NULL | §A.6 三个字段全为 ⭕ |

`gold_query`：

| 列 | 决定 | 理由 |
|---|---|---|
| `question` / `sql` / `domain` / `ast_fingerprint` / `bundle_version` / `source` | NOT NULL | `domain`/`ast_fingerprint` 进唯一键（可空会让唯一键失效）；`source`/"这条从哪来"是回溯与审核的最低要求 |
| `verified_by` / `verified_at` | **NULL** | Gold Query 不只有人工审核一条来源：W1A 的 `eval/gold_query_seed_v1.json`（08 §4.1 明列）与将来的批量导入**没有人工审核人**。钉成 NOT NULL 会逼写入方编一个审核人 —— 那正是"编造数据" |
| `tenant_id` | **NULL** | 不是"漏填"，是**双层库的物理判据**：`NULL` = 全局认证库（需额外审批），非 `NULL` = 租户私有（§11.7）。列注释里写死，防后来人当漏填 |

⚠️ **`source` 不做 CHECK**：07 与 PRD 都只给了列名，**没有给取值集**（不同于 `reason_code` 有 §A.6 的 10 值）。
W1B **不发明值集**；DB 只保证非空，取值由写入方（审核流程 / 种子导入）给。值集定义登记为待裁。

## 唯一约束：`UNIQUE NULLS NOT DISTINCT`（本迁移最重要的一个决定）

§A.6 幂等口径 = "同 `task_id` + 同 `reason_code` 视为同一条"，§12.3 的唯一键 = `(task_id, user_id, reason_code)`。
两者**等价**（`task_id` 函数决定 `user_id` —— 一个任务只属于一个用户），取三列形式（更明确）。

⚠️ 但 PG 里 `NULL` **互不相等**：`reason_code` 可空 ⇒ 用户不填归因时
`(task_id, user_id, NULL)` 与 `(task_id, user_id, NULL)` 被判为**不同行**，
**唯一约束形同虚设**、A.12 幂等失效（同一任务可刷无限条空归因反馈，把待审核池灌满）。

→ 用 **`UNIQUE NULLS NOT DISTINCT`**（PG 15+；本机栈 = `pgvector/pgvector:pg16`，`ci.yml:59` 同）。
不加这个子句，这条唯一键就是**看起来有、实际没有** —— 属于本项目最忌讳的"假护栏"。

## 刻意不做（如实登记）

| # | 事项 | 理由与去处 |
|---|---|---|
| 1 | **审核状态机 / `status` 列 / 审核端点** | §A.6 只定义了 `POST /feedback`（进"待审核池"），**没有定义"谁审、怎么审"的接口**。没有状态机就加 `status` 列 = 给一个没人改的字段。⇒ 审核流程（含"进全局库需额外审批"，§11.7）归**架构/W4 后续**；届时若必须落状态，另开迁移 |
| 2 | `gold_query` 的**写入通道** | 写入方 = 审核通过者，而审核接口未定义（见 #1）。表先建好，写入通道等流程落地再补（`feedback` 的写入通道本次随表交付 —— 它有明确调用方 = W4 端点） |
| 3 | `created_at` / `updated_at` | §12.3 两行都没有，且**没有任何规范性查询模式需要它**（`feedback_id`/`gold_id` 是 ULID，内嵌时间戳，用于排序展示足够；待审核池的"按时间"查询不在任何契约里）。**不为"将来大概会用到"补列**（对齐 0004 的取舍取向） |
| 4 | 保留期清理 | 两张表都是**永久**（§12.3:2443）；无清理动作，故不给属主外的 DELETE |
| 5 | `app_ro` 的 GRANT | 同 0004：两张表都不在只读业务路径上（业务 SQL 只碰 `v_*` 视图）。`gold_query` 的 few-shot 读取走 **metadata 池 = `app_rw`**（§12.3:2291 把"反馈 / Gold Query"归 metadata 池） |
| 6 | `app_rw` 的 UPDATE / DELETE | 反馈记录与 Gold Query 都是**沉淀资产**（§12.3"永久"）；事后改写会毁掉"进库门槛"这条审计链。用权限层钉死，不靠代码自觉（同 `audit_log`/`cost_ledger` 的取向） |
| 7 | `gold_query.tier` 列 | **禁止**（`app/core/enums.py::GoldQueryTier` docstring 明文）：物理判据是 `tenant_id IS NULL`，再加一个 `tier` 列 = 同一事实的第二份真相 |
| 8 | downgrade | 07 §12.6：只写 up，不写 down（同 0001–0004） |

**离线护栏**：`tests/unit/test_migration_0005_runtime_contract.py` ——
`FeedbackReasonCode` 字面值 ↔ `feedback.reason_code` 的 CHECK 字面、两表列集 ↔ 各写入通道的白名单、
以及"这是唯一一处超出 §12.3 表行的列"的显式登记（补列必须在这里被点名，防止悄悄扩散）。
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# ============================================================================
# 取值集字面值 —— 唯一来源是 `app/core/enums.py`（W0 所有）。
# ⚠️ 与 0004 同款刻意写死：迁移会被独立于应用代码的 alembic 子进程执行，要的是
# **落库那一刻**的冻结快照。两处漂移由离线契约单测当场抓（它两边都读、逐字比对）。
# ============================================================================

_FEEDBACK_REASON_CODES = (
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
)

_REASONS = ", ".join(repr(code) for code in _FEEDBACK_REASON_CODES)

# ============================================================================
# DDL 提为模块级常量：离线契约单测直接 import 解析（不在测试里对 upgrade() 做手术）。
# ============================================================================

#: ⚠️ `UNIQUE NULLS NOT DISTINCT` 见文件头 —— 少了这三个词，`reason_code` 为 NULL 时
#: 唯一约束不生效（PG 的 NULL 互不相等），A.12 幂等当场失效。
_DDL_FEEDBACK = f"""
        CREATE TABLE IF NOT EXISTS app.feedback (
            feedback_id          text PRIMARY KEY,
            task_id              text NOT NULL,
            user_id              text NOT NULL,
            is_correct           boolean NOT NULL,
            reason_code          text CHECK (reason_code IN ({_REASONS})),
            corrected_sql        text,
            comment              text,
            correct_result_hint  text,
            CONSTRAINT uq_feedback_task_user_reason
                UNIQUE NULLS NOT DISTINCT (task_id, user_id, reason_code)
        )
        """

#: ⚠️ `tenant_id` 可空**不是**疏漏：NULL = 全局认证库，非 NULL = 租户私有（§11.7 双层库）。
#: 列注释写死这条语义，否则后来人必然当成漏填。
_DDL_GOLD_QUERY = """
        CREATE TABLE IF NOT EXISTS app.gold_query (
            gold_id          text PRIMARY KEY,
            tenant_id        text,
            question         text NOT NULL,
            sql              text NOT NULL,
            domain           text NOT NULL,
            verified_by      text,
            verified_at      timestamptz,
            source           text NOT NULL,
            ast_fingerprint  text NOT NULL,
            bundle_version   text NOT NULL,
            CONSTRAINT uq_gold_query_fingerprint_domain UNIQUE (ast_fingerprint, domain)
        )
        """

_IX_GOLD_QUERY = (
    # §11.7 的检索规则是**唯一**的读路径，其 WHERE 明写 domain / bundle_version：
    #   WHERE (tenant_id IS NULL OR tenant_id = :tenant_id) AND domain = :domain
    #     AND bundle_version = :active_version
    # `(tenant_id IS NULL OR …)` 对 B-tree 不是可索引形态 ⇒ 索引建在另两个等值列上最实用。
    "CREATE INDEX IF NOT EXISTS ix_gold_query_domain_bundle "
    "ON app.gold_query (domain, bundle_version)",
)

_COMMENT_GOLD_QUERY_TENANT = (
    "COMMENT ON COLUMN app.gold_query.tenant_id IS "
    "'NULL = 全局认证库（所有租户可见，需额外审批）；非 NULL = 该租户私有（07 §11.7）'"
)
_COMMENT_FEEDBACK_REASON = (
    "COMMENT ON COLUMN app.feedback.reason_code IS "
    "'可空（§A.6 标 ⭕）。唯一键用 NULLS NOT DISTINCT，故空值也被视为同一条'"
)
_COMMENT_GOLD_QUERY_SOURCE = (
    "COMMENT ON COLUMN app.gold_query.source IS "
    "'来源。⚠️ 取值集在 07/PRD 中均未定义（只给了列名），故此处不设 CHECK；由写入方定'"
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. feedback —— 07 §12.3:2354 + §A.6 请求字段（correct_result_hint 补齐）
    # ------------------------------------------------------------------
    op.execute(_DDL_FEEDBACK)
    op.execute(_COMMENT_FEEDBACK_REASON)

    # ------------------------------------------------------------------
    # 2. gold_query —— 07 §12.3:2355 + §11.7（tenant_id 双语义 / bundle_version 补齐）
    # ------------------------------------------------------------------
    op.execute(_DDL_GOLD_QUERY)
    for stmt in _IX_GOLD_QUERY:
        op.execute(stmt)
    op.execute(_COMMENT_GOLD_QUERY_TENANT)
    op.execute(_COMMENT_GOLD_QUERY_SOURCE)

    # ------------------------------------------------------------------
    # 3. 权限（最小化，逐表 —— 同 0002/0004 的"禁止 GRANT ALL"纪律）
    # ------------------------------------------------------------------
    # app_rw：只写只读（INSERT/SELECT）。UPDATE/DELETE 刻意不给（见文件头 #6）：
    # `gold_query` 的 few-shot 读取走 metadata 池（= app_rw，§12.3:2291），
    # `feedback` 只有端点写入路径。
    op.execute("GRANT SELECT, INSERT ON app.feedback TO app_rw")
    op.execute("GRANT SELECT, INSERT ON app.gold_query TO app_rw")
    # 属主（MIGRATION_DATABASE_URL 那一组）保留全部权限 —— 审核/清理用它跑。


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001–0004 的裁定）。
    pass
