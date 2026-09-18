"""分桶限流 —— 附录 A §A.0.6 / 07 §9.2 的实现。

归属窗口：W1B（用户裁定 `3.a`）。

## 为什么是"精确滑窗"而不是固定窗口

固定窗口在**窗口边界**会放过 2 倍突发：`10/min` 的实际最坏形态是在 12:00:59 打 10 次、
12:01:00 再打 10 次 —— 一秒钟内 20 次。对 LLM（按 token 计费）与 DB（连接池只有 40）
都不友好，而这类"合规的滥用"从来不会在功能测试里出现。
→ ZSET 精确滑窗：`ZREMRANGEBYSCORE` 清理过期 → `ZCARD` 计数 → `ZADD` 记本次，
**整段用 Lua 原子执行**（不用 Lua 的话 `ZCARD` 与 `ZADD` 之间的并发会少算）。

## ⚠️ 三个诚实边界（不得当作已实现）

1. **`GLOBAL_CONCURRENCY` 桶未实现，且不是"忘了"** —— 它是**并发租约**（进入时 +1、
   退出时 -1、断连必须释放），机制在 07 §9.5（背压与排队），
   且强依赖 SSE 生命周期（W4）。用 60s 滑窗去近似"100 并发"是**假实现**：
   它会把"1 秒内打了 100 次"判成超限，却对"100 个长连接挂着不结束"完全无感 ——
   而后者才是这个桶要防的。→ `check()` 遇到该桶**直接抛** `NotImplementedError`，
   而不是返回一个看起来合理的判定。
2. ~~**`per_tenant` 维度当前未启用**~~ → **已接线（U-38 关闭，2026-09-16）**：
   前置 `app/cache/keys.rate_limit_tenant` 已由 W0 补齐（commit `c63f67a`），
   本模块 `check()` 现对四个桶同时执行用户级与租户级两条窗口（`ADMIN` 桶租户列是 `—`，不设限）。
   两维度必落不同 ZSET：用户键 `rl:{bucket}:{tenant}:{user}` / 租户键 `rl:t:{bucket}:{tenant}`。
3. **本模块不做任何日志 / 指标**：`app.api` 是 L5，可以 import `obs`，
   但"哪个桶被限了"属 §14.5 的归因指标口径，归 W7 与端点层（W4）在**统一出口**打，
   不在这里各打一遍 —— 两处打点必然出现标签不一致。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from app.cache import keys as cache_keys
from app.core.contracts import IdentityContext, RateLimitDecision, RateLimiterPort
from app.core.enums import RATE_LIMIT_BUCKET_RETRY_AFTER_S, RateLimitBucket

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from redis.asyncio import Redis

__all__ = [
    "ENFORCED_DIMENSIONS",
    "RATE_LIMIT_RULES",
    "SLIDING_WINDOW_SCRIPT",
    "UNENFORCED_DIMENSIONS",
    "UNIMPLEMENTED_BUCKETS",
    "LimiterNotImplemented",
    "RateLimitQuota",
    "RateLimitRule",
    "RedisBucketRateLimiter",
]


class LimiterNotImplemented(RuntimeError):
    """该桶**没有**实现，且刻意不提供一个看起来合理的近似值。

    ⚠️ 刻意不继承 `CommerceQLError`：它不该有机会被映射成一个 HTTP 响应而"看起来正常"。
    遇到它说明**接线错了**（把未实现的桶当已实现的用），应当在联调期就炸掉。
    """


#: 精确滑窗脚本（**唯一**的判定实现）。
#:
#: 返回值：`{allowed, user_count, tenant_count, ref_epoch_ms}`
#:   - `allowed`：`1` 放行 / `0` 超限；
#:   - `ref_epoch_ms`：超限时被拒那一侧的**最早**时间戳（供调用方换算精确的 Retry-After；
#:     本模块当前不用它 —— 定值表已在 `enums.RATE_LIMIT_BUCKET_RETRY_AFTER_S`，
#:     但把它返回来是为了让"想要精确值"的调用方不必改脚本）。
#:
#: ⚠️ **时间戳取自 Redis 服务端 `TIME`**，不取应用侧时钟。两个理由：
#:   ① 多实例部署时各实例的墙钟可能有毫秒级偏差，会让同一租户的计数在两个实例上错位；
#:   ② **绕开 N-18**：应用侧"读时间"需要 `ClockPort`，而 `ClockPort` 的
#:      `semantics()` 来自语义包 —— 限流器依赖语义包会造出一条不该有的启动依赖链。
#:      Redis 的时间是**基础设施的时间**，不是业务口径时间，两回事。
#:
#: ⚠️ 两个维度**先全查、后全写**（而不是"查一个写一个"）：
#: 否则"用户维度通过、租户维度超限"时，本次请求已经吃掉了用户配额 ——
#: 被拒的请求不该消耗配额（它连执行都没开始）。
#:
#: ⚠️ **第 3 个参数为 0 = 该维度不启用**，此时脚本**不碰**对应的 key。
#: 因此"未启用"时 `KEYS[2]` 传什么都不会有副作用 —— 但 Python 侧仍强制校验它，
#: 见 `RedisBucketRateLimiter._window_keys`（防止有人启用租户维度时忘了换 key）。
SLIDING_WINDOW_SCRIPT: Final[str] = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local win = tonumber(ARGV[3])
local ulim = tonumber(ARGV[1])
local tlim = tonumber(ARGV[2])

local ucount = 0
local tcount = 0

if ulim > 0 then
  redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - win)
  ucount = redis.call('ZCARD', KEYS[1])
end
if tlim > 0 then
  redis.call('ZREMRANGEBYSCORE', KEYS[2], 0, now - win)
  tcount = redis.call('ZCARD', KEYS[2])
end

if (ulim > 0 and ucount >= ulim) or (tlim > 0 and tcount >= tlim) then
  local ref = now
  if ulim > 0 and ucount >= ulim then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    if oldest[2] then ref = tonumber(oldest[2]) end
  elseif tlim > 0 and tcount >= tlim then
    local oldest = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
    if oldest[2] then ref = tonumber(oldest[2]) end
  end
  return {0, ucount, tcount, ref}
end

if ulim > 0 then
  redis.call('ZADD', KEYS[1], now, ARGV[4])
  redis.call('PEXPIRE', KEYS[1], win)
end
if tlim > 0 then
  redis.call('ZADD', KEYS[2], now, ARGV[4])
  redis.call('PEXPIRE', KEYS[2], win)
end
return {1, ucount + 1, tcount + 1, now}
"""


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """单个桶的两条窗口限（07 §9.2 的表）。`None` = 该维度不设限。

    ⚠️ `per_tenant_per_min` 的**读取条件**：`ADMIN` 桶该列是 `None`（§9.2 的"单租户"列就是 `—`，
    见 `RATE_LIMIT_RULES` 行内注释），其余桶在 `check()` 里照读 ——
    删掉这列会让下一个人以为"设计里没有租户维度"，从而**重新发明**一遍数字。
    """

    bucket: RateLimitBucket
    per_user_per_min: int | None
    per_tenant_per_min: int | None


