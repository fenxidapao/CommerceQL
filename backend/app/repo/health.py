"""依赖健康探针的**实现**（元数据库 / checkpointer / Redis）—— 附录 A §A.8.1 / 07 §18.2。

归属窗口：W1B（`app/repo/**`）。**注册**动作不在这里 —— 见"为什么本文件不自己注册"。

## 三个探针，各自的失败语义不同

| 探针 | 判什么 | 失败意味着 |
|---|---|---|
| `metadata_db` | 元数据池能取到连接并执行 `SELECT 1` | 会话 / 审计 / 状态写全部不可用 → **摘流量** |
| `checkpointer` | 检查点池能取连接，**且 `lg` schema 的表族已就绪** | 图一跑就炸（`setup()` 未执行） → 摘流量 |
| `redis` | `PING` 通 | 会话锁 / 限流 / 事件重放不可用。⚠️ 它们**是安全边界**（锁没拿到 = 会话可能串行失效），故 Redis 是**硬依赖而非降级项**（附录 A §A.8.1） |

三者都属 `DependencyKind.HARD`（取值集在 `app.core.enums.DEPENDENCY_KIND`，本文件**不重复定义**）。

## ⚠️ 为什么本文件不自己调用 `health.register_probe`

`register_probe` 在 `app/api/routers/health.py`（**L5**）。本文件在 `app/repo/`（**L0**）——
L0 import L5 是**反向依赖**，会被 `.importlinter` 的 R-DEP-1 直接拦下。
→ 因此本文件只**产出**探针表（`build_probe_table`），注册由组装根 `app/main.py` 做。
这不是"绕开 lint"，而是 lint 在正确工作：**只有组装根天然横跨各层**。

## 诚实边界（不得当作已完成）

- **探针不做任何日志**：`repo`（L0）不得 import `app.obs`（L1，反向依赖）。
  因此失败时 `detail` 只放**异常类名**，不带异常正文 —— 这既是信息损失，也是避免
  `psycopg` 的 `OperationalError` 把 DSN / 用户名回显到**可能未鉴权**的 `/healthz` 上（N-11 的精神）。
  **未捕获异常一律向上抛**，由端点层的统一处理兜住（那里把异常类名写进 `detail`）。
  → 待 W7：在探针边界加日志，把完整异常正文留在服务端日志里（现为已登记缺口）。
- **`semantic_bundle_loaded` / `llm` / `embedding` 三个探针本窗口不接线**：
  它们分别归 W2A 与 W7（`docs/08 §4.1`）。未接线的槽位由
  `app/api/routers/health.py` 的 `_unwired_probe` 如实上报为 `healthy=false` ——
  这套"不谎报健康"的机制是阶段 0 特意做的，本窗口**沿用而不绕过**。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.contracts import HealthProbeResult
from app.core.enums import DEPENDENCY_KIND, Dependency
from app.repo.pools import CHECKPOINT_SCHEMA, POOL_ACQUIRE_TIMEOUT_S

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查
    from psycopg_pool import AsyncConnectionPool
    from redis.asyncio import Redis

__all__ = [
    "CHECKPOINT_TABLE_FAMILY",
    "ProbeFn",
    "build_probe_table",
    "probe_checkpointer",
    "probe_metadata_db",
    "probe_redis",
]

#: `AsyncPostgresSaver.setup()` 应建出的表族（`lg` schema）。
#:
#: ⚠️ 清单是**实测得来**（2026-09-15，本机跑完 `setup()` 后读 `pg_class`），不是照文档抄的：
#: 少了 `checkpoint_migrations` 就漏判"迁移脚本没跑完"，
#: 少了 `checkpoint_blobs` 就漏判"大 payload 存不进去"（长对话会先把这一张写满）。
CHECKPOINT_TABLE_FAMILY: Final[tuple[str, ...]] = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
)

#: 探针签名。⚠️ 与 `app/api/routers/health.py` 的 `ProbeFn` **结构相同、名字相同、但不是同一个对象** ——
#: 这是有意的：`repo`（L0）不能 import 端点层（L5）。二者都是
#: `Callable[[], Awaitable[HealthProbeResult]]`，所以能直接互相赋值。
#: ⚠️ 若哪天端点层改了签名，这里**不会**报错 —— 由 `app/main.py` 的注册点做类型检查兜住。
ProbeFn = Callable[[], Awaitable[HealthProbeResult]]


def _result(dependency: Dependency, *, healthy: bool, detail: str | None = None) -> HealthProbeResult:
    """统一构造（`kind` 一律取自 `enums`，**不在本文件写第二份硬/软分级**）。"""
    return HealthProbeResult(
        dependency=dependency,
        kind=DEPENDENCY_KIND[dependency],
        healthy=healthy,
        detail=detail,
    )


def probe_metadata_db(engine: AsyncEngine) -> ProbeFn:
    """元数据库探针：`SELECT 1` + 回显 `application_name`。

    ⚠️ 回显 `application_name` 不是装饰 —— 它是 **T-A1 观测手段本身**
    （`pg_stat_activity` 里靠它把三条池的连接分开）。健康检查里带上它，
    等于让"这条连接属于哪个池"在**运维面上随时可读**，而不必去翻压测报告。

    ⚠️ 探针**不缓存结果**：readiness 的价值全在"此刻"。
    加缓存会让"DB 刚挂"之后仍有最长一个缓存期的窗口返回 200 → 流量被继续导入。
    """
    async def _probe() -> HealthProbeResult:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1, current_setting('application_name'), current_database()")
                )
            ).first()
        if row is None:  # pragma: no cover - `SELECT 1` 必然返回一行
            return _result(Dependency.METADATA_DB, healthy=False, detail="SELECT 1 未返回行")
        return _result(
            Dependency.METADATA_DB,
            healthy=True,
            detail=f"app={row[1]} db={row[2]}",
        )

    return _probe


def probe_checkpointer(pool: AsyncConnectionPool) -> ProbeFn:
    """checkpointer 探针：池可取连接**且** `lg` 的表族齐备。

    ⚠️ 为什么不只探"池能取连接"：那样在**忘了跑 `setup()`** 时仍然报健康，
    而图一执行就抛 `UndefinedTable` —— 每次查询都失败、健康检查却全绿，
    是最难排查的一类组合（探针说没事、用户说全挂）。

    ⚠️ 用 `to_regclass()` 一次问完四张表：它是**不抛错**的存在性查询
    （表不存在返回 NULL）。用 `information_schema` 也能查，但那是视图，
    需要额外的权限与 schema 过滤，且慢得多。
    """
    placeholders = ", ".join(f"'{CHECKPOINT_SCHEMA}.{t}'" for t in CHECKPOINT_TABLE_FAMILY)
    # ⚠️ 这里是**裸 SQL 字符串**而不是 SQLAlchemy 的 `text()`：checkpoint 池给的是
    # `psycopg` 连接（`AsyncConnectionPool`），不是 SQLAlchemy 连接 ——
    # 传 `TextClause` 进去会直接报 "No overload variant of execute matches"。
    # 表名来自本模块常量、无外部输入，故直接插值安全（与 metadata/analytics 两条池的差别，见 `repo/pools.py`）。
    sql = (
        f"SELECT current_setting('application_name'), "
        f"(SELECT count(*) FROM unnest(ARRAY[{placeholders}]) AS s(name) "
        f" WHERE to_regclass(s.name) IS NOT NULL)"
    )

    async def _probe() -> HealthProbeResult:
        # ⚠️ **必须显式给 `timeout`**：`psycopg_pool` 的默认值是 30s（为业务借用设计的）。
        # 用在探针上时，依赖不可达会让 `/healthz/ready` 实测 35.8s 才作答 ——
        # 而附录 D 给 `/healthz/ready` 的平台预算只有 5s（`healthcheck.timeout`），
        # 于是"诚实的 503"永远传不到消费者手里，只留下一次超时。见 `POOL_ACQUIRE_TIMEOUT_S`。
        #
        # `AsyncConnectionPool.connection()` 在 `open=False` 时会抛
        # `PoolClosed` —— 那正是"池没打开"，属**真实的未就绪**，如实上报而非绕过。
        async with pool.connection(timeout=POOL_ACQUIRE_TIMEOUT_S) as conn:
            cursor = await conn.execute(sql)
            row = await cursor.fetchone()
        if row is None:  # pragma: no cover - 聚合查询必然返回一行
            return _result(Dependency.CHECKPOINTER, healthy=False, detail="检查点探针未返回行")
        application_name, present = str(row[0]), int(row[1])
        expected = len(CHECKPOINT_TABLE_FAMILY)
        if present != expected:
            return _result(
                Dependency.CHECKPOINTER,
                healthy=False,
                detail=(
                    f"lg schema 表族不齐（{present}/{expected}）—— "
                    f"`AsyncPostgresSaver.setup()` 未执行或未跑完"
                ),
            )
        return _result(
            Dependency.CHECKPOINTER,
            healthy=True,
            detail=f"app={application_name} lg 表族 {present}/{expected}",
        )

    return _probe


def probe_redis(client: Redis) -> ProbeFn:
    """Redis 探针：`PING`。

    ⚠️ **不**顺手把"有没有权限"也探了（例如试写一个临时键）：
    那会给每 15s 一次的探针加上一次写操作，且在 `maxmemory-policy=allkeys-lru`
    下可能把有用的键挤掉。Redis 自身的 ACL 问题会在**第一次真实使用**时暴露
    （而那时错误码是明确的 `NOAUTH`/`NOPERM`），比探针里猜要准。
    """
    async def _probe() -> HealthProbeResult:
        pong = await client.ping()
        if not pong:  # pragma: no cover - ping 非真即抛
            return _result(Dependency.REDIS, healthy=False, detail="PING 未返回 PONG")
        info: dict[str, Any] = await client.info(section="server")
        return _result(
            Dependency.REDIS,
            healthy=True,
            detail=f"redis {info.get('redis_version', '?')}",
        )

    return _probe


def build_probe_table(
    *,
    metadata_engine: AsyncEngine,
    checkpoint_pool: AsyncConnectionPool,
    redis_client: Redis,
) -> dict[Dependency, ProbeFn]:
    """本窗口负责的三个探针（**只这三个**）。

    ⚠️ 返回 `dict[Dependency, ProbeFn]` 而不是"直接注册"：
    注册动作归组装根（见文件头）。同时这个形状让"本窗口该接几个"变成**可断言的事实** ——
    单测可以比对"表里的键 == 硬依赖集合减去 W2A/W7 的那一个"，
    防止某天有人顺手把 `EMBEDDING`（**软依赖**）也塞进来，把降级变成不可用（N-21）。
    """
    return {
        Dependency.METADATA_DB: probe_metadata_db(metadata_engine),
        Dependency.CHECKPOINTER: probe_checkpointer(checkpoint_pool),
        Dependency.REDIS: probe_redis(redis_client),
    }
