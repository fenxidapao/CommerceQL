"""审计写入 —— 骨架（07 §12.4 / N-09 / ADR-14）。

归属窗口：W0 立骨架 → **W1B 实现**（docs/08 §4.1：`app/repo/**` 归 W1B；§3.1 的 §4.1 表把
审计表读写划给 `repo`，本文件是 `obs` 侧的端口实现位）。

⚠️ **归属冲突（已在交付说明中登记）**：07 §12.4 的"四重保证"第 ③ 层写的是
`repo/audit.py`，而 07 §3.2 的目录树与 docs/08 §3.1 的清单写的是 `obs/audit.py`。
两者只能有一个是权威 —— 阶段 0 按 **08 §3.1 的清单**（`obs/audit.py`）建文件，
**并在此处显式标注**，请架构窗口裁定后统一（登记为 U-18）。

**两段式结构（§12.4 的落库形态）—— 时机与阻断性都不同，实现时不得合并：**

| 段 | 表 | 时机 | 失败后果 |
|---|---|---|---|
| 段 1 | `audit_log` | `data` 事件**之前** | **阻断**：fail-closed，不发 `data`，`error(INTERNAL)` + P0 告警 |
| 段 2 | `audit_log_supplement` | `complete` 之后 | **不阻断**：结果已下发，只告警 |

**不可变性的四重保证（缺一层都不算"不可变"）**：
① DB 权限：`app_rw` 对该表**只有 INSERT**（唯一无法被应用代码绕过的一层）；
② 触发器：`UPDATE`/`DELETE` 直接抛异常（权限配错时的兜底）；
③ 代码层：只暴露 `insert()`，**无 update/delete 方法**；CI 静态断言本模块无 `UPDATE`/`DELETE` 语句；
④ 测试层：集成测试以 `app_rw` 尝试 `UPDATE`/`DELETE` → **必须失败**。

⚠️ 保留与归档：留存 ≥90 天；按月**分区**，过期用 `DROP PARTITION` 而不是逐行 `DELETE`
（逐行删既与 append-only 语义冲突，也会造成表膨胀）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.contracts import AuditSinkPort, IdentityContext

__all__ = ["AuditWriter"]


class AuditWriter(AuditSinkPort):
    """`AuditSinkPort` 的实现位（**待 W1B 实现**）。

    ⚠️ 本类的两个方法**故意不提供默认实现**：
    审计的失败语义是安全边界（fail-closed），给一个"先占位、以后再补"的空实现，
    会让"结果已经下发了但审计没写"这件事在阶段 0 就被允许 —— 那正是 N-09 要阻止的。
    """

    async def write_pre(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        """段 1：写 `audit_log`（**必须在 `data` 事件之前提交**）。"""
        raise NotImplementedError(
            "AuditWriter.write_pre 由 W1B 实现（07 §12.4 段 1 / N-09）。"
            "实现要求：与结果下发在同一逻辑事务内；失败即 fail-closed（不下发 data + P0 告警）；"
            "禁止提供 update/delete 方法。"
        )

    async def write_supp(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        """段 2：写 `audit_log_supplement`（`complete` 之后，**失败不阻断**）。"""
        raise NotImplementedError(
            "AuditWriter.write_supp 由 W1B 实现（07 §12.4 段 2 / §14.2 G2）。"
            "实现要求：失败只告警；必须覆盖'客户端取消/断连'路径（07 §18.3 步 5 —— 取消也必须留痕）。"
        )
