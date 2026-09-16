"""0001 —— 角色、schema 与审计表的 append-only 四重保证（前两重）

Revision ID: 0001
Revises: —
Create Date: 2026-09-15

归属窗口：W1B（docs/08 §3.3 产出 ③「审计两段式（§12.4 的四重保证）」）。

**本迁移做什么、为什么必须做在最前面**

07 §12.4 的 append-only 有四重保证，其中**两重只能由数据库提供**：

| # | 层 | 本迁移 |
|---|---|---|
| ① | **DB 权限**：`app_rw` 对该表**只有 INSERT** | ✅ `GRANT INSERT` + 显式 `REVOKE UPDATE/DELETE` |
| ② | **触发器**：`UPDATE`/`DELETE` 直接抛异常 | ✅ `trg_audit_log_immutable` |
| ③ | 代码层：只暴露 `insert()` | ⛔ `app/obs/audit.py`（不是迁移的事） |
| ④ | 测试层：以 `app_rw` 尝试 `UPDATE`/`DELETE` 必须失败 | ⛔ `tests/integration/`（不是迁移的事） |

⚠️ **为什么 ① 和 ② 都要做**（不是"有权限就够了"）：
权限是**可以被改的**（一次误操作的 `GRANT` 就把保证抹掉了，且不会有任何报错）；
触发器是**跟着表走的**（除非显式 DROP TRIGGER，否则一直在）。
两者失效模式不同 → 缺一不可。这正是 §12.4 写"双保险"的意思。

**诚实裁剪（必须写明，不得当作已完成）**

| 项 | 07 要求 | 本阶段做法 | 理由与触发条件 |
|---|---|---|---|
| 按月**分区** | §12.4.1「按月分区，过期 `DROP PARTITION`」 | ⛔ 未做，建**普通表** | 分区的收益是"归档时不逐行删"，而 P0 的数据量远达不到需要归档的量级；提前引入会带来"下月分区谁建"的运维依赖（W7）。**触发条件**：单表 > 5000 万行，或首次出现真实归档需求 → 那时改用 `PARTITION BY RANGE ("timestamp")`，并把 PK 改为 `(log_id, "timestamp")`（分区表 PK 必须含分区键）。⚠️ 该改动的连带影响：`audit_log_supplement` 的 FK 必须改成引用 `(task_id, "timestamp")` 或改为**去掉 FK 只留索引**（P0 建议后者）。 |
| `supplement` 的触发器 | §12.4 只对 `audit_log` 写了触发器 | ⛔ 未加 | 按文档字面执行。`supplement` 的不可变性目前只由 ① 权限层保证 —— 这一条**如实登记**，若架构窗口认为它也该有触发器（它同样是审计），补一个 `CREATE TRIGGER` 即可（零风险）。 |

**⚠️ 迁移必须由属主/超级用户执行**（`MIGRATION_DATABASE_URL`）：
`app_rw` 故意没有 `CREATEROLE` —— 那正是"最小权限"的一部分。
"""

from __future__ import annotations

import os
import re

from alembic import op

from app.repo.dsn import DsnPair

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

#: 角色密码白名单。**必须校验**：`CREATE ROLE ... PASSWORD 'x'` 的密码是**字面量**，
#: PG 不支持在 DDL 里用绑定参数 —— 于是这里成了唯一的注入面。
#: 宁可让迁移对"含引号的密码"直接失败，也不做转义字符串（转义写错 = 提权）。
_SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9_.\-]{6,64}$")


def _password_for(env_key: str, dsn_pair: DsnPair, which: str) -> str:
    """从运行时的 DSN 里取角色密码 —— **不硬编码、不新增配置项**。

    取值顺序：`APP_RW_PASSWORD` / `APP_RO_PASSWORD` 环境变量 > DSN 里的密码。
    用 DSN 里的密码是有意的：它保证"迁移建的角色"与"应用连的角色"**不可能不一致** ——
    而这两者不一致的表现是 `password authentication failed`，排查成本远高于此处。
    """
    explicit = os.environ.get(env_key)
    password = explicit or getattr(dsn_pair, which).password
    if not _SAFE_PASSWORD.match(password or ""):
        raise RuntimeError(
            f"{which} 的密码不满足白名单 {_SAFE_PASSWORD.pattern} —— "
            f"迁移拒绝把它拼进 DDL（CREATE ROLE 的 PASSWORD 无法用绑定参数，"
            f"此处是唯一的注入面）。请改用字母数字/._- 组成的密码，或通过 {env_key} 显式提供。"
        )
    return password


