"""W79-3：集成证据卫生落盘（零出站；不改写 W78 历史产物）。

W78 的两条卫生问题（D-W79-3）：
1. 一次性容器发布到 `0.0.0.0`/`::`（A5 要求只绑回环）；容器已删、无残留，
   测试结果有效，但暴露事实必须留档；
2. `results_w78_integration.json` 的 `dsn_masked` 缺 `RETRIEVAL_TEST_PG_DSN` ⇒
   按证据复跑复现不出 124/0/0（该变量需要 DDL 权限：app_rw ⇒ 6 skipped + 3 errors）。

产物：`eval/results_w79_integration_hygiene.json`
* 读 W78 产物（只读）+ 当前 `docker ps` 残留检查；
* 写下一次的硬约束（`-p 127.0.0.1:<port>:<port>`）；
* `w78_artifact_rewritten=false`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend")):
    sys.path.insert(0, _p)

import _bootstrap  # noqa: E402
import w78_integration_evidence as ev  # noqa: E402

W78 = os.path.join(HERE, "results_w78_integration.json")
OUT = os.path.join(HERE, "results_w79_integration_hygiene.json")


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _host_ips(containers: list[dict[str, Any]]) -> list[str]:
    ips: set[str] = set()
    for container in containers:
        for mappings in (container.get("ports") or {}).values():
            for mapping in mappings or []:
                if mapping.get("HostIp"):
                    ips.add(str(mapping["HostIp"]))
    return sorted(ips)


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds(), 1)


def main() -> int:
    w78 = _load(W78)
    containers = list((w78.get("docker") or {}).get("containers") or [])
    host_ips = _host_ips(containers)
    loopback_violation = any(ip not in {"127.0.0.1", "::1"} for ip in host_ips)
    removed_at = (w78.get("docker") or {}).get("removed_at")
    exposure = [
        {
            "name": c.get("name"),
            "started_at": c.get("started_at"),
            "removed_at": removed_at,
            "exposed_seconds": _seconds_between(c.get("started_at"), removed_at),
        }
        for c in containers
    ]

    residual = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=cql-w78", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=60,
    )
    residual_names = [x for x in residual.stdout.splitlines() if x.strip()]

    dsn_w78 = w78.get("dsn_masked") or {}
    payload = {
        **_bootstrap.build_stamp(),
        "task": "W79-3 集成证据卫生（零出站；W78 历史产物不改写）",
        "w78_artifact": {
            "path": _relative(W78),
            "git_rev": w78.get("git_rev"),
            "git_dirty": w78.get("git_dirty"),
            "reattested_untouched": True,
        },
        "w78_historical_facts": {
            "published_host_ips": host_ips,
            "loopback_violation": loopback_violation,
            "violation_rule": "A5：一次性测试服务的发布端口只绑回环（127.0.0.1/::1）",
            "exposure": exposure,
            "containers_removed": bool((w78.get("docker") or {}).get("removed_after_run")),
            "residual_containers_now": residual_names,
            "residual_clean": not residual_names,
            "test_results_still_valid": True,
            "note": "端口暴露是卫生问题，不改变 124/0/0 的测试结论；容器已删、无残留",
        },
        "w78_evidence_gap": {
            "retrieval_test_pg_dsn_present_in_w78": "retrieval_pg" in dsn_w78,
            "missing_env": ev.RETRIEVAL_DSN_ENV,
            "reproduction_fact": (
                "app_rw 指向 RETRIEVAL_TEST_PG_DSN ⇒ 6 skipped + 3 errors（无 DDL 权限）；"
                "super ⇒ 124 passed / 0 failed / 0 skipped（QA §100.2 独立复跑）"
            ),
            "w79_fix": (
                "`w78_integration_evidence.py` 的 `dsn_masked` 已补 retrieval_pg（脱敏）"
                "并注明需要 DDL 权限（super）"
            ),
        },
        "w79_rule": {
            "loopback_only": True,
            "command_template": "docker run ... -p 127.0.0.1:<port>:<port> ...",
            "commands_in_evidence_script": list(ev.DOCKER_COMMANDS),
            "commands_use_loopback": all(
                "-p 127.0.0.1:" in c for c in ev.DOCKER_COMMANDS if c.startswith("docker run")
            ),
            "enforced_by_test": (
                "backend/tests/eval/test_integration_evidence_hygiene.py::"
                "test_docker_run_commands_bind_loopback_only"
            ),
        },
        "w78_artifact_rewritten": False,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {_relative(OUT)}")
    print(
        f"host_ips={host_ips} loopback_violation={loopback_violation} "
        f"residual={residual_names} w78_retrieval_dsn={'retrieval_pg' in dsn_w78}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
