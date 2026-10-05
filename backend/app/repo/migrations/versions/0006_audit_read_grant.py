"""0006 —— 审计**读**路径的授权：`app_ro` 得到 `audit_log` / `audit_log_supplement` 的 SELECT

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05

归属窗口：W8（T-37 A2，docs/08 §4.1：`app/repo/**` + migrations）。

**派单来源**：QA 第 14 轮 T-37 主单 A2 ＋ `docs/02 §A.9.5 判据块`（2026-10-05 第 12 轮，本窗落笔）。
判据① 原文：**"连接角色 = `app_ro`（只读连接），不是 `app_rw`"** ⇒ 没有这一条 GRANT，
`app/repo/audit_read.py` 的每条 SELECT 都会以权限失败收场（503 `DB_UNAVAILABLE`），
而"§A.9.5 已实现"就只是一句注释。

--------------------------------------------------------------------------
一、为什么 0001 的授权今天不够
--------------------------------------------------------------------------
`0001_roles_and_audit_append_only.py:182` 只给 `app_rw` 授了 `INSERT, SELECT`，
`app_ro` 只有 `USAGE ON SCHEMA app`（`:181`）。同文件 `:183` 的注释自己留了口子：
**"若将来要读，另行授权（注册到 RELAY）"** —— 本迁移就是那一次"另行授权"，在此登记：

| 事实 | 迁移 0001（2026-09 冻结制品） | 本迁移 |
|---|---|---|
| `app_ro` 能否 SELECT 审计两张表 | 否 | 是 |
| 读路径的连接 | 不存在读路径 | `pools.analytics`（= `app_ro`） |
| 写路径 | `pools.metadata`（= `app_rw`），fail-closed | **不变**（本迁移不动任何写权限） |

--------------------------------------------------------------------------
二、为什么只授 SELECT，且还要显式 REVOKE 一遍写权限
--------------------------------------------------------------------------
`GRANT SELECT` 单独一行看起来已经够了，但 0001 的理由在这里同样成立（原文 `:184-187`）：
`REVOKE ... FROM PUBLIC` 只收回**默认**权限，而运维为排障临时授过又忘了收回**不会有任何报错**。
⇒ 这里对 `app_ro` 显式收回 `INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER`，
让"只读"成为**幂等的落库事实**而不是"我们没给它写过"。
第二层保证本来就在：`ALTER ROLE app_ro SET default_transaction_read_only = on`（0001:120）。

--------------------------------------------------------------------------
三、🔴 刻意不做：本表的 RLS 策略（判据③ 的第二道保证）
--------------------------------------------------------------------------
判据③ 要求"服务端 `WHERE tenant_id = JWT.tenant_id` ＋ RLS 策略"两道同时成立。
本迁移**只交付得了第一道**，第二道的 DDL 落在这里会被当场拦住 ——

- `tests/unit/test_rls_policy_provenance.py` ① 扫 `versions/` 下**所有**四位前缀迁移
  （glob `[0-9][0-9][0-9][0-9]_*.py`，0006 也落入），禁止可执行常量里出现
  `CREATE POLICY` / `ENABLE|FORCE ROW LEVEL SECURITY`（ADR-10：策略只能由语义包派生）；
- 而审计表**不是语义资产** ⇒ `app/semantics/materialize.py::derive_policy_statements()`
  不会为它产出任何策略 ⇒ 派生通道与守卫通道都对它关闭。

两个必须同时知道的陷阱（`app/obs/audit.py` 的 ⑤ 段，2026-10-02 补记）：
① 只写一条 `FOR SELECT` 的策略会触发 PG 的**默认拒绝** ⇒ `INSERT` 被拒 ⇒ 审计写是
   fail-closed（NFR-3.4）⇒ **每个请求都失败**；要补必须同时给一条 `FOR INSERT WITH CHECK (true)`。
② `app/obs/audit.py` ⑤ 段写的是"本表属主 = `app_rw`，属主对 RLS 免疫 ⇒ 只 `ENABLE` 不 `FORCE` 是假边界"。
   🔻 **本窗 2026-10-05 在共享 `ecom` 上现查（只读目录查询）：该句对本表不成立** ——
   `pg_get_userbyid(relowner)` = **`postgres`**（迁移由超管连接执行 ⇒ 建表者就是超管），
   `relrowsecurity = f`、`relforcerowsecurity = f`、`pg_policies` 计数 0；
   而 6 张业务底表实测 `owner = app_rw`、`rls = t`、`force = t`（那句免疫只对**它们**成立）。
   ⇒ 对本表而言 `ENABLE`（不 `FORCE`）**已经**约束 `app_ro` 与 `app_rw` 两个非属主角色 ——
   这是好消息（不需要 `FORCE` 就能有真边界），也是坏消息（`app_rw` 的审计 INSERT 会一起被约束 ⇒ 陷阱 ① 必踩）。

⇒ 这是一个**需要裁定的冲突**（守卫覆盖面 vs 审计表非语义资产），不在本窗擅自绕过。
本轮的交付面：读路径**照做**身份 GUC 三键同语句注入（策略一旦在位即自动生效），
并把策略状态**现查**进响应（`pg_class.relrowsecurity` ＋ `pg_policies` 计数），
让"第二道保证今天不在位"成为页面可见的事实而不是文档里的一句话；
跨租户不可读由 `tests/integration/test_audit_read_rls.py` 在**一次性库**里
（测试内自造策略对）连库证明 —— 该件同时**实测**了陷阱 ①：
缺 `FOR INSERT WITH CHECK (true)` 时 `app_rw` 的审计 INSERT 报 `InsufficientPrivilege`（42501）。

**离线护栏**：`tests/contract/test_admin_audit_contract.py`（形状、错误码、限流桶、
"读路径只 SELECT"的源码级断言）＋ 上述集成件。

"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_AUDIT_TABLES = "app.audit_log, app.audit_log_supplement"

_GRANT_SELECT_TO_RO = f"GRANT SELECT ON {_AUDIT_TABLES} TO app_ro"

#: ⚠️ 不含 `SELECT`：那一格正是本次要授的。写权限逐个收回，理由见文件头第二节。
_REVOKE_WRITE_FROM_RO = (
    f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON {_AUDIT_TABLES} FROM app_ro"
)


def upgrade() -> None:
    op.execute(_GRANT_SELECT_TO_RO)
    op.execute(_REVOKE_WRITE_FROM_RO)


def downgrade() -> None:
    # 07 §12.6：只写 up，不写 down（同 0001–0005）。
    pass
