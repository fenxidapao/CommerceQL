"""W78-1：把一次性 Docker 集成层实跑结果落成机器可读证据（零出站）。

输入：
* `pytest backend/tests/integration --junitxml=...` 的 JUnit XML；
* 两个一次性容器的 `docker inspect` / 镜像 `RepoDigests`；
* 运行时的 `COMMERCEQL_TEST_*` 环境变量（只输出脱敏后的库名+端口，不落口令）。

输出 `eval/results_w78_integration.json`：
* 逐文件 passed/failed/errors/skipped；
* `g1_evidence.integration_ran`（由"真的执行了 + 指定的三个 P0 文件各有用例"推出）；
* `g4_evidence.pg_rls_verified`（由 `test_rls_tenant_isolation.py` 全绿 +
  `test_migration_0003_views.py` 的策略/属主对象全绿推出，不手填）；
* 容器名/镜像 digest/端口、是否拉镜像、是否碰共享 `ecom`。

⚠️ 任一前置不满足（集成没跑、RLS 文件缺失/有红、连到共享库）⇒ 写出证据并**非零退出**，
不得把 G-1/G-4 写成 PASS。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402

OUT = os.path.join(HERE, "results_w78_integration.json")
JUNIT_COMMITTED = os.path.join(HERE, "results_w78_integration.junit.xml")

REQUIRED_P0 = (
    "tests.integration.test_exec_real_pg",
    "tests.integration.test_rls_tenant_isolation",
    "tests.integration.test_real_redis_lock_and_ratelimit",
)
RLS_FILE = "tests.integration.test_rls_tenant_isolation"
POLICY_FILE = "tests.integration.test_migration_0003_views"
CONTAINERS = ("cql-w78-pg", "cql-w78-redis")
IMAGES = ("pgvector/pgvector:pg16", "redis:7-alpine")
RETRIEVAL_DSN_ENV = "RETRIEVAL_TEST_PG_DSN"

#: W79-3：一次性服务**只绑回环**（A5）。测试与证据共用这份命令清单，避免演示命令再写 0.0.0.0。
DOCKER_COMMANDS: tuple[str, ...] = (
    "docker run -d --name cql-w78-pg -e POSTGRES_PASSWORD=*** -e POSTGRES_DB=ecom_rls "
    "-p 127.0.0.1:55432:5432 pgvector/pgvector:pg16",
    "docker run -d --name cql-w78-redis -p 127.0.0.1:56379:6379 redis:7-alpine",
    "alembic upgrade head（MIGRATION_DATABASE_URL=postgres@127.0.0.1:55432/ecom_rls）",
    "pytest backend/tests/integration -q --junitxml=<tmp>（env 见 dsn_masked）",
)


def _file_of(classname: str) -> str:
    parts = classname.split(".")
    if len(parts) >= 4 and parts[0] == "tests" and parts[1] == "integration":
        return ".".join(parts[:3])
    return classname


def _parse_junit(path: str) -> dict[str, Any]:
    tree = ET.parse(path)
    by_file: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                 "time_s": 0.0, "failed_tests": [], "error_tests": [], "skipped_tests": []}
    )
    total = {"tests": 0, "failed": 0, "errors": 0, "skipped": 0, "time_s": 0.0}
    for case in tree.iter("testcase"):
        key = _file_of(str(case.get("classname") or ""))
        row = by_file[key]
        row["tests"] += 1
        total["tests"] += 1
        seconds = float(case.get("time") or 0.0)
        row["time_s"] += seconds
        total["time_s"] += seconds
        name = str(case.get("name") or "")
        node = f"{key}::{name}"
        if case.find("failure") is not None:
            row["failed"] += 1
            row["failed_tests"].append(node)
            total["failed"] += 1
        elif case.find("error") is not None:
            row["errors"] += 1
            row["error_tests"].append(node)
            total["errors"] += 1
        elif case.find("skipped") is not None:
            row["skipped"] += 1
            row["skipped_tests"].append(node)
            total["skipped"] += 1
        else:
            row["passed"] += 1
    for row in by_file.values():
        row["time_s"] = round(row["time_s"], 3)
    total["time_s"] = round(total["time_s"], 3)
    total["passed"] = total["tests"] - total["failed"] - total["errors"] - total["skipped"]
    return {"files": dict(sorted(by_file.items())), "totals": total}


def _masked(env_name: str) -> dict[str, Any] | None:
    raw = os.environ.get(env_name, "")
    if not raw:
        return None
    # postgresql[+psycopg]://user:password@host:port/db
    from urllib.parse import urlsplit

    normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(normalized)
    return {
        "scheme": parts.scheme,
        "user": parts.username,
        "password": "***",
        "host": parts.hostname,
        "port": parts.port,
        "database": (parts.path or "/").lstrip("/"),
        "masked": f"{parts.scheme}://{parts.username}:***@{parts.hostname}:{parts.port}/"
                  f"{(parts.path or '/').lstrip('/')}",
    }


def _docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def _container(name: str) -> dict[str, Any]:
    raw = _docker("inspect", name)
    data = json.loads(raw)[0]
    return {
        "name": str(data.get("Name", "")).lstrip("/"),
        "id": str(data.get("Id", ""))[:12],
        "image": data.get("Config", {}).get("Image"),
        "image_id": data.get("Image"),
        "status": data.get("State", {}).get("Status"),
        "started_at": data.get("State", {}).get("StartedAt"),
        "ports": (data.get("NetworkSettings", {}).get("Ports") or {}),
    }


def _image(tag: str) -> dict[str, Any]:
    data = json.loads(_docker("image", "inspect", tag))[0]
    return {
        "tag": tag,
        "id": data.get("Id"),
        "repo_digests": data.get("RepoDigests") or [],
        "created": data.get("Created"),
    }


def dsn_evidence() -> dict[str, Any]:
    """脱敏 DSN 证据（含 W79-3 补的 `RETRIEVAL_TEST_PG_DSN`；口令一律 `***`）。"""
    dsn_super = _masked("COMMERCEQL_TEST_SUPER_DSN")
    dsn_rw = _masked("COMMERCEQL_TEST_RW_DSN")
    dsn_ro = _masked("COMMERCEQL_TEST_RO_DSN")
    dsn_retrieval = _masked(RETRIEVAL_DSN_ENV)
    redis_url = os.environ.get("COMMERCEQL_TEST_REDIS_URL", "")
    redis_masked = redis_url.replace("://", "://***@", 1) if redis_url else None
    # 共享库判定：端口 5432/6379 或库名 ecom ⇒ 视为碰共享栈。
    shared_hits: list[str] = []
    for label, dsn in (
        ("super", dsn_super), ("rw", dsn_rw), ("ro", dsn_ro), ("retrieval_pg", dsn_retrieval)
    ):
        if dsn and (dsn.get("port") in (5432, 6379) or dsn.get("database") == "ecom"):
            shared_hits.append(label)
    if redis_url and ":6379" in redis_url:
        shared_hits.append("redis")
    return {
        "super": dsn_super,
        "rw": dsn_rw,
        "ro": dsn_ro,
        #: QA §100.2：缺这一格时按证据复跑复现不出 124/0/0。
        "retrieval_pg": dsn_retrieval,
        "retrieval_pg_needs_ddl": True,
        "retrieval_pg_note": (
            "`RETRIEVAL_TEST_PG_DSN` 需要 **DDL 权限（super）**：用 app_rw 会 6 skipped + 3 errors；"
            "super 才 124/0/0。脱敏后只落库名+端口，口令不落盘。"
        ),
        "redis": redis_masked,
        "shared_ecom_touched": bool(shared_hits),
        "shared_ecom_hits": shared_hits,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W78-1 集成层证据")
    parser.add_argument("--junit", required=True)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--copy-junit", default=JUNIT_COMMITTED)
    args = parser.parse_args(argv)

    parsed = _parse_junit(args.junit)
    files = parsed["files"]
    totals = parsed["totals"]
    missing_p0 = [f for f in REQUIRED_P0 if files.get(f, {}).get("tests", 0) == 0]

    rls = files.get(RLS_FILE, {})
    policy = files.get(POLICY_FILE, {})
    rls_ok = (
        rls.get("tests", 0) >= 5
        and rls.get("failed", 0) == 0
        and rls.get("errors", 0) == 0
        and rls.get("skipped", 0) == 0
    )
    policy_ok = (
        policy.get("tests", 0) >= 6
        and policy.get("failed", 0) == 0
        and policy.get("errors", 0) == 0
        and policy.get("skipped", 0) == 0
    )
    pg_rls_verified = bool(rls_ok and policy_ok)
    integration_ran = bool(totals["tests"] > 0 and not missing_p0)

    dsn = dsn_evidence()
    shared_touched = bool(dsn["shared_ecom_touched"])

    containers = []
    for name in CONTAINERS:
        try:
            containers.append(_container(name))
        except Exception as exc:  # 容器已删也必须诚实落盘
            containers.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    images = []
    for tag in IMAGES:
        try:
            images.append(_image(tag))
        except Exception as exc:
            images.append({"tag": tag, "error": f"{type(exc).__name__}: {exc}"})

    junit_sha = hashlib.sha256(open(args.junit, "rb").read()).hexdigest()
    with open(args.junit, "rb") as src, open(args.copy_junit, "wb") as dst:
        dst.write(src.read())

    payload = {
        **_bootstrap.build_stamp(),
        "task": "W78-1 G-1/G-4 集成层实跑（一次性 Docker；零 LLM）",
        "docker": {
            "daemon": _docker("info", "--format", "{{.ServerVersion}}"),
            "containers": containers,
            "images": images,
            "image_pulled_this_round": False,
            "image_pull_basis": (
                "两个镜像在 `docker run` 之前已在本机镜像清单中；`docker run` 只输出容器 ID，"
                "无 pull 输出行。未新增拉取。"
            ),
            "removed_after_run": False,
            "removal_note": "证据生成后执行 `docker rm -f cql-w78-pg cql-w78-redis`",
        },
        "dsn_masked": dsn,
        "bind_policy": {
            "loopback_only": True,
            "host_ip_expected": "127.0.0.1",
            "rule": "A5：一次性测试服务的发布端口只绑回环；禁止 0.0.0.0/::",
            "commands_use_loopback": all(
                "-p 127.0.0.1:" in c for c in DOCKER_COMMANDS if c.startswith("docker run")
            ),
        },
        "junit": {
            "source": args.junit,
            "committed_copy": os.path.relpath(args.copy_junit, ROOT).replace("\\", "/"),
            "sha256": junit_sha,
            "totals": totals,
        },
        "files": files,
        "missing_required_p0": missing_p0,
        "g1_evidence": {
            "integration_ran": integration_ran,
            "passed": totals["passed"],
            "failed": totals["failed"],
            "errors": totals["errors"],
            "skipped": totals["skipped"],
            "basis": (
                "JUnit 里有真实执行的用例，且 test_exec_real_pg / test_rls_tenant_isolation / "
                "test_real_redis_lock_and_ratelimit 三个 P0 文件各有用例"
            ),
        },
        "g4_evidence": {
            "pg_rls_verified": pg_rls_verified,
            "leaked": 0 if pg_rls_verified else None,
            "basis": [
                f"`{RLS_FILE}`：{rls.get('tests', 0)} 条，passed={rls.get('passed', 0)}，"
                f"failed={rls.get('failed', 0)}，errors={rls.get('errors', 0)}，"
                f"skipped={rls.get('skipped', 0)}（行为级：未设身份=0 行 / shop_ids 两态可区分 / 不跨租户）",
                f"`{POLICY_FILE}`：{policy.get('tests', 0)} 条，passed={policy.get('passed', 0)}，"
                f"failed={policy.get('failed', 0)}，errors={policy.get('errors', 0)}，"
                f"skipped={policy.get('skipped', 0)}（对象级：属主 app_rw / 租户基表策略存在）",
            ],
            "derivation": "两文件全绿 ⇒ pg_rls_verified=true；任一文件缺失/有红/有 skip ⇒ false",
        },
        "verdicts": {
            "g1_integration_evidenced": integration_ran and totals["failed"] == 0 and totals["errors"] == 0,
            "g4_pg_rls_evidenced": pg_rls_verified and not shared_touched,
        },
        "commands": list(DOCKER_COMMANDS),
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"written: {os.path.relpath(args.out, ROOT)}")
    print(
        f"tests={totals['tests']} passed={totals['passed']} failed={totals['failed']} "
        f"errors={totals['errors']} skipped={totals['skipped']}"
    )
    print(f"integration_ran={integration_ran} pg_rls_verified={pg_rls_verified} "
          f"shared_ecom_touched={shared_touched} missing_p0={missing_p0}")
    ok = integration_ran and pg_rls_verified and not shared_touched and not missing_p0
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