#: 限流四头的**名字**在这里定义（`Retry-After` 在 `app/api/errors.py`）。
#: ⚠️ 方向是单向的：`errors.py` import 本模块，本模块**不得** import `errors.py`
#: （两边互相 import 会让"头名"与"映射"绕成一个环 —— 那时谁也说不清哪个是唯一来源）。
HEADER_RATE_LIMIT_BUCKET: Final[str] = "X-RateLimit-Bucket"
HEADER_RATE_LIMIT_LIMIT: Final[str] = "X-RateLimit-Limit"
HEADER_RATE_LIMIT_REMAINING: Final[str] = "X-RateLimit-Remaining"
HEADER_RATE_LIMIT_RESET: Final[str] = "X-RateLimit-Reset"

#: 四个头名（顺序 = 文档与前端约定的顺序，仅用于 CORS 暴露清单）。
RATE_LIMIT_HEADER_NAMES: Final[tuple[str, str, str, str]] = (
    HEADER_RATE_LIMIT_BUCKET,
    HEADER_RATE_LIMIT_LIMIT,
    HEADER_RATE_LIMIT_REMAINING,
    HEADER_RATE_LIMIT_RESET,
)


@dataclass(frozen=True, slots=True)
class RateLimitQuota:
    """一次限流判定的**完整事实**：判定 + 配额三数 → `X-RateLimit-*` 四头。

    ⚠️ 为什么不是直接扩 `core/contracts.RateLimitDecision`：那是 **L0 端口类型**（W0 持有），
    扩它等于让所有 Port 消费者都拿到三个"只有接入层才用得上"的字段。
    故本类落在**实现侧**（`app/api/ratelimit.py`，整体移交 W4 的文件），
    `check()` 仍只返回端口类型 —— 端口契约不变，多出来的是实现能力。

    ⚠️ `limit=None` 表示**该维度不设限**（`RATE_LIMIT_RULES` 里的 `None`），
    此时三个头**一律不下发**：下发 `Limit: 0` 会让前端的配额条显示"0/0"（看起来像被禁用），
    而真实语义是"这一维不参与限流"。
    """

    decision: RateLimitDecision
    #: 用户维度配额（`None` = 该维度不设限）。
    limit: int | None = None
    #: 剩余额度。**被拒时恒为 0**（见 `check_with_quota` 的注释）。
    remaining: int | None = None
    #: 窗口重置时刻（epoch 秒，**取自 Redis 服务端时间**，见 `SLIDING_WINDOW_SCRIPT`）。
    reset_epoch_s: int | None = None

    def headers(self) -> dict[str, str]:
        """本节流事实对应的响应头。

        ⚠️ `Bucket` **恒发**（附录 A §A.0.6 补充规则："每次请求都返回"）：
        前端只有拿到它才能定位"是哪个桶超限"，也才能只对 `query` 桶更新配额条（W5 RELAY §1.4）。
        """
        headers = {HEADER_RATE_LIMIT_BUCKET: self.decision.bucket.value}
        if self.limit is not None:
            headers[HEADER_RATE_LIMIT_LIMIT] = str(self.limit)
        if self.remaining is not None:
            headers[HEADER_RATE_LIMIT_REMAINING] = str(self.remaining)
        if self.reset_epoch_s is not None:
            headers[HEADER_RATE_LIMIT_RESET] = str(self.reset_epoch_s)
        return headers


