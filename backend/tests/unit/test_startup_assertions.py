"""启动断言的离线断言（07 §18.4 的四条 + 三态收放机制）。

归属窗口：W1B（`tests/unit/**` 随被测模块）。

## ⚠️ 这个文件证明什么、不证明什么

| 断言 | 在这里（离线） | 在 `tests/integration/`（连库） |
|---|---|---|
| 判定逻辑的**全部分支**（角色缺失 / 超级用户 / dtr=off / 维度不匹配 / 表不存在 / 权限四项 / 触发器缺失） | ✅ 喂事实即可覆盖 | — |
| **取事实的 SQL 真的能跑通**、库里的真实配置真的合格 | ❌ 喂的是构造的事实 | ✅ |
| `PENDING → prod 致命` 的 env-gate | ✅ 双断言钉死 | — |

只做离线断言会产生"判定逻辑对、SQL 写错"的假绿灯（SQL 写错时离线用例照样全绿）；
只做集成断言则无法覆盖"角色是超级用户""维度不匹配"这类**当前环境不会出现**的分支。
两者都需要，且**各写各的证据**。
"""

from __future__ import annotations

import pytest

from app.core.config import STARTUP_ASSERTIONS_DELEGATED_TO_W1B, AppEnv, Settings
from app.core.errors import ConfigError
from app.repo import startup_assertions as sa
from app.repo.startup_assertions import (
    AssertionOutcome,
    AssertionStatus,
    AuditAccess,
    StartupProbes,
)

_RW = "postgresql+psycopg://app_rw:pw@localhost:5432/ecom"
_RO = "postgresql+psycopg://app_ro:pw@localhost:5432/ecom"


def _settings(app_env: AppEnv = AppEnv.DEV) -> Settings:
    """构造 `Settings`。

    ⚠️ `APP_ENV=prod` 时**必须**同时给齐 τ 校准三元组，否则 `config.py` 的模型校验
    会先抛 `ValidationError`（那是 U-19 的 env-gate 在起作用）。这不是测试的麻烦，
    而是"prod 配置本身就不是随便能构造出来的"这一事实 —— 顺手把它写进用例，
    免得后来者以为可以绕过。
    """
    kwargs: dict[str, object] = {
        "APP_ENV": app_env,
        "DATABASE_URL": _RW,
        "ANALYTICS_DB_URL": _RO,
    }
    if app_env is AppEnv.PROD:
        kwargs.update(
            BINDING_TAU_MODEL_ID="bge-reranker-v2-m3",
            BINDING_TAU_PROMPT_VERSION="rank-v1",
            BINDING_TAU_CALIBRATED_AT="2026-09-15T00:00:00+08:00",
        )
    return Settings(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. 清单一致性（**双向**）
# ---------------------------------------------------------------------------

def test_implemented_assertions_match_the_delegated_list() -> None:
    """本文件实现的断言名 {==} `config.STARTUP_ASSERTIONS_DELEGATED_TO_W1B`。

    方向 ① 少了实现 → 会有一条"写在清单里、却从来没人执行"的断言（**静默的保护缺失**）；
    方向 ② 多了实现 → 会有一条"没有文档依据的启动门禁"（**某天把人卡在启动外且无法归因**）。
    两个方向都必须红，所以 `assert_covers_delegated_names` 用的是 `!=` 而不是子集比较。
    """
    sa.assert_covers_delegated_names()
    assert set(sa.ASSERTION_NAMES) == set(STARTUP_ASSERTIONS_DELEGATED_TO_W1B)


def test_extra_implementation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 负向：多实现一条**未登记**的断言必须被拦下（否则它就是一条无依据的门禁）。"""
    monkeypatch.setattr(sa, "ASSERTION_NAMES", (*sa.ASSERTION_NAMES, "hand_written_extra_gate"))
    with pytest.raises(ConfigError, match="实现未声明"):
        sa.assert_covers_delegated_names()


def test_missing_implementation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 负向：少实现一条**已登记**的断言必须被拦下（否则清单里那条永远不执行）。"""
    monkeypatch.setattr(sa, "ASSERTION_NAMES", sa.ASSERTION_NAMES[:-1])
    with pytest.raises(ConfigError, match="声明未实现"):
        sa.assert_covers_delegated_names()


# ---------------------------------------------------------------------------
# 2. analytics_dsn_is_read_only（N-02 / 07 §18.4 第 2 条）
# ---------------------------------------------------------------------------

def test_analytics_read_only_pass() -> None:
    outcome = sa.evaluate_analytics_is_read_only(connecting_role="app_ro", row=(False, "on"))
    assert outcome.status is AssertionStatus.PASS


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (None, "角色不存在"),
        ((True, "on"), "超级用户"),
        ((False, "off"), "default_transaction_read_only"),
    ],
)
def test_analytics_read_only_fails(row: object, reason: str) -> None:
    """三种失败形态各自成一条 —— 它们**根因不同、修法不同**。

    尤其 `(True, "on")` 这一条：超级用户**也**会显示 `dtr=on`（它只是默认值），
    所以"dtr 对"不代表"角色对"。只查 dtr 的实现会把它判成 PASS，
    而超级用户会绕过 RLS 与只读事务 —— N-02 的整套保证对它就等于不存在。
    """
    outcome = sa.evaluate_analytics_is_read_only(connecting_role="app_ro", row=row)  # type: ignore[arg-type]
    assert outcome.status is AssertionStatus.FAIL
    assert reason in outcome.detail


