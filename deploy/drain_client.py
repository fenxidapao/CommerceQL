"""停机闸门的**进程外**触发客户端（07 §18.3 第 1~2 步）。

归属窗口：W7（`deploy/**`）。由 `deploy/entrypoint.sh` 调用，**不是**给人手敲的
（人手敲也可以，就这两个 GET/POST）。

## 为什么需要"进程外"这一趟
`docker stop` 把 TERM 只发给 PID 1。若 PID 1 就是 uvicorn，那么按 uvicorn 0.53 的实测顺序
（**停监听 → 等在途连接结束 → 才发 lifespan shutdown**），写在 lifespan 关闭段里的
`REGISTRY.drain()` 永远**晚于**"流结束"这个事件本身 —— 它在等一件本该由它触发的事。
所以必须有一个人在 TERM **传导给 uvicorn 之前**先把 drain 置位。见 `entrypoint.sh`。

## 为什么只用标准库
镜像是 `python:3.13-slim`，**没有 curl**（docs/05 附录 D 里 `docker compose exec api curl …`
那句因此在实测中不可用）。这里用 `urllib`：不必为了停机往镜像里多装一个包，
也不把 `httpx` 拉进停机路径（停机时事件循环正被 uvicorn 收尾，不该再起一个异步客户端）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

__all__ = ["begin", "main", "wait_for_zero"]

#: 单次 HTTP 的上限（秒）。停机窗口里一次请求卡住就等于整台机器卡住，必须夹紧。
_REQUEST_TIMEOUT_S = 3.0


def _base_url() -> str:
    port = os.environ.get("PORT", "8000")
    # 127.0.0.1 而不是 localhost：slim 镜像里主机名解析不总可靠，
    # 而"能不能优雅停机"不该取决于容器 DNS。
    return f"http://127.0.0.1:{port}/api/v1/healthz/drain"


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _request(method: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(_base_url(), method=method)
    if token:
        request.add_header("X-Drain-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        _say(f"[drain] {method} → HTTP {exc.code} {body}")
        return {}
    except Exception as exc:  # 停机路径上的任何失败都不该让调用方脚本自己死掉
        _say(f"[drain] {method} 失败：{type(exc).__name__}: {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def begin() -> dict[str, object]:
    """置位 drain（`POST`）→ `{"draining": true, "inflight": n}`；失败或未启用返回 `{}`。

    ⚠️ `DRAIN_TOKEN` 未设置 ⇒ 端点返回 403（fail-closed：不开一个无鉴权的远程停机口）。
    此时本脚本**继续走老路**（把 TERM 转给 uvicorn，由 lifespan 兜第二道），
    并把"闸门未启用"如实打出来 —— 而不是让容器卡在一个 403 上。
    """
    token = os.environ.get("DRAIN_TOKEN", "")
    if not token:
        _say("[drain] DRAIN_TOKEN 未设置 ⇒ 闸门禁用，直接转发 SIGTERM（lifespan 兜第二道）")
        return {}
    return _request("POST", token)


def wait_for_zero(budget_s: float, interval_s: float = 1.0) -> bool:
    """轮询 `GET` 直到在途流归零或预算耗尽。返回**是否排空**。"""
    token = os.environ.get("DRAIN_TOKEN", "")
    deadline = time.monotonic() + budget_s
    drained = False
    while time.monotonic() < deadline:
        payload = _request("GET", token)
        if payload.get("draining") is True and payload.get("inflight") == 0:
            drained = True
            break
        time.sleep(interval_s)
    _say(f"[drain] 排空={'yes' if drained else 'no'} 预算={budget_s}s")
    return drained


def main(argv: list[str]) -> int:
    """`begin-wait <预算秒>`：置位后等到在途流归零。

    退出码**恒为 0**：本脚本失败绝不能让 `entrypoint.sh`（`set -eu`）在转发 TERM 之前退出 ——
    那会把一次"可降级的停机"变成"SIGKILL 断连"。
    """
    if len(argv) >= 2 and argv[1] == "begin-wait":
        budget = float(argv[2]) if len(argv) > 2 else 32.0
        payload = begin()
        if payload:
            _say(f"[drain] 已置位，在途流={payload.get('inflight')}")
            wait_for_zero(budget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
