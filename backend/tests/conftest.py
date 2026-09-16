"""pytest 全局装置（W0 所有，docs/08 §3.1）。

**存在的理由**：`app/core/config.py` 的必填项含 `DEEPSEEK_API_KEY` / 两个 DSN。
若测试依赖真实环境变量，就会出现两种坏结果之一：
  · 开发者在本机导出真密钥才能跑测试（**密钥因此散落**）；
  · 或者有人把密钥写进测试文件（**更糟**）。

所以这里注入**明显的非密钥占位值**，并遵循两条纪律：
  ① `setdefault` —— 真实环境变量优先，不覆盖 CI 的注入；
  ② 占位值一律带 `placeholder` / `stub` / `local` 字样，**遇到"疑似真密钥"的断言必须失败**。
     (`test_config_failfast.py::test_env_example_does_not_ship_real_secrets` 是配套的另一半。)

`app/main.py` 的文档字符串早已声明"CI 与单测通过 `tests/conftest.py` 提供非密钥占位值" ——
本文件就是兑现那句话。（阶段 0 交付时它其实**不存在**，是复跑测试时才补上的：
`create_app()` 的用例当场红了。文档里写了"有"，但盘上没有 —— 属于"影子承诺"。）
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator

import pytest

#: 非密钥占位环境变量。**刻意写得像占位符**，且 DSN 指向 compose 服务名（真实环境里不可能是这些值）。
_PLACEHOLDER_ENV: dict[str, str] = {
    "APP_ENV": "dev",
    "DEEPSEEK_API_KEY": "sk-placeholder-not-a-real-key",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DATABASE_URL": "postgresql+psycopg://app_rw:placeholder@pg:5432/ecom",
    "ANALYTICS_DB_URL": "postgresql+psycopg://app_ro:placeholder@pg:5432/ecom",
    "REDIS_URL": "redis://redis:6379/0",
    # ADR-17 的本地 stub IdP：校验代码与真实 IdP 完全一致，只把 JWKS 来源做成配置
    "JWT_PUBLIC_KEY": "placeholder-public-key",
    "JWT_ISSUER": "https://issuer.invalid/",
    "OAUTH_TENANT_ID": "placeholder-tenant",
    "OAUTH_CLIENT_ID": "placeholder-client",
    "OAUTH_CLIENT_SECRET": "placeholder-secret",
    "CORS_ALLOWED_ORIGINS": "",
    "ENABLE_RESULT_CACHE_CONFIRMED": "false",
}


@pytest.fixture(scope="session", autouse=True)
def _placeholder_env() -> Iterator[None]:
    """会话级注入占位环境（`setdefault`，不覆盖真实值）。"""
    for key, value in _PLACEHOLDER_ENV.items():
        os.environ.setdefault(key, value)
    yield


@pytest.fixture(scope="session", autouse=True)
def _win32_selector_event_loop_policy() -> Iterator[None]:
    """win32 下把事件循环策略换成 Selector（**U-39**，2026-09-16）。

    根因：psycopg async 在 Windows **只支持** `SelectorEventLoop`，而 Windows 默认是
    `ProactorEventLoop`；阶段 1B（B4）让 `lifespan` 第一次做真实 I/O（启动断言 +
    readiness 探针走 psycopg async）后，`TestClient(create_app())` 的用例当场撞上
    `psycopg.InterfaceError`。这是**环境不兼容第一次暴露**，不是断言逻辑写错
    （W1B 已做对照实验：同一份代码换策略后完全正常）。

    ⚠️ **刻意不用** `asyncio.to_thread` + 同步连接去"修"：那能让测试变绿，
    但会把"应用本体在 Windows 宿主跑不起来（附录 D E-1：开发期即用 Docker）"
    这个事实藏起来 —— 修症状留病因。唯一合法的转绿路径就是本 fixture。
    非 win32 下是 no-op（Linux CI / 容器不受影响）。
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    yield


@pytest.fixture(autouse=True)
def _reset_tau_gauge() -> Iterator[None]:
    """把指标 gauge 复位，避免"某个用例改了 gauge 影响下一个用例"的用例间耦合。

    `app/obs/metrics.py` 的 gauge 是模块级全局状态（这正是 gauge 的语义），
    而 `create_app()` 会在 lifespan 里写它 —— 不隔离的话，测试的执行顺序会影响结果。
    """
    from app.obs import metrics

    metrics.set_binding_tau_calibrated(False)
    yield
