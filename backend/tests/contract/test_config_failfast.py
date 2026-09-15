"""契约断言：配置 fail-fast、`.env.example` 同步性，以及 **U-19 的 env-gate**。

归属窗口：W0（docs/08 §3.1）。对应 07 §18.4（启动即校验）与 N-15 / N-27 / U-01 / ADR-12。

为什么这些断言必须存在：
  `app/core/config.py` 里那 7 条 `model_validator` 是**最后一道**防误配的墙 ——
  它们拦的都是"配置能加载、但运行起来行为是错的"的情况
  （两套 DSN 指向同一账号 = 只读保证形同虚设；τ 未校准 = 绑定阈值无意义；
    融合权重不归一 = 分数跨查询不可比）。
  这类问题**不会**在启动时报错，只会在几个月后表现为"结果就是不太对"。
  所以墙必须自己也被测。

⚠️ 本文件同时**钉住 U-19 这个有意的取舍**：
  τ 校准检查只在 `APP_ENV=prod` 下强制（否则阶段 0 的 api 容器会在
  `docker compose up` 时崩溃重启，DoD① 的 /live=200 · /ready=503 变成不可验证）。
  若后续有人把它改回无条件强制，`test_tau_gate_is_prod_only_by_design` 会红掉并指向 U-19 ——
  这不是阻碍改动，而是**要求改动者显式推翻一个已登记的决策**，而不是顺手改掉。

⚠️ 本文件还如实登记了一处**实测暴露的限制**（见 §5）：
  `extra="forbid"` 拦得住"传错关键字的初始化参数"，**拦不住"拼错的环境变量名"**。
  pydantic-settings 会静默忽略未知环境变量。故真正的防线是
  `deploy/.env.example` ↔ `Settings.model_fields` 的**双向同步断言**，而不是 extra。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, Settings

pytestmark = pytest.mark.contract

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _BACKEND_ROOT.parent / "deploy" / ".env.example"


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
# 环境变量全集**直接取自 `Settings.model_fields`**，不手写：
#   手写清单会随配置项增删而漂移，且最容易犯的错是"手写了一个根本不存在的字段名"
#   （阶段 0 实测踩过：`OAUTH_CLIENT_SECRET` 看似像配置项，实际 config.py 里没有，
#     于是它被 pydantic-settings **静默忽略**，夹具"看起来在工作"其实少给了东西）。
_MANAGED_KEYS: tuple[str, ...] = tuple(Settings.model_fields)

#: 构造一个合法 `Settings` 所需的**最小**环境变量集。
#: 其余 60+ 项都有默认值；这里只给"不给就没法启动"的那几项。
_MINIMAL_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+psycopg://app_rw:pw@h:5432/commerceql",
    "ANALYTICS_DB_URL": "postgresql+psycopg://app_ro:pw@h:5432/commerceql",
    "REDIS_URL": "redis://h:6379/0",
    # ⚠️ 不给 stub 就构造不出来 —— 它是**必填**项（无默认值），这是刻意的：
    #    "启动时缺少 LLM 密钥"必须在启动时报错，而不是等到第一条查询才 500。
    "DEEPSEEK_API_KEY": "sk-stub-not-a-real-key",
}

_CALIBRATED_TAU: dict[str, object] = {
    "BINDING_TAU_MODEL_ID": "deepseek-chat@2026-08",
    "BINDING_TAU_PROMPT_VERSION": "binding-prompt-v1",
    "BINDING_TAU_CALIBRATED_AT": "2026-09-01T00:00:00+08:00",
}


def _build(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    """构造 `Settings`，**不读 `.env` 文件**（否则结果随开发者本地配置漂移）。"""
    for key in _MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in _MINIMAL_ENV.items():
        monkeypatch.setenv(key, value)
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _expect_fail(monkeypatch: pytest.MonkeyPatch, fragment: str, **overrides: object) -> str:
    with pytest.raises(ValidationError) as excinfo:
        _build(monkeypatch, **overrides)
    message = str(excinfo.value)
    assert fragment in message, f"报错信息未包含 {fragment!r}：\n{message}"
    return message


# ---------------------------------------------------------------------------
# 1. 基线
# ---------------------------------------------------------------------------

def test_minimal_env_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build(monkeypatch)
    assert settings.APP_ENV is AppEnv.DEV
    assert settings.ENABLE_RESULT_CACHE is False


def test_settings_are_lazy() -> None:
    """`app.core.config` 的 import 不得要求环境变量齐全（N-01：确定性模块可离线测）。

    若哪天有人加了模块级 `settings = Settings()`，本测试会红 —— 那会毁掉
    "只想跑一个离线单测却要先配生产密钥"的可用性。

    ⚠️ 为什么用**子进程**而不是 `importlib.reload`（阶段 0 实测踩过这个坑）：
    `reload` 会原地改写模块 `__dict__`，于是**旧类**的 `model_validator` 闭包里的
    `__globals__` 指向了**新**枚举，而旧类的字段注解仍绑定**旧**枚举 ——
    `self.APP_ENV is AppEnv.PROD` 两边来自不同类对象，恒为 False。
    表现为"prod 的校验悄悄失效、测试顺序一换就红"。
    子进程没有这个污染，且更贴近真实场景（真的是一个干净的进程在 import）。
    """
    env = {k: v for k, v in os.environ.items() if k not in set(_MANAGED_KEYS)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.core.config as c; assert c._settings is None, 'import 即实例化了 Settings'",
        ],
        cwd=str(_BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "在**没有任何配置环境变量**的子进程里 `import app.core.config` 失败：\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_get_settings_is_a_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_settings()` 必须缓存 —— 反复构造 `Settings()` 会让"启动即校验"变成"每次调用都校验"，
    而 pydantic-settings 每次构造都要重读全部环境变量（66 项 + dotenv 解析）。"""
    import app.core.config as config_module

    for key in _MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in _MINIMAL_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(config_module, "_settings", None, raising=False)
    try:
        first = config_module.get_settings()
        assert config_module.get_settings() is first
    finally:
        monkeypatch.setattr(config_module, "_settings", None, raising=False)


