"""U-124 判据③：三池 `search_path` 形态的离线契约断言。

归属窗口：W2A（07 v1.7.1 裁定，三方同批：W1B pools / W0 常量 / W2A materialize）。

背景（07 v1.7.1 U-124，P0）：闸门 `ast_gate.py:529-534` 拒绝一切 schema 限定名（R16，
冻结红队集形状）⇒ 业务 SQL 只能写**裸资产名**；而 analytics 池连接建立时不带
`search_path` ⇒ `"$user", public` ⇒ 裸资产名一律 `undefined_table`。两边互相指认成死锁：
改 R16 会被冻结红队集形状否决，不改则预检永远 0 条 ok（G-6 没有分母）。
裁定 = **不改 R16**，DB 侧兜底：analytics 池连接建立时固定 `search_path=<APP_SCHEMA>`
（照 `checkpoint_connect_kwargs` 的 `lg` 先例）。

| 池 | 契约形态 | 依据 |
|---|---|---|
| metadata | **不得**带 `options`/search_path | U-124 禁止动作⑦：不扩散到 metadata 池 |
| analytics | `options = -c search_path=<APP_SCHEMA>` | 判据①：连接建立时固定（非连接内 `SET`，禁止动作⑥） |
| checkpoint | `options = -c search_path=lg`（既有） | 07 §5.5 表在 `lg`；本次不动，钉住防回退 |

⚠️ 离线断言证明的是**装配代码没写错**；"真栈上 `SELECT pay_amount FROM v_order_paid`
能出 ok"（判据④）是运行时事实，需 w7load-api 实测（W7 六臂对照的 C 臂），
本文件**不**声称已验。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import APP_SCHEMA, Settings
from app.repo import pools as pools_mod
from app.repo.pools import (
    ANALYTICS_APPLICATION_NAME,
    CHECKPOINT_SCHEMA,
    checkpoint_connect_kwargs,
)

_RW = "postgresql+psycopg://app_rw:pw@localhost:5432/ecom"
_RO = "postgresql+psycopg://app_ro:pw@localhost:5432/ecom"


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]  # 其余字段来自 conftest 的占位环境
        DATABASE_URL=_RW,
        ANALYTICS_DB_URL=_RO,
    )


def test_app_schema_constant_is_pinned() -> None:
    """唯一真相点的**值**钉在这里：改 `APP_SCHEMA` 的值必须过这道门。

    `app` 这个字面量全仓只允许出现在 `app/core/config.py`（判据②）；
    测试作为契约面钉值不算第二份实现，反而是防止"悄悄换 schema 名"的唯一哨兵。
    """
    assert APP_SCHEMA == "app"


def test_analytics_connect_args_pin_search_path() -> None:
    """判据① 正面：analytics 连接参数必须带池级 `search_path`（唯一构造点）。"""
    args = pools_mod.analytics_connect_args()
    assert args["application_name"] == ANALYTICS_APPLICATION_NAME
    assert args["options"] == f"-c search_path={APP_SCHEMA}"


def test_metadata_connect_args_carry_no_search_path() -> None:
    """禁止动作⑦ 反面：metadata 池不得被扩散带上 search_path。"""
    args = pools_mod._connect_args(
        pools_mod.POOL_SPECS[pools_mod.PoolKind.METADATA].application_name
    )
    assert "options" not in args


def test_checkpoint_connect_kwargs_pin_lg_search_path() -> None:
    """既有 `lg` 先例钉住防回退：本次 U-124 **不动** checkpoint 池（判据边界）。"""
    kwargs = checkpoint_connect_kwargs()
    assert kwargs["options"] == f"-c search_path={CHECKPOINT_SCHEMA}"
    assert CHECKPOINT_SCHEMA != APP_SCHEMA  # 两池 search_path 不同源，混写即事故


@pytest.mark.parametrize(
    ("builder_name", "expected_search_path"),
    [("build_metadata_engine", None), ("build_analytics_engine", APP_SCHEMA)],
)
def test_builders_route_through_unique_construction_point(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    builder_name: str,
    expected_search_path: str | None,
) -> None:
    """装配函数必须经 `_connect_args` 唯一构造点取参，且 search_path 各归各位。

    用录制包装器而不是读 SQLAlchemy 池内部（`pool._creator` 是普通函数，
    connect_args 不暴露在公开面上）——录到的**就是装配实际所用的参数**，
    同时顺带证明装配没有绕开构造点手写 dict（那样录制会为空）。
    """
    recorded: list[dict[str, Any]] = []
    real = pools_mod._connect_args

    def spy(application_name: str, *, search_path: str | None = None) -> dict[str, str]:
        args = real(application_name, search_path=search_path)
        recorded.append({"application_name": application_name, **args})
        return args

    monkeypatch.setattr(pools_mod, "_connect_args", spy)
    builder = getattr(pools_mod, builder_name)
    builder(settings)

    assert len(recorded) == 1, f"{builder_name} 应恰好经构造点取参一次"
    call = recorded[0]
    assert "options" not in call or f"search_path={expected_search_path}" in call[
        "options"
    ], f"{builder_name} 的 search_path 形态漂移：{call}"
    if expected_search_path is None:
        assert "options" not in call
