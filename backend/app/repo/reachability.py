"""把「**连不上依赖**」与「**依赖答了、但答案不合格**」分开。

归属窗口：W1B（`app/repo/**`）。

## 为什么必须分开（本模块存在的唯一理由）

启动期的失败有两类，**处置方式相反**：

| 情形 | 得到的事实 | 正确处置 |
|---|---|---|
| 依赖**答了**，但配置不合格（角色是超级用户 / 审计表可 UPDATE / 维度不匹配） | 判定 = **不合格** | **拒绝启动**（07 §18.4）—— 任何环境，含 dev |
| 依赖**连不上**（未部署 / DNS 不通 / 端口未监听 / 池超时） | **无法判定** | 非 prod：放行 + 如实上报（`/healthz/ready`=503）；prod：拒绝启动（fail-closed，与 U-19 的 env-gate 同形） |

把后者当 fatal 会让「**服务起来了、但硬依赖未接**」这个状态**不可达** ——
而 07 §18.2 的 readiness 语义是"**摘流量，不重启**"、
§18.4.1 的背景说明更直接点名 `live=200` 且 `ready=503` **必须可达**。
把前者当"无法判定"则更坏：真正的错配会被一节 WARN 掩掉，永远没人修。

**实测代价（这条纪律不是洁癖）**：`tests/conftest.py` 注入的占位 DSN 指向 compose 服务名
（离线时**必然**连不上），一旦启动期把"连不上"当致命，**任何构造 `create_app()` 的用例都会红**
—— 包括 CI 的 `contract-tests` job（ubuntu runner 上没有 PG/Redis 服务）。

## ⚠️ 刻意**不**收进来的类型（不是遗漏，是防归类污染）

- `psycopg.InterfaceError` / `sqlalchemy.exc.InterfaceError`（实测：它**不是**
  `OperationalError` 的子类）—— 它的真实含义是"**你用错了**"，不是"依赖不在"。
  最典型的实例：**Windows 默认 `ProactorEventLoop`** 下 psycopg async 直接拒绝工作
  （附录 D `E-1` 已定"部署用 Docker"，Linux 无此问题，但本机开发会踩）。
  若把它归成"依赖不可达"，那么"本机事件循环不兼容"就会**伪装成"库没起"**：
  测试变绿、病因消失、U-39 一类的真问题被一节 WARN 掩掉。**宁可红着，也不许错归因。**
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

__all__ = [
    "UNREACHABLE_ERROR_TYPES",
    "Unreachable",
    "is_unreachable",
    "unreachable_from",
]


@lru_cache(maxsize=1)
def _error_types() -> tuple[type[BaseException], ...]:
    """「连不上」的异常类型集合（惰性构造，避免仅为静态检查也要拖进三个驱动）。

    取值来源与理由（**全部本机实测过继承关系，勿凭印象增删**）：

    | 类型 | 覆盖的实测事实 |
    |---|---|
    | `psycopg.OperationalError` | 连接被拒 / DNS 失败 / `connect_timeout` 到点；**含** `errors.ConnectionTimeout` 与 `psycopg_pool.PoolTimeout`（实测均为其子类） |
    | `sqlalchemy.exc.OperationalError` | SQLAlchemy 包装后的同一事实（实测 `psycopg.OperationalError` **不是**它的子类 → 必须单列） |
    | `redis.exceptions.ConnectionError` | redis-py 连不上 |
    | `redis.exceptions.TimeoutError` | ⚠️ 实测它**不是** `ConnectionError` 的子类 → 必须单列，漏了就会让"Redis 挂了"变成未捕获异常 |
    """
    import psycopg
    import redis.exceptions as redis_exc
    import sqlalchemy.exc as sa_exc

    return (
        psycopg.OperationalError,
        sa_exc.OperationalError,
        redis_exc.ConnectionError,
        redis_exc.TimeoutError,
    )


def UNREACHABLE_ERROR_TYPES() -> tuple[type[BaseException], ...]:
    """`except` 子句用的类型元组（函数形式，因为值要惰性构造）。"""
    return _error_types()


def is_unreachable(exc: BaseException) -> bool:
    """`exc` 是否表达"我连不上"，而不是"依赖答了但不对"。"""
    return isinstance(exc, _error_types())


@dataclass(frozen=True, slots=True)
class Unreachable:
    """「**无法判定**」的显式取值 —— 与「判定为不合格」在**类型上**区分开。

    ⚠️ 为什么不用 `None` 表示：`None` 在现有判定里已经有确定含义
    （例如分析库那条的 `None` = "该角色在库里根本不存在" → **FAIL**）。
    用同一个 `None` 承载两种相反事实，迟早有人把"连不上"读成"角色配错了"。
    """

    reason: str

    def __str__(self) -> str:
        return self.reason


def unreachable_from(exc: BaseException) -> Unreachable:
    """从异常构造 `Unreachable`。

    ⚠️ 只留**异常类名**，不带 DSN / 主机 / 角色名：
    `reason` 会进启动日志与 `ConfigError` 文本，而"连不上"时最容易被顺手带出去的
    恰恰是连接串片段（含口令）。要定位主机请用 `application_name` 与部署侧配置，不要靠日志泄露。
    """
    return Unreachable(reason=f"依赖不可达（{type(exc).__name__}）")