# ---------------------------------------------------------------------------
# 2. U-01：两套 DSN 的隔离
# ---------------------------------------------------------------------------

def test_dsns_must_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    """U-01 的核心：`ANALYTICS_DB_URL` 与 `DATABASE_URL` 同值 → "只读账号"成了纸面承诺，
    分析查询将拿写权限跑（N-02 被绕过，而 RLS 之外再无兜底）。"""
    _expect_fail(monkeypatch, "不得相同", ANALYTICS_DB_URL=_MINIMAL_ENV["DATABASE_URL"])


def test_dsn_must_be_psycopg3(monkeypatch: pytest.MonkeyPatch) -> None:
    """psycopg2 不支持 `set_config(..., is_local=true)` 的形状，且本项目依赖 psycopg3 的
    服务端游标语义 → 必须显式拒绝，而不是"能装上就跑"。"""
    _expect_fail(monkeypatch, "psycopg", DATABASE_URL="postgresql://app_rw:pw@h:5432/db")


def test_analytics_dsn_must_be_psycopg3(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_fail(
        monkeypatch,
        "psycopg",
        ANALYTICS_DB_URL="postgresql+psycopg2://app_ro:pw@h:5432/commerceql",
    )


# ---------------------------------------------------------------------------
# 3. N-27 + ★ U-19：τ 的 env-gate
# ---------------------------------------------------------------------------

def test_tau_uncalibrated_boots_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段 0 / 本地开发：τ 未校准**允许启动**，但状态必须可见（不隐瞒）。"""
    settings = _build(monkeypatch, APP_ENV="dev")
    assert settings.binding_tau_is_calibrated is False


def test_tau_uncalibrated_refuses_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """N-27 的强制力在 prod 下一点不减。"""
    _expect_fail(monkeypatch, "BINDING_TAU", APP_ENV="prod")


def test_tau_version_without_calibration_refuses_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """只声明版本、不给校准时间 —— 最容易蒙混过关的一档，必须单独拦。"""
    overrides: dict[str, object] = {
        "APP_ENV": "prod",
        "BINDING_TAU_MODEL_ID": _CALIBRATED_TAU["BINDING_TAU_MODEL_ID"],
        "BINDING_TAU_PROMPT_VERSION": _CALIBRATED_TAU["BINDING_TAU_PROMPT_VERSION"],
    }
    _expect_fail(monkeypatch, "CALIBRATED_AT", **overrides)


def test_fully_calibrated_tau_boots_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build(monkeypatch, APP_ENV="prod", **_CALIBRATED_TAU)
    assert settings.binding_tau_is_calibrated is True


def test_tau_gate_is_prod_only_by_design(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 钉住 U-19 这一有意取舍（改动它必须显式推翻一个已登记的决策）。

    阶段 0 的 DoD① 要求 `docker compose up` 后三探针可达；而 τ 的校准是 W2B 的产出，
    阶段 0 根本不存在。若 τ 检查变成无条件强制，api 容器会崩溃重启，
    `/live` 与 `/ready` 都无法访问，**DoD① 变成不可验证**。

    若要收紧，请改这条测试并**同时**更新交付说明里的 U-19，而不是绕过它。
    更合适的收紧方式是加「非 prod 却连生产 DSN → 拒绝启动」，而不是把 τ 检查改回无条件。
    """
    dev = _build(monkeypatch, APP_ENV="dev")
    assert dev.binding_tau_is_calibrated is False  # 未校准仍可构造 → 证明是 env-gate

    with pytest.raises(ValidationError):
        _build(monkeypatch, APP_ENV="prod")  # 同一份配置在 prod 下必须被拒


@pytest.mark.parametrize("env", ["staging"])
def test_tau_gate_does_not_apply_to_staging(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    """只有 `prod` 触发强制 —— staging 是预生产，未校准的 τ 不应阻断联调。

    注意：这**不等于**"staging 可以端着未校准的 τ 对外服务" ——
    那是运维纪律问题，不是配置校验能解决的；本断言只固定"不阻断启动"这一行为。
    """
    settings = _build(monkeypatch, APP_ENV=env)
    assert settings.binding_tau_is_calibrated is False


# ---------------------------------------------------------------------------
# 4. 其余 fail-fast 项
# ---------------------------------------------------------------------------

def test_prod_forbids_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """prod 走同源反代（07 §18.4 列为常见误配）：有 CORS 白名单 = 有人在绕过反代直连。"""
    _expect_fail(
        monkeypatch,
        "CORS_ALLOWED_ORIGINS",
        APP_ENV="prod",
        CORS_ALLOWED_ORIGINS="https://evil.example",
        **_CALIBRATED_TAU,
    )


def test_result_cache_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-12 / PRD §12.4：结果缓存"键设计错 = 事故，收益小风险大" → 二次确认。"""
    _expect_fail(monkeypatch, "ENABLE_RESULT_CACHE_CONFIRMED", ENABLE_RESULT_CACHE="true")


def test_result_cache_ok_with_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build(
        monkeypatch,
        ENABLE_RESULT_CACHE="true",
        ENABLE_RESULT_CACHE_CONFIRMED="true",
    )
    assert settings.ENABLE_RESULT_CACHE is True


@pytest.mark.parametrize(
    ("key", "threshold_key", "fragment"),
    [
        ("GATE3_COST_WARN", "GATE3_COST_REJECT", "GATE3_COST"),
        ("GATE3_ROWS_WARN", "GATE3_ROWS_REJECT", "GATE3_ROWS"),
    ],
)
def test_gate3_warn_must_be_below_reject(
    monkeypatch: pytest.MonkeyPatch, key: str, threshold_key: str, fragment: str
) -> None:
    """warn ≥ reject → 预警档永不触发 = 等于没有预警（直接跳到拒绝）。

    取 reject 的默认值当 warn —— 即 `warn == reject` 这个最容易写错的边界。
    """
    defaults = _build(monkeypatch)
    _expect_fail(monkeypatch, fragment, **{key: getattr(defaults, threshold_key)})


def test_fusion_weights_must_sum_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """不归一 → 融合分数跨查询不可比 → 阈值调参失去意义。"""
    _expect_fail(
        monkeypatch,
        "之和必须为 1.0",
        DENSE_WEIGHT="0.9",
        SPARSE_WEIGHT="0.9",
        VALUE_WEIGHT="0.1",
        GRAPH_WEIGHT="0.1",
    )


def test_fusion_weights_default_sum_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build(monkeypatch)
    total = (
        settings.DENSE_WEIGHT
        + settings.SPARSE_WEIGHT
        + settings.VALUE_WEIGHT
        + settings.GRAPH_WEIGHT
    )
    assert abs(total - 1.0) <= 0.01, f"默认权重之和 = {total}"


def test_session_lock_wait_has_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """07 §9.5：禁止无限排队（无上限 = 延迟不可预期）。"""
    _expect_fail(monkeypatch, "SESSION_LOCK_WAIT_MS", SESSION_LOCK_WAIT_MS="60000")


def test_invalid_timezone_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_fail(monkeypatch, "TIMEZONE", TIMEZONE="Mars/Olympus_Mons")


def test_invalid_log_level_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_fail(monkeypatch, "LOG_LEVEL", LOG_LEVEL="VERBOSE")


# ---------------------------------------------------------------------------
# 5. ★ 实测暴露的限制：extra="forbid" 拦不住拼错的环境变量名
# ---------------------------------------------------------------------------
# `SettingsConfigDict(extra="forbid")` 的注释曾写成"环境变量名写错即启动失败"。
# 阶段 0 实测证明这句话**不成立**：pydantic-settings 对未知**环境变量**是静默忽略的，
# extra 只作用于显式传入的初始化参数与 dotenv 内容。
#
# 这条限制必须被固定的两个理由：
#   ① 它会让人误以为"有防护"而不去建立真正的防线（.env.example 同步断言）；
#   ② 静默忽略的表现是"配置项悄悄退回默认值"，正是最贵的一类故障。

def test_unknown_init_kwarg_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """extra="forbid" 真正生效的场景：显式传错关键字。"""
    for key in _MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)
    kwargs = {**_MINIMAL_ENV, "DATABSE_URL": "typo"}
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]
    assert "Extra inputs are not permitted" in str(excinfo.value)


def test_unknown_env_var_is_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ **如实记录限制**：拼错的环境变量名**不会**导致启动失败。

    本断言不是在"认可"这个行为，而是把一个已核实的限制写进契约 ——
    若将来 pydantic-settings 改了行为（或我们改成显式校验），这条会红，
    提示"限制已消失，可以更新文档与防线"。
    """
    settings = _build(monkeypatch, DATABSE_URL="typo", REDIS_URL_TYPO="typo")
    assert _MINIMAL_ENV["DATABASE_URL"] == settings.DATABASE_URL  # 拼错的那份被忽略，值未变
    assert not hasattr(settings, "DATABSE_URL")


# ---------------------------------------------------------------------------
# 6. 真正的防线：`deploy/.env.example` ↔ `Settings.model_fields` 双向同步
# ---------------------------------------------------------------------------
# 这是替代 extra 的实际保护措施。它拦的是 07 §18.4 / config.py 明文要求的场景：
#   "新增配置项必须同步 07 附-6 与 `.env.example`，否则新机器部署会缺项"
# 缺项的后果很隐蔽：新机器用默认值启动，而默认值通常是"最不安全但能跑"的那一档。

def _env_example_keys() -> set[str]:
    assert _ENV_EXAMPLE.exists(), f"缺少 {_ENV_EXAMPLE}（阶段 0 清单内文件）"
    keys: set[str] = set()
    for raw in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def test_env_example_has_no_stale_keys() -> None:
    """`.env.example` 不得留有已删除的配置项（否则新机器会照抄一个无效变量，
    而由于 §5 的限制，它**不会报错** —— 只会让人以为配置生效了）。"""
    stale = sorted(_env_example_keys() - set(Settings.model_fields))
    assert not stale, f".env.example 含 config.py 里不存在的键：{stale}"


def test_env_example_covers_every_setting() -> None:
    """每个配置项都必须出现在 `.env.example`（新机器部署不缺项）。"""
    missing = sorted(set(Settings.model_fields) - _env_example_keys())
    assert not missing, f"以下配置项未写进 deploy/.env.example：{missing}"


def test_env_example_keys_are_upper_snake_case() -> None:
    bad = sorted(k for k in _env_example_keys() if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k))
    assert not bad, f"配置键必须全大写蛇形（case_sensitive=False 依赖此约定）：{bad}"


def test_env_example_does_not_ship_real_secrets() -> None:
    """`.env.example` 里的密钥类字段必须是**明显的占位符** ——

    DoD④（gitleaks 无命中）建立在"示例文件里没有真密钥"之上。
    真实事故记录在 PRD §11.5：示例文件带着可用密钥被提交。

    判定方式刻意保守：只承认 docker-compose 服务名/回环地址这类**结构性**占位主机，
    其余一律视为"可能指向真实环境"。宁可让新机器部署时多改一行，也不要漏一个真密钥。
    """
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    # 1) 任何看起来像真实 DeepSeek 密钥的值
    assert not re.search(r"^[A-Z_]+=.*\bsk-[A-Za-z0-9]{16,}", text, flags=re.MULTILINE), (
        ".env.example 疑似包含真实 DeepSeek 密钥（sk- 长串）"
    )

    # 2) DSN 的主机必须是 compose 服务名或回环地址
    placeholder_hosts = {"pg", "pgbouncer", "redis", "localhost", "127.0.0.1", "postgres"}
    for key in ("DATABASE_URL", "ANALYTICS_DB_URL", "REDIS_URL"):
        match = re.search(rf"^{key}=(.*)$", text, flags=re.MULTILINE)
        assert match, f".env.example 缺少 {key}"
        value = match.group(1).strip()
        # `scheme://[user:pass@]host:port/...` —— 有无 `@` 都要能取到 host
        authority = value.split("://", 1)[-1].split("/", 1)[0]
        host = authority.rsplit("@", 1)[-1].split(":", 1)[0].strip()
        assert host in placeholder_hosts, (
            f"{key} 的主机 {host!r} 不像占位符（允许：{sorted(placeholder_hosts)}）；"
            f"完整值：{value!r}"
        )


# ---------------------------------------------------------------------------
# 8. ★ 行尾注释泄漏（本会话实测发现的真缺陷，2026-09-15）
# ---------------------------------------------------------------------------
# **根因（已实测复现）**：python-dotenv 只在**值非空**时才剥离 ` # 注释`：
#       A=                → ''            ✅
#       B=value  # cmt    → 'value'       ✅
#       C=  # only cmt    → '# only cmt'  ❌ **注释变成了值**
#
# **实际后果**：`.env.example` 里 5 个键静默拿到注释文本，其中 4 个是 τ 校准三元组
# + 报告引用（`BINDING_TAU_MODEL_ID` / `_PROMPT_VERSION` / `_CALIBRATED_AT` / `_REPORT_REF`）
# → 三个"必填"字段全部"非空" → `binding_tau_is_calibrated` 恒为 **True**：
#   · **N-27 的 prod 门禁形同虚设**（它是靠"这三项非空"来判定的）；
#   · **U-19 硬要求① 的启动 WARN 永远不会打**（代码以为 τ 已校准）。
# 即：一处解析陷阱把刚裁定的两处保护同时绕过了，而且**全程没有任何报错**。
#
# 下面三条断言分别守：数据（示例文件）、代码（兜底校验）、默认态（τ 未校准）。

#: 值必须留空的键 —— 它们空着才代表"未配置/未校准"这个**状态**。
_MUST_BE_EMPTY = (
    "DEEPSEEK_API_KEY",
    "BINDING_TAU_MODEL_ID",
    "BINDING_TAU_PROMPT_VERSION",
    "BINDING_TAU_CALIBRATED_AT",
    "BINDING_TAU_REPORT_REF",
)


def _env_example_values() -> dict[str, str | None]:
    """用**生产同一个解析器**（`python-dotenv`，pydantic-settings 的 env_file 后端）读示例文件。

    ⚠️ 刻意不用自己写的正则去解析：那样测的是"我理解的 .env 语法"，
    而不是"程序实际读到的值" —— 本缺陷正是**两者不一致**造成的。
    `python-dotenv` 是 `pydantic-settings[dotenv]` 的传递依赖，不新增依赖。
    """
    import dotenv

    return {
        key: value
        for key, value in dotenv.dotenv_values(_ENV_EXAMPLE).items()
    }


@pytest.mark.parametrize("key", _MUST_BE_EMPTY)
def test_env_example_empty_valued_keys_stay_empty(key: str) -> None:
    """示例文件里这些键必须解析成**空串**，不能被行尾注释污染。"""
    value = _env_example_values()[key]
    assert value == "", (
        f".env.example 的 {key} 解析出非空值 {value!r} —— "
        f"疑似把行尾注释读成了值（python-dotenv 在值为空时不剥离 ` # 注释`）"
    )


def test_env_example_has_no_comment_leak_anywhere() -> None:
    """全量扫描：**任何**键的值都不得以 `#` 开头。

    比"检查那 5 个键"更强 —— 它拦的是**规则**而不是**实例**：
    以后新增任何 `KEY=  # 说明` 的行都会在这里红掉。
    """
    leaked = {
        key: value
        for key, value in _env_example_values().items()
        if isinstance(value, str) and value.lstrip().startswith("#")
    }
    assert not leaked, (
        f".env.example 有键把行尾注释读成了值：{leaked}\n"
        f"  修法：把注释移到上一行，让该行只留 `KEY=`（该文件顶部有完整说明）"
    )


def test_config_rejects_comment_leaked_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """代码层兜底：值以 `#` 开头 → **拒绝启动**（而不是带着垃圾值跑起来）。

    为什么不让 pydantic 悄悄 strip 掉：strip 会把"配置错误"变成"配置正常"，
    作者永远不知道自己写错了；而这里的正确反应是**让人改那一行**。
    """
    _expect_fail(
        monkeypatch,
        "行尾注释",
        BINDING_TAU_CALIBRATED_AT="# ★ 必填：ISO8601",
    )


def test_env_example_default_state_is_uncalibrated() -> None:
    """把示例文件当默认配置用时，τ 必须落在**未校准**态 ——

    这是 U-19 那条 WARN 的触发条件。若示例文件让 τ "看起来已校准"，
    那么每个新环境都会带着"已校准"的假象启动（而且没人会去看那一行）。
    """
    values = _env_example_values()
    calibrated = bool(
        values.get("BINDING_TAU_MODEL_ID")
        and values.get("BINDING_TAU_PROMPT_VERSION")
        and values.get("BINDING_TAU_CALIBRATED_AT")
    )
    assert calibrated is False, ".env.example 复制出来的默认环境不应是「已校准」态"
