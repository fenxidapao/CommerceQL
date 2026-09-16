"""启动期断言 —— **必须连上真实依赖才能判定的 4 条**（07 §18.4 / docs/08 §3.3）。

归属窗口：W1B。

## 为什么这 4 条不能写在 `app/core/config.py`

`config.py` 的校验分两级（该文件头已写明）：
- **纯配置级**（import 后即可校验，CI 可跑）：类型 / 范围 / 互斥；
- **需真实依赖级**（必须连库才能判定）：列出在
  `config.STARTUP_ASSERTIONS_DELEGATED_TO_W1B`，**归本文件实现**。

这 4 条共同的特征是：**违反时不会有任何报错，只会让某个保护静默失效**。
例如"分析连接其实可写"——代码照跑，测试照绿，只有在一次事故复盘时才会被发现。

## ⚠️ 本文件的核心设计：**三态**而不是两态（PASS / PENDING / FAIL）

两态（通过 / 拒绝启动）在阶段 1B **必然做假**：

| 断言 | 阶段 1B 的真实状态 |
|---|---|
| `analytics_dsn_is_read_only` | 可判定（角色已由迁移 0001 建好） |
| `audit_log_append_only_enforced` | 可判定（表与触发器已由迁移 0001 建好） |
| `embedding_dim_matches_vector_column` | **判不了** —— `app.embed_doc` 是 **W2A 物化的**，当前库内不存在 |
| `semantic_bundle_passed_five_step_validation` | **判不了** —— 五步校验器归 **W2A**（`semantics/loader.py`） |

若强行两态，只剩两条路，**两条都是错的**：
- 把它当"通过"→ 假绿灯（正是 N-15"带错配置跑起来"要防的）；
- 把它当"失败"→ 拒绝启动 → `docker compose up` 时 api 容器崩溃重启 →
  **DoD①「`/healthz/live`=200 且 `/healthz/ready`=503」这个状态变得不可达**。

→ 因此引入第三态 **`PENDING`（前置条件尚未具备）**，并附两条纪律：

1. **`PENDING` 不等于通过** —— 它必须打 WARN 日志、必须进返回值，**不得静默**；
2. **`APP_ENV=prod` 下 `PENDING` 升级为 `FAIL`** —— 生产环境**不存在**"前置条件待补"这种状态，
   要么依赖齐备、要么不启动。这条 env-gate 与 **U-19（τ 校准）** 同构，理由也同一条：
   不能因为"开发期依赖还没到位"就让生产侧的保护一起失效。

### `PENDING` 的第二个来源：**依赖连不上**（2026-09-16 补）

`PENDING` 不只用于"上游窗口还没交付"，还用于"**依赖压根连不上**"。
两种事实都判 `PENDING`、都放行、都在 prod 升级为致命，但 **`detail` 必须写清是哪种**：

| 来源 | 事实 | 归因对象 |
|---|---|---|
| 上游未交付 | 连上了，但那条事实还不存在（如 `app.embed_doc` 未物化） | 上游窗口（W2A） |
| **依赖不可达** | **连不上，什么事实都取不到**（未部署 / DNS 不通 / 超时） | **部署/运维**（不是上游窗口） |

**为什么"连不上"不能判 `FAIL`**（这条在 2026-09-16 被实测推翻过一次）：
判 `FAIL` 会让启动期直接抛异常，于是「**服务起来了、但硬依赖未接**」这个状态
**不可达** —— 而 07 §18.2（readiness = 摘流量**不重启**）与 §18.4.1
（`live=200` 且 `ready=503` **必须可达**）都要求它可达。
实测后果：CI 的 `contract-tests` job（ubuntu runner，**无 PG/Redis 服务**）上
任何构造 `create_app()` 的用例都会红。分类的唯一出处 = `repo/reachability.py`。

**钉死机制**（与 `test_tau_gate_is_prod_only_by_design` 同构）：
契约测试 `test_pending_is_fatal_only_in_prod_by_design` **双断言** ——
同一份 PENDING 结果在 `APP_ENV=dev` 下**不得**致命、在 `APP_ENV=prod` 下**必须**致命。
想把 prod 收紧去掉的人，必须先改红这条带决策编号的测试。

## 一致性自检

`assert_covers_delegated_names()` 断言"本文件实现的断言名集合 ==
`STARTUP_ASSERTIONS_DELEGATED_TO_W1B`"。没有它，`config.py` 那边（W0 持有）**新增第 5 条**时，
本文件不会有任何反应 —— 那会造出一条"写在清单里、却从来没人执行"的断言。
反向同样拦：本文件多实现一条**未登记**的断言 → 立即红（防"顺手加检查"变成第二份真相）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import STARTUP_ASSERTIONS_DELEGATED_TO_W1B, AppEnv, Settings
from app.core.errors import ConfigError
from app.repo.dsn import READ_ONLY_ROLE_ASSERTION_SQL, to_libpq_conninfo
from app.repo.reachability import (
    UNREACHABLE_ERROR_TYPES,
    Unreachable,
    unreachable_from,
)

__all__ = [
    "ANALYTICS_DSN_IS_READ_ONLY",
    "ASSERTION_NAMES",
    "AUDIT_LOG_APPEND_ONLY_ENFORCED",
    "EMBEDDING_DIM_MATCHES_VECTOR_COLUMN",
    "SEMANTIC_BUNDLE_PASSED_FIVE_STEP_VALIDATION",
    "AssertionOutcome",
    "AssertionStatus",
    "AuditAccess",
    "StartupProbes",
    "Unreachable",
    "assert_covers_delegated_names",
    "enforce_startup_assertions",
    "evaluate_analytics_is_read_only",
    "evaluate_audit_append_only",
    "evaluate_embedding_dim",
    "evaluate_semantic_bundle",
    "live_probes",
    "run_startup_assertions",
]

#: 断言名 —— **必须与 `config.STARTUP_ASSERTIONS_DELEGATED_TO_W1B` 逐字一致**。
#: 写成常量而不是散落的字符串：名字是**跨文件的键**，写错一处就静默漏跑一条。
ANALYTICS_DSN_IS_READ_ONLY: Final[str] = "analytics_dsn_is_read_only"
EMBEDDING_DIM_MATCHES_VECTOR_COLUMN: Final[str] = "embedding_dim_matches_vector_column"
AUDIT_LOG_APPEND_ONLY_ENFORCED: Final[str] = "audit_log_append_only_enforced"
SEMANTIC_BUNDLE_PASSED_FIVE_STEP_VALIDATION: Final[str] = "semantic_bundle_passed_five_step_validation"

ASSERTION_NAMES: Final[tuple[str, ...]] = (
    ANALYTICS_DSN_IS_READ_ONLY,
    EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
    AUDIT_LOG_APPEND_ONLY_ENFORCED,
    SEMANTIC_BUNDLE_PASSED_FIVE_STEP_VALIDATION,
)


class AssertionStatus(StrEnum):
    """三态（见文件头）。**没有第四态** —— 需要第四态说明判定口径还没想清楚。"""

    PASS = "pass"
    #: 前置条件尚未具备（依赖上游窗口的交付）。**不是"通过"** —— 必须可见。
    PENDING = "pending"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class AssertionOutcome:
    """单条断言的判定结果。"""

    name: str
    status: AssertionStatus
    detail: str
    #: 该断言的 `PENDING` 在 `APP_ENV=prod` 下是否升级为 `FAIL`。
    #: ⚠️ 默认 `True`：新增断言时**默认按生产口径**，要放宽必须显式写 `False` 并说明理由。
    #:    反过来（默认 False）会让"忘了收紧"变成默认行为，而漏掉的后果是生产带着缺失依赖启动。
    strict_in_prod: bool = True

    def is_fatal(self, settings: Settings) -> bool:
        """是否应当**拒绝启动**。

        ⚠️ 分离成一个方法而不是在调用点写 `if status is FAIL or (PENDING and prod)`：
        这个判断在两处被需要（`enforce_*` 与启动日志），两处各写一遍就会各错一次 ——
        而错的方向恰好是"漏掉 prod 收紧"，那正是本设计要防的。
        """
        if self.status is AssertionStatus.FAIL:
            return True
        if self.status is AssertionStatus.PENDING:
            return self.strict_in_prod and settings.APP_ENV is AppEnv.PROD
        return False


# ============================================================================
# 探针的原始观测（**只放事实，不放判定** —— 判定是下面的纯函数）
# ============================================================================

@dataclass(frozen=True, slots=True)
class AuditAccess:
    """`app.audit_log` 的库侧事实（一条 `SELECT` 就能取全，但表不存在时连 `has_*_privilege` 都会报错）。

    ⚠️ `connecting_role_is_superuser` 是**必需**的一项，不是"顺手加的"：
    `has_table_privilege` 对超级用户恒为 true（超级用户绕过 ACL）→ 若 api 用超级用户 DSN 连库，
    权限四项会全部为真，**看起来像"权限配错了"**，而根因是"连库的人根本不对"。
    两项分开报，排查方向才不会跑偏。
    """

    table_present: bool
    connecting_role: str
    connecting_role_is_superuser: bool
    can_insert: bool
    can_update: bool
    can_delete: bool
    can_truncate: bool
    trigger_present: bool


@dataclass(frozen=True, slots=True)
class StartupProbes:
    """四条断言所需的**最小 I/O 面**。

    ⚠️ 之所以把 I/O 抽成可注入的 callable 而不是直接在断言里连库：
    N-01 要求确定性模块**离线可测**。判定逻辑（下面那四个 `evaluate_*`）是纯函数，
    单测直接喂事实即可覆盖全部边界（含"表不存在""超级用户""维度不匹配"）；
    只有下面 3 个 I/O 闭包需要真实依赖，由集成测试覆盖。

    ⚠️ 三个闭包**不得**抛"连不上"类异常，必须返回 `Unreachable`
    （由 `live_probes` 里的守卫统一转换；分类唯一出处见 `repo/reachability.py`）。
    否则"依赖没起来"会变成启动期异常 —— 而 07 §18.4.1 要求
    「服务起来了、但硬依赖未接」这个状态**可达**。
    """

    analytics_role: Callable[[], Awaitable[tuple[bool, str] | Unreachable | None]]
    vector_column: Callable[[], Awaitable[tuple[str, int | None] | Unreachable | None]]
    audit_access: Callable[[], Awaitable[AuditAccess | Unreachable]]


# ============================================================================
# 判定（**纯函数** —— 无 I/O、无全局状态；边界条件逐条覆盖）
# ============================================================================

def _pending_unreachable(
    *, name: str, dependency: str, unreachable: Unreachable
) -> AssertionOutcome:
    """「**无法判定**」的统一产出（三条 I/O 断言共用，避免三处各写一份措辞）。

    ⚠️ 判 `PENDING` 而**不是** `FAIL`，是本设计里最容易被人"顺手改回去"的一处：
    "连不上"不等于"配错了"。判成 `FAIL` 的后果不是更严格，而是
    **把「服务起来了、但硬依赖未接」这个状态变成不可达**（07 §18.4.1 明确要求它可达），
    并让 CI 里任何构造 `create_app()` 的用例在无依赖环境下必红。

    ⚠️ `strict_in_prod=True`：prod 下"无法判定"必须升级为拒绝启动 ——
    生产不允许带着未验证的配置跑起来（与 U-19 的 env-gate 同形：非 prod 放行但不得隐瞒）。
    """
    return AssertionOutcome(
        name=name,
        status=AssertionStatus.PENDING,
        detail=(
            f"{unreachable.reason} → 本项**无法判定**（≠「不合格」）。"
            f"依赖={dependency}；`/healthz/ready` 会如实报 503（07 §18.2：摘流量不重启）。"
            "归因=**部署/依赖未就绪**，不是上游窗口缺交付"
        ),
    )


def evaluate_analytics_is_read_only(
    *, connecting_role: str, row: tuple[bool, str] | Unreachable | None
) -> AssertionOutcome:
    """07 §18.4 第 2 条 / N-02。

    `row` = `(is_super, default_transaction_read_only)`，来自
    `repo/dsn.READ_ONLY_ROLE_ASSERTION_SQL`；`None` = 该角色不存在（DSN 指向的角色根本没建）。

    ⚠️ 断言两件事而非一件：
    ① 不是超级用户（`rolsuper OR NOT rolcanlogin`）—— 超级用户绕过 RLS 与只读事务；
    ② `default_transaction_read_only = 'on'` —— 这是"连上即只读"，**与"没有写权限"是两道独立机制**。
    只查 ① 会漏掉"有登录权限的普通角色忘了设只读"，只查 ② 会漏掉"用超级用户连库"。

    ⚠️ 三种取值**含义互斥**，不得合并：`Unreachable`（连不上 → PENDING）、
    `None`（连上了但角色不存在 → FAIL）、元组（连上了、角色在 → 逐项判）。
    """
    if isinstance(row, Unreachable):
        return _pending_unreachable(
            name=ANALYTICS_DSN_IS_READ_ONLY,
            dependency="ANALYTICS_DB_URL（业务只读库）",
            unreachable=row,
        )
    if row is None:
        return AssertionOutcome(
            name=ANALYTICS_DSN_IS_READ_ONLY,
            status=AssertionStatus.FAIL,
            detail=(
                f"ANALYTICS_DB_URL 指向的角色不存在：{connecting_role!r}。"
                f"迁移 0001 未执行或 DSN 写错了角色名"
            ),
        )

    is_super, dtr = row
    if is_super:
        return AssertionOutcome(
            name=ANALYTICS_DSN_IS_READ_ONLY,
            status=AssertionStatus.FAIL,
            detail=(
                f"分析连接的角色 {connecting_role!r} 是超级用户或不可登录 —— "
                f"N-02 的整套保证（RLS + 只读）对超级用户**不生效**"
            ),
        )
    if dtr.strip().lower() != "on":
        return AssertionOutcome(
            name=ANALYTICS_DSN_IS_READ_ONLY,
            status=AssertionStatus.FAIL,
            detail=(
                f"分析连接的角色 {connecting_role!r} 的 default_transaction_read_only = "
                f"{dtr!r}，应为 'on'（ADR-08：只读的物理形态是角色级只读）"
            ),
        )
    return AssertionOutcome(
        name=ANALYTICS_DSN_IS_READ_ONLY,
        status=AssertionStatus.PASS,
        detail=f"角色 {connecting_role!r}：非超级用户且 default_transaction_read_only=on",
    )


def evaluate_embedding_dim(
    *, declared_dim: int, column: tuple[str, int | None] | Unreachable | None
) -> AssertionOutcome:
    """07 §18.4 第 3 条：`EMBEDDING_DIM` 与向量列维度一致。

    `column` = `(type_name, dim)`；`None` = 表或列不存在（**前置未具备 → PENDING**）。

    ⚠️ 为什么"列不存在"必须是 `PENDING` 而不是 `FAIL`：
    该列由 **W2A** 物化（`semantics/loader.py` 跑 §6.1 的五步校验后建表）。
    阶段 1B 它必然不存在 —— 把它判 `FAIL` 等于"阶段 1B 的服务永远起不来"，
    而 07 §18.4 的"拒绝启动"针对的是**配错了**，不是**上游还没交付**。
    prod 下这条会被 `strict_in_prod` 收成致命（见 `AssertionOutcome.is_fatal`）。

    ⚠️ `Unreachable`（连不上元数据库）与 `None`（连上了、列不在）都判 `PENDING`，
    但**理由不同、detail 必不相同**：前者是"部署/依赖未就绪"，后者是"W2A 未交付"。
    合并措辞会让排查的人找错对象。
    """
    if isinstance(column, Unreachable):
        return _pending_unreachable(
            name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
            dependency="DATABASE_URL（元数据库）",
            unreachable=column,
        )
    if column is None:
        return AssertionOutcome(
            name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
            status=AssertionStatus.PENDING,
            detail=(
                "向量列 app.embed_doc.embedding 尚不存在 —— 语义包物化归 **W2A**"
                "（`semantics/loader.py`，07 §6.1 / §6.2）；物化后本断言自动转为可判定"
            ),
        )

    type_name, column_dim = column
    if not type_name.startswith("vector"):
        return AssertionOutcome(
            name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
            status=AssertionStatus.FAIL,
            detail=(
                f"app.embed_doc.embedding 的类型是 {type_name!r}，不是 vector —— "
                f"向量检索（ADR-04）会直接失效"
            ),
        )
    if column_dim is None:
        return AssertionOutcome(
            name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
            status=AssertionStatus.FAIL,
            detail=(
                f"app.embed_doc.embedding 是 {type_name!r}（**未声明维度**）—— "
                f"pgvector 无法建 HNSW 索引，插入异维向量时才报错（太晚）"
            ),
        )
    if column_dim != declared_dim:
        return AssertionOutcome(
            name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
            status=AssertionStatus.FAIL,
            detail=(
                f"EMBEDDING_DIM={declared_dim} 与向量列维度 {column_dim} 不一致 —— "
                f"换 embedding 模型后必须同步重建向量列，否则查询期报维度错（N-15 要防的正是这个）"
            ),
        )
    return AssertionOutcome(
        name=EMBEDDING_DIM_MATCHES_VECTOR_COLUMN,
        status=AssertionStatus.PASS,
        detail=f"EMBEDDING_DIM={declared_dim} == 向量列 {type_name}",
    )


def evaluate_audit_append_only(access: AuditAccess | Unreachable) -> AssertionOutcome:
    """07 §18.4 第 5 条 / N-09 的**前提**。

    ⚠️ 检查的是"append-only 的**前置条件**"，不是"审计写不写得进去"。
    四层保证里这属于第 ①（DB 权限）与第 ②（触发器）两层 —— 它们的失效方式是
    **完全静默**的（权限被改、触发器被删，都不会有任何报错）。

    五项逐项断言，且**必须包含 TRUNCATE**：
    `TRUNCATE` 删全表且**不触发行级触发器** → 只查 UPDATE/DELETE 会漏掉它，
    而漏掉的后果是四层保证一起失效却毫无提示（集成用例已单独立过这一条）。

    ⚠️ `Unreachable`（连不上元数据库）判 `PENDING`：此时**没有任何事实**可判，
    连"表在不在"都不知道 —— 报成 `FAIL` 会让"库没起"表现为"权限配错了"。
    """
    if isinstance(access, Unreachable):
        return _pending_unreachable(
            name=AUDIT_LOG_APPEND_ONLY_ENFORCED,
            dependency="DATABASE_URL（元数据库）",
            unreachable=access,
        )
    if not access.table_present:
        return AssertionOutcome(
            name=AUDIT_LOG_APPEND_ONLY_ENFORCED,
            status=AssertionStatus.FAIL,
            detail=(
                "app.audit_log 不存在 —— 迁移 0001 未执行。"
                "07 §18.2 的启动顺序要求『迁移先于 api』，此处为硬前置"
            ),
        )

    problems: list[str] = []
    if not access.can_insert:
        problems.append(f"角色 {access.connecting_role!r} **缺少** INSERT（审计写不进去 → 主链路必然 fail-closed）")
    if access.can_update:
        problems.append("角色可 UPDATE（append-only 第 ① 层失效）")
    if access.can_delete:
        problems.append("角色可 DELETE（append-only 第 ① 层失效）")
    if access.can_truncate:
        problems.append("角色可 TRUNCATE（删全表且**不触发行级触发器** → 第 ①② 层一起失效）")
    if not access.trigger_present:
        problems.append("触发器 trg_audit_log_immutable 不存在（append-only 第 ② 层失效）")

    if access.connecting_role_is_superuser:
        # 单独一条：超级用户会绕过 ACL，上述四项权限全为 true —— 若只报"可 UPDATE"，
        # 排查方向会被引到"GRANT 配错了"，而真相是"连库的身份不对"。
        problems.insert(0, f"连接角色 {access.connecting_role!r} 是超级用户（绕过 ACL，权限四项全部失真）")

    if problems:
        return AssertionOutcome(
            name=AUDIT_LOG_APPEND_ONLY_ENFORCED,
            status=AssertionStatus.FAIL,
            detail="；".join(problems),
        )
    return AssertionOutcome(
        name=AUDIT_LOG_APPEND_ONLY_ENFORCED,
        status=AssertionStatus.PASS,
        detail=(
            f"角色 {access.connecting_role!r}：INSERT ✅ / UPDATE ❌ / DELETE ❌ / TRUNCATE ❌ "
            f"且触发器在位"
        ),
    )


def evaluate_semantic_bundle(*, validator: Callable[[], Awaitable[None]] | None) -> AssertionOutcome:
    """07 §18.4 第 4 条：语义包通过 §6.1 五步校验。

    ⚠️ **本窗口只留插槽，不实现校验**（`validator=None` → `PENDING`）。
    这不是偷懒，是**避免制造第二份真相**：五步校验的产出形态（物化表 + 版本指针）
    归 W2A 的 `semantics/loader.py`；W1B 在这里再写一遍校验，两份实现必然随时间分叉。

    补充事实（供下一窗口直接用）：W1A 已交付**独立可跑的** `semantic/validate_bundle.py`
    （27 项断言，刻意不 import `app.*`）。它是**作者侧**校验器，
    与"启动期对**已物化**的包做校验"不是同一个动作 —— 不要在启动期直接 shell 调用它。
    """
    if validator is None:
        return AssertionOutcome(
            name=SEMANTIC_BUNDLE_PASSED_FIVE_STEP_VALIDATION,
            status=AssertionStatus.PENDING,
            detail=(
                "五步校验器未接线 —— 归 **W2A**（`semantics/loader.py`，07 §6.1）。"
                "W1B 在此仅留插槽（`StartupProbes` 之外的单参数注入点），"
                "避免与 W2A 各写一份校验"
            ),
        )
    return AssertionOutcome(
        name=SEMANTIC_BUNDLE_PASSED_FIVE_STEP_VALIDATION,
        status=AssertionStatus.PASS,
        detail="注入的校验器已通过",
    )


# ============================================================================
# I/O 实现（唯一会连库的部分）
# ============================================================================

async def _fetch_analytics_role(dsn: str) -> tuple[bool, str] | None:
    """连 `ANALYTICS_DB_URL` 并问 `pg_roles`（**用只读连接自己问自己**）。

    ⚠️ 用 psycopg 直连而**不**复用 `repo/pools` 的 SQLAlchemy engine：
    启动断言的语义是"这条 DSN 本身对不对"，必须**发生在任何池建立之前** ——
    池一旦建立，"连通性失败"与"角色配错"就会混成同一个 `PoolTimeout`。
    这也是 `READ_ONLY_ROLE_ASSERTION_SQL` 用 `current_user` 而不是写死 `'app_ro'` 的原因：
    断言的对象是"连上来的这个人"，而不是"我猜配置里写的是谁"。
    """
    import psycopg

    conn = await psycopg.AsyncConnection.connect(to_libpq_conninfo(dsn), connect_timeout=5)
    try:
        cursor = await conn.execute(READ_ONLY_ROLE_ASSERTION_SQL)
        row = await cursor.fetchone()
        if row is None:
            return None
        # ⚠️ psycopg 的返回行不是下标可取的元组 —— 必须 `fetchone()` 后解包（W1B 实测踩过）。
        is_super, dtr = row
        return bool(is_super), str(dtr)
    finally:
        await conn.close()


async def _fetch_current_role(dsn: str) -> tuple[str, bool]:
    """连接角色名 + 是否超级用户（供审计断言归因用）。"""
    import psycopg

    conn = await psycopg.AsyncConnection.connect(to_libpq_conninfo(dsn), connect_timeout=5)
    try:
        cursor = await conn.execute(
            "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
        )
        row = await cursor.fetchone()
        if row is None:  # pragma: no cover - PG 必然返回一行
            raise ConfigError("无法读取 current_user")
        role, is_super = row
        return str(role), bool(is_super)
    finally:
        await conn.close()


async def _fetch_audit_access(engine: AsyncEngine) -> AuditAccess:
    """读 `app.audit_log` 的权限与触发器事实（**两次查询**，顺序不可换）。

    ⚠️ 不能合成一条 `SELECT`：表不存在时 `has_table_privilege` 会**直接报错**
    （`relation "app.audit_log" does not exist`），而不是返回 false。
    而这条断言恰恰要能回答"表不存在"这个事实 —— 所以先问存在性，再问权限。
    """
    async with engine.connect() as conn:
        present = await conn.scalar(text("SELECT to_regclass('app.audit_log') IS NOT NULL"))
        role_row = (
            await conn.execute(
                text(
                    "SELECT current_user, "
                    "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
                )
            )
        ).first()
    if role_row is None:  # pragma: no cover - PG 必然返回一行
        raise ConfigError("无法读取 current_user")
    connecting_role, is_super = str(role_row[0]), bool(role_row[1])

    if not present:
        # 早返回：此时任何 `has_*_privilege` 都会抛错，而"表不存在"本身就是完整答案。
        return AuditAccess(
            table_present=False,
            connecting_role=connecting_role,
            connecting_role_is_superuser=is_super,
            can_insert=False,
            can_update=False,
            can_delete=False,
            can_truncate=False,
            trigger_present=False,
        )

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT has_table_privilege(current_user, 'app.audit_log', 'INSERT'),
                           has_table_privilege(current_user, 'app.audit_log', 'UPDATE'),
                           has_table_privilege(current_user, 'app.audit_log', 'DELETE'),
                           has_table_privilege(current_user, 'app.audit_log', 'TRUNCATE'),
                           EXISTS (
                             SELECT 1 FROM pg_trigger
                             WHERE tgname = 'trg_audit_log_immutable'
                               AND tgrelid = to_regclass('app.audit_log')
                           )
                    """
                )
            )
        ).first()
    if row is None:  # pragma: no cover - 聚合查询必然返回一行
        raise ConfigError("无法读取 app.audit_log 的权限事实")

    return AuditAccess(
        table_present=True,
        connecting_role=connecting_role,
        connecting_role_is_superuser=is_super,
        can_insert=bool(row[0]),
        can_update=bool(row[1]),
        can_delete=bool(row[2]),
        can_truncate=bool(row[3]),
        trigger_present=bool(row[4]),
    )