def _runtime_dsn_pair() -> DsnPair:
    """运行时的两条 DSN（与 `app/core/config.py` 读的是**同一组**环境变量）。"""
    return DsnPair.from_raw(
        os.environ.get("DATABASE_URL", "postgresql+psycopg://app_rw:app_rw_pwd@localhost:5432/ecom"),
        os.environ.get("ANALYTICS_DB_URL", "postgresql+psycopg://app_ro:app_ro_pwd@localhost:5432/ecom"),
    )


def upgrade() -> None:
    pair = _runtime_dsn_pair()
    rw_password = _password_for("APP_RW_PASSWORD", pair, "metadata_parsed")
    ro_password = _password_for("APP_RO_PASSWORD", pair, "analytics_parsed")

    # ------------------------------------------------------------------
    # 0. schema
    # ------------------------------------------------------------------
    # `app` = 业务与审计表；`lg` = LangGraph 检查点（§5.5 定的表族名）。
    # 刻意**不用** public：pgvector 与 LangGraph 都会建对象，
    # 混在 public 里会让"哪张表是谁的"完全看不出来（也是 RLS 策略最容易配错的地方）。
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS lg")

    # ------------------------------------------------------------------
    # 1. 两个角色（ADR-08：只读强制的物理形态 = 角色级只读）
    # ------------------------------------------------------------------
    # ⚠️ `app_ro` 的只读由**两道**构成，缺一不可：
    #   · `SET default_transaction_read_only = on`（本迁移）—— 角色级默认，连上即生效；
    #   · 无任何表级写权限（本迁移不给）—— 即使有人 `SET default_transaction_read_only = off`，
    #     也没有权限可写。
    # 启动期还有第三条（`app/repo/startup_assertions.py` 读 pg_settings 断言）——
    # 因为前两条都是"配置"，而配置**可以被悄悄改掉**（正是 N-02 要防的）。
    for role, password in (("app_rw", rw_password), ("app_ro", ro_password)):
        op.execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD '{password}'
                  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
              ELSE
                ALTER ROLE {role} LOGIN PASSWORD '{password}'
                  NOSUPERUSER NOCREATEDB NOCREATEROLE;
              END IF;
            END $$;
            """
        )
    op.execute("ALTER ROLE app_ro SET default_transaction_read_only = on")
    # `app_rw` 显式关掉它 —— 否则一旦实例级/库级把 dtr 打开，元数据写入会静默失败。
    op.execute("ALTER ROLE app_rw SET default_transaction_read_only = off")

    # ------------------------------------------------------------------
    # 2. 审计表（§12.4 段 1 / 段 2）
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.audit_log (
            log_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            task_id             text        NOT NULL,
            tenant_id           text        NOT NULL,
            user_id             text        NOT NULL,
            role                text        NOT NULL,
            "timestamp"         timestamptz NOT NULL DEFAULT now(),
            raw_question        text        NOT NULL,
            final_executed_sql  text,
            tables_accessed     text[]      NOT NULL DEFAULT '{}',
            columns_accessed    text[]      NOT NULL DEFAULT '{}',
            row_count_returned  integer,
            pii_columns_hit     text[]      NOT NULL DEFAULT '{}',
            truncated           boolean     NOT NULL DEFAULT false,
            scope_level         text,
            bundle_version      text,
            prompt_version      text,
            model_version       text,
            latency_ms          jsonb       NOT NULL DEFAULT '{}'::jsonb,
            outcome             text        NOT NULL,
            refusal_reason      text,
            -- `supplement` 的 FK 需要被引用列唯一。同时它是一条**有意义的**约束：
            -- 同一 task 不应产生两条段 1 审计（那意味着结果被下发了两次）。
            CONSTRAINT uq_audit_log_task_id UNIQUE (task_id)
        )
        """
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_ts ON app.audit_log (tenant_id, "timestamp" DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audit_log_task_id ON app.audit_log (task_id)')

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.audit_log_supplement (
            task_id             text PRIMARY KEY
                                REFERENCES app.audit_log (task_id) ON DELETE RESTRICT,
            input_tokens        integer       NOT NULL DEFAULT 0,
            output_tokens       integer       NOT NULL DEFAULT 0,
            cache_hit_tokens    integer       NOT NULL DEFAULT 0,
            cost_cny            numeric(12,4) NOT NULL DEFAULT 0,
            latency_ms_present  integer,
            chart_type          text,
            insight_hash        text,
            degradations        text[]        NOT NULL DEFAULT '{}'
        )
        """
    )

    # ------------------------------------------------------------------
    # 3. append-only：权限层（①）
    # ------------------------------------------------------------------
    op.execute("GRANT USAGE ON SCHEMA app TO app_rw")
    op.execute("GRANT USAGE ON SCHEMA app TO app_ro")
    op.execute("REVOKE ALL ON app.audit_log, app.audit_log_supplement FROM PUBLIC")
    op.execute("GRANT INSERT, SELECT ON app.audit_log, app.audit_log_supplement TO app_rw")
    # ⚠️ 显式 REVOKE 而不是"不给就够了"：`REVOKE ... FROM PUBLIC` 只收回**默认**权限，
    # 若某次运维为了排障临时授过 UPDATE 又忘了收回，只有这一行能把它掰回来 ——
    # 而"忘收回"这件事**不会产生任何报错**（N-09 的失效方式就是这样静默）。
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON app.audit_log, app.audit_log_supplement FROM app_rw")

    # ------------------------------------------------------------------
    # 4. append-only：触发器层（②）
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.deny_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log is append-only (07 N-09 / ADR-14)：不允许 % 操作', TG_OP;
        END; $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON app.audit_log")
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_immutable
          BEFORE UPDATE OR DELETE ON app.audit_log
          FOR EACH ROW EXECUTE FUNCTION app.deny_mutation()
        """
    )

    # ------------------------------------------------------------------
    # 5. LangGraph 检查点（`lg` schema）—— §5.5「与业务各自独立」
    # ------------------------------------------------------------------
    # 表本身由 `AsyncPostgresSaver.setup()` 建（它的 DDL 随库版本走，
    # 手抄一份到迁移里 = 制造第二份真相）。这里只给**建表所需的 schema 权限**。
    op.execute("GRANT USAGE, CREATE ON SCHEMA lg TO app_rw")
    op.execute("REVOKE ALL ON SCHEMA lg FROM PUBLIC")
    # ⚠️ **刻意不设** `ALTER ROLE app_rw SET search_path = ...`：
    #   · §8.1 要求 `search_path` 在**连接建立时固定**（为了让 AST-R16 的 DB 侧兜底生效），
    #     那是连接参数的事，不是角色默认值的事 —— 角色级默认值会被 `SET LOCAL` 覆盖，
    #     且改它会影响**所有** app_rw 连接（包括 alembic 自己）；
    #   · 更实际的风险：`search_path` 的第一个 schema 决定 `setup()` 把 checkpoint 表
    #     建在哪。若设成 `app, lg, public`，checkpoint 表就会落进 `app` schema，
    #     与"§5.5 说表在 lg"直接矛盾 —— 而这类错误**不会报错**，只会让 W7 的 7 天清理
    #     找不到表。→ checkpoint 的 schema 由 `AsyncPostgresSaver` 的构造参数显式指定，
    #     不靠 search_path 兜底（`app/graph/build.py` 里落实）。


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down。见 `script.py.mako` 的说明。
    pass