#: 07 §9.2 的表（**逐行对齐，不是调优结果**）。
#: 窗口长度统一 60s —— 该表每一行都是「N 次 / 分钟」，没有第二个窗口长度。
RATE_LIMIT_RULES: Final[Mapping[RateLimitBucket, RateLimitRule]] = MappingProxyType(
    {
        RateLimitBucket.QUERY: RateLimitRule(RateLimitBucket.QUERY, 10, 100),
        RateLimitBucket.READ: RateLimitRule(RateLimitBucket.READ, 120, 1200),
        RateLimitBucket.WRITE: RateLimitRule(RateLimitBucket.WRITE, 30, 300),
        # 管理员类**只限单用户**（§9.2 的"单租户"列是 `—`）：租户管理员本来就是本租户的最高权限，
        # 再叠加租户级配额只会把"平台管理员排查故障"一起限住。
        RateLimitBucket.ADMIN: RateLimitRule(RateLimitBucket.ADMIN, 5, None),
        RateLimitBucket.GLOBAL_CONCURRENCY: RateLimitRule(RateLimitBucket.GLOBAL_CONCURRENCY, None, None),
    }
)

#: 窗口长度（秒）。**一个常量而不是散落的 `60`**：改窗口长度时改这里 +
#: `RATE_LIMIT_RULES` 的语义说明，不必逐桶找。
WINDOW_S: Final[int] = 60

#: 已实现的桶。⚠️ `GLOBAL_CONCURRENCY` **不在**其中 —— 见文件头第 1 条。
UNIMPLEMENTED_BUCKETS: Final[frozenset[RateLimitBucket]] = frozenset(
    {RateLimitBucket.GLOBAL_CONCURRENCY}
)

#: 已启用的配额维度。**契约测试会读它**：两个维度都必须在列 ——
#: 少了哪一个，就说明有人把哪条窗口静默拆掉了（07 §9.2 的表是逐行契约）。
ENFORCED_DIMENSIONS: Final[frozenset[str]] = frozenset({"per_user", "per_tenant"})

#: 契约要求、但当前**未启用**的维度。**当前为空**：
#: `per_tenant` 曾因缺 `cache/keys.rate_limit_tenant` 而未接线（**U-38**，W0 于
#: commit `c63f67a` 补齐键构造，本模块随即接线）。保留这个集合本身 ——
#: 下次再有"契约里有、实现里没有"的维度，登记到这里，让缺席**写在代码里**而不是散在文档里。
UNENFORCED_DIMENSIONS: Final[frozenset[str]] = frozenset()