def test_read_only_flag_is_case_insensitive() -> None:
    """PG 可能回 `on` / `ON` / `off`（受 `pg_settings.setting` 的呈现影响）—— 大小写不该决定启动成败。"""
    assert (
        sa.evaluate_analytics_is_read_only(connecting_role="app_ro", row=(False, "ON")).status
        is AssertionStatus.PASS
    )


# ---------------------------------------------------------------------------
# 3. embedding_dim_matches_vector_column（07 §18.4 第 3 条）
# ---------------------------------------------------------------------------

def test_vector_column_absent_is_pending_not_fail() -> None:
    """★ 列不存在 → **PENDING**（不是 FAIL，也不是 PASS）。

    这条是整个三态设计的**存在理由**：向量列由 W2A 物化，阶段 1B 必然不存在。
    判 FAIL → 服务永远起不来（DoD① 不可达）；判 PASS → 假绿灯（N-15 要防的正是它）。
    """
    outcome = sa.evaluate_embedding_dim(declared_dim=1024, column=None)
    assert outcome.status is AssertionStatus.PENDING
    assert "W2A" in outcome.detail


@pytest.mark.parametrize(
    ("column", "reason"),
    [
        (("real", None), "不是 vector"),
        (("vector", None), "未声明维度"),
        (("vector(768)", 768), "不一致"),
    ],
)
def test_embedding_dim_fails(column: tuple[str, int | None], reason: str) -> None:
    outcome = sa.evaluate_embedding_dim(declared_dim=1024, column=column)
    assert outcome.status is AssertionStatus.FAIL
    assert reason in outcome.detail


def test_embedding_dim_pass() -> None:
    outcome = sa.evaluate_embedding_dim(declared_dim=1024, column=("vector(1024)", 1024))
    assert outcome.status is AssertionStatus.PASS


# ---------------------------------------------------------------------------
# 4. audit_log_append_only_enforced（N-09 的前提 / 07 §18.4 第 5 条）
# ---------------------------------------------------------------------------

def _access(**overrides: object) -> AuditAccess:
    base: dict[str, object] = {
        "table_present": True,
        "connecting_role": "app_rw",
        "connecting_role_is_superuser": False,
        "can_insert": True,
        "can_update": False,
        "can_delete": False,
        "can_truncate": False,
        "trigger_present": True,
    }
    base.update(overrides)
    return AuditAccess(**base)  # type: ignore[arg-type]


def test_audit_append_only_pass() -> None:
    outcome = sa.evaluate_audit_append_only(_access())
    assert outcome.status is AssertionStatus.PASS


