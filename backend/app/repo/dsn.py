"""两套 DSN 的唯一入口 —— 修正上游冲突 U-01（07 §3.3）。

归属窗口：W0 定契约 → W1B 接管实现（docs/08 §4.1：`app/repo/**` 归 W1B）。

**上游冲突（U-01，已由 PRD v1.4 修正，此处落地）**：
PRD 原把 `DATABASE_URL` 描述为"PG **只读副本**"，但 `session` / `audit_log` / `cost_ledger` /
评测表**都必须写** —— 按字面实现会**直接写失败**。现拆为两条：

| 连接 | 用途 | 角色 | 环境变量 |
|---|---|---|---|
| 元数据连接 | session / query_task / audit_log / cost_ledger / eval_* / 语义包物化 / checkpointer | `app_rw`（对 `audit_log` **仅 INSERT**） | `DATABASE_URL` |
| 分析连接 | 业务查询（**唯一**可发业务 SQL 的连接） | `app_ro`（`default_transaction_read_only=on` + 无写权限 + RLS 生效） | `ANALYTICS_DB_URL` |

⚠️ 三条硬规则（07 §3.3）：
1. 两个连接池**独立**，且 checkpointer 与业务查询**再分池**（N-14，共三池，禁止混用）；
2. 分析连接**只能**经"注入身份上下文管理器"获取（ADR-09）；
3. 启动期断言 `ANALYTICS_DB_URL` 的角色具备 `default_transaction_read_only`，**否则拒绝启动**。

⚠️ 本模块**不 import SQLAlchemy**：它是 L0，只负责"给出字符串与校验规则"。
拿引擎/会话是 W1B 的事，且那样才能保证"两条 DSN 只有一个出处"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlparse

__all__ = [
    "IDENTITY_GUC_KEYS",
    "IDENTITY_INJECTION_TEMPLATE",
    "READ_ONLY_ROLE_ASSERTION_SQL",
    "DsnPair",
    "ParsedDsn",
    "to_libpq_conninfo",
]


@dataclass(frozen=True, slots=True)
class ParsedDsn:
    """拆解后的 DSN（**不含 SQLAlchemy 依赖**）。"""

    user: str
    password: str
    host: str
    port: int
    database: str
    raw: str

    @property
    def is_default_read_only_role(self) -> bool:
        """是否指向只读角色。**健壮性来自启动期 SQL 断言，而不是这个名字判断。**

        这里只做"快速失败"的第一道（名字级），真正的保证在 `READ_ONLY_ROLE_ASSERTION_SQL`。
        理由：角色名是人起的，权限是数据库给的 —— 只信后者。
        """
        return self.user == "app_ro"


def _parse(url: str) -> ParsedDsn:
    parsed = urlparse(url)
    if parsed.scheme != "postgresql+psycopg":
        raise ValueError(f"DSN 必须是 postgresql+psycopg://（psycopg 3）：{url!r}")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ValueError(f"DSN 缺少 host 或 database：{url!r}")
    return ParsedDsn(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        raw=url,
    )


@dataclass(frozen=True, slots=True)
class DsnPair:
    """元数据（R/W）与分析（RO）两条连接串。**构造即校验**。"""

    metadata: str
    analytics: str

    def __post_init__(self) -> None:
        meta = _parse(self.metadata)
        ana = _parse(self.analytics)

        # 两条 DSN 不得相同 —— 相同意味着"只读角色"实际是 app_rw，N-02 的整套保证当场失效。
        if self.metadata == self.analytics:
            raise ValueError(
                "DATABASE_URL 与 ANALYTICS_DB_URL 不得相同（N-02 / 07 §3.3）"
            )
        # 两条 DSN 必须指向同一实例同一库（P0 是**角色级**只读，不是物理副本）。
        # 若指到两处，语义包物化与业务查询就会看到不同数据，且没有任何报错。
        if (meta.host, meta.port, meta.database) != (ana.host, ana.port, ana.database):
            raise ValueError(
                f"P0 的两条 DSN 必须指向同一实例同一库（角色级只读，非物理副本）："
                f"{meta.host}:{meta.port}/{meta.database} != {ana.host}:{ana.port}/{ana.database}"
            )

    @property
    def metadata_parsed(self) -> ParsedDsn:
        return _parse(self.metadata)

    @property
    def analytics_parsed(self) -> ParsedDsn:
        return _parse(self.analytics)

    @classmethod
    def from_raw(cls, metadata_url: str, analytics_url: str) -> DsnPair:
        return cls(metadata=metadata_url, analytics=analytics_url)


#: 身份注入用的 GUC 键名（ADR-09 / 07 §13.3）。**键名本身就是契约**：
#: 数据库侧的 RLS 策略直接读它们，改名等于改数据库策略。
IDENTITY_GUC_KEYS: Final[tuple[str, ...]] = (
    "app.tenant_id",
    "app.role",
    "app.shop_ids",
)

#: 启动期断言（07 §18.4 第 2 条 / N-02）。
#: **必须**在启动时执行；失败即拒绝启动 —— 因为"分析连接其实可写"不会有任何报错，
#: 只会在某次事故复盘时才发现。
READ_ONLY_ROLE_ASSERTION_SQL: Final[str] = (
    "SELECT rolsuper OR NOT rolcanlogin AS is_super, "
    "       (SELECT setting FROM pg_settings WHERE name = 'default_transaction_read_only') AS dtr "
    "FROM pg_roles WHERE rolname = current_user"
)

#: 身份注入**应该**长这样（值用绑定参数，不用字面量拼接）。
#:
#: ⚠️ 为什么不用 `SET LOCAL app.tenant_id = 't_001'`（07 §13.3 的示意写法）：
#: `SET` 的 GUC 值**不能用绑定参数**，只能拼字符串 → 直接违反 N-04（用户可控值严禁拼进 SQL 字面量）。
#: `set_config(name, value, is_local)` 的 value 是**普通参数**，可以安全绑定。
#: 这里把这条差异写进契约的原因：它是"照着文档写就踩坑"的典型，而踩下去是注入面。
IDENTITY_INJECTION_TEMPLATE: Final[str] = (
    "SELECT set_config('app.tenant_id', $1, true), "
    "       set_config('app.role', $2, true), "
    "       set_config('app.shop_ids', $3, true)"
)


#: SQLAlchemy 的 psycopg3 方言前缀 ↔ libpq 的 scheme。
_SQLALCHEMY_SCHEME: Final[str] = "postgresql+psycopg://"
_LIBPQ_SCHEME: Final[str] = "postgresql://"


def to_libpq_conninfo(url: str) -> str:
    """`postgresql+psycopg://…` → `postgresql://…`（libpq 形态）。

    ⚠️ **为什么必须有一个转换函数，而不是在调用点手写 `replace()`**：
    DSN 有两种消费者，认的形态不同 ——

    | 消费者 | 要什么 | 给错了会怎样 |
    |---|---|---|
    | SQLAlchemy `create_async_engine` | `postgresql+psycopg://` | 报 `NoSuchModuleError`（还算清楚） |
    | `psycopg.connect` / `AsyncConnectionPool` | `postgresql://` | ⚠️ **不报错在明显的地方**：它被当作"无法解析的 conninfo"，池会**持续重试到超时**，最终报的是一句 `PoolTimeout: couldn't get a connection after 30.00 sec` —— 排查方向会指向"数据库挂了/密码错了"，而不是"前缀多了个 `+psycopg`"（本窗口实测踩过） |

    第二条就是本函数存在的理由：**错误信息的误导方向**比错误本身更贵。

    ⚠️ 对未知 scheme **直接抛错**（不"尽力而为"地返回原值）：
    静默透传会让上面那个 30 秒超时重新出现，而调用点以为已经转换过了。
    """
    if url.startswith(_SQLALCHEMY_SCHEME):
        return _LIBPQ_SCHEME + url[len(_SQLALCHEMY_SCHEME) :]
    if url.startswith(_LIBPQ_SCHEME):
        return url
    raise ValueError(
        f"DSN scheme 无法识别，拒绝静默透传（会变成一句误导性的 PoolTimeout）：{url[:24]!r}…"
    )