async def _fetch_vector_column(engine: AsyncEngine) -> tuple[str, int | None] | None:
    """读 `app.embed_doc.embedding` 的类型与维度。

    ⚠️ 用 `format_type(atttypid, atttypmod)` 取类型名而**不**直接读 `atttypmod` 当维度：
    pgvector 确实把维度放在 `atttypmod` 里，但这是**实现细节**（无文档承诺）。
    解析 `format_type` 得到的 `vector(1024)` 是**类型系统的对外表述**，稳定得多；
    且它在"列存在但不是 vector 类型"时给出可读的判据（→ FAIL 并带上真实类型名）。
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    WHERE a.attrelid = to_regclass('app.embed_doc')
                      AND a.attname = 'embedding'
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                    """
                )
            )
        ).first()
    if row is None:
        return None
    type_name = str(row[0])
    if not type_name.startswith("vector"):
        return type_name, None
    inner = type_name.removeprefix("vector").strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        return type_name, None  # 无 typmod 的裸 vector → 无维度约束
    digits = inner[1:-1].strip()
    return type_name, int(digits) if digits.isdigit() else None


async def _guarded[T](fn: Callable[[], Awaitable[T]]) -> T | Unreachable:
    """把「连不上」转成 `Unreachable`；**其余异常照常向上抛**。

    ⚠️ 这里只吞 `repo/reachability.py` 认定的那一组类型（连接被拒 / DNS 失败 / 超时）。
    `psycopg.InterfaceError`（Windows `ProactorEventLoop` 下 psycopg async 的典型报错）
    **刻意不吞** —— 吞了会让"本机事件循环不兼容"伪装成"库没起"，
    测试变绿、病因消失。宁可红着，也不许错归因（详见该模块的说明）。
    """
    try:
        return await fn()
    except UNREACHABLE_ERROR_TYPES() as exc:
        return unreachable_from(exc)


