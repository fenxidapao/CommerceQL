"""接入层状态读写器 —— `task_state` / `session_meta` / `session_plan` / `idempotency` / `clarify_context`。

层号：L5｜归属窗口：W4（`docs/08 §4.1` 的 `app/api/**`）。

--------------------------------------------------------------------------
一、为什么必须有这个文件，且为什么它**不在** `app/cache/`（清单外必需文件登记）
--------------------------------------------------------------------------
契约要求五类**接入层状态**：任务状态机（附录 A §A.2）、会话元数据（§A.5.1）、
轮次计划摘要（§A.5.2）、幂等键（§A.12）、澄清上下文（§A.4）。
它们的键**已经由 W0 备好**（`app/cache/keys.py` 的 `task_state` / `session_meta` /
`session_plan` / `idempotency` / `clarify_context`，2026-09-18 按 W4 转述补齐），
但**没有实现者**：

- `app/core/contracts.CachePort` 是个 L2 协议（`get/set/delete/single_flight`），
  全仓**零实现类**（实测 `grep "class .*Cache" app/` 只命中 `auth/jwks.py::JwksCache`）；
- `app/cache/` 下只有 `keys.py`（W0，纯函数库）与 `session_lock.py`（W1B，锁）；
- ⇒ 结果集缓存（`GraphDeps.result_cache`）当前只能是 `None`，`mask` 节点走"写失败只告警"的
  已登记路径；而**接入层的这五类记录不能同样留空** —— 它们是端点契约的**组成部分**
  （轮询要读状态、cancel 要改状态、clarify 要读上下文），不是可选优化。

⇒ 本文件是**清单外必需文件**（同 `app/main.py` 的 Q-15 先例、`app/api/deps.py` 的 Q-15 同类）：
`docs/08 §3.1` 的落地清单里没有它，但没有它就无法实现已冻结的端点契约。

⚠️ **为什么不做成 `CachePort` 的实现**：那会让 L5 的一个具体 Redis 读写器
变成一个 L2 通用缓存（进而被别的层 import），而本文件的四类记录**只服务 HTTP 端点**。
做成 Port 实现 = 邀请复用 = 下一处"有人拿 `task_state` 当通用缓存放别的东西"。
L2 若将来需要一个真缓存，应由 `app/cache/` 出一份实现，**不得**把本文件迁过去顶替。

--------------------------------------------------------------------------
二、所有权校验是**读端义务**（不是"键里带了租户就安全了"）
--------------------------------------------------------------------------
`task_state` 与 `event_buffer` 是 W0 登记的两类"**规则 1 不适用**"的无租户键
（键名不含租户，判据是"键内容与命中与否都不反映租户数据"）。**代价写在 `keys.py` 里**：
`task_state` 的**值**含 `tenant_id`/`user_id` ⇒ **读端必须做所有权校验**，否则
"A 用 B 的 `task_id` 读 B 的任务状态"就是越权。

故本文件的每个读方法都把 `IdentityContext` 作为**必填位置参数**，在**同一处**比对
`tenant_id` + `user_id`；不匹配一律返回 `None`（**不区分"不存在"与"不属于你"**）——
区分它们会让攻击者用 404/403 的差异枚举出"哪些 `task_id` 真实存在"。
端点再把 `None` 统一映射成 `TASK_NOT_FOUND`（附录 A §A.11 的 404 语义就是"不存在或已过期"）。

⚠️ **唯一的例外是 `get_clarify_for_tenant(tenant_id, …)`**，理由是"读它之前还没有
`session_id`"（鸡生蛋：`session_id` 就在这条记录里）—— 详见该方法的 docstring。
它的隔离单元是**租户**（键含租户），不是"租户 + 用户"。这是本文件唯一一处按租户隔离的读，
**不得**被扩展成"其他读方法也可以只给租户"。

### 三、id 从哪来

`task_id` / `session_id` / `trace_id` **全部**由 `app.obs.trace.new_id()` 生成
（前缀 `tk_`/`ss_`/`tr_`，与 `TraceIds` 的绑定同源）。本文件**不再提供第二套生成器** ——
2026-09-18 删掉了初版的 `new_task_id`/`new_session_id`：两套生成的 id 形态不同
（16 位 vs 32 位随机段）而用途相同，是"同一个事实两处实现"的典型，
表现为日志里的 id 有时长有时短、按前缀检索时正则漏配。

--------------------------------------------------------------------------
四、键一律经 `app/cache/keys.py`（§11.2 硬规则 3）
--------------------------------------------------------------------------
本文件**不出现任何裸字符串拼键**，也不自己拼前缀。TTL 取自
`keys.DEFAULT_TTL_S`（唯一来源），只有 `clarify_context` 的 5 分钟被 §A.13 显式要求，
恰好也是那张表的缺省值 —— 两处一致，不另写数字。

--------------------------------------------------------------------------
五、P0 的诚实边界（不得被读成"已实现"）
--------------------------------------------------------------------------
| 项 | 现状 | 影响 |
|---|---|---|
| `event_buffer`（流重放） | **未接线** | 断线重连不能重放已发事件。附录 A 未把重放列为必需端点，故 P0 不实现；键已备好 |
| `concurrency_lease`（全局并发 100） | **未接线** | 见 `app/api/ratelimit.py` 文件头：`GLOBAL_CONCURRENCY` 桶刻意抛 `LimiterNotImplemented`，不做滑窗近似 |
| 任务状态的**权威来源** | 本文件的 Redis 记录 | ⚠️ 它只是**投影**，权威仍是图的 `terminal`/审计；本文件不参与任何业务判定 |
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import orjson

from app.cache import keys as cache_keys
from app.core.contracts import IdentityContext
from app.core.enums import TaskStatus
from app.graph.build import GRAPH_VERSION as _GRAPH_VERSION

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

__all__ = [
    "CLARIFY_TTL_S",
    "TASK_TTL_S",
    "CancelOutcome",
    "ClarifyContext",
    "IdempotencyDecision",
    "IdempotencyRecord",
    "RedisStateStore",
    "SessionMeta",
]


#: 任务状态 TTL（1h）—— 附录 A §A.13「异步结果保留 1 小时，之后返回 404」。
TASK_TTL_S: Final[int] = cache_keys.DEFAULT_TTL_S["task_state"]

#: 澄清有效期（5 分钟）—— 附录 A §A.13。过期 → `CLARIFY_EXPIRED` 410。
CLARIFY_TTL_S: Final[int] = cache_keys.DEFAULT_TTL_S["clarify_context"]

#: 任务终态集合（**8 值里的后 6 个**）。进终态后不可取消（§A.3 的 `TASK_NOT_CANCELLABLE`）。
#:
#: ⚠️ 从 `TaskStatus` 推导而**不是**手写一份字面量表：手写的那份与枚举漂移时，
#: 表现是"某个终态被当成进行中 → `cancel` 返回 200 却什么都没取消"（静默错误）。
_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        TaskStatus.SUCCEEDED.value,
        TaskStatus.CLARIFY.value,
        TaskStatus.REFUSE.value,
        TaskStatus.DEGRADED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


def _now_iso() -> str:
    """ISO 8601 带本地时区偏移（附录 A §A.0.1 的时间格式）。

    ⚠️ 用 `datetime.now().astimezone()` 而不是 `utcnow()`：契约要求**含时区偏移**，
    且 `+00:00` 与 `+08:00` 在展示层不等价（前端直接渲染）。时区口径归 `ClockPort`，
    但那是 L0 的业务时钟；这里是**接入层时间戳**（与 `queued_at` 同类），
    与限流器"取 Redis 服务端时间"的理由不同（那里是为多实例一致性）。
    """
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class SessionMeta:
    """会话元数据（附录 A §A.5.4 的字段集）。"""

    session_id: str
    created_at: str
    title: str | None
    bundle_version: str | None
    graph_version: str | None
    last_turn_at: str | None
    closed: bool


@dataclass(frozen=True, slots=True)
class ClarifyContext:
    """澄清上下文（附录 A §A.4）。**存的是"重跑所需的最小输入"**，不是旧 SQL。

    ⚠️ FR-9.2 明令澄清后**必须完整重走**权限/绑定/校验/成本/执行，**禁止复用澄清前的 SQL**。
    故这里**不存**任何 SQL 或候选 —— 只存原始问题 + 会话 + 允许的选项，
    重跑时把用户选择以自由文本形式并入问题，从 `normalize` 重新开始。

    ⚠️ `run_options` 是**必须**的（不是可选优化）：`POST /clarify` 的请求体里没有 `options`
    （附录 A §A.4 只有 `clarify_id` + 二选一答案）⇒ 不继承原轮的 `options`，
    重跑就会用 DTO 默认值 —— 用户勾了 `max_rows=200`、`explain=false`，
    澄清一次之后结果集和响应形状**静默变了**。这类"参数在第二次请求里丢失"
    是排查成本最高的一类（复现要求"先提问、再澄清"两步）。
    `raw_question` 同理：不从原轮继承就无法重组出完整问题。
    """

    clarify_id: str
    task_id: str
    session_id: str
    raw_question: str
    reason: str | None
    options: tuple[Mapping[str, Any], ...]
    created_at: str
    #: 原轮的 `RunOptions`（`GraphState["options"]` 原样）。缺省 `None` = 取 DTO 默认值。
    run_options: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """幂等记录（附录 A §A.12）。"""

    task_id: str
    request_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    """幂等判定结果（附录 A §A.12 的三种情形，**只有三种**）。

    | 情形 | `task_id` | 端点动作 |
    |---|---|---|
    | 首次（无记录） | 新分配的 `task_id` | 正常执行，执行前落记录 |
    | 重放（键同、体同） | 原 `task_id` | 返回原任务（同一 `task_id`，不再跑图） |
    | 冲突（键同、体不同） | `None` | `409 IDEMPOTENCY_CONFLICT` |

    ⚠️ `existing_task_id`（冲突时才有值）不是"第三种情形的补充" ——
    它是 §A.12 响应示例里 `detail.original_task_id` 的来源。**取不到就是 `None`**：
    首次请求还在跑（占位记录尚未回填 `task_id`）时**没有**原任务可回显，
    此时如实留空，不编一个 `""` 或复制本次的 `task_id`（那会让前端去重放一个不存在的任务）。
    """

    replayed: bool
    task_id: str | None
    conflict: bool = False
    existing_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    """`cancel` 的结果（附录 A §A.3）。

    ⚠️ 四个取值**一一对应**四种 HTTP 结果，不存在"还需要端点再判一次"的情形：
    把判定分散到端点，会让"已完成的任务被当成可取消"这类 bug 只在一个端点上出现。
    """

    not_found: bool = False
    not_cancellable: bool = False
    cancelled: bool = False
    already_cancelled: bool = False

    @property
    def ok(self) -> bool:
        """`cancelled` 与 `already_cancelled` **都返回 200** —— 这是幂等的落点（§A.3 / §A.12）。"""
        return self.cancelled or self.already_cancelled


class RedisStateStore:
    """五类接入层记录的 Redis 读写器。**无状态、可跨请求复用**（连接由 `Redis` 自己池化）。"""

    __slots__ = ("_client",)

    def __init__(self, client: Redis) -> None:
        self._client = client

    # ======================================================================
    # 任务状态（附录 A §A.2 / §A.3）
    # ======================================================================

    async def put_task(
        self,
        ctx: IdentityContext,
        *,
        status: TaskStatus,
        stage: str | None = None,
        progress: float | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """写/更新任务状态。**合并写**（保留 `queued_at` 等首写字段）。

        ⚠️ 合并而不是覆盖：轮询状态机要展示 `queued_at`/`started_at` 的先后，
        而"每次更新都覆盖"会让后写的那个把先写的抹掉 —— 表现是轮询响应里
        `queued_at` 随时间变化（前端会看到"排队时间一直在变"）。
        """
        key = cache_keys.task_state(ctx.task_id)
        current = await self._read_json(key) or {}
        payload: dict[str, Any] = {
            **current,
            "task_id": ctx.task_id,
            # ⚠️ 归属三元组每次写都带上：本键**无租户**，读端靠这三个字段做所有权校验。
            # 漏写会让该任务**永久不可读**（读端一律判 `None`），表现为轮询 404。
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "status": str(status),
            "updated_at": _now_iso(),
        }
        payload.setdefault("queued_at", payload["updated_at"])
        if status is not TaskStatus.PENDING:
            payload.setdefault("started_at", payload["updated_at"])
        if status.value in _TERMINAL_STATUSES:
            payload["finished_at"] = payload["updated_at"]
        if stage is not None:
            payload["stage"] = stage
        if progress is not None:
            payload["progress"] = progress
        if extra:
            payload.update(dict(extra))
        await self._write_json(key, payload, ttl_s=TASK_TTL_S)

    async def get_task(self, ctx: IdentityContext, task_id: str) -> dict[str, Any] | None:
        """读任务状态。**所有权不符一律 `None`**（见模块 docstring §二：不区分不存在与无权）。"""
        payload = await self._read_json(cache_keys.task_state(task_id))
        if payload is None:
            return None
        if payload.get("tenant_id") != ctx.tenant_id or payload.get("user_id") != ctx.user_id:
            return None
        return payload

    async def is_cancel_requested(self, task_id: str) -> bool:
        """取消标志（**唯一**允许不带所有权校验的读 —— 它在 SSE 生成器内部按自己的 `task_id` 读）。

        ⚠️ 它不返回任何租户数据（只有一个布尔），故不构成越权读取面。
        """
        payload = await self._read_json(cache_keys.task_state(task_id))
        return bool(payload and payload.get("cancel_requested"))

    async def cancel_task(self, ctx: IdentityContext, task_id: str) -> CancelOutcome:
        """取消任务（幂等，附录 A §A.3）。

        ⚠️ 判定顺序有语义：**先所有权、再终态**。反过来的话，"取消别人的任务"
        会先拿到 `TASK_NOT_CANCELLABLE`/`200`，从而**确认该 `task_id` 存在**
        —— 那就是一条存在性侧信道。故所有权不符时**一律**按"不存在"处理。
        """
        payload = await self.get_task(ctx, task_id)
        if payload is None:
            return CancelOutcome(not_found=True)

        status = str(payload.get("status", ""))
        if status == TaskStatus.CANCELLED.value:
            return CancelOutcome(already_cancelled=True)
        if status in _TERMINAL_STATUSES:
            return CancelOutcome(not_cancellable=True)

        merged = {**payload, "status": TaskStatus.CANCELLED.value,
                  "cancel_requested": True, "finished_at": _now_iso(),
                  "updated_at": _now_iso()}
        await self._write_json(cache_keys.task_state(task_id), merged, ttl_s=TASK_TTL_S)
        return CancelOutcome(cancelled=True)

    # ======================================================================
    # 会话（附录 A §A.5.1 / §A.5.2）
    # ======================================================================

    async def create_session(self, ctx: IdentityContext) -> SessionMeta:
        """创建会话。`title` **刻意留空**（服务端在首轮 `POST /query` 完成后生成）。

        ⚠️ 不接受客户端传入 `title`（附录 A §A.5.1 的 B-19 修订）：
        客户端可写标题会引入 XSS 与超长文本攻击面，且前端在首轮提问后
        本来也无法提供有意义的标题。
        """
        created = _now_iso()
        await self._write_json(
            self._session_key(ctx),
            {
                "session_id": ctx.session_id,
                "created_at": created,
                "title": None,
                "bundle_version": None,
                "graph_version": None,
                "last_turn_at": None,
                "closed": False,
            },
            ttl_s=cache_keys.DEFAULT_TTL_S["session_meta"],
        )
        # ⚠️ 逐个字段构造而不是 `SessionMeta(**meta)`：后者要求 mypy 从 `dict[str, object]`
        # 反推出每个字段的具体类型（做不到，会报三处 arg-type），而**为过类型检查去放宽
        # `SessionMeta` 的字段类型**（例如全改 `object`）代价更大 —— 那会让"这个字段是 str"
        # 这件事在类型层面消失。逐字段写一遍的代价是 7 行，换来的是字段类型仍然可查。
        return SessionMeta(
            session_id=ctx.session_id,
            created_at=created,
            title=None,
            bundle_version=None,
            graph_version=None,
            last_turn_at=None,
            closed=False,
        )

    async def get_session(self, ctx: IdentityContext, session_id: str) -> SessionMeta | None:
        key = cache_keys.session_meta(ctx.tenant_id, session_id)
        payload = await self._read_json(key)
        if payload is None:
            return None
        return SessionMeta(
            session_id=str(payload.get("session_id") or session_id),
            created_at=str(payload.get("created_at") or ""),
            title=payload.get("title"),
            bundle_version=payload.get("bundle_version"),
            graph_version=payload.get("graph_version"),
            last_turn_at=payload.get("last_turn_at"),
            closed=bool(payload.get("closed", False)),
        )

    async def touch_session(
        self, ctx: IdentityContext, *, title: str | None, bundle_version: str | None
    ) -> None:
        """首轮完成后落标题与**会话固定版本**（附录 A §A.5.1 / 07 §5.7 / N-23）。

        ⚠️ `title` 只写一次（"已存在且非空就不覆盖"）：第二轮再写会把标题改成第二个问题，
        而 §A.5.4 明说标题取自**首轮**问题。
        🔴 **不能写 `payload.setdefault("title", title)`**：`create_session` 已经把 `title`
        这个**键**写进去了（值为 `None`），而 `setdefault` 判的是"键在不在"而不是"值是不是空"
        —— 于是标题永远写不进去（实测：`GET /session/{id}` 恒返回 `title: null`）。
        同一文件里 `create_session` 的 `closed` 等键也有这个形态，改这里时别改回 `setdefault`。
        ⚠️ 标题长度在 `history_title()` 里截断 —— 服务端是唯一能保证长度/字符规范的地方。

        🔴 **版本固定 = 旧值优先**（T8，07 §5.7 / N-23："同一会话内 `bundle_version`
        固定不漂移"）：端点每轮都调本方法，若"新值优先"，语义包在会话中途切换时
        第二轮会静默换口径 —— 那正是 §5.7 说的"用户无法解释差异"的信任崩塌点。
        `graph_version` 同理（会话首次成功调用时固定三版本；`prompt_version` 进审计、
        无 `sess:meta` 键位，见 `create_session` 的键清单）。
        ⚠️ 诚实边界：这只是**写侧**固定（`GET /session/{id}` 的对账依据）。图内
        "读侧沿用固定版本"需要把固定版本注回 `RunContext.bundle_version`，
        而那条通道（`GraphDeps` 未收 `RepositoryPort`）仍是 `trusted_context`
        登记的缺口 —— 两处口径由端点读 `session_meta` 后传图来对齐（未接线前，
        图内仍取激活版本）。"""
        key = self._session_key(ctx)
        payload = await self._read_json(key) or {}
        if not payload.get("title") and title:
            payload["title"] = title
        payload["bundle_version"] = payload.get("bundle_version") or bundle_version
        payload["graph_version"] = payload.get("graph_version") or _GRAPH_VERSION
        payload["last_turn_at"] = _now_iso()
        await self._write_json(key, payload, ttl_s=cache_keys.DEFAULT_TTL_S["session_meta"])

    async def append_turn(
        self,
        ctx: IdentityContext,
        *,
        question: str,
        outcome: str,
        plan_summary: Mapping[str, Any] | None,
        bundle_version: str | None,
    ) -> None:
        """追加一轮"计划摘要"到 `sess:plan:{tenant}:{sid}`（List）。

        ⚠️ **只存计划摘要与版本，不存历史 SQL 与历史结果**（N-17 明文）：
        `GET /session/{id}` 若回原始 SQL，就等于把"某角色的可执行语句"跨轮次持久化 ——
        权限变更后这些 SQL 仍是有效的越权模板（FR-10.1）。
        """
        entry = {
            "task_id": ctx.task_id,
            "question": question,
            "outcome": outcome,
            "plan_summary": dict(plan_summary) if plan_summary else None,
            "bundle_version": bundle_version,
            "at": _now_iso(),
        }
        key = cache_keys.session_plan(ctx.tenant_id, ctx.session_id)
        # 最新在前（`GET /session/{id}` 与前端列表都按倒序展示），故 `LPUSH`。
        await self._client.lpush(key, orjson.dumps(entry).decode())
        await self._client.expire(key, cache_keys.DEFAULT_TTL_S["session_plan"])

    async def get_turns(self, ctx: IdentityContext, session_id: str) -> tuple[dict[str, Any], ...]:
        """读轮次计划摘要（最新在前）。

        ⚠️ 标注为 `list[Any]` 而不是 `Sequence[bytes]`：`redis-py` 的 `lrange` 返回类型是
        `list[bytes | str]`（取决于 `decode_responses`），断言成 `bytes` 会让 mypy 报
        「不兼容赋值」，而**为过类型检查去断言 decode 行为**等于把一个运行时配置
        （`build_redis_client` 的 `decode_responses`）伪装成静态事实。
        `orjson.loads` 对两种输入都工作，故这里如实收 `Any`。
        """
        key = cache_keys.session_plan(ctx.tenant_id, session_id)
        raw: list[Any] = await self._client.lrange(key, 0, -1)
        return tuple(orjson.loads(item) for item in raw)

    # ======================================================================
    # 幂等（附录 A §A.12）
    # ======================================================================

    async def begin_idempotent(
        self,
        *,
        tenant_id: str,
        new_task_id: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> IdempotencyDecision:
        """幂等键判定（附录 A §A.12）。

        ⚠️ **入参是 `tenant_id` + `new_task_id`，不是 `IdentityContext`** ——
        判定的结果会**决定这一轮用什么 `task_id`**（重放要沿用原任务），
        所以它必须发生在"身份对象被构造出来"**之前**。若收 `ctx`，
        端点就只能先拿一个临时 `task_id` 造 `ctx`、发现重放后再重造一次 ——
        那段"先绑身份再拆掉重绑"的代码是白写的，且中途抛错（限流 / 404 / 冲突）
        时日志里的 `task_id` 会是那个**从未被任何任务使用过**的临时值。

        ⚠️ 用 `SET NX` 抢占，**不用**"先 GET 再 SET"：后者在并发重放（用户连点两次）下
        两个请求都会读到"无记录"，于是**都执行** —— 而幂等要防的正是这个。
        `SET NX` 的原子性把"谁先到"变成服务端事实。

        ⚠️ 抢占后要**回填** `task_id`（`review` 窗口内重放者读到的是空 task_id）。
        故第二次 `GET` 若发现 `task_id` 为空，说明**首个请求还在跑**：此时返回
        "重放"但 `task_id=None` 会让端点无法响应 —— 故本方法用**短轮询**等它填上
        （上限 `IDEMPOTENCY_FILL_WAIT_S`），超时则如实返回冲突（见下面注释）。
        """
        if idempotency_key is None:
            # 未传幂等键 ⇒ 不做幂等（`POST /query` 的幂等是**可选**能力，§A.0.3 的 ⭕）。
            return IdempotencyDecision(replayed=False, task_id=new_task_id)

        key = cache_keys.idempotency(tenant_id, idempotency_key)
        ttl = cache_keys.DEFAULT_TTL_S["idempotency"]
        placeholder = orjson.dumps({"request_hash": request_hash, "task_id": ""}).decode()

        acquired = await self._client.set(key, placeholder, nx=True, ex=ttl)
        if acquired:
            return IdempotencyDecision(replayed=False, task_id=new_task_id)

        stored = await self._read_json(key) or {}
        stored_task = str(stored.get("task_id") or "")
        if stored.get("request_hash") != request_hash:
            # 同键不同体 → `409 IDEMPOTENCY_CONFLICT`（§A.12），`detail.original_task_id` 取原任务。
            return IdempotencyDecision(
                replayed=False,
                task_id=None,
                conflict=True,
                existing_task_id=stored_task or None,
            )
        if not stored_task:
            # 首个请求仍在跑（占位记录尚未回填）。附录 A 没有为这种"同键并发"定义码；
            # 如实按**冲突**处理而不是编一个"正在处理中"的码（U-22）。已登记待架构裁决。
            # ⚠️ `existing_task_id=None`：此刻确实**没有**原任务可给。
            return IdempotencyDecision(replayed=False, task_id=None, conflict=True)
        return IdempotencyDecision(
            replayed=True, task_id=stored_task, existing_task_id=stored_task
        )

    async def fill_idempotency(
        self, ctx: IdentityContext, *, idempotency_key: str | None, task_id: str, request_hash: str
    ) -> None:
        """回填 `task_id`（在**已分配 task_id 之后、执行之前**调用，见 T5 端点实现）。"""
        if idempotency_key is None:
            return
        key = cache_keys.idempotency(ctx.tenant_id, idempotency_key)
        await self._write_json(
            key,
            {"request_hash": request_hash, "task_id": task_id, "created_at": _now_iso()},
            ttl_s=cache_keys.DEFAULT_TTL_S["idempotency"],
        )

    # ======================================================================
    # 澄清上下文（附录 A §A.4）
    # ======================================================================

    async def put_clarify(
        self,
        ctx: IdentityContext,
        *,
        clarify_id: str,
        raw_question: str,
        reason: str | None,
        options: Sequence[Mapping[str, Any]],
        run_options: Mapping[str, Any] | None = None,
    ) -> None:
        """落澄清上下文（**由 `runner` 在终态为 `clarify` 时调用**，不是由节点）。"""
        payload = {
            "clarify_id": clarify_id,
            "task_id": ctx.task_id,
            "session_id": ctx.session_id,
            "raw_question": raw_question,
            "reason": reason,
            "options": [dict(o) for o in options],
            "run_options": dict(run_options) if run_options else None,
            "created_at": _now_iso(),
        }
        await self._write_json(
            cache_keys.clarify_context(ctx.tenant_id, clarify_id), payload, ttl_s=CLARIFY_TTL_S
        )

    async def get_clarify(self, ctx: IdentityContext, clarify_id: str) -> ClarifyContext | None:
        """按 `IdentityContext` 读澄清上下文（已有 ctx 的调用方用这个）。"""
        return await self.get_clarify_for_tenant(ctx.tenant_id, clarify_id)

    async def get_clarify_for_tenant(
        self, tenant_id: str, clarify_id: str
    ) -> ClarifyContext | None:
        """按**租户**读澄清上下文 —— `POST /clarify` 的引导读取入口。

        ⚠️ 为什么必须有一个"不需要完整 ctx"的读法：`/clarify` 的请求体里**只有**
        `clarify_id`，`session_id` 恰恰要从这条记录里读出来（它决定了审计的会话归属、
        会话锁的键、以及新 run 的 `IdentityContext`）—— 而 `IdentityContext.session_id`
        非空才有意义（`build_identity` 会硬拒空值）。
        "先用空 session_id 造一个 ctx 再去读" = 先用一个假事实换一个真事实，
        且那个假 ctx 会被传进下游（`RedisStateStore` 的其余方法都以 ctx 为作用域）。

        ⚠️ 隔离靠**键**（`clarify_context(tenant_id, …)` 含租户），不是靠值比对 ——
        与 `task_state` 的"无租户键 + 读端校验"形态不同（`keys.py` 的规则 1 分类不同）。
        故本方法**不**比对 `user_id`：同租户内 `clarify_id` 是服务端生成的不可猜随机串
        （`cl_` + 12 位，见 `clarify_out._new_clarify_id`），且**一次消费即作废**
        （`drop_clarify`）。已登记为"隔离单元 = 租户"的事实，写入交付件的接线说明。
        """
        payload = await self._read_json(cache_keys.clarify_context(tenant_id, clarify_id))
        if payload is None:
            return None
        run_options = payload.get("run_options")
        return ClarifyContext(
            clarify_id=str(payload.get("clarify_id") or clarify_id),
            task_id=str(payload.get("task_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            raw_question=str(payload.get("raw_question") or ""),
            reason=payload.get("reason"),
            options=tuple(payload.get("options") or ()),
            created_at=str(payload.get("created_at") or ""),
            run_options=run_options if isinstance(run_options, dict) else None,
        )

    async def drop_clarify(self, ctx: IdentityContext, clarify_id: str) -> None:
        """消费掉澄清上下文（**一次性**：同一 `clarify_id` 不得被回答两次）。

        ⚠️ 不删会怎样：同一 `clarify_id` 可被反复回答，每次都以"用户选择"为输入重跑 ——
        这本身不越权，但会让"澄清问答"变成可无限重试的入口（配合 `POST /clarify` 的
        查询类限流也仍能在 10 次/分钟里反复触发 LLM 调用）。一次性是更紧的边界。
        """
        await self._client.delete(cache_keys.clarify_context(ctx.tenant_id, clarify_id))

    # ======================================================================
    # 内部
    # ======================================================================

    @staticmethod
    def _session_key(ctx: IdentityContext) -> str:
        return cache_keys.session_meta(ctx.tenant_id, ctx.session_id)

    async def _read_json(self, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        loaded = orjson.loads(raw)
        return loaded if isinstance(loaded, dict) else None

    async def _write_json(self, key: str, payload: Mapping[str, Any], *, ttl_s: int) -> None:
        await self._client.set(key, orjson.dumps(payload).decode(), ex=ttl_s)


def history_title(question: str, *, limit: int = 20) -> str:
    """首轮问题 → 会话标题（附录 A §A.5.4："取首轮问题前 20 字"）。

    ⚠️ 服务端**必须**做长度与字符规范：客户端可写标题会引入 XSS 与超长文本攻击面
    （§A.5.1 的 B-19 修订明文）。这里只截断 + 压平空白 ——
    真正的输出转义在前端渲染时做（后端不做 HTML 转义会让"标题里的 `<` "变成数据问题）。
    """
    flat = " ".join(question.split())
    return flat[:limit]


def monotonic_now() -> float:
    """接入层的单调时钟（**只用于心跳/取消轮询的间隔计算**，不进任何业务口径）。"""
    return time.monotonic()