def test_audit_table_missing_fails() -> None:
    """表不存在 = 迁移没跑 = **硬前置不成立** → FAIL（这条**不是** PENDING）。

    ⚠️ 与向量列那条的差别值得说明：向量列"不存在"是**上游未交付**（判 PENDING），
    而审计表"不存在"是**本窗口自己的迁移没执行**（判 FAIL）。
    区分标准是"这件事归谁" —— 归自己的必须是 FAIL，否则"我忘了跑迁移"会被
    伪装成"上游还没做完"。
    """
    outcome = sa.evaluate_audit_append_only(_access(table_present=False))
    assert outcome.status is AssertionStatus.FAIL
    assert "迁移 0001" in outcome.detail


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"can_update": True}, "UPDATE"),
        ({"can_delete": True}, "DELETE"),
        # ★ TRUNCATE 单独列一条：它删全表且**不触发行级触发器** →
        # 只查 UPDATE/DELETE 会漏掉它，而漏掉的后果是四层保证一起失效却毫无提示。
        ({"can_truncate": True}, "TRUNCATE"),
        ({"trigger_present": False}, "触发器"),
        ({"can_insert": False}, "INSERT"),
    ],
)
def test_audit_append_only_fails(overrides: dict[str, bool], reason: str) -> None:
    outcome = sa.evaluate_audit_append_only(_access(**overrides))
    assert outcome.status is AssertionStatus.FAIL
    assert reason in outcome.detail


def test_superuser_connection_is_reported_first() -> None:
    """超级用户连接必须**单独且置顶**报出来。

    超级用户绕过 ACL → 权限四项会显示"可 UPDATE / 可 DELETE"（其实权限配置没问题）。
    不单独报的话，排查方向会被引到"GRANT 配错了"，而真相是"连库的身份不对"。
    """
    outcome = sa.evaluate_audit_append_only(_access(connecting_role_is_superuser=True))
    assert outcome.status is AssertionStatus.FAIL
    assert outcome.detail.startswith("连接角色")
    assert "超级用户" in outcome.detail


# ---------------------------------------------------------------------------
# 5. semantic_bundle_passed_five_step_validation（插槽）
# ---------------------------------------------------------------------------

def test_semantic_bundle_slot_is_pending_and_names_w2a() -> None:
    """插槽未接线 → PENDING，且 detail **必须点名 W2A**。

    "有个东西没就绪"不是可行动的信息；"归 W2A（`semantics/loader.py`）"才是。
    这条也是本窗口不自己实现校验的理由：与 W2A 各写一份必然分叉（U-18 的教训）。
    """
    outcome = sa.evaluate_semantic_bundle(validator=None)
    assert outcome.status is AssertionStatus.PENDING
    assert "W2A" in outcome.detail and "semantics/loader.py" in outcome.detail


# ---------------------------------------------------------------------------
# 6. ★ 三态的 env-gate（与 U-19 的 τ 门禁同构）
# ---------------------------------------------------------------------------

def test_pending_is_fatal_only_in_prod_by_design() -> None:
    """★ 同一份 PENDING：`dev` 放行、`prod` 拒绝启动。**双断言**。

    这条测试就是"钉死机制"本身（与 `test_tau_gate_is_prod_only_by_design` 同构）：
    想把 prod 收紧去掉，必须**先改红这条带决策编号的测试**，
    而不是"顺手把 `is_fatal` 改一行"。

    两个方向都不能省：
    ① 只断言 prod 致命 → 无法区分"env-gate"与"一律致命"（后者会让阶段 1B 起不来）；
    ② 只断言 dev 放行 → 无法证明"生产真的收紧了"，那才是安全侧的那一半。
    """
    pending = AssertionOutcome(
        name="embedding_dim_matches_vector_column",
        status=AssertionStatus.PENDING,
        detail="stub",
    )
    assert pending.is_fatal(_settings(AppEnv.DEV)) is False, "dev 下 PENDING 不得致命（否则 DoD① 不可达）"
    assert pending.is_fatal(_settings(AppEnv.PROD)) is True, "prod 下 PENDING 必须致命（不存在'前置待补'的生产）"