def live_probes(settings: Settings, *, metadata_engine: AsyncEngine) -> StartupProbes:
    """把上面三个 I/O 实现绑成 `StartupProbes`。

    ⚠️ `metadata_engine` 由调用方（`app/main.py` 的组装根）注入，本模块**不自建池** ——
    `repo/pools.py` 是"三池"的唯一装配点（N-14），这里再建一个就多了一个没人管的池。

    ⚠️ 三个闭包**一律包 `_guarded`**：调用方（`run_startup_assertions`）据此假定
    "取事实这一步不会因依赖不可达而抛"。少包一个，那条断言就会在依赖未起时
    以异常形式炸穿启动路径 —— 症状离病因很远（看起来像 500/启动崩溃，而不是 503）。
    """
    return StartupProbes(
        analytics_role=lambda: _guarded(lambda: _fetch_analytics_role(settings.ANALYTICS_DB_URL)),
        vector_column=lambda: _guarded(lambda: _fetch_vector_column(metadata_engine)),
        audit_access=lambda: _guarded(lambda: _fetch_audit_access(metadata_engine)),
    )


# ============================================================================
# 编排
# ============================================================================

def assert_covers_delegated_names() -> None:
    """本文件实现的断言名 {==} `config` 里登记的那 4 个。**双向**比对。

    双向的理由：单向（只查"登记的都实现了"）漏掉"实现了一条没人登记的" ——
    那会造出一条**没有文档依据**的启动门禁，而它的失效方式（某天把别人卡在启动外）
    极难归因。反之亦然。两个方向都拦，`config.py` 与本文件才不会各说各话（U-18 教训）。
    """
    implemented = set(ASSERTION_NAMES)
    declared = set(STARTUP_ASSERTIONS_DELEGATED_TO_W1B)
    if implemented != declared:
        raise ConfigError(
            "启动断言清单与本文件实现不一致："
            f"声明未实现={sorted(declared - implemented)}；"
            f"实现未声明={sorted(implemented - declared)}"
        )


