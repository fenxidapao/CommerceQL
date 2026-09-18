"""§18.3 停机链的**跨文件不变量**（`deploy/**` 归 W7；docs/08 §4.1）。

归属窗口：W7。

## 为什么这个测试只能"读文件"
一条停机链的四个关键量，分散在四种语言写的四个地方，**任何一处都看不见其余三处**：

- `deploy/entrypoint.sh` —— shell 默认值 `DRAIN_BUDGET_S:-32`、`GRACEFUL_SHUTDOWN_TIMEOUT_S:-5`
- `app/obs/instrumentation.py` —— Python 常量 `DRAIN_TIMEOUT_S = 30.0`
- `deploy/docker-compose.yml` —— yaml `stop_grace_period: 40s`
- `deploy/Dockerfile` —— `CMD ["sh", "/srv/entrypoint.sh"]`（装配面：链到底活不活）

而它们的失效方式全是**静默**的：把 40s 改成 30s，镜像照建、测试照绿，只在每次重启时
让 SIGKILL 落在 drain 中间（= §18.3 要避免的那件事）。把 `CMD` 换回 `exec uvicorn` 同样
不会让任何东西变红 —— trap 只是不再存在于信号路径上。本文件是**唯一**能把这四处放到
同一张桌子上的地方。

## 本文件**不**证明的东西
运行时时序。"置位之后在途流才收尾""预算耗尽仍会转发 TERM""无 token 不卡死"这三条
的证据是一次性容器 + 假 drain 端点的实测（2026-09-18，见 `deploy/runbook/README.md` §四-2），
pytest 起不了 Docker，也不该为跑测试去碰 W6 在用的共享栈。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = _REPO_ROOT / "deploy"


# ---------------------------------------------------------------------------
# 解析（每个 helper 都在"读不到"时**炸掉**而不是返回默认值：静默的 0 会让预算断言
# 变成"0 < 0 所以通过"那种假绿）
# ---------------------------------------------------------------------------


def _read(name: str) -> str:
    """读 `deploy/` 下的一个文件，**路径每次调用时现拼**。

    ⚠️ 不要把 `Path` 提成模块常量：那等于在同一进程里留一个后门，任何一次
    `mod._ENTRYPOINT = 某个副本` 都会把"验证仓库的部署面"悄悄变成"验证一份变异副本"，
    而断言看起来一模一样。
    """
    path = _DEPLOY / name
    assert path.is_file(), f"{path} 不存在 ⇒ 本测试的对象就是仓库里的部署面，缺文件即链条不存在"
    return path.read_text(encoding="utf-8")


def _entrypoint_text() -> str:
    return _read("entrypoint.sh")


def _shell_default(name: str) -> float:
    match = re.search(rf"\$\{{{name}:-([0-9.]+)\}}", _entrypoint_text())
    assert match, (
        f"`entrypoint.sh` 里读不到 `{name}` 的 shell 默认值 ⇒ 该预算不再由 shell 单独持有，"
        f"本测试的解析前提失效。改写法可以，但要同步改这里（否则下一次漂移没人拦）"
    )
    return float(match.group(1))


def _api_service_block() -> str:
    """取 `services.api` 的整块文本（两空格缩进的下一个键为界，注释行不算界）。"""
    text = _read("docker-compose.yml")
    match = re.search(r"^  api:\n(.*?)(?=^  (?!#)\S|\Z)", text, re.M | re.S)
    assert match, "docker-compose.yml 里找不到两空格缩进的 `api:` 服务块 ⇒ 解析前提失效"
    return match.group(1)


def _stop_grace_period_s() -> float:
    match = re.search(r"^\s+stop_grace_period:\s*([0-9]+)s\b", _api_service_block(), re.M)
    assert match, (
        "`api` 服务没有 `stop_grace_period` ⇒ Docker 用默认 **10s**，而应用侧 drain 要 30s "
        "⇒ 每次重启都在 SIGKILL 处断流（07 §18.3 的失败形态）"
    )
    return float(match.group(1))


def _shutdown_body() -> str:
    """trap 函数 `_shutdown() { ... }` 的函数体。"""
    match = re.search(r"_shutdown\(\) \{\n(.*?)\n\}", _entrypoint_text(), re.S)
    assert match, "`entrypoint.sh` 里读不到 `_shutdown()` 函数体 ⇒ trap 编排改了形制，解析前提失效"
    return match.group(1)


# ---------------------------------------------------------------------------
# 一、三个时间预算必须自洽
# ---------------------------------------------------------------------------


def test_outer_drain_budget_is_longer_than_the_apps_own_drain_timeout() -> None:
    """`DRAIN_BUDGET_S`(外层轮询) > `DRAIN_TIMEOUT_S`(应用内等待)。

    反过来就是"闸门还没排空就 TERM"，等于没装闸门 —— 而两个数字分别在 shell 和 Python 里，
    没有任何一处能同时看见它们。
    """
    from app.obs import instrumentation

    budget = _shell_default("DRAIN_BUDGET_S")
    assert budget > instrumentation.DRAIN_TIMEOUT_S, (
        f"外层 drain 预算 {budget}s ≤ 应用侧 DRAIN_TIMEOUT_S={instrumentation.DRAIN_TIMEOUT_S}s"
        "⇒ entrypoint 会在应用还在等流的时候就把 TERM 转出去"
    )


def test_full_shutdown_chain_fits_inside_stop_grace_period() -> None:
    """drain 预算 + uvicorn 收尾上限 < Compose 的 `stop_grace_period`。

    等号都不行：`stop_grace_period` 到点就是 SIGKILL，静默断连。留出的差就是
    "PID 1 自己退出 + 容器拆除"的时间。
    """
    drain = _shell_default("DRAIN_BUDGET_S")
    graceful = _shell_default("GRACEFUL_SHUTDOWN_TIMEOUT_S")
    grace = _stop_grace_period_s()
    assert drain + graceful < grace, (
        f"{drain} + {graceful} = {drain + graceful}s ≥ stop_grace_period={grace}s"
        "⇒ 正常路径下 SIGKILL 可达，§18.3 的整段推导失效"
    )


def test_uvicorn_still_gets_a_graceful_shutdown_ceiling() -> None:
    """`--timeout-graceful-shutdown` 必须**引用变量**而不是写死数字。

    写死会让上面的预算测试对着一个已经不存在的数绿着。
    """
    text = _entrypoint_text()
    assert '--timeout-graceful-shutdown "$GRACEFUL_SHUTDOWN_TIMEOUT_S"' in text, (
        "uvicorn 的收尾上限丢了或变成字面量 ⇒ 有一个没被登记到的长连接就能把 shutdown 拖到 SIGKILL"
    )


# ---------------------------------------------------------------------------
# 二、链的顺序与装配（顺序错了 = 语义错了，但功能一样"正常"）
# ---------------------------------------------------------------------------


def test_drain_gate_opens_before_sigterm_is_forwarded() -> None:
    """trap 体内：**先**调 drain 闸门，**后**转发 TERM。

    ⚠️ 只看全文的本末先后是不够的（闸门要是被挪到 trap 外面就根本不会执行），
    所以这里在 `_shutdown()` 函数体内部定位两个锚点。
    """
    body = _shutdown_body()
    gate = body.find("drain_client.py begin-wait")
    forward = body.find('kill -TERM "$UVICORN_PID"')
    assert gate != -1, "trap 里不再打开 drain 闸门 ⇒ §18.3 第 1~2 步脱钩，TERM 直达 uvicorn"
    assert forward != -1, "trap 里不再把 TERM 转给服务进程 ⇒ uvicorn 收不到信号，只能等 SIGKILL"
    assert gate < forward, "闸门必须在转发 TERM **之前**打开：先 TERM 就等于让 uvicorn 无限等在途连接"


def test_image_launches_the_entrypoint_not_uvicorn_directly() -> None:
    """装配面：PID 1 必须是会 trap 信号的脚本。

    这一条最容易被"顺手优化 Dockerfile"破坏，且破坏后**没有任何功能会变坏** ——
    服务照起、请求照跑，只有 `docker stop` 的时候才退化成静默断连。
    """
    dockerfile = _read("Dockerfile")
    launches = re.findall(r"^(?:CMD|ENTRYPOINT)\s+(.*)$", dockerfile, re.M)
    assert launches, "Dockerfile 没有 CMD/ENTRYPOINT ⇒ 镜像起不来，停机链无从谈起"
    joined = "\n".join(launches)
    assert "entrypoint.sh" in joined, (
        f"启动指令不含 `entrypoint.sh`（实际：{joined!r}）⇒ PID 1 不是编排者，trap 不在信号路径上"
    )
    assert "uvicorn" not in joined, (
        f"启动指令直接是 uvicorn（{joined!r}）⇒ drain/摘流量整段被绕过，回到 §18.3 的静默断连形态"
    )
    for artifact in ("entrypoint.sh", "drain_client.py"):
        assert re.search(rf"^COPY\s.*{re.escape(artifact)}", dockerfile, re.M), (
            f"`{artifact}` 没被 COPY 进镜像 ⇒ 启动即失败或闸门永不调用"
        )


# ---------------------------------------------------------------------------
# 三、收尾段：等的是"服务进程真没了"，不是"wait 返回了"
# ---------------------------------------------------------------------------


def test_exit_is_gated_on_service_liveness_not_on_a_single_wait() -> None:
    """收尾段必须有"判活 + 重等"，不能单次 `wait` 后直接 `exit`。

    实测坑（一次性容器复现）：dash 在 trap 跑过之后会**反复**把 `wait` 的结果报成
    128+signo，即使服务进程自己 `exit 0`。所以"wait 返回了"不等于"服务退出了"，
    据此退出就是**在 uvicorn 收尾之前把容器拆掉** —— 正是本窗口最初版本的缺陷形态。
    """
    tail = _entrypoint_text().split("\nstatus=0\n", 1)
    assert len(tail) == 2, "收尾段（`status=0` 起）形制变了 ⇒ 本测试的解析前提失效"
    block = tail[1]
    assert 'kill -0 "$UVICORN_PID"' in block, "收尾段没判服务进程是否还活着就退出"
    assert block.count('wait "$UVICORN_PID"') >= 2, "只 wait 一次的收尾段在信号之后拿不到服务的真实退出时机"