def test_strict_in_prod_false_opts_out_explicitly() -> None:
    """显式 `strict_in_prod=False` 可以在 prod 下也放行 —— 但必须**写出来**。

    ⚠️ 当前**没有任何一条断言**用它。它存在是为了让"放宽"成为一个需要显式书写的动作：
    默认值必须是 `True`（生产口径），否则"忘了收紧"会变成默认行为。
    """
    relaxed = AssertionOutcome(
        name="x", status=AssertionStatus.PENDING, detail="stub", strict_in_prod=False
    )
    assert relaxed.is_fatal(_settings(AppEnv.PROD)) is False


def test_fail_is_fatal_in_every_env() -> None:
    """`FAIL` 无条件致命 —— env-gate 只作用于 `PENDING`，不作用于真实失败。"""
    failed = AssertionOutcome(name="x", status=AssertionStatus.FAIL, detail="stub")
    assert failed.is_fatal(_settings(AppEnv.DEV)) is True
    assert failed.is_fatal(_settings(AppEnv.PROD)) is True


# ---------------------------------------------------------------------------
# 7. 编排：顺序稳定、并行取事实、失败即拒绝启动
# ---------------------------------------------------------------------------

class _Logger:
    """记录调用（**不**断言日志正文 —— 那会把日志措辞变成契约，而它不是）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.calls.append(("info", event))

    def warning(self, event: str, **kwargs: object) -> None:
        self.calls.append(("warning", event))

    def error(self, event: str, **kwargs: object) -> None:
        self.calls.append(("error", event))


def _probes(**overrides: object) -> StartupProbes:
    async def analytics_role() -> tuple[bool, str] | None:
        return (False, "on")

    async def vector_column() -> tuple[str, int | None] | None:
        return None

    async def audit_access() -> AuditAccess:
        return _access()

    base: dict[str, object] = {
        "analytics_role": analytics_role,
        "vector_column": vector_column,
        "audit_access": audit_access,
    }
    base.update(overrides)
    return StartupProbes(**base)  # type: ignore[arg-type]


async def test_run_startup_assertions_returns_the_declared_order() -> None:
    """返回顺序 == `ASSERTION_NAMES`（顺序稳定 → 每次启动的日志可 diff）。"""
    outcomes = await sa.run_startup_assertions(_settings(), _probes())
    assert tuple(o.name for o in outcomes) == sa.ASSERTION_NAMES


async def test_pending_does_not_block_in_dev_and_is_logged() -> None:
    """dev：PENDING（向量列缺失 + 语义包插槽）**不**拒绝启动，但**必须**打 WARN。

    "不隐瞒"的落点就是这条 WARN —— 若 PENDING 静默通过，U-19 那套"放行但不隐瞒"
    的纪律在启动断言这里就只剩"放行"了。
    """
    logger = _Logger()
    outcomes = await sa.enforce_startup_assertions(_settings(AppEnv.DEV), _probes(), logger=logger)
    assert all(o.status is not AssertionStatus.FAIL for o in outcomes)
    assert ("warning", "startup_assertion_pending") in logger.calls
    assert ("info", "startup_assertion") in logger.calls


async def test_fail_refuses_to_start() -> None:
    """任一 FAIL → 抛 `ConfigError`（07 §18.4 fail-fast）。"""

    async def bad_audit() -> AuditAccess:
        return _access(can_delete=True)

    logger = _Logger()
    with pytest.raises(ConfigError, match="拒绝启动"):
        await sa.enforce_startup_assertions(_settings(), _probes(audit_access=bad_audit), logger=logger)
    assert ("error", "startup_assertions_failed") in logger.calls


async def test_prod_refuses_to_start_on_pending_alone() -> None:
    """★ prod：**仅**因为 PENDING 也要拒绝启动（与 `is_fatal` 的双断言呼应，端到端再钉一次）。"""
    logger = _Logger()
    with pytest.raises(ConfigError, match="拒绝启动"):
        await sa.enforce_startup_assertions(_settings(AppEnv.PROD), _probes(), logger=logger)
