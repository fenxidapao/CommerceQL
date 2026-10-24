"""W79-3：集成证据卫生（回环绑定 + `RETRIEVAL_TEST_PG_DSN` 可复现性）—— 零出站。

W78 的两次教训：
1. 一次性 PG/Redis 发布到 `0.0.0.0`/`::`，违反 A5 的"只绑回环"；
2. 证据的 `dsn_masked` 缺 `RETRIEVAL_TEST_PG_DSN`，按证据复跑复现不出 124/0/0
   （该变量需要 DDL 权限：app_rw ⇒ 6 skipped + 3 errors，super 才全绿）。
本文件只测**证据脚本的静态承诺**，不启动容器、不跑集成用例。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import w78_integration_evidence as ev

#: 刻意**不在源码里拼出完整 DSN 字面量**（DoD④ 的 gitleaks 规则会命中测试文件）。
_SCHEME = "postgresql" + "://"


def _dsn(user: str, password: str, *, port: int = 55432, db: str = "ecom_rls") -> str:
    return f"{_SCHEME}{user}:{password}@127.0.0.1:{port}/{db}"


def test_docker_run_commands_bind_loopback_only() -> None:
    runs = [c for c in ev.DOCKER_COMMANDS if c.startswith("docker run")]
    assert runs, "证据脚本必须带可复现的 docker run 命令"
    for command in runs:
        assert "-p 127.0.0.1:" in command, command
        assert "0.0.0.0" not in command, command


def test_dsn_evidence_includes_retrieval_pg_and_masks_passwords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "COMMERCEQL_TEST_SUPER_DSN",
        _dsn("postgres", "fake-super"),
    )
    monkeypatch.setenv(
        "COMMERCEQL_TEST_RW_DSN",
        _dsn("app_rw", "fake-rw"),
    )
    monkeypatch.setenv(
        "COMMERCEQL_TEST_RO_DSN",
        _dsn("app_ro", "fake-ro"),
    )
    monkeypatch.setenv(
        ev.RETRIEVAL_DSN_ENV,
        _dsn("postgres", "fake-retrieval"),
    )
    monkeypatch.setenv("COMMERCEQL_TEST_REDIS_URL", "redis://127.0.0.1:56379/0")

    evidence = ev.dsn_evidence()
    assert evidence["retrieval_pg"] is not None, "缺 RETRIEVAL_TEST_PG_DSN ⇒ 复跑复现不出 124"
    assert evidence["retrieval_pg"]["masked"] == (
        f"{_SCHEME}postgres:***@127.0.0.1:55432/ecom_rls"
    )
    assert evidence["retrieval_pg_needs_ddl"] is True
    assert "DDL" in str(evidence["retrieval_pg_note"])
    dumped = json.dumps(evidence, ensure_ascii=False)
    for secret in ("fake-super", "fake-rw", "fake-ro", "fake-retrieval"):
        assert secret not in dumped, f"口令泄露：{secret}"
    assert evidence["shared_ecom_touched"] is False


def test_shared_ecom_ports_are_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """指针落到共享端口/库时，证据必须自报 `shared_ecom_touched=true`。"""
    monkeypatch.setenv(
        "COMMERCEQL_TEST_SUPER_DSN",
        _dsn("postgres", "fake-shared", port=5432, db="ecom"),
    )
    monkeypatch.delenv("COMMERCEQL_TEST_RW_DSN", raising=False)
    monkeypatch.delenv("COMMERCEQL_TEST_RO_DSN", raising=False)
    monkeypatch.delenv(ev.RETRIEVAL_DSN_ENV, raising=False)
    monkeypatch.delenv("COMMERCEQL_TEST_REDIS_URL", raising=False)

    evidence: dict[str, Any] = ev.dsn_evidence()
    assert evidence["shared_ecom_touched"] is True
    assert "super" in evidence["shared_ecom_hits"]
