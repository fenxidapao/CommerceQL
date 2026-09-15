"""日志 / 指标 / trace 字段名唯一来源（07 §15.1、§15.3、附-5）。

归属窗口：W0 立骨架 → **W7 补全**（docs/08 §4.1：`app/obs/**` = W0 → W7）。

为什么字段名要单列一个文件（07 附-5 明文要求）：
> "两者字段名必须一致，由 `obs/schema.py` 单一定义"

否则同一件事（比如"本轮用了哪个 prompt 版本"）会在日志里叫 `prompt_version`、
在指标标签里叫 `prompt_ver`，然后**看板与日志对不上号**，而这属于"能用但排不了障"，
比不能跑更难发现。

⚠️ **诚实边界（阶段 0）**：本文件当前**只收录已核实字段**（07 §15.1 的链路/身份/阶段三组）。
其余字段组（模型与版本 / 成本 / 结果与范围 / 错误）与 §15.3 的完整指标清单
**需要在 W7 开工时逐条回填** —— 阶段 0 不凭空造名字（造出来的名字一旦被 W7 沿用，
就是把"未核实的猜测"写成了契约）。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PENDING_FIELD_GROUPS_OWNER_W7", "VERIFIED_LOG_FIELD_GROUPS", "LogField", "SpanName"]


class LogField(StrEnum):
    """结构化日志字段名（JSON Lines，**字段即契约**，07 §15.1）。"""

    # 组 1｜链路（全链路贯穿，含图节点）
    TRACE_ID = "trace_id"
    TASK_ID = "task_id"
    SESSION_ID = "session_id"
    SPAN = "span"

    # 组 2｜身份（受审计要求留存）
    TENANT_ID = "tenant_id"
    USER_ID = "user_id"
    ROLE = "role"

    # 组 3｜阶段
    STAGE = "stage"
    NODE = "node"
    ELAPSED_MS = "elapsed_ms"


class SpanName(StrEnum):
    """图节点级 span 名（07 §15.2 trace 传播）。

    ⚠️ `NODE` 字段**只进日志，绝不进 SSE**（06 D2 红线）——
    把内部节点名暴露给前端等于把实现细节变成了对外契约，之后想拆节点就得走破坏性变更。
    """

    TRUSTED_CONTEXT = "trusted_context"
    NORMALIZE = "normalize"
    INTENT = "intent"
    LINK = "link"
    BIND = "bind"
    PLAN = "plan"
    GEN_SQL = "gen_sql"
    GATE1 = "gate1"
    GATE2 = "gate2"
    GATE3 = "gate3"
    EXECUTE = "execute"
    REPAIR = "repair"
    PRESENT = "present"
    AUDIT_PRE = "audit_pre"
    AUDIT_SUPP = "audit_supp"


#: 已核实并落地的字段组（对应 07 §15.1 前三行）。
VERIFIED_LOG_FIELD_GROUPS: tuple[str, ...] = ("链路", "身份", "阶段")

#: 待 W7 回填的字段组 —— 明确列出，避免"以为已经写完了"。
PENDING_FIELD_GROUPS_OWNER_W7: tuple[str, ...] = (
    "模型与版本（model / prompt_version / bundle_version / graph_version）—— 07 §15.1",
    "成本（input_tokens / output_tokens / cache_hit_tokens / cost_cny）—— 07 §15.1、PRD §14.1",
    "结果与范围（row_count / truncated / scope_level / retrieval_mode / binding_state / binding_layer）—— 07 §15.1、§12.3",
    "错误（error_code / retry_count）—— 07 §15.1、§14.5",
    "指标清单全集（含**标签基数上限**）—— 07 §15.3",
    "告警规则实现 —— 07 §15.4",
)
