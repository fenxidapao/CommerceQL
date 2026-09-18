#!/bin/sh
# ============================================================================
# api 容器的 PID 1 —— 优雅停机六步的**编排者**（07 §18.3；docs/08 §4.1：`deploy/**` 归 W7）
#
# ## 本脚本存在的唯一理由
# `docker stop` 只把 TERM 发给 PID 1。如果 PID 1 直接是 uvicorn，那么按 uvicorn 0.53 的
# 实测顺序「停监听 → **等**在途连接结束 → 才发 lifespan shutdown」，写在 lifespan 关闭段里的
# `REGISTRY.drain()` 永远晚于"流结束"本身：它在等一件本该由它触发的事，
# 结果是 `stop_grace_period` 到点 → SIGKILL → **静默断连**（正是 §18.3 要避免的形态）。
# 所以要有一个脚本，在 TERM 传导给 uvicorn **之前**先把 drain 置位：
#   1. `POST /healthz/drain` ⇒ `/healthz/ready` 立刻 503（摘流量）
#   2. 轮询 `GET /healthz/drain` 直到在途 SSE 归零（中间件会给每条未终态的流注入
#      `error(INTERNAL)` + `terminal:true`，见 `app/obs/instrumentation.py`）
#   3. 把 TERM 转给 uvicorn（此时它手里已经没有在途连接，等得很快）
#
# ## 时间预算（三个数字必须自洽，改任何一个都要同时改另两个）
#   DRAIN_BUDGET_S(32)  >  应用侧 drain 预算 DRAIN_TIMEOUT_S(30)
#   DRAIN_BUDGET_S(32) + uvicorn 的 --timeout-graceful-shutdown(5) = 37
#     <  Compose 的 stop_grace_period(40)  ⇒ 正常路径下 SIGKILL 不可达
#
# ## 为什么不用 `exec uvicorn`
# `exec` 会让 uvicorn 顶掉 PID 1，于是 TERM 直接进 uvicorn，本脚本的 trap 形同虚设。
# 代价是脚本要自己负责转发信号与退出码 —— 这正是它存在的意义。
# ============================================================================
set -eu

UVICORN_PID=""
DRAIN_BUDGET_S="${DRAIN_BUDGET_S:-32}"
GRACEFUL_SHUTDOWN_TIMEOUT_S="${GRACEFUL_SHUTDOWN_TIMEOUT_S:-5}"

_shutdown() {
    # $1 = 收到的信号名。trap 里不能用 `set -e` 的隐式退出，全部显式兜住。
    sig="$1"
    echo "[entrypoint] 收到 ${sig} ⇒ 开始优雅停机" >&2

    # 第 1~2 步：置位 drain 并等在途 SSE 收尾。
    # `|| true` 是刻意的：闸门失败（token 未设、应用已挂）只该让停机**退回老路**，
    # 不该让脚本在第 3 步之前退出 —— 那样 uvicorn 收不到 TERM，只能等 SIGKILL。
    python /srv/drain_client.py begin-wait "$DRAIN_BUDGET_S" || true

    # 第 3 步：把信号转给真正的服务进程。
    if [ -n "$UVICORN_PID" ] && kill -0 "$UVICORN_PID" 2>/dev/null; then
        kill -TERM "$UVICORN_PID"
    fi
}

trap '_shutdown TERM' TERM
trap '_shutdown INT' INT

# `--timeout-graceful-shutdown` 是**兜底的兜底**：闸门已经把在途流排空了，
# 这里再给一个上限，防止某个没被登记到的长连接（比如非 SSE 的挂死请求）
# 把 shutdown 拖到 SIGKILL。
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
    --no-access-log --timeout-graceful-shutdown "$GRACEFUL_SHUTDOWN_TIMEOUT_S" &
UVICORN_PID=$!
echo "[entrypoint] uvicorn pid=${UVICORN_PID}" >&2

# 等服务进程真正退出。
#
# ⚠️ dash 的实测坑（一次性容器桩复现，见 reports/w7/DELIVERY.md 的 §18.3 时序回执）：
# trap 一旦跑过（尤其里面起过子进程），`wait` 会**反复**返回 128+signo，即使子进程
# 自己正常退出 0。所以"再 wait 一次"这种单次重试**拿不到**真实退出码。
# 这里因此把两件事分开：
#   - **时序**（必须守住）：子进程还活着就一直等。PID 1 一旦先退出，容器立即拆除，
#     剩下没收尾的连接就是 §18.3 要避免的静默断连。判活用 `kill -0`。
#   - **退出码**（承认拿不到）：不伪造。`wait` 反复被打断时按 143 退出，并在日志里
#     写明它是脚本产物。运维判据是 **137 = 被 SIGKILL（drain 超时 = 失败形态）**，
#     而 143 = 闸门走完、服务进程自己退了。
status=0
spins=0
wait "$UVICORN_PID" || status=$?
while [ "$status" -gt 128 ]; do
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        break
    fi
    spins=$((spins + 1))
    # 80×0.5s 只是"wait 每次都立刻返回"这种病态情形的保险丝；正常情况下
    # 循环里的 `wait` 会阻塞到子进程退出，用不到这个上限。
    if [ "$spins" -ge 80 ]; then
        echo "[entrypoint] 服务进程 ${spins} 次重等后仍未退出 ⇒ 放弃等待" >&2
        break
    fi
    sleep 0.5
    wait "$UVICORN_PID" || status=$?
done

if [ "$status" -gt 128 ]; then
    echo "[entrypoint] uvicorn 已退出；status=${status} 是 dash 在 trap 之后对 wait 的伪影，不代表服务被信号杀死（判据：137 才是 SIGKILL）" >&2
else
    echo "[entrypoint] uvicorn 退出，status=${status}" >&2
fi
exit "$status"
