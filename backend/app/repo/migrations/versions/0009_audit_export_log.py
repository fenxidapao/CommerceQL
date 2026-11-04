"""0009 —— 导出审计表 `app.audit_export_log`（Phase B B2）

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04

归属窗口：Phase B B2（`计划_合并版 §4 B2`）。迁移号预留依据 = `docs/08 §4.1` 的
2026-11-02 补登记原文「`0009` 留给 B2 的 `audit_export_log`；`B` 的 `workflow_and_runs` 仍为 `0010`」。

============================================================================
一、为什么是**新表**，而不是给 `app.audit_log` 加一列 `action`
============================================================================

`app.audit_log` 的形状是**查询级两段式**：段 1（`audit_log`，fail-closed，`UNIQUE(task_id)`）
+ 段 2（`audit_log_supplement`，`task_id` 引用段 1）。这个形状本身就是 07 §14.2 G2 的判据基础。

导出是**另一个动作**，且发生在查询结束之后：

- 它没有"前段"可写 —— 数据早已下发过一次；把导出行塞进段 1 只能伪造一行 `task_id`；
- 若给 `audit_log` 加 `action` 列，则 `0001` 建立的那些 NOT NULL 列（`raw_question` /
  `outcome` / `tables_accessed` / `columns_accessed` …）对导出行**没有意义**，只能填占位值 ——
  这正是本项目已实锤四次的"一个字段两个语义"病害。

⇒ 新表只是**复制** append-only 的三重保险，不牵动既有审计表任何权限/触发器。

============================================================================
二、append-only 三重保险（与 `app.audit_log` 同款；少一条这份审计就是空话）
============================================================================

| # | 层 | 本迁移落什么 | 第三重在哪 |
|---|---|---|---|
| ① | 权限 | `GRANT INSERT, SELECT TO app_rw` + **显式** `REVOKE UPDATE, DELETE, TRUNCATE` | 本文件 |
| ② | 触发器 | `trg_audit_export_log_immutable` BEFORE UPDATE OR DELETE | 本文件 |
| ③ | 代码层 | 只暴露 `insert`，不提供 update/delete | `app/repo/audit_export_store.py` + `app/obs/audit.py` |

⚠️ ① 必须**显式** REVOKE 而不是"不给就够了"（`0001` 第 183-186 行的同款理由）：
`REVOKE ... FROM PUBLIC` 只收回**默认**权限；某次排障临时授过 `UPDATE` 又忘收回时，
只有这一行能把它掰回来 —— 而"忘收回"这件事**不会产生任何报错**（N-09 的失效方式就是静默）。

⚠️ ② 用**新的**触发器函数 `app.deny_export_log_mutation()`，不 `CREATE OR REPLACE`
`app.deny_mutation()`：后者的异常文案写死了 `'audit_log is append-only'`，复用它会让
导出表的拒绝信息指向**错误的表**。异常文案是运维唯一的定位线索，不能"差不多"。

============================================================================
三、列与约束（每一列为什么在）
============================================================================

- `export_id`：自增主键。一行 = 一次**审计已落库**的导出（审计失败时进程在落库前就止步，
  故不存在"半行"）；
- `task_id`：**外键**引用 `app.audit_log(task_id)`，`ON DELETE RESTRICT` —— 这是一条有意义的
  约束，不是形式：导出读的是那次查询的结果集缓存，而没有段 1 审计的查询不可能有结果下发
  （`audit_pre` fail-closed，N-09）⇒ 外键把"没有审计的 task 不可能被导出"变成机器判据。
  ⚠️ 与 `audit_log_supplement` 的差别：那张表 `task_id` 是主键（一 task 一段 2），
  本表一 task 可导出多次 ⇒ `task_id` 只能是外键，不能当主键；
- `tenant_id` / `user_id` / `role`：**身份一律来自服务端 `IdentityContext`**，
  不从请求体取（07 §13.1 第 2 条：让请求方决定"谁干的"等于审计失效）；
- `"timestamp"`：`DEFAULT now()`。与 `audit_log` **同名同义**，故两表可联查
  （"这次导出的查询长什么样"）；
- `export_format`：P0 唯一格式 `csv`。**不加 CHECK 约束** —— 取值集归 `core/enums`，
  在迁移里再写一份 = 枚举变更时被迫重写迁移（`0008` 对 `role` 的同款裁定）；
- `row_count` / `truncated`：**这次真正写进文件的行数**与是否被 LIMIT 截断。
  两者都来自结果集缓存的 payload（`data_frame.DATA_PAYLOAD_KEYS`），不是重新查一次库 ——
  重查会引入"导出的数据与用户看到的数据不一致"这条最坏的不一致。
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.audit_export_log (
            export_id       bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            task_id         text        NOT NULL
                            REFERENCES app.audit_log (task_id) ON DELETE RESTRICT,
            tenant_id       text        NOT NULL,
            user_id         text        NOT NULL,
            role            text        NOT NULL,
            "timestamp"     timestamptz NOT NULL DEFAULT now(),
            export_format   text        NOT NULL DEFAULT 'csv',
            row_count       integer     NOT NULL,
            truncated       boolean     NOT NULL DEFAULT false
        )
        """
    )
    # 与 `audit_log` 同款两条索引：按租户+时间查（管理端点用），按 task 联查（取证用）。
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_audit_export_log_tenant_ts '
        'ON app.audit_export_log (tenant_id, "timestamp" DESC)'
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_export_log_task_id "
        "ON app.audit_export_log (task_id)"
    )

    # ------------------------------------------------------------------
    # ① append-only：权限层
    # ------------------------------------------------------------------
    op.execute("REVOKE ALL ON app.audit_export_log FROM PUBLIC")
    op.execute("GRANT INSERT, SELECT ON app.audit_export_log TO app_rw")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON app.audit_export_log FROM app_rw")

    # ------------------------------------------------------------------
    # ② append-only：触发器层（独立函数，文案必须指向本表）
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.deny_export_log_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_export_log is append-only (07 N-09 / ADR-14)：不允许 % 操作', TG_OP;
        END; $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_export_log_immutable ON app.audit_export_log"
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_export_log_immutable
          BEFORE UPDATE OR DELETE ON app.audit_export_log
          FOR EACH ROW EXECUTE FUNCTION app.deny_export_log_mutation()
        """
    )


def downgrade() -> None:
    """回滚只删本迁移建立的对象；既有审计表一字不动。"""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_export_log_immutable ON app.audit_export_log"
    )
    op.execute("DROP FUNCTION IF EXISTS app.deny_export_log_mutation()")
    op.execute("DROP TABLE IF EXISTS app.audit_export_log")
