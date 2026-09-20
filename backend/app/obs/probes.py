"""软依赖探针（LLM / embedding）—— 附录 A §A.8.1 的"可降级依赖"这一半。

归属窗口：W7（docs/08 §4.1：`app/obs/**` 指标与采样器部分）

## 为什么只有这两个探针放在这里，硬依赖仍在 `app/repo/health.py`
硬依赖（元数据库 / checkpointer / Redis）探的是**自己的连接池与 Redis 客户端**，
它们的构造事实归 W1B（`app/repo`）。软依赖探的是**两个互相独立的外部 HTTP 服务**
（DeepSeek 在公网、Ollama 在宿主），与仓储层无关，且都必须遵守同一条纪律：
**探测失败只能表达"降级"，绝不能表达"不可用"**（N-21）。

## 探针只做"可达性"，不做"可用性证明"
⚠️ 这是刻意的收窄，也是本文件的诚实边界：
· 一次 TCP+TLS+HTTP 握手成功 **不等于** 模型会返回可解析的 JSON、不等于配额还在；
· 因此 `healthy=True` 的语义是"**上游可达**"，写进 `detail` 里，不写成"LLM 正常"。
真正的"这次调用成功了没"由 `degraded_total` / `llm_json_parse_failure_total` 承载（§15.3）。

## 为什么零配额
`/healthz`（聚合详情）会被 UI 健康点周期性拉（06 §11.4）。若探针走一次真补全，
就是"每 30 秒烧一次额度"，且把观测链路变成了额度依赖。两个探针都只做 **GET 根路径 /
`/api/tags`**：Ollama 完全本地，DeepSeek 只到 HTTP 层（不带 key、不产生 token）。

## U-108：判据与门限分离（v1.3 裁定，07 §18.2）
本轮改的不是"阈值取几秒"，是**三件互相咬合的事**，缺一件就还是假负：
① **复用 `httpx.AsyncClient`** —— 旧实现每次探测新建客户端 ⇒ 探针测到的其实是
   **TCP+TLS 建连耗时**（实测容器→DeepSeek 建连 p95 **4.09s**，而复用连接后只要 **0.11s**）。
   不先修这一条，抬高阈值只是把假负的门槛挪高，抖动一大照样复现。
② **两个探针不共用常量** —— 公网 DeepSeek 与本机 Ollama 的时延形态差三个数量级
   （实测 p95：4,087ms vs 6ms）。一个常量服务两个消费者 = 本项目已第三次出现的同款缺陷
   （前两次："一个 DSN 服务两个消费者"）。
③ **`healthy=false` 只表示"真不可达"**（连接层失败 / 超过松弛上界）；
   "**慢**" ⇒ `healthy=true` + `detail` 说明 + **本模块自己发 WARN**。
   ⚠️ 为什么 WARN 在这里发而不是靠 `health.py`：`_log_probe_details()` 只把
   **unhealthy** 的 detail 写日志（§A.8.4 不许有 `probe_detail` 字段，detail 一律只进日志），
   所以"可达但慢"这条信息若不在这里吵，出了本文件就**没有任何地方拿得到**。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx

from app.core.contracts import HealthProbeResult
from app.core.enums import DEPENDENCY_KIND, Dependency
from app.obs.logging import get_logger

__all__ = [
    "ProbeFn",
    "aclose_probe_clients",
    "make_embedding_probe",
    "make_llm_probe",
    "warm_probe_connections",
]

_log = get_logger(__name__)

#: 探针签名。**就地定义而不是 `from app.repo.health import ProbeFn`** ——
#: U-18 的代价约束是「`obs/` 内除 `audit.py` 外不得引入 `repo` 依赖」
#: （`tests/contract/test_obs_audit_contract.py` 静态扫描 + `.importlinter` r-dep-3 双道闸门），
#: 借一个类型别名也会被判违规。三处同名 `ProbeFn`（此处 / `repo.health` / `api.routers.health`）
#: 是**同一形状的鸭子类型**，`register_probe` 接受的是可调用对象本身，不需要导入关系成立。
ProbeFn = Callable[[], Awaitable[HealthProbeResult]]

# ---------------------------------------------------------------------------
# 门限（U-108 ②：两个探针各一套）。取数依据全部写在常量旁边（U-22：不给出处 = 逼下一个人发明数字）
# 复测脚本与完整读数见 `deploy/loadtest/README.md` §三.0.2。
# ---------------------------------------------------------------------------

#: **硬超时 = 真不可达的判定线**。取数分两层，因为这两层给出的尾巴不一样长：
#: · 裸 TCP+TLS 建连 n=20（容器内）：p50 142ms / p95 4,097ms / max 4,102ms，
#:   且是**双峰**的 —— 17 次落在 85–150ms，3 次落在 4,090–4,102ms（后一簇离散仅 12ms）。
#: · httpx 路径（含 DNS 与多 A 记录回退）实测：一次 **5,236ms 成功**、
#:   两次分别在 **8,119ms / 8,151ms 被当时的 8.0s 界截断**（真值未知）。
#: ⇒ **8.0s 已被自己的读数证伪**（"p95 × 1.96"只覆盖了裸建连那一层，漏了 httpx 的回退路径）。
#:   12.0s = 已见成功值 5.2s 的 ~2.3 倍，仍远小于 UI 轮询的 30s。
#: ⚠️ **残余，别读成"到此为止了"**：间歇性长尾不会被任何界消掉，抬高界只是把假负的概率压低。
#:   所以 `healthy=False` 的 detail **必须**写清失败发生在哪一层（连接层 / 松弛上界 / 本地池）——
#:   那才是这处修改真正交付的东西，而不是那个数字。
#: ⚠️ 它**不占**附录 D 的 `healthcheck.timeout: 5s` —— 那个预算打在 `/healthz/ready`（只含硬依赖），
#:    本探针只进 `/healthz` 聚合详情（消费者 = UI 健康点 / 运维）。唯一时延约束是
#:    "远小于 UI 轮询间隔 30s"（07 §18.2 ①）。旧注释里"2.0s 是为了塞进 5s 预算"是错的归因。
LLM_PROBE_TIMEOUT_S: Final[float] = 12.0

#: "慢"的判定点（**不改变 healthy**，只加 detail + WARN）。
#: 复用连接下实测 ~0.11s ⇒ 1.0s 是它的 ~7 倍：越过即"连接池冷了 / 上游开始排队"，
#: 是下一次真超时的前兆，值得吵一声，但不许因此报"不可达"（§18.2 ③）。
LLM_PROBE_SLOW_S: Final[float] = 1.0

#: 取数（同一批，容器内 → `host.docker.internal:11434`）：`/api/tags` 空闲 p95 **6ms**；
#: **6 路 embedding 并发期间** n=92 仍 max **7ms** ⇒ "本机服务正忙会拖慢 tags"这个常见假设
#: 被实测否掉了，所以门限不必为它留量级。1.0s = 实测 max 的 ~140 倍，覆盖容器↔宿主往返抖动。
#: 与 LLM 的 8.0s 分开是必须的：共用一个数意味着要么把本机说成"永远可达且快"，
#: 要么把公网长尾误判成"挂了"。
EMBEDDING_PROBE_TIMEOUT_S: Final[float] = 1.0

#: 本机服务的"慢"线：实测 max 7ms 的 ~28 倍。到 0.2s 已经不是抖动，是 Ollama 在排队。
EMBEDDING_PROBE_SLOW_S: Final[float] = 0.2

#: 连接复用要**跨得过 UI 的 30s 轮询**才成立；httpx 默认 `keepalive_expiry=5s`
#: ⇒ 用默认值的话"复用"是空的，第二次探测照样重新握手。60s 实测跨 30s / 65s 闲置仍复用成功。
_KEEPALIVE_EXPIRY_S: Final[float] = 60.0

#: 每个探针工厂一份缓存（`{"timeout_s","transport","loop","client"}`）。
#: 用可变 list 持有"工厂 ↔ 它的客户端缓存"这条对应关系，是为了停机时还能拿到那些
#: 跨探测复用的客户端去关（`aclose_probe_clients`）—— 生产就 2 个（llm / embedding）。
_CACHES: Final[list[dict[str, Any]]] = []


def _result(dependency: Dependency, *, healthy: bool, detail: str) -> HealthProbeResult:
    """构造探针结果。`kind` 只从 `DEPENDENCY_KIND` 单一定义取（软/硬不是这里能改的）。"""
    return HealthProbeResult(
        dependency=dependency, kind=DEPENDENCY_KIND[dependency], healthy=healthy, detail=detail
    )


def _new_cache(
    timeout_s: float, transport: httpx.AsyncBaseTransport | None, url: str
) -> dict[str, Any]:
    cache: dict[str, Any] = {"timeout_s": timeout_s, "transport": transport, "url": url}
    _CACHES.append(cache)
    return cache


async def _client_for(cache: dict[str, Any]) -> httpx.AsyncClient:
    """取（必要时新建）**跨探测复用**的客户端。

    ⚠️ 判据是"运行中的事件循环是不是同一个"：`httpx.AsyncClient` 的连接池绑死在
    首次使用它的循环上，跨循环复用会拿到一个"看着活着、一 send 就炸"的池 ——
    那正是 U-108 要修的假负的反面形态（把工具自己变成故障源）。测试里每个用例一个新循环，
    所以这条路径在测试中会被走到；生产 lifespan 只有一个循环，于是复用真的成立。
    """
    loop = asyncio.get_running_loop()
    client = cache.get("client")
    if client is not None and cache.get("loop") is loop:
        return client  # type: ignore[no-any-return]

    stale = client
    new = httpx.AsyncClient(
        # 单个数值 = 同时给 connect/read/write/pool 四个阶段（§18.2 的"松弛上界"就是一个总预算，
        # 刻意不拆成"连接 3s + 读 5s"：拆了就有第二个没人对齐的门限，而 ③ 只要一条判定线）
        timeout=cache["timeout_s"],
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=2, max_keepalive_connections=2, keepalive_expiry=_KEEPALIVE_EXPIRY_S
        ),
        transport=cache["transport"],
    )
    # 赋值与取值之间**没有 await** ⇒ 同一循环内不可能有两个协程各建一份（无需锁）。
    cache["loop"] = loop
    cache["client"] = new
    if stale is not None:  # 换循环了：旧池属于已结束的循环，尽力关掉，失败也不该影响探测
        with contextlib.suppress(Exception):
            await stale.aclose()
    return new


async def aclose_probe_clients() -> int:
    """停机时归还上游连接（07 §18.3 第 4 步"归还连接"覆盖**出站**这一半）。

    返回关掉的客户端数。由 `app/main.py` 的 lifespan 关闭段调用 —— 探针客户端是模块级
    持有的，进程退出会让 socket 随之消失，但 uvicorn 在 shutdown 后仍要转一会儿事件循环，
    留着未关的客户端就是那一句 `Event loop is closed` 的来源。
    """
    closed = 0
    for cache in list(_CACHES):
        client = cache.pop("client", None)
        cache.pop("loop", None)
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
                closed += 1
    return closed


async def warm_probe_connections() -> dict[str, int]:
    """装配期先把 TCP+TLS 握手付掉（尽力而为，**永不抛**，也不影响启动成败）。

    为什么这一步值得单独存在，而不是"让第一次探测自己去付"：
    实测冷连接是**双峰**的 —— 20 次里 17 次落在 85–150ms，3 次落在 4,090–4,102ms
    （后一簇离散度只有 12ms ⇒ 更像一条固定的回退路径，而不是网络抖动），
    而**只有第一次探测会付这笔钱**：池暖了之后实测 89–110ms。
    启动期正是"付一次握手不亏"的时刻 —— 那时候还没有人在轮询 `/healthz`。
    不这么做的话，假负就会固定落在"进程刚起来的第一次健康检查"上，
    而那恰恰是运维最在看的一刻（= U-108 那个教训原样复现）。
    """
    spent: dict[str, int] = {}
    for cache in list(_CACHES):
        if cache["transport"] is not None:
            continue  # 测试接缝建出来的探针：暖身会真发一次请求，不该去碰别的用例留下的假域名
        # （`aclose_probe_clients` 不做这个过滤 —— 关闭只是无害的清理，没有外呼）
        started = time.perf_counter()
        try:
            client = await _client_for(cache)
            await client.get(cache["url"])
        except Exception:  # 暖身失败不是故障：下一次探测会自己再试
            _log.warning(
                "probe_warm_failed",
                url=cache["url"],
                why="装配期暖连接失败不影响启动；探测路径自己会重试（U-108）",
            )
        spent[str(cache["url"])] = round((time.perf_counter() - started) * 1000)
    return spent


def _classify_failure(
    dependency: Dependency, exc: BaseException, *, elapsed_s: float, bound_s: float
) -> HealthProbeResult:
    """把"没拿到 HTTP 响应"分成三类，写清是哪一类 —— **它们的运维含义不同**。

    ⚠️ 判定**顺序**是实的：httpx 里 `ConnectTimeout` 只是 `TimeoutException` 的子类，
    与 `ConnectError` 是兄弟（不是它的子类）。所以必须**先**显式判 `ConnectTimeout` ——
    否则"握手都没完成"会掉进超时分支、被写成"连接已建立但没响应"，
    而这两句的排查方向相反（一个查网络/DNS/出口，一个查上游进程）。
    """
    if isinstance(exc, httpx.ConnectTimeout | httpx.ConnectError):
        cause = f"连接层失败（DNS / TCP / TLS 未建立）：{type(exc).__name__}"
    elif isinstance(exc, httpx.PoolTimeout):
        # 同为 TimeoutException 的子类，但请求**根本没发出去** —— 说成"连接已建立"是假话
        cause = f"本地连接池在 {bound_s:.1f}s 内没给出连接（未发出请求，{type(exc).__name__}）"
    elif isinstance(exc, httpx.TimeoutException):
        cause = (
            f"连接已建立但在松弛上界 {bound_s:.1f}s 内没走完一次请求"
            f"（实测 {elapsed_s:.1f}s，{type(exc).__name__}）"
        )
    else:
        cause = f"连接已建立、HTTP 层异常：{type(exc).__name__}"
    degrade = {
        Dependency.LLM: "走降级：模板查询 / 提示重试",
        Dependency.EMBEDDING: "走降级：稀疏 + Join 图扩展",
    }[dependency]
    return _result(dependency, healthy=False, detail=f"上游不可达：{cause}（{degrade}）")


def _note_slow(dependency: Dependency, base_url: str, elapsed_s: float, slow_s: float) -> None:
    """"可达但慢" ⇒ `healthy` 不动，只吵日志（§18.2 ③：慢与没接**不许**是同一个布尔）。"""
    _log.warning(
        "probe_slow",
        dependency=dependency.value,
        base_url=base_url,
        elapsed_ms=round(elapsed_s * 1000),
        slow_threshold_s=slow_s,
        reason="可达性判定不受影响（U-108：慢 ≠ 不可达），但这是下一次真超时的前兆",
    )


def make_llm_probe(
    base_url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> ProbeFn:
    """对话模型可达性探针（GET 根路径）。

    ⚠️ 只判"拿到了任意 HTTP 响应"：`401/404` 同样算可达 —— 那说明 DNS、TCP、TLS、
    HTTP 服务本身都是活的，剩下的鉴权/配额问题会在真实调用里以 `degraded(llm_unavailable)`
    暴露（那才是该告警的信号）。**刻意不打补全请求**：零配额、零延迟污染。

    `transport` 只是测试接缝（`httpx.MockTransport`），生产装配不传 —— 不为它开配置键。
    """
    cache = _new_cache(LLM_PROBE_TIMEOUT_S, transport, base_url)

    async def probe() -> HealthProbeResult:
        client = await _client_for(cache)
        started = time.perf_counter()
        try:
            # 宽捕获是刻意的：探针**永不**因为异常而变成"没有这一项"（缺席会让 `all(...)` 更容易通过）
            response = await client.get(base_url)
        except Exception as exc:
            return _classify_failure(
                Dependency.LLM,
                exc,
                elapsed_s=time.perf_counter() - started,
                bound_s=cache["timeout_s"],
            )
        elapsed = time.perf_counter() - started
        slow = elapsed > LLM_PROBE_SLOW_S
        if slow:
            _note_slow(Dependency.LLM, base_url, elapsed, LLM_PROBE_SLOW_S)
        return _result(
            Dependency.LLM,
            healthy=True,
            detail=(
                f"上游可达（HTTP {response.status_code}；未校验鉴权与配额；"
                f"耗时 {elapsed * 1000:.0f}ms）"
                + (f"；慢于阈值 {LLM_PROBE_SLOW_S}s，判定不变，见 probe_slow 日志" if slow else "")
            ),
        )

    return probe


def make_embedding_probe(
    base_url: str,
    model: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeFn:
    """embedding 可达性探针（Ollama `GET /api/tags`，纯本地、零额度）。

    比 LLM 多做一步"**模型在不在**"判定：Ollama 活着但模型没拉取，是本项目实测过的
    真实故障形态，而它的表现是"检索退化成 sparse_only 却没人知道"——
    所以 `detail` 里要能区分"连不上"与"连上了但没有这个模型"。

    ⚠️ 这里**不改** `status>=400` 与"模型不在列"两条判据的 `healthy=False`：
    U-108 裁的是"慢 vs 没接"这一根轴，"接上了但服务在报错/没装模型"不是"慢"，
    把它一并改成 healthy=true 会是另一处越权。
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    cache = _new_cache(EMBEDDING_PROBE_TIMEOUT_S, transport, url)

    async def probe() -> HealthProbeResult:
        client = await _client_for(cache)
        started = time.perf_counter()
        try:
            response = await client.get(url)
        except Exception as exc:  # 同 `make_llm_probe`：宽捕获是刻意的，理由写在那一侧
            return _classify_failure(
                Dependency.EMBEDDING,
                exc,
                elapsed_s=time.perf_counter() - started,
                bound_s=cache["timeout_s"],
            )
        elapsed = time.perf_counter() - started
        if elapsed > EMBEDDING_PROBE_SLOW_S:
            _note_slow(Dependency.EMBEDDING, url, elapsed, EMBEDDING_PROBE_SLOW_S)
        if response.status_code >= 400:
            return _result(
                Dependency.EMBEDDING,
                healthy=False,
                detail=f"Ollama 返回 HTTP {response.status_code}（走降级：稀疏 + Join 图扩展）",
            )
        listed: list[str] = []
        with contextlib.suppress(Exception):
            payload = response.json()
            models = payload.get("models") if isinstance(payload, dict) else None
            listed = [str(m.get("name", "")) for m in models if isinstance(m, dict)] if models else []
        suffix = f"；耗时 {elapsed * 1000:.0f}ms"
        if listed and not any(name == model or name.startswith(f"{model}:") for name in listed):
            return _result(
                Dependency.EMBEDDING,
                healthy=False,
                detail=(
                    f"Ollama 可达但未加载模型 {model}"
                    f"（已加载：{','.join(sorted(set(listed))[:5])}）{suffix}"
                ),
            )
        return _result(
            Dependency.EMBEDDING,
            healthy=True,
            detail=f"Ollama 可达，模型 {model} 在列{suffix}",
        )

    return probe