class RedisBucketRateLimiter(RateLimiterPort):
    """`RateLimiterPort` 的 Redis/ZSET 实现。"""

    def __init__(self, client: Redis, *, window_s: int = WINDOW_S) -> None:
        if window_s <= 0:
            raise ValueError(f"window_s 必须为正：{window_s}")
        self._client = client
        self._window_s = window_s

    def _window_keys(
        self, bucket: RateLimitBucket, ctx: IdentityContext
    ) -> tuple[str, str]:
        """两个窗口键。

        ⚠️ 用户键**必须**走 `cache_keys.rate_limit`、租户键**必须**走 `cache_keys.rate_limit_tenant`
        （§11.2 硬规则 3：全项目只能调用该模块的函数，禁止裸拼）。
        用户键已含 `tenant_id` 与 `sha256(user_id)[:16]` —— 明文 `user_id` 不得进键（PII 面）。

        ⚠️ 两键**防撞是 W0 在键空间层面保证的**（`rl:{b}:{t}:{u}` 4 段 vs `rl:t:{b}:{t}` 第 2 段字面量），
        但本函数仍断言两者不等：一旦相等，脚本会在**同一个 ZSET** 上做两次判定
        → 用户配额被当成租户配额 → 表现为"限流忽然变得极严"，且不会有任何报错。
        这就是那个 `raise` 存在的全部意义。
        """
        user_key = cache_keys.rate_limit(bucket.value, ctx.tenant_id, ctx.user_id)
        tenant_key = cache_keys.rate_limit_tenant(bucket.value, ctx.tenant_id)
        if tenant_key == user_key:  # pragma: no cover - 键空间防撞已保证；这是对"有人改键格式"的哨兵
            raise LimiterNotImplemented(
                "租户键与用户键相等 —— 两维度会在同一个 ZSET 上重复判定。"
                "检查 cache/keys 的键格式是否被改动"
            )
        return user_key, tenant_key

    async def check(self, bucket: RateLimitBucket, ctx: IdentityContext) -> RateLimitDecision:
        """判定是否放行 —— **Port 方法**，只回端口类型（`RateLimitDecision`）。

        ⚠️ 单次 Lua 调用：本方法是 `check_with_quota` 的薄投影，**不重复计数**
        （两次独立判定会把同一次请求记两笔，配额会比文档少一半）。
        """
        return (await self.check_with_quota(bucket, ctx)).decision

    async def check_with_quota(
        self, bucket: RateLimitBucket, ctx: IdentityContext
    ) -> RateLimitQuota:
        """判定是否放行，并**顺带**给出配额三数（逐桶 `X-RateLimit-*` 四头的来源）。

        ⚠️ 成员（ZSET 的 member）用 `task_id + 随机后缀` 而**不用**裸 `task_id`：
        幂等重放会让两个请求共用 `task_id`，而 ZSET 里同 member 会**覆盖**而不是累加 →
        计数偏小（限流少算）。这类偏差只在"同一 task 被重试"时出现，正是最需要限流保护的时刻。

        ⚠️ `remaining` 在**被拒**时恒为 `0`，而不是 `limit - used`：被拒说明"此刻不能再发"，
        真实的剩余额度在这个桶上是 0；给出正数会让前端的配额条显示"还有 3 次"却收到 429
        —— 那正是 §A.0.6 要避免的"头与状态自相矛盾"。
        """
        if bucket in UNIMPLEMENTED_BUCKETS:
            raise LimiterNotImplemented(
                f"{bucket.value} 桶未实现，且刻意不提供近似值（07 §9.2 的该行是**并发租约**，"
                f"机制在 §9.5，依赖 SSE 生命周期 → 归 W4）。"
                f"用 60s 滑窗近似它会把『长连接挂着不结束』判成正常"
            )

        rule = RATE_LIMIT_RULES[bucket]
        user_limit = rule.per_user_per_min or 0
        # `None`（= 该维度不设限，如 ADMIN）与 0 同效：脚本不碰 KEYS[2]。
        tenant_limit = rule.per_tenant_per_min or 0
        user_key, tenant_key = self._window_keys(bucket, ctx)

        member = f"{ctx.task_id}:{uuid.uuid4().hex}"
        result = await self._client.eval(
            SLIDING_WINDOW_SCRIPT,
            2,
            user_key,
            tenant_key,
            str(user_limit),
            str(tenant_limit),
            str(self._window_s * 1000),
            member,
        )
        allowed = int(result[0]) == 1
        decision = RateLimitDecision(
            allowed=allowed,
            bucket=bucket,
            # ⚠️ `Retry-After` **只从 `enums` 的定值表取**（单一来源）：
            # 在这里另写一套数字，就会与 `app/api/errors.map_rate_limited` 的取值分叉，
            # 表现为"`429` 响应头的倒计时与文档不符"，而两者都"看起来对"。
            retry_after_s=None if allowed else RATE_LIMIT_BUCKET_RETRY_AFTER_S[bucket],
        )
        return RateLimitQuota(
            decision=decision,
            limit=user_limit or None,
            remaining=_remaining(user_limit, int(result[1]), allowed=allowed),
            # 脚本第 4 个返回值 = Redis 服务端"现在"（epoch 毫秒），重置时刻 = 现在 + 窗口。
            reset_epoch_s=int(result[3]) // 1000 + self._window_s,
        )


def _remaining(user_limit: int, user_count: int, *, allowed: bool) -> int | None:
    """用户维度剩余额度。`user_limit=0`（该维度不设限）→ `None`（三头都不下发）。"""
    if user_limit <= 0:
        return None
    return max(0, user_limit - user_count) if allowed else 0
