"""三池的唯一装配点 —— **禁止在别处再建连接池**（07 §8.1 / N-14 / R-10）。

归属窗口：W1B（docs/08 §4.1：`app/repo/**`）。

**为什么必须"三池且只有一个装配点"**（07 §8.1 开宗明义）：

| 池 | DSN | 角色 | 用途 | 为什么不能合并 |
|---|---|---|---|---|
| metadata | `DATABASE_URL` | `app_rw` | session / query_task / audit_log / cost_ledger / 语义物化 / 评测表 | 可写 |
| analytics | `ANALYTICS_DB_URL` | `app_ro` | **业务查询唯一下发通道** | `default_transaction_read_only=on`；合并即意味着"业务 SQL 跑在可写连接上"，N-02 的整套保证当场失效 |
| checkpoint | `DATABASE_URL` | `app_rw` | LangGraph 检查点读写 | **与 metadata 同 DSN 也必须分池**：checkpoint 的写入频率与持有时长完全由图引擎决定，一旦与业务写入共享池，**图的一次重放打满池 = 审计写不进去 = 主链路 fail-closed**（N-14 / R-10） |

⚠️ **本文件是"三池"这个事实的唯一落点**。任何模块想拿连接，只能：
- 业务 SQL → `SqlExecutorPort`（W2D 实现，内部用 analytics 池）；
- 元数据 → `RepositoryPort` / 审计 → `AuditSinkPort`（内部用 metadata 池）；
- 检查点 → `app/graph/build.py` 装配时**注入**（本模块提供工厂，不提供全局单例）。

--------------------------------------------------------------------------------
**依赖登记状态（诚实标注，不得当作已完成）**

本模块直接 `import psycopg_pool`。它**不是新增安装**：`psycopg-pool` 是
`langgraph-checkpoint-postgres` 的**传递依赖**，已随阶段 0 的 venv 一起装妥（实测 3.3.1）。

但按 07 ADR-20 的口径，"**直接用**"仍应进白名单登记（否则下一个人会以为它是随手装的）。
登记涉及三处共享文件，**均归 W0**（`docs/08 §4.1`）：

1. `backend/pyproject.toml` 的 `dependencies` 加 `psycopg-pool>=3.2`；
2. `tests/contract/test_dependency_whitelist.py` 的 `_EXPECTED_MAIN` 加 `psycopg-pool`；
3. `docs/07` ADR-20 表格加一行说明用途。

用户已于 2026-09-15 裁定"**都钉**"（含把 `langgraph==1.2.11` /
`langgraph-checkpoint-postgres==3.1.2` 两个开放区间改成精确版本）——
按 §4.3 四步流程，**W1B 不自行落笔这三处**，diff 见交付说明。
⚠️ 在 W0 落笔之前，本模块的用法**不构成**"已登记依赖"；契约测试不会红（它是静态集合比对，
不扫描 import），**这正是它需要被显式写在这里的原因**：不写就成了静默违规。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.repo.dsn import DsnPair, to_libpq_conninfo

if TYPE_CHECKING:  # pragma: no cover - 仅为类型检查，运行时不导入
    from psycopg_pool import AsyncConnectionPool

__all__ = [
    "ANALYTICS_APPLICATION_NAME",
    "CHECKPOINT_SCHEMA",
    "CHECKPOINT_APPLICATION_NAME",
    "METADATA_APPLICATION_NAME",
    "POOL_ACQUIRE_TIMEOUT_S",
    "POOL_SPECS",
    "PoolKind",
    "PoolSeparationError",
    "ThreePools",
    "assert_application_names_are_unique",
    "checkpoint_connect_kwargs",
    "assert_pools_are_separated",
    "build_analytics_engine",
    "build_checkpoint_pool",
    "build_metadata_engine",
    "build_three_pools",
]


class PoolSeparationError(RuntimeError):
    """三池被误用（DSN 串了 / 池对象复用 / application_name 撞了）。

    ⚠️ 刻意**不继承** `CommerceQLError`：这不是业务错误，是**装配缺陷**，
    应当在构造期就炸掉，不应该有机会变成一次 HTTP 响应。
    """


class PoolKind(StrEnum):
    """三个池的名字（07 §8.1）。

    ⚠️ **不是**在 `app/core/enums.py` 里定义的第二份取值集 —— `enums.py` 当前
    **没有**池名取值集（它管的是契约面取值：错误码 / 事件 / 阶段 / 角色…），
    本枚举是该概念的第一份定义。若架构窗口日后把它收进 `enums.py`，
    **本文件必须改为 import，不得保留两份**（记忆里的 U-18 教训：同一事实写两遍必成矛盾）。
    """

    METADATA = "metadata"
    ANALYTICS = "analytics"
    CHECKPOINT = "checkpoint"


#: `pg_stat_activity.application_name` 取值。**它就是观测手段本身**：
#: T-A1 要回答"checkpoint 连接持有多久"，靠的正是按 application_name 把三条池的后端分开看
#: （只按 datname 分不开 —— 三个池连的是**同一个库**）。
METADATA_APPLICATION_NAME: Final[str] = "commerceql-metadata"
ANALYTICS_APPLICATION_NAME: Final[str] = "commerceql-analytics"
CHECKPOINT_APPLICATION_NAME: Final[str] = "commerceql-checkpoint"

#: LangGraph 检查点表所在的 schema（07 §5.5 / §3.2）。
#:
#: ⚠️ 它必须与迁移 `0001` 里 `CREATE SCHEMA lg` 一致 —— 两处写的是同一个事实。
#: 本常量是**运行时**那一处（连接参数）；迁移是**DDL** 那一处。
#: 迁移文件的注释里已注明"schema 由 `AsyncPostgresSaver` 的构造参数显式指定"，
#: 指向的就是本常量。
CHECKPOINT_SCHEMA: Final[str] = "lg"


@dataclass(frozen=True, slots=True)
class PoolSpec:
    """池规格（07 §8.1 的建议值 + §16.3 的算数）。

    ⚠️ `pool_size` / `max_overflow` 的数值来自 07，**不是**本窗口的调优结论。
    T-A1 的结论若推翻 checkpoint 那一行，改动落在这里 + 07 §16.3，不散落各处。
    """

    kind: PoolKind
    application_name: str
    pool_size: int
    max_overflow: int
    #: 为何是这个值 —— 取值理由必须能对上文档，否则半年后没人敢改
    rationale: str

    @property
    def max_size(self) -> int:
        """池的**硬上限** = `pool_size + max_overflow`。

        ⚠️ 它是唯一的求和处：`max_size` 在 07 里既用于"应用侧逻辑连接上限 = 40+20+20 = 80"
        的算术，也用于 `AsyncConnectionPool(max_size=...)` 与 T-A1 的预热目标。
        三处各写一次 `pool_size + max_overflow`，迟早会有一处写错 —— 而写错的后果是
        "池上限与文档算术不一致"，没有任何报错。
        """
        return self.pool_size + self.max_overflow


#: 07 §8.1 的池规格表（逐字对齐，含 §16.3 的算数）。
POOL_SPECS: Final[dict[PoolKind, PoolSpec]] = {
    PoolKind.METADATA: PoolSpec(
        kind=PoolKind.METADATA,
        application_name=METADATA_APPLICATION_NAME,
        pool_size=10,
        max_overflow=10,
        rationale="07 §16.3：分散在 audit_pre/audit_supp/状态写 ≈3% 持有率 → 50 并发下 ≈2 个",
    ),
    PoolKind.ANALYTICS: PoolSpec(
        kind=PoolKind.ANALYTICS,
        application_name=ANALYTICS_APPLICATION_NAME,
        pool_size=20,
        max_overflow=20,
        rationale="07 §16.3：只在 exec 阶段持有 ≈37% → 50 并发下 ≈19 个（上限 40 留余量）",
    ),
    PoolKind.CHECKPOINT: PoolSpec(
        kind=PoolKind.CHECKPOINT,
        application_name=CHECKPOINT_APPLICATION_NAME,
        # ⚠️ 这两个数字是**初值**，其正确性由 T-A1 决定（07 §16.3 原文："需实测"）。
        #    T-A1 结论落进 `reports/t-a1/` 之后，本行与 07 §16.3 的表必须同步改。
        pool_size=10,
        max_overflow=10,
        rationale="07 §16.3 初值；**待实测**——T-A1（20 并发压测）裁定后回填",
    ),
}


#: 单次"向池要一条连接"的最大等待（秒）。
#:
#: ⚠️ **只用于探针与启动期检查，不用于查询路径** —— 见下面两条边界。
#:
#: ## 取值推导（不是随手挑的）
#:
#: 附录 D 的 `api.healthcheck` 写死了平台侧如何看待 `/healthz/ready`：
#: `timeout: 5s`。到点 `curl` 被杀，**消费者看到的是"超时"，而不是端点的应答体**。
#: 也就是说：readiness 路径（3 个硬依赖）必须在 5s 内作答，否则"诚实的 503"根本传不出去。
#:
#: 而 `psycopg_pool` 的默认 `timeout=30s` 是给**业务借用**设计的
#: （在忙池上等一个空位，等 30s 是合理策略）。同一个默认值放在探针/启动检查上会反向：
#: 实测（2026-09-16，本机，依赖不可达）——
#:
#: | 位置 | 实测耗时 |
#: |---|---|
#: | `ensure_checkpoint_schema()` → `_count_present_checkpoint_tables` → `pool.connection()` | **30.65s**（启动被卡住） |
#: | `probe_checkpointer()` → `pool.connection()` | **30s**（`/healthz/ready` 端到端实测 **35.8s**） |
#:
#: 后果不只是"慢"：每次探针要占住一个 worker 达 30s —— **健康端点自己成了可用性风险**。
#:
#: 2.0s = 5s 预算（附录 D）÷ 3 个硬依赖 ≈ 1.67s，取整向上到 2.0s。
#:
#: ## ⚠️ 边界一：本常量**不声称已满足 5s 契约**
#:
#: `app/api/routers/health.py::_collect` 当前是**串行**遍历硬依赖（该文件归 W7），
#: 故最坏情况 3 × 2.0s = 6s，**仍会超 5s**。本常量把 30s 降到 2s，
#: 真正的达成要靠 `_collect` 并行化（已登记给 W7）。
#:
#: ## ⚠️ 边界二：查询路径的池策略**不在此处定**
#:
#: 07 §14.4.1 已自述 `DB_UNAVAILABLE` 的 `Retry-After = 5s` **无机制推导**
#: （07 至今未定义 DB 层的重连/池超时规则），并把"补 §8 的池超时与重连规则 →
#: 复核该值"记在**架构窗口**名下（07 §20.1 第 8 项）。
#: 因此本窗口**不去改池的构造默认值**（那会连带改变业务借用的语义），
#: 只在"探针 / 启动检查"这些**必须快速作答**的调用点上按调用点收口。
POOL_ACQUIRE_TIMEOUT_S: Final[float] = 2.0


# ============================================================================
# 装配
# ============================================================================

def _connect_args(application_name: str) -> dict[str, str]:
    """连接级固定参数（07 §8.1 末段：`search_path` / `statement_timeout` 不写进连接串）。

    ⚠️ 这里**只**放 `application_name`：
    - `statement_timeout` / `work_mem` 必须用 `SET LOCAL` **按请求**设定 —— 写进连接串会
      **污染池化连接**（下一位借用者会继承上一位的超时值，且没有任何报错）；
    - `search_path` 归 W2A 的认证视图 schema（AST-R16 的 DB 侧兜底），本阶段不擅自设。
    """
    return {"application_name": application_name}


def build_metadata_engine(settings: Settings) -> AsyncEngine:
    """元数据 R/W 池（`app_rw`）。"""
    spec = POOL_SPECS[PoolKind.METADATA]
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=spec.pool_size,
        max_overflow=spec.max_overflow,
        pool_pre_ping=True,          # 池化连接可能已被 pgbouncer/PG 掐断，借出前先探
        connect_args=_connect_args(spec.application_name),
    )


def build_analytics_engine(settings: Settings) -> AsyncEngine:
    """分析只读池（`app_ro`）—— **业务 SQL 的唯一出口**（N-02）。

    ⚠️ 本函数只造池。**注入身份**（`SET LOCAL app.tenant_id/...`，ADR-09）由
    `SqlExecutorPort` 的实现用 `app.repo.dsn.IDENTITY_INJECTION_TEMPLATE` 完成 ——
    这里**不做**，因为"取连接"与"注入身份"必须原子地绑在一起，
    拆成两步就会有人只做第一步（那正是 ADR-09 要防的"忘了 SET LOCAL → 全量可见"）。
    """
    spec = POOL_SPECS[PoolKind.ANALYTICS]
    return create_async_engine(
        settings.ANALYTICS_DB_URL,
        pool_size=spec.pool_size,
        max_overflow=spec.max_overflow,
        pool_pre_ping=True,
        connect_args=_connect_args(spec.application_name),
    )


def build_checkpoint_pool(settings: Settings) -> AsyncConnectionPool:
    """检查点池 —— **独立于 metadata**（N-14）。

    ⚠️ 返回的是 `psycopg_pool.AsyncConnectionPool`（**不是** SQLAlchemy engine）：
    `langgraph-checkpoint-postgres` 的 `AsyncPostgresSaver` 接受的是 psycopg 连接池，
    中间再套一层 SQLAlchemy 只会多一层借还、且拿不到 saver 的 `_cursor()` 语义
    （T-A1 要观测的正是那一层）。

    ⚠️ `open=False` 是**刻意的**：`AsyncConnectionPool` 在 `open=True` 时会绑定创建它的
    event loop，在 import 期或非 async 上下文里构造会直接炸（"attached to a different loop"）。
    → 统一"构造 → 由调用方在 async 上下文里 `await pool.open()`"，
    与 `app/main.py`「import 期零 I/O」的装配原则一致。
    """
    from psycopg_pool import AsyncConnectionPool  # 见文件头"依赖登记状态"

    spec = POOL_SPECS[PoolKind.CHECKPOINT]
    return AsyncConnectionPool(
        # ⚠️ **必须转成 libpq 形态**：`AsyncConnectionPool` 不吃 SQLAlchemy 的 `+psycopg` 前缀。
        # 传错的后果特别隐蔽 —— 它不是报"DSN 非法"，而是把整条串当成"解析不出 host"，
        # 于是一次次重连，30 秒后抛 `PoolTimeout: couldn't get a connection`。
        # 排查方向会被引到"数据库没起来/密码错"，而真相是前缀多了 9 个字符。
        # 转换函数在 `repo/dsn.py`（DSN 唯一入口），不在调用点手写 replace。
        conninfo=to_libpq_conninfo(settings.DATABASE_URL),
        min_size=1,
        max_size=spec.max_size,
        open=False,
        kwargs=checkpoint_connect_kwargs(),
    )


def checkpoint_connect_kwargs() -> dict[str, Any]:
    """**checkpoint 连接**的构造参数 —— 唯一来源，池与单连接两条路都从这里取。

    ⚠️ 四个参数，每一个都是实测逼出来的（不是"照文档抄的建议值"）：

    ① `application_name = commerceql-checkpoint`
       T-A1 的 `pg_stat_activity` 观测**完全依赖**它把连接归因到 checkpoint 池。
       与 metadata / analytics 撞名会让"这条连接是谁持有的"无法回答。

    ② `options = -c search_path=lg`
       `AsyncPostgresSaver.setup()` 的第一条 DDL 是
       `CREATE TABLE IF NOT EXISTS checkpoint_migrations (...)` —— **不带 schema 限定**，
       于是它落在 `search_path` 的第一个可写 schema 上。实测（本窗口）：
         · 不给 `search_path` → 落在 `public` → `permission denied for schema public`
           （PG 15+ 起 `PUBLIC` 对 `public` 已无 CREATE），**报错在 setup 的第一步**；
         · 给成 `app, lg, public` → 表会**静默**落进 `app`，与 07 §5.5「表在 `lg`」矛盾，
           而这类错误不报错、只在 W7 的 7 天归档清理找不到表时才暴露。
       → 只给 `lg`，让"表在哪"没有第二种可能。

    ③ `autocommit = True` —— **必需，否则 setup() 必失败**。
       saver 的迁移脚本里有 `CREATE INDEX CONCURRENTLY`，而它
       **不能在事务块内执行**（`ActiveSqlTransaction`）。
       psycopg 默认在第一次 `execute` 时隐式开启事务 → 必然撞上。
       这不是"为了绕过限制"，而是 LangGraph 官方对
       `AsyncPostgresSaver` + 连接池的推荐配置。

    ④ `prepare_threshold = None`（关闭命名预处理语句）
       07 §16.3 末行明文要求：**事务池化下命名预处理语句不可靠**。
       现在 `pgbouncer` 还没起，所以这条**尚未在真实 pgbouncer 上验证** ——
       登记为"已按 §16.3 预设，待 W7 起 pgbouncer 后复验"。
       ⚠️ 同一问题也适用于 metadata / analytics 两条 SQLAlchemy 池，
       本窗口**未**在那边加（那会改动 W2D/W7 的语义且当前无法验证），
       已登记为待裁定项 —— 见交付说明。

    ⚠️ 依赖 `lg` schema **已存在**（迁移 `0001` 创建）。
    若删掉迁移直接跑 saver，报错是 `schema "lg" does not exist` —— 比静默落错 schema 好。
    """
    return {
        **_connect_args(POOL_SPECS[PoolKind.CHECKPOINT].application_name),
        "options": f"-c search_path={CHECKPOINT_SCHEMA}",
        "autocommit": True,
        "prepare_threshold": None,
    }


@dataclass(frozen=True, slots=True)
class ThreePools:
    """三个池的**唯一持有对象**。

    为什么要包成一个不可变对象：`assert_pools_are_separated` 需要一个"能一次看全三个池"
    的位置。若三池各自漂在不同模块的全局变量里，"有没有串用"就只能靠人读代码。
    """

    metadata: AsyncEngine
    analytics: AsyncEngine
    checkpoint: AsyncConnectionPool


def build_three_pools(settings: Settings) -> ThreePools:
    """一次构造三池并**当场自证互不串用**。"""
    assert_application_names_are_unique()
    pools = ThreePools(
        metadata=build_metadata_engine(settings),
        analytics=build_analytics_engine(settings),
        checkpoint=build_checkpoint_pool(settings),
    )
    assert_pools_are_separated(pools, DsnPair.from_raw(settings.DATABASE_URL, settings.ANALYTICS_DB_URL))
    return pools


def assert_pools_are_separated(pools: ThreePools, dsn_pair: DsnPair) -> None:
    """DoD④「三池互不串用」的**装配期**断言（纯函数，离线可测）。

    ⚠️ 这里检查的是**装配事实**，不是"权限是否真的只读" ——
    后者必须连库才能判定（`app/repo/startup_assertions.py` 的 `analytics_dsn_is_read_only`）。
    两层都要有：装配期拦"写错了对象"，启动期拦"对象对了但权限配错了"。

    三条检查（任何一条失败都是**装配缺陷**，不是运行时故障）：

    1. **池对象不得复用**：三个必须是不同实例。复用 = 某一条 DSN 根本没被用上。
    2. **DSN 归属正确**：metadata 必须用 `DATABASE_URL`、analytics 必须用 `ANALYTICS_DB_URL`。
       ⚠️ 这一条不是形式主义：把两个参数**写反**（`build_analytics_engine` 里读
       `settings.DATABASE_URL`）不会报任何错，只会让业务 SQL 跑在可写连接上 —— 而
       "能不能写"恰恰是 N-02 唯一的边界。
    3. **`application_name` 三者互不相同**且与规格表逐字一致。

    ⚠️ **诚实边界**：第 3 条在这里只能校验**规格表自洽**，不能证明"连接上真的带了它" ——
    那要看 `pg_stat_activity`，属**集成测试**范畴（`tests/integration/`）。
    取法上刻意**不**去掏 SQLAlchemy 的私有属性（`dialect._connect_args_*` 之类）：
    那种断言会随 SQLAlchemy 小版本静默失效，变成一条"永远为真"的假绿灯。
    真正的事实由集成用例 `test_each_pool_reports_its_own_application_name` 连库验。
    """
    # ⚠️ 用 `id()` 集合而不是两两 `is`：metadata/analytics 是 `AsyncEngine`，
    #    checkpoint 是 `AsyncConnectionPool` —— **类型不重叠**，mypy（strict）会把
    #    `engine is pool` 判为 "Non-overlapping identity check"（永远为假）。
    #    mypy 是对的：那两个**不可能**是同一对象。但它说不出"它们必须都不同"这件事，
    #    而 `id()` 三个一起比才把这句写完，且顺带覆盖了"三者全同"的情况。
    if len({id(pools.metadata), id(pools.analytics), id(pools.checkpoint)}) != 3:
        raise PoolSeparationError(
            "三池必须各自独立实例（N-14）：检测到池对象被复用 —— "
            "复用即意味着某一条 DSN 根本没被用上"
        )

    # SQLAlchemy 的 `engine.url` 会把密码打码，故用 `render_as_string(hide_password=False)` 比对
    meta_url = pools.metadata.url.render_as_string(hide_password=False)
    ana_url = pools.analytics.url.render_as_string(hide_password=False)
    if meta_url != dsn_pair.metadata:
        raise PoolSeparationError(
            f"metadata 池的 DSN 不是 DATABASE_URL：{meta_url!r} != {dsn_pair.metadata!r}"
        )
    if ana_url != dsn_pair.analytics:
        raise PoolSeparationError(
            f"analytics 池的 DSN 不是 ANALYTICS_DB_URL：{ana_url!r} != {dsn_pair.analytics!r}"
        )

    # checkpoint 与 metadata **共用 DSN 但必须分池**：对象不同已在上面证过，
    # 这里再确认它俩的 application_name 不同 —— 那正是 T-A1 观测能区分二者的前提。
    if POOL_SPECS[PoolKind.CHECKPOINT].application_name in (
        POOL_SPECS[PoolKind.METADATA].application_name,
        POOL_SPECS[PoolKind.ANALYTICS].application_name,
    ):
        raise PoolSeparationError("三池的 application_name 必须互不相同")


def assert_application_names_are_unique() -> None:
    """规格表级自检：三个 `application_name` 互不相同且非空。

    与 `assert_pools_are_separated` 分开，是为了让"改规格表"这件事单独可测 ——
    它同时也是 `tests/unit/test_pools.py` 的入口。
    """
    names = [spec.application_name for spec in POOL_SPECS.values()]
    if len(set(names)) != len(POOL_SPECS) or not all(names):
        raise PoolSeparationError(f"三池的 application_name 必须互不相同且非空：{names}")
    expected = {
        PoolKind.METADATA: METADATA_APPLICATION_NAME,
        PoolKind.ANALYTICS: ANALYTICS_APPLICATION_NAME,
        PoolKind.CHECKPOINT: CHECKPOINT_APPLICATION_NAME,
    }
    for kind, name in expected.items():
        if POOL_SPECS[kind].application_name != name:
            raise PoolSeparationError(
                f"{kind} 池的 application_name 与常量不一致："
                f"{POOL_SPECS[kind].application_name!r} != {name!r}"
            )