async def run_startup_assertions(
    settings: Settings, probes: StartupProbes
) -> tuple[AssertionOutcome, ...]:
    """跑全部 4 条，**按清单顺序返回**（顺序稳定 → 日志可 diff）。

    ⚠️ 三条 I/O 断言**并行**发出（`asyncio.gather`）：它们互不依赖，
    串行会让 api 的启动时间无谓地叠加三次连接超时（pg 未就绪时最坏 15s）。
    语义包那条是纯插槽、无 I/O，故直接构造。
    """
    import asyncio

    assert_covers_delegated_names()

    role_row, vector_col, audit_access = await asyncio.gather(
        probes.analytics_role(),
        probes.vector_column(),
        probes.audit_access(),
    )

    return (
        evaluate_analytics_is_read_only(
            connecting_role=_role_from_dsn(settings.ANALYTICS_DB_URL), row=role_row
        ),
        evaluate_embedding_dim(declared_dim=settings.EMBEDDING_DIM, column=vector_col),
        evaluate_audit_append_only(audit_access),
        # ⚠️ 插槽传 `None`：见 `evaluate_semantic_bundle` 的说明（避免与 W2A 各写一份校验）。
        evaluate_semantic_bundle(validator=None),
    )


def _role_from_dsn(dsn: str) -> str:
    """从 DSN 取角色名（**仅用于日志归因**，判定一律以库侧 `current_user` 为准）。

    ⚠️ 两者**可能不同**（DSN 里写的角色名与实际连上的角色可以被 `pg_hba` / `SET ROLE` 改掉）——
    判定用库侧的 `current_user`，这里这个只用来让日志可读。
    把它当判据，就等于相信配置而不是相信数据库 —— 而 N-02 要防的恰恰是这一点。
    """
    from urllib.parse import unquote, urlparse

    return unquote(urlparse(dsn).username or "?")


