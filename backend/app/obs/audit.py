"""审计写入 —— 两段式的**策略层**（07 §12.4 / N-09 / ADR-14）。

归属窗口：W0 立骨架 → **W1B 实现**。

⚠️ **归属裁定（U-18，已由 07 §12.4.1 销账）**：审计写入落 `obs/audit.py`，
而不是 `repo/audit.py`。理由三条（原文见 §12.4.1）：审计是**横切关注点**、
分层仍然合法（`obs` 在 L1、`repo` 在 L0）、放 `repo/` 会把 fail-closed 边界
降级成"一张表的读写"。
**代价（本文件必须承担的）**：`obs/` 从此**不再是纯无副作用模块** —— 它包含一个
会**阻断主链路**的写入。约束：`obs/` 内**除本文件外**任何模块不得 import `repo`，
该约束由 `.importlinter` 的 R-DEP-3 机器化（不是纪律）。

**两段式结构 —— 时机与阻断性都不同，实现时不得合并：**

| 段 | 表 | 时机 | 失败后果 |
|---|---|---|---|
| 段 1 | `audit_log` | `data` 事件**之前** | **阻断**：fail-closed，不发 `data`，`error(INTERNAL)` + P0 告警 |
| 段 2 | `audit_log_supplement` | `complete` 之后 | **不阻断**：结果已下发，只告警 |

**不可变性的四重保证（第 ③④ 层在本文件的可见形态）：**
① DB 权限（迁移 `0001`）｜② 触发器（迁移 `0001`）｜③ **本层只暴露 `write_pre` / `write_supp`**，
**无 update/delete**（由 `tests/unit/test_audit_writer.py` 静态断言，覆盖本文件与 `repo/audit_store.py`）｜
④ 集成测试以 `app_rw` 尝试 UPDATE/DELETE 必须失败（`tests/integration/test_audit_append_only.py`）。

⚠️ **本文件不定义任何指标**：`obs/metrics.py` 明文写着"阶段 0 刻意不定义任何指标名"，
且"审计写失败率"的标签口径属 §15.3 的清单（W7）。本层用**日志**承载可见性 ——
日志字段名是契约（`obs/schema.py`），不新增指标名。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.contracts import AuditSinkPort, IdentityContext
from app.core.errors import AuditWriteFailed
from app.obs.logging import get_logger
from app.repo.audit_store import AuditSchemaMismatch, AuditStore

__all__ = ["AuditWriter"]

_logger = get_logger(__name__)


class AuditWriter(AuditSinkPort):
    """`AuditSinkPort` 的实现：**身份来自 `ctx`，payload 只带业务事实**。

    ⚠️ 为什么本类**不提供** "关闭 fail-closed 的开关"（例如 `strict=False`）：
    NFR-3.4 明确要求审计写入失败时**不得**降级为"先放过去"。
    一个这样的开关，在第一次线上抖动时就会被打开，然后再也没关回去 ——
    而它打开的正是"结果下发了、审计没记"这个窗口，那等于让 N-09 失效。
    """

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    @staticmethod
    def _identity(ctx: IdentityContext) -> dict[str, Any]:
        """`IdentityContext` → 身份列。

        ⚠️ `role` 取 `.value` 而不是传枚举对象：两者在当前实现下等价
        （`Role` 是 `StrEnum`），但传枚举依赖"驱动恰好按 str 适配"这件事；
        显式取 `.value`，让"库里存的是字符串"成为代码里看得见的事实
        （`audit_log.role` 是 `text` 列，不是 enum 类型 —— 迁移 `0001` 如此）。
        """
        return {
            "task_id": ctx.task_id,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "role": ctx.role.value,
        }

    async def write_pre(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        """段 1：写 `audit_log`（**必须在 `data` 事件之前提交**）。

        失败语义 = **fail-closed**（N-09 / ADR-14）：抛 `AuditWriteFailed`，
        调用方**不得**继续下发 `data`。

        ⚠️ 两类错误**刻意分开**：
        - `AuditSchemaMismatch`（字段名不在白名单 / 缺必填列 / 试图传身份列）→ **原样抛出**。
          它是编程错误，包装成"审计写失败"会让排查方向从"字段名写错了"偏到"数据库有问题"。
        - 其余任何异常（连接失败 / 约束冲突 / 超时）→ 包成 `AuditWriteFailed`，
          并**保留原异常链**（`from exc`）：审计失败必须能定位到根因，
          否则"审计写不进去"会变成一个永远查不出原因的高频故障。
        """
        try:
            await self._store.insert_audit_log(self._identity(ctx), payload)
        except AuditSchemaMismatch:
            raise
        except Exception as exc:
            _logger.error(
                "audit_pre_failed",
                phase="pre",
                outcome="fail_closed",
                task_id=ctx.task_id,
                error_type=type(exc).__name__,
                extra_fact="段 1 审计未落库 → 不得下发 data（N-09 fail-closed）+ P0 告警",
            )
            raise AuditWriteFailed(
                "审计写入失败，已阻断本次结果下发（N-09 fail-closed）",
                detail={"phase": "pre", "error_type": type(exc).__name__},
            ) from exc

    async def write_supp(self, ctx: IdentityContext, payload: Mapping[str, Any]) -> None:
        """段 2：写 `audit_log_supplement`（`complete` 之后，**失败不阻断**）。

        失败语义 = **只告警**（07 §14.2 G2）：结果已经下发过，此时抛异常
        只会把一次成功的查询变成一次 500，而用户看到的是一份**已经完整的结果**。

        ⚠️ `AuditSchemaMismatch` 在这里**也**不抛（与段 1 不同）：
        段 1 抛它是为了"不让脏字段流进审计表"；段 2 若抛，就会把
        "补充信息字段名写错"升级成"用户的查询失败"—— 收益为零、代价明确。
        它改由**日志**承载（`audit_supp_failed` + `error_type=AuditSchemaMismatch`），
        这才符合 §14.2 G2 的"只告警"。

        ⚠️ 本方法必须覆盖"客户端取消/断连"路径（07 §18.3 步 5、§14.2 E7）——
        但**覆盖它不靠本文件**：取消发生在调用方（W4 的 SSE 端点），
        它要在 `CancelledError` 的清理路径里**仍然调用**本方法。
        这里能做的只有"不因自身原因抛异常"，从而让调用方敢于在 `finally` 里调。
        """
        try:
            await self._store.insert_supplement(ctx.task_id, payload)
        except Exception as exc:
            _logger.error(
                "audit_supp_failed",
                phase="supp",
                outcome="non_blocking",
                task_id=ctx.task_id,
                error_type=type(exc).__name__,
                extra_fact=(
                    "段 2 审计未落库 —— 结果已下发，不阻断（07 §14.2 G2）；"
                    "但成本/token 相关统计会缺失，需告警跟进"
                ),
            )