async def enforce_startup_assertions(
    settings: Settings,
    probes: StartupProbes,
    *,
    logger: Any,
) -> tuple[AssertionOutcome, ...]:
    """跑断言；**任一致命 → 抛 `ConfigError` 拒绝启动**（07 §18.4 fail-fast）。

    日志纪律（U-19「不得隐瞒」的同一条纪律，适用于 `PENDING`）：
    - `PASS` → INFO，一行一条，带上 detail（排查时第一眼看的就是这里）；
    - `PENDING` → **WARN**，且 detail 里必须写"归哪个窗口" —— 否则下一个人只会看到
      "有个东西没就绪"，不知道该找谁；
    - `FAIL` → 先 ERROR 打出全部失败项（**不是第一条就抛**），让一次启动就能看到所有问题。
    """
    outcomes = await run_startup_assertions(settings, probes)

    for outcome in outcomes:
        if outcome.status is AssertionStatus.PASS:
            logger.info("startup_assertion", assertion=outcome.name, detail=outcome.detail)
        elif outcome.status is AssertionStatus.PENDING:
            logger.warning(
                "startup_assertion_pending",
                assertion=outcome.name,
                detail=outcome.detail,
                app_env=str(settings.APP_ENV),
                env_gated=True,
                why="前置条件尚未具备；APP_ENV=prod 下本项会升级为拒绝启动",
            )

    fatal = [o for o in outcomes if o.is_fatal(settings)]
    if fatal:
        logger.error(
            "startup_assertions_failed",
            failed=[o.name for o in fatal],
            detail=[o.detail for o in fatal],
        )
        raise ConfigError(
            "启动期断言未通过，拒绝启动（07 §18.4 fail-fast）："
            + "；".join(f"{o.name}({o.status.value})：{o.detail}" for o in fatal)
        )
    return outcomes
