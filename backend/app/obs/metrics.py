"""指标本体 —— 07 §15.3 清单 + **标签基数上限**（W7 落地）。

归属窗口：W0 立骨架 → **W7 实现指标/采样器**（docs/08 §4.1）。`audit.py` 归 W1B、
`logging.py` 归 W0，本文件的"指标部分"归 W7。

## 为什么是手写 exposition 而不是 `prometheus_client`

`prometheus_client` 不在依赖白名单里（ADR-20 / 附录 D §D.2.1），而加依赖要同时改
`backend/pyproject.toml` 与 `tests/contract/test_dependency_whitelist.py` —— **两者都归 W0**，
W7 只能提需求。手写 Prometheus 文本格式只有几行语法，换来两个实际收益：

1. **基数上限在写入处兑现**：`_Metric._admits()` 对"标签名 → 上界 → 已见取值"做硬校验，
   越界即丢弃并计入 `metric_label_overflow_total`。库做不到这件事（它只认标签名，不认上界）。
2. 零新增下载、零白名单双录账。

代价（如实登记）：没有 `process_*` / `python_*` 运行时指标；直方图同为**累积桶**，
PromQL `histogram_quantile` 口径与库一致。

## 准入规则（沿用 W0，未放松）

**只落 07 §15.3 明文在列的指标**（类型 + 标签 + 基数都给了）。指标名是本文件起的
（07 只给语义名），按 Prometheus 惯例加 `_total` / `_seconds` 后缀；
`binding_tau_calibrated` 由 §18.4.1 明文给定。**改名/加名的唯一迁移点就是本文件。**

## "Gauge 语义"的三行怎么落成 Counter（口径声明，不是私自放宽）

§15.3 给 **澄清率 / 检索降级率 / 首次执行成功率与平均纠错轮次** 的类型写的是 Gauge。
"率"是**窗口占比**：单实例的瞬时 gauge 既答不出"最近 5 分钟澄清率"，也无法跨实例聚合
（两台机器 gauge 的算术平均 ≠ 全体平均，这是 PromQL 的经典错误）。
⇒ 本文件按 **Counter + PromQL `rate()` 求占比** 落，告警（§15.4）与看板（§15.5）同口径。
取值仍只来自 `core/enums.py`。

## 三条指标纪律（§15.3 强制；本文件是它的机器执行点）

| # | 纪律 | 兑现方式 |
|---|---|---|
| ① | 禁止 `user_id`/`task_id`/`session_id` 作标签 | `UNBOUNDED_FORBIDDEN_LABELS` → 写入时抛 `ValueError`（编程错误要炸在测试里，不能静默少一条线） |
| ② | 每个标签有显式基数上限 | `BOUNDED_ALLOWED_LABELS` → 越界丢弃 + `metric_label_overflow_total{metric}` 计数 |
| ③ | 标签枚举值来自 `core/enums.py` | 每指标 `domains` 由枚举生成；域外取值**丢弃**而不是照收 |

纪律 ③ 需要 `domains` 而不能只靠 ②：`reason` 这个标签名在 §15.3 出现两次
（拒答 4 值 / 降级 8 值），全局上界只能取 8 —— 没有逐指标取值域，
"把 `llm_unavailable` 写进拒答指标"这种错就会静默通过。

## 数据源（谁在什么时候调用 `observe_*`）

| 采集面 | 调用点 |
|---|---|
| HTTP 请求数 / 时延 / 在途 | `app/obs/instrumentation.py` 的 ASGI 中间件（W7） |
| 语义结果面（**仅这 8 项**：终态 / 澄清 / 拒答 / 降级 / 闸门 / 执行失败 / 阶段耗时 / 契约违规） | 同一中间件的 **SSE 帧观测器** —— 帧是 §14.3 的公开记录，且 `node` 名按 06 D2 红线不进帧。⚠️ **检索模式、token 计量、纠错轮次不在这个观测器的覆盖面里**：帧里没有这三类事实，别以为"帧观测器接了 = 全部语义指标都接了" |
| `ui_contract_violation` | 同一观测器在**出口字节层**独立复核 §14.3 序列约束（不看 `EventRecorder` 的自评计数） |
| `binding_state` / `binding_layer` | `app/api/deps.py:MetricsBindingObserver`（W4 已接，本文件只提供计量端） |
| τ 校准 | `app/main.py` lifespan 启动段（W1B）+ `app/binding/__init__.py` |
| 日成本 / 上游并发 / 事件循环延迟 | `app/obs/samplers.py` 周期采样器（W7）。⚠️ 前两个是**有条件接线**：`cost_ledger` 为 None 则成本采样器不注册；上游并发等 W3A 的 `inflight(model)` 公开读口（缺它就不接，见下） |
| `startup_assertion_state`（★ U-105） | `app/main.py` lifespan **第 3.5 段**（W7 追加）。取值域由那里注入 —— 本文件不能 `import app.repo`（R-DEP-3）⇒ 见 `bind_startup_assertion_domains` 的 docstring |

## 未接线项（诚实清单，不得被读成"已落地"）

**先记住导出规律**（`render_prometheus_text()`，与本文件纪律无关，是**标签声明**决定的）：

* **A 类 · 恒 0 已导出**：标签**声明了取值域**（或干脆无标签）⇒ 从未观测时仍输出 `# TYPE` + 一条值为 0 的序列。
  危险读法："看到 0" ≠ "这类事件没发生"，也可能是**采集点不存在**。
* **B 类 · 整族不输出**：有标签**未声明取值域**且从未观测 ⇒ 该前缀在 `/metrics` 里**根本不存在**。
  危险读法："没看到线" ≠ "值为 0"，也可能是"有流量但标签被丢弃"。
* ⚠️ **第三种：类别会随运行期改变** —— `startup_assertion_state` 的域是**绑定进来**的，
  所以它在 `bind_startup_assertion_domains` 之前是 B 类（整族不输出）、之后是 A 类（12 条 0 序列齐备）。
  在这条上"整族不输出"多了一层含义：**装配没跑到第 3.5 段**（而那种情况下任何 `observe` 都会当场抛，
  不会静默）⇒ 读这族时先确认进程是**完整启动**过的。

| §15.3 行 | 类别 | 状态 | 缺什么 |
|---|---|---|---|
| 图节点耗时 Histogram `node`(≤20) | —— | **未采**，且本文件**不登记**同名指标（登记了恒 0 = 假仪表） | 帧里没有节点名；`app/graph/build.py` 的节点包装器需要一个观测钩子（W4 域），需求见 `reports/w7/RELAY.md`。本期用 `stage_duration_seconds{stage}` 承接诊断粒度 |
| token 计量 `llm_tokens_total{token_key}` | A | 本体在、**无调用点** → 导出 4 条恒 0 序列 | token 用量在 `app/llm`（W3A 域）的响应里，需一行 `observe_llm_tokens(...)`；§15.4 第 7 条（token/请求 周环比）与缓存命中率屏因此**无数据源** |
| 检索模式 `retrieval_mode_total{retrieval_mode}` | A | 本体在、**无调用点** → 导出恒 0 序列 | 检索器返回的 `mode` 在 `app/retrieval`（W2B 域），需一行 `observe_retrieval_mode(...)`；§18.7 的"检索降级率"判据因此只能读探针与 `meta.retrieval_mode` |
| 首次成功率 / 平均纠错轮次 `gen_sql_rounds_total` | A | 本体在、**无调用点** → 导出恒 0 序列 | 需要按 `sql_ready` 帧计数（观测器看得到帧但**刻意没记**：轮次语义归 `app/graph`，避免把"帧数"冒充"纠错轮次"），需求见 RELAY |
| 反馈"有误"率 `feedback_reason_total{reason_code}` | A | 本体在、**无调用点** → 导出 10 条恒 0 序列 | 反馈落 `feedback` 表（W1B 域），需 feedback 表采样器；§15.3 未给它目标值 |
| JSON 解析失败率 `llm_json_parse_failure_total` | B | 本体在、**无调用点** → **整族不输出** | `MetricsSink` 只在成功时回调；失败分支在 `app/llm`（W3A 域）内，需一行 `observe_json_parse_failure(...)` |
| 上游并发 `llm_upstream_concurrency{model}` | B | 采样器已写好、**不注册** | `ChatClient` 没有公开的"已占用几格"读口；不去翻私有字段（改名即静默失效），接缝需求见 `reports/w7/RELAY.md` |
| 标签溢出 `metric_label_overflow_total{metric}` | B | 本体在、**正常系统里恒不输出** | 只有基数被突破时才有值 —— 这条**缺席才是好消息**，不要为它补 0 |
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Final

from app.core.enums import (
    ActionTaken,
    AstRule,
    BindingLayer,
    BindingState,
    ClarifyReason,
    DegradedReason,
    FeedbackReasonCode,
    GateNo,
    Outcome,
    RefuseReason,
    RetrievalMode,
    Stage,
    TokenKey,
)

# ============================================================================
# 一、标签基数红线（W0 定义 → W7 补全 §15.3 需要的键；上界一律写死）
# ============================================================================

#: **绝对禁止**作为指标标签的键（无界基数）。
#: 这不是性能建议，是可用性红线：一个 `user_id` 标签能在一个下午内把指标存储写满，
#: 而且症状表现为"监控先挂了"，与业务无关却最先被发现。
UNBOUNDED_FORBIDDEN_LABELS: Final[frozenset[str]] = frozenset(
    {
        "trace_id",
        "task_id",
        "session_id",
        "user_id",
        "raw_question",
        "sql_text",
        "clarify_id",
        "idempotency_key",
    }
)

#: **允许**作为标签的键（有界基数）。上界来自 07 §15.3 的标签列。
#: ⚠️ 上界**只能按标签名**给，而 §15.3 里 `reason` 一名两义（拒答 4 / 降级 8）→
#:    这里取上界 8，逐指标的窄域由 `_MetricSpec.domains` 兑现。
BOUNDED_ALLOWED_LABELS: Final[dict[str, int]] = {
    "stage": 6,             # 07 §14.3 约束 8
    "gate_no": 3,           # 1/2/3
    "rule_id": 21,          # AST-R01…R20（07 §7.2；§14.2 D1 曾误写 R01…R16，见 U-16）**+ 空值**。
                            # ⚠️ 上界曾经写 20：`EMPTY_LABEL_VALUE` 也是一个**不同的序列取值**
                            #   （"载体本轮没给规则号"），域实际是 21。写 20 的后果不是报错，
                            #   而是"第 21 个被观测到的取值"静默丢弃 + 记一次 overflow ——
                            #   丢哪个取决于**到达顺序**，等于给闸门统计装了个随机洞。
                            #   不变式由 `tests/unit/test_obs_metrics_cardinality.py` 全局守住。
    "refuse_reason": 4,     # C-12
    "degraded_reason": 8,   # C-08
    "action_taken": 7,      # C-08
    "error_code": 28,       # 附录 A §A.11
    "bucket": 5,            # A.0.6（含全局并发桶）
    "binding_state": 4,     # 四态
    "binding_layer": 4,     # L1–L4（N-27 约束 5）
    "state": 4,             # §15.3：binding_state_total 的标签键（BindingState.value）
    "layer": 4,             # §15.3：binding_layer_total 的标签键（BindingLayer.value）
    "retrieval_mode": 2,    # C-11
    "scope_level": 3,       # A.1.5
    "role": 7,              # 07 §13.2
    "model": 2,             # flash / pro（P0）
    "prompt_version": 8,    # 灰度期上限（§15.3 给 ≤10，本项更严）
    "graph_version": 8,
    # --- W7 按 §15.3 标签列补的键 ---
    "endpoint": 20,         # §15.3 系统行
    "status": 10,           # §15.3 给 ≤10；实现取状态类（2xx/3xx/4xx/5xx），见 `status_class`
    "outcome": 5,           # Outcome 五值
    "reason": 8,            # 一名两义的上界（见上方注释）
    "kind": 8,              # §15.3 `ui_contract_violation` 的标签
    "error_class": 9,       # 07 §8.9 的 8 类 + `resource_exceeded`（§A.11 的 EXEC_RESOURCE_EXCEEDED）
    # --- U-105（架构裁定，2026-09-20）：启动校验三态镜像 ---
    "assertion": 4,         # `repo/startup_assertions.ASSERTION_NAMES` 的条数（**封闭集**，见下）
    "assertion_status": 3,  # `AssertionStatus` 三值 pass/pending/fail。⚠️ 刻意**不叫 `status`** ——
                            #   `status` 已被 HTTP 状态类占用（≤10）、`state` 已被 BindingState 占用（≤4），
                            #   同名两义会让 `BOUNDED_ALLOWED_LABELS` 的上界在两个指标间互相背锅
                            #   （`reason` 就是登记在案的那处疤，不再新增第二处）。
    "token_key": 4,         # C-03 四键
    "reason_code": 10,      # §A.6 反馈原因码
    "metric": 40,           # `metric_label_overflow_total` 自身：受控指标数上界
}

#: 空值在标签里是**有语义的**："该载体本轮没给这个维度"（例如闸门拒绝帧缺 `rule_id`）。
#: 刻意不填 `"unknown"` —— 那会把"载体缺字段"伪装成"存在一个叫 unknown 的规则"。
EMPTY_LABEL_VALUE: Final[str] = ""


def _enum_values(enumerant: type[Enum]) -> tuple[str, ...]:
    return tuple(str(item.value) for item in enumerant)


# ============================================================================
# 二、注册表本体
# ============================================================================

COUNTER: Final[str] = "counter"
GAUGE: Final[str] = "gauge"
HISTOGRAM: Final[str] = "histogram"

#: 延迟桶（秒）。**必须让 §16.1 的两条验收线落在桶边界上**：P95 ≤ 8s（G-6）
#: 与 P1 告警 > 15s。`histogram_quantile` 只能在相邻边界间插值 ——
#: 桶边界不压验收线，"刚好达标 / 刚好超标"就判不出来。
LATENCY_BUCKETS_S: Final[tuple[float, ...]] = (
    0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0, 120.0,
)


class _MetricSpec:
    """指标声明：名字 + 类型 + 标签集 + **逐标签取值域** + 直方图桶。

    `closed`（★ U-105）标出**封闭集**标签：取值域由代码里的枚举/常量表决定，
    出现第 N+1 个取值只能是代码错误，不是"运行时观测到的新事实"。
    这类标签的越界处置与开放集**相反** —— 开放集（如 `rule_id`）丢弃 + 计溢出，
    因为脏数据不该打挂请求；封闭集**当场抛**，因为静默截断会把"代码少了一个分支"
    伪装成"这类断言从没红过"（那正是启动校验指标最不该有的失效方式）。
    """

    __slots__ = ("buckets", "closed", "domains", "help", "kind", "labels", "name")

    def __init__(
        self,
        name: str,
        kind: str,
        *,
        help_text: str,
        labels: tuple[str, ...] = (),
        domains: Mapping[str, Iterable[str]] | None = None,
        buckets: tuple[float, ...] | None = None,
        closed: tuple[str, ...] = (),
    ) -> None:
        if kind not in (COUNTER, GAUGE, HISTOGRAM):
            raise ValueError(f"未知指标类型：{kind}")
        for label in labels:
            if label in UNBOUNDED_FORBIDDEN_LABELS:
                raise ValueError(f"{name}: 标签 {label!r} 属无界基数，禁止作标签（§15.3 纪律①）")
            if label not in BOUNDED_ALLOWED_LABELS:
                raise ValueError(f"{name}: 标签 {label!r} 未声明基数上限（§15.3 纪律②）")
        for label in closed:
            if label not in labels:
                raise ValueError(f"{name}: 封闭集标签 {label!r} 不在该指标的标签集内")
        self.name = name
        self.kind = kind
        self.help = help_text
        self.labels = labels
        self.closed: frozenset[str] = frozenset(closed)
        self.domains: dict[str, tuple[str, ...]] = {
            key: tuple(values) for key, values in (domains or {}).items()
        }
        self.buckets = buckets

    def bind_domain(self, label: str, values: Iterable[str]) -> tuple[str, ...]:
        """**运行期**填取值域（封闭集专用），返回生效的域。

        为什么必须有这条路：R-DEP-3 禁止 `app/obs/**`（除 `audit.py`）依赖 `app/repo/**`，
        所以本文件**不能** `from app.repo.startup_assertions import ASSERTION_NAMES`。
        而 U-105 要求"取值从 `ASSERTION_NAMES` / `AssertionStatus` 导出，禁手抄"
        ⇒ 唯一合规形态是：**由已经 import 得到的那一侧（`app/main.py` 的 lifespan）把域注进来**。
        手抄一份字面量在这里不是风格问题，是"改一处忘改另一处、而 CI 不红"的漂移源。
        """
        if label not in self.labels:
            raise ValueError(f"{self.name}: 标签 {label!r} 未声明")
        bound = tuple(dict.fromkeys(str(v) for v in values))
        if not bound:
            raise ValueError(f"{self.name}: 标签 {label!r} 的取值域不能为空")
        ceiling = BOUNDED_ALLOWED_LABELS[label]
        if len(bound) > ceiling:
            raise ValueError(
                f"{self.name}: 标签 {label!r} 声明了 {len(bound)} 个取值，超过基数上界 {ceiling}"
                "（§15.3 纪律②）⇒ 要么改上界并留裁定出处，要么这不该是封闭集"
            )
        existing = self.domains.get(label)
        if existing is not None and existing != bound:
            raise ValueError(
                f"{self.name}: 标签 {label!r} 的取值域已绑定为 {existing}，不允许二次绑定改域"
                "（否则同一进程内先后两次启动能给出两套真相）"
            )
        self.domains[label] = bound
        return bound


class _Metric:
    """一个指标的样本集。

    并发模型用 `threading.Lock` 而不是 `asyncio.Lock`：写入点横跨事件循环与线程池
    （审计/检查点走同步 psycopg 的线程），后者在非循环线程上会当场炸。
    锁粒度是"单指标"，临界区是一次自增加字典写 —— 相对 LLM 的秒级耗时属噪声。
    """

    __slots__ = ("_hist", "_lock", "_observed", "_scalars", "_seen", "spec")

    def __init__(self, spec: _MetricSpec) -> None:
        self.spec = spec
        self._lock = threading.Lock()
        self._scalars: dict[tuple[str, ...], float] = {}
        # 直方图：series key → (逐桶计数, 样本和, 样本数)
        self._hist: dict[tuple[str, ...], tuple[list[int], float, int]] = {}
        self._seen: dict[str, dict[str, None]] = {label: {} for label in spec.labels}
        self._observed = False

    # -- 基数闸门 -----------------------------------------------------------

    def _admits(self, labels: Mapping[str, str]) -> bool:
        """标签名 / 取值域 / 基数三重校验。`False` = 本次观测**丢弃**。

        两类失败的处置相反，且都是刻意的：
        · 标签名不合法 = 编程错误 → **抛**（让它在测试里红，而不是看板上悄悄少一条线）；
        · 取值域外 / 基数越界 = 运行时数据条件 → **丢弃 + 计溢出**（不能让脏数据打挂请求）。
        """
        for name in labels:
            if name in UNBOUNDED_FORBIDDEN_LABELS:
                raise ValueError(f"{self.spec.name}: 标签 {name!r} 属无界基数（§15.3 纪律①）")
            if name not in self._seen:
                raise ValueError(
                    f"{self.spec.name}: 标签 {name!r} 未在该指标声明的标签集内或无上界"
                )
        # ★ 封闭集（U-105）先单独过一遍：越界是**代码错误**，必须在写任何状态之前抛，
        #   且不走下面的"丢弃 + 计溢出" —— 那会把"少了一个分支"伪装成"这类事件从没发生过"。
        for name in self.spec.closed:
            value = labels.get(name)
            if value is None:
                raise ValueError(f"{self.spec.name}: 封闭集标签 {name!r} 必须给值")
            domain = self.spec.domains.get(name)
            if domain is None:
                raise ValueError(
                    f"{self.spec.name}: 封闭集标签 {name!r} 的取值域尚未绑定"
                    f"（应由装配方调用 `bind_domain` 从源枚举导出 ⇒ 不在这里手抄）"
                )
            if value not in domain:
                raise ValueError(
                    f"{self.spec.name}: 封闭集标签 {name!r} 收到域外取值 {value!r}"
                    f"（域 = {domain}）⇒ 这是代码错误，不是观测事实，不静默丢弃"
                )
            seen = self._seen[name]
            if value not in seen and len(seen) >= BOUNDED_ALLOWED_LABELS[name]:
                raise ValueError(
                    f"{self.spec.name}: 封闭集标签 {name!r} 已观测到 {len(seen)} 个取值，"
                    f"{value!r} 会突破上界 {BOUNDED_ALLOWED_LABELS[name]} ⇒ 域与上界不一致，代码错误"
                )
        for name, value in labels.items():
            domain = self.spec.domains.get(name)
            if domain is not None and value not in domain:
                self._overflow()
                return False
        with self._lock:
            for name, value in labels.items():
                seen = self._seen[name]
                if value not in seen and len(seen) >= BOUNDED_ALLOWED_LABELS[name]:
                    self._overflow()
                    return False
            for name, value in labels.items():
                self._seen[name].setdefault(value)
        return True

    def _overflow(self) -> None:
        """越界本身必须可观测 —— 否则"看板少了一条线"会被读成"没发生过这类事件"。"""
        METRIC_LABEL_OVERFLOW_TOTAL.inc(metric=self.spec.name)

    def _key(self, labels: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(labels.get(name, EMPTY_LABEL_VALUE) for name in self.spec.labels)

    # -- 写入 ---------------------------------------------------------------

    def inc(self, value: float = 1.0, **labels: str) -> None:
        if self.spec.kind is not COUNTER:
            raise TypeError(f"{self.spec.name} 不是 counter")
        self._record(value, labels)

    def set_value(self, value: float, **labels: str) -> None:
        if self.spec.kind is not GAUGE:
            raise TypeError(f"{self.spec.name} 不是 gauge")
        if not self._admits(labels):
            return
        with self._lock:
            self._scalars[self._key(labels)] = float(value)
            self._observed = True

    def observe(self, value: float, **labels: str) -> None:
        if self.spec.kind is not HISTOGRAM:
            raise TypeError(f"{self.spec.name} 不是 histogram")
        if not self._admits(labels):
            return
        buckets = self.spec.buckets or LATENCY_BUCKETS_S
        with self._lock:
            key = self._key(labels)
            counts, total, count = self._hist.get(key) or ([0] * len(buckets), 0.0, 0)
            for index, upper in enumerate(buckets):
                if value <= upper:
                    counts[index] += 1
                    break
            else:  # 超出最大桶：不进任何桶，但仍计 sum/count（Prometheus 同口径）
                pass
            self._hist[key] = (counts, total + value, count + 1)
            self._observed = True

    def _record(self, value: float, labels: Mapping[str, str]) -> None:
        if not self._admits(labels):
            return
        with self._lock:
            key = self._key(labels)
            self._scalars[key] = self._scalars.get(key, 0.0) + value
            self._observed = True

    # -- 读出 ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.spec.name

    def value(self, **labels: str) -> float:
        """读回一个序列（契约测试与停机 drain 用）。未观测 = 0。"""
        key = self._key(labels)
        if self.spec.kind is HISTOGRAM:
            return float(self._hist.get(key, ([], 0.0, 0))[2])
        return self._scalars.get(key, 0.0)

    def total(self) -> float:
        """全部序列之和（在途请求总数这类"跨序列聚合"判据用）。"""
        if self.spec.kind is HISTOGRAM:
            return float(sum(entry[2] for entry in self._hist.values()))
        return float(sum(self._scalars.values()))

    def observed(self) -> bool:
        """本轮进程里是否真的写入过（区分"恒 0"与"没接过"）。"""
        return self._observed

    def series_keys(self) -> tuple[tuple[str, ...], ...]:
        source = self._hist if self.spec.kind is HISTOGRAM else self._scalars
        return tuple(sorted(source))

    # -- 渲染 ---------------------------------------------------------------

    def render(self) -> list[str]:
        spec = self.spec
        lines = [f"# HELP {spec.name} {spec.help}", f"# TYPE {spec.name} {spec.kind}"]
        for labels in self._series():
            if spec.kind is HISTOGRAM:
                lines.extend(self._render_histogram(labels))
            else:
                key = self._key(labels)
                lines.append(f"{spec.name}{_fmt(labels)} {self._scalars.get(key, 0.0):g}")
        return lines

    def _render_histogram(self, labels: Mapping[str, str]) -> list[str]:
        spec = self.spec
        buckets = spec.buckets or LATENCY_BUCKETS_S
        counts, total, count = self._hist.get(self._key(labels)) or ([0] * len(buckets), 0.0, 0)
        lines = []
        cumulative = 0
        for index, upper in enumerate(buckets):
            cumulative += counts[index]
            lines.append(f"{spec.name}_bucket{_fmt({**labels, 'le': _le(upper)})} {cumulative}")
        lines.append(f"{spec.name}_bucket{_fmt({**labels, 'le': '+Inf'})} {count}")
        lines.append(f"{spec.name}_sum{_fmt(labels)} {total:g}")
        lines.append(f"{spec.name}_count{_fmt(labels)} {count}")
        return lines

    def _series(self) -> list[dict[str, str]]:
        """序列清单。

        所有标签都有取值域 → **未观测的取值也输出 0**（W0 定下的口径：看板与告警
        不必处理"序列尚未出现"的缺席语义）；否则只输出实际观测到的序列。
        """
        spec = self.spec
        declared = self._declared_series()
        if declared is None:
            return [dict(zip(spec.labels, key, strict=True)) for key in self.series_keys()]
        observed = {self._key(labels): labels for labels in declared}
        extra = [
            dict(zip(spec.labels, key, strict=True))
            for key in self.series_keys()
            if key not in observed
        ]
        return [*declared, *extra]

    def _declared_series(self) -> list[dict[str, str]] | None:
        spec = self.spec
        if not spec.labels:
            return [{}]
        if any(name not in spec.domains for name in spec.labels):
            return None
        combos = itertools.product(*(spec.domains[name] for name in spec.labels))
        return [dict(zip(spec.labels, combo, strict=True)) for combo in combos]

    def _reset(self) -> None:
        with self._lock:
            self._scalars.clear()
            self._hist.clear()
            for seen in self._seen.values():
                seen.clear()
            self._observed = False


def _le(upper: float) -> str:
    return "+Inf" if upper == float("inf") else f"{upper:g}"


def _fmt(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{value}"' for key, value in labels.items()) + "}"


_REGISTRY: dict[str, _Metric] = {}
_REGISTRY_LOCK = threading.Lock()


def register_metric(spec: _MetricSpec) -> _Metric:
    """登记指标。**同名重复登记返回既有对象**（幂等）。

    幂等而不是抛：热重载与测试导入会让模块重复执行，"重复导入即炸"会把
    `--reload` 变成无法自助的故障。
    """
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(spec.name)
        if existing is not None:
            return existing
        created = _Metric(spec)
        _REGISTRY[spec.name] = created
        return created


def get_metric(name: str) -> _Metric | None:
    return _REGISTRY.get(name)


def metric_names() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def reset_for_tests() -> None:
    """清空样本（**保留声明**）。指标是模块级全局状态，跨用例残留会让
    "计数 = 1" 这类断言依赖执行顺序（`tests/conftest.py` 复位 τ gauge 同理）。
    生产路径不调用。
    """
    for metric in _REGISTRY.values():
        metric._reset()


# ============================================================================
# 三、§15.3 指标清单（逐行对照 07；每行给"类型 / 标签 / 上界 / 数据源"）
# ============================================================================

METRIC_LABEL_OVERFLOW_TOTAL = register_metric(
    _MetricSpec(
        "metric_label_overflow_total",
        COUNTER,
        help_text="被基数闸门丢弃的观测次数（按指标名）。非零 = 标签取值超出域或基数上限（§15.3 纪律②③）",
        labels=("metric",),
    )
)

# --- 系统 ------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = register_metric(
    _MetricSpec(
        "http_requests_total",
        COUNTER,
        help_text="请求 QPS / 错误率的分子（§15.3 系统行：endpoint(≤20) / status(≤10)）。"
        "status 取状态类（2xx/3xx/4xx/5xx），错误分布由 §14.5 的语义指标承载",
        labels=("endpoint", "status"),
    )
)

HTTP_REQUEST_DURATION_SECONDS = register_metric(
    _MetricSpec(
        "http_request_duration_seconds",
        HISTOGRAM,
        help_text="端到端请求时延。**SSE 请求的观测终点 = 响应体写完**（客户端已收到 terminal），"
        "与 §16.1 U-13 的『端到端 = 收到 complete』同口径 —— G-6 的 P95≤8s 以此为准",
        labels=("endpoint",),
        buckets=LATENCY_BUCKETS_S,
    )
)

HTTP_REQUESTS_INFLIGHT = register_metric(
    _MetricSpec(
        "http_requests_inflight",
        GAUGE,
        help_text="在途请求数（含在途 SSE 流）。优雅停机 drain 的判据（§18.3 步 2）",
        labels=("endpoint",),
    )
)

STAGE_DURATION_SECONDS = register_metric(
    _MetricSpec(
        "stage_duration_seconds",
        HISTOGRAM,
        help_text="编排阶段耗时（帧侧口径：SSE `stage.elapsed_ms` 的相邻差值）。"
        "⚠️ **不是** §15.3 的『图节点耗时』：节点名不进 SSE（06 D2 红线），"
        "节点级直方图待 app/graph 的观测钩子（见 RELAY 上呈）",
        labels=("stage",),
        domains={"stage": _enum_values(Stage)},
        buckets=LATENCY_BUCKETS_S,
    )
)

LLM_UPSTREAM_CONCURRENCY = register_metric(
    _MetricSpec(
        "llm_upstream_concurrency",
        GAUGE,
        help_text="上游 LLM 并发占用（§15.3 系统行 model(2)）。"
        "数据源：app/obs/samplers.py 对 ChatClient 信号量的只读内省（公共访问器需求已上呈）",
        labels=("model",),
    )
)

# --- 语义 ------------------------------------------------------------------

QUERY_OUTCOME_TOTAL = register_metric(
    _MetricSpec(
        "query_outcome_total",
        COUNTER,
        help_text="终态分布（Outcome 五值）。**澄清率 = {outcome=\"clarify\"} / 全体**"
        "（§15.3 Gauge 行的 Counter 化，见模块 docstring）；NFR-7.1 上限 15%",
        labels=("outcome",),
        domains={"outcome": _enum_values(Outcome)},
    )
)

CLARIFY_TOTAL = register_metric(
    _MetricSpec(
        "clarify_total",
        COUNTER,
        help_text="澄清原因分布（ClarifyReason 2 值）。与 query_outcome_total{outcome=\"clarify\"} 同源：本指标答『为什么澄清』，前者答『澄清占比』",
        labels=("reason",),
        domains={"reason": _enum_values(ClarifyReason)},
    )
)

BINDING_STATE = register_metric(
    _MetricSpec(
        "binding_state_total",
        COUNTER,
        help_text="07 §15.3：binding_state 四态分布（澄清率异常的诊断入口）",
        labels=("state",),
        domains={"state": _enum_values(BindingState)},
    )
)

BINDING_LAYER = register_metric(
    _MetricSpec(
        "binding_layer_total",
        COUNTER,
        help_text="07 §15.3：binding_layer 分布（L4 占比 = 语义层质量仪表盘，N-25）",
        labels=("layer",),
        domains={"layer": _enum_values(BindingLayer)},
    )
)

REFUSE_TOTAL = register_metric(
    _MetricSpec(
        "refuse_total",
        COUNTER,
        help_text="拒答原因分布（§14.5：refuse.reason 四值，C-12）。⚠️ 闸门拒绝**不是**拒答（§14.2 D1/D3）",
        labels=("reason",),
        domains={"reason": _enum_values(RefuseReason)},
    )
)

DEGRADED_TOTAL = register_metric(
    _MetricSpec(
        "degraded_total",
        COUNTER,
        help_text="降级事件（§14.5：degraded.reason 8 值 × action_taken 7 值，C-08）。降级率 = 本指标 / 请求数",
        labels=("reason", "action_taken"),
        domains={
            "reason": _enum_values(DegradedReason),
            "action_taken": _enum_values(ActionTaken),
        },
    )
)

GATE_REJECT_TOTAL = register_metric(
    _MetricSpec(
        "gate_reject_total",
        COUNTER,
        help_text="闸门拒绝率（§14.5：按 gate_no + **rule_id** 分组 —— §7.2 要求 rule_id 进 gate_detail 的原因）。"
        "『危险 SQL 放行』P0 的间接探测口是**突降**，不是突增。rule_id 空值 = 载体本轮未给规则号",
        labels=("gate_no", "rule_id"),
        domains={
            "gate_no": tuple(str(int(gate)) for gate in GateNo),
            "rule_id": (EMPTY_LABEL_VALUE, *_enum_values(AstRule)),
        },
    )
)

EXEC_FAILURE_TOTAL = register_metric(
    _MetricSpec(
        "exec_failure_total",
        COUNTER,
        help_text="执行失败率（§14.5：按 07 §8.9 的**内部错误类**，不是 PG 原始码 —— 原始码含表名/列名/值，N-11）",
        labels=("error_class",),
        domains={
            "error_class": (
                "unknown_column",
                "unknown_table",
                "type_mismatch",
                "unknown_function",
                "syntax_error",
                "timeout",
                "permission",
                "db_unavailable",
                "resource_exceeded",
            )
        },
    )
)

RETRIEVAL_MODE_TOTAL = register_metric(
    _MetricSpec(
        "retrieval_mode_total",
        COUNTER,
        help_text="检索模式分布（C-11）。**检索降级率 = {retrieval_mode=\"sparse_only\"} / 全体**（§15.3 Gauge 行）",
        labels=("retrieval_mode",),
        domains={"retrieval_mode": _enum_values(RetrievalMode)},
    )
)

LLM_TOKENS_TOTAL = register_metric(
    _MetricSpec(
        "llm_tokens_total",
        COUNTER,
        help_text="token 计量（C-03 四键）。**prompt 前缀缓存命中率 = cache_hit / input**（§15.3 缓存命中率行）；"
        "token/请求 周环比告警（§15.4 P2）的分子",
        labels=("token_key",),
        domains={"token_key": _enum_values(TokenKey)},
    )
)

GEN_SQL_ROUNDS_TOTAL = register_metric(
    _MetricSpec(
        "gen_sql_rounds_total",
        COUNTER,
        help_text="本轮 sql_ready 帧次数累加（§15.3『首次执行成功率 / 平均纠错轮次』）。"
        "平均轮次 = 本指标 / 请求数；首次即成功 = 单轮请求的占比",
    )
)

JSON_PARSE_FAILURE_TOTAL = register_metric(
    _MetricSpec(
        "llm_json_parse_failure_total",
        COUNTER,
        help_text="JSON 解析失败率（§15.3 语义行，prompt_version ≤8）—— **最早预示 prompt 退化**的指标。"
        "⚠️ 调用点在 app/llm（W3A 域）的解析失败分支，本期未接线 → 未观测时**不输出序列**（不补 0 冒充已采）",
        labels=("prompt_version",),
    )
)

DAILY_COST_CNY = register_metric(
    _MetricSpec(
        "daily_cost_cny",
        GAUGE,
        help_text="当日累计成本（元）。数据源：audit_log_supplement 的日聚合（§10.4 预算计数器的观测面）。"
        "§15.4 告警：80% P1 / 100% P0",
    )
)

FEEDBACK_REASON_TOTAL = register_metric(
    _MetricSpec(
        "feedback_reason_total",
        COUNTER,
        help_text="用户反馈『有误』分布（§15.3 质量行，reason_code 10 值，§A.6 的归因路由依据）。"
        "数据源：feedback 表周期采样，非请求路径",
        labels=("reason_code",),
        domains={"reason_code": _enum_values(FeedbackReasonCode)},
    )
)

# --- 契约 ------------------------------------------------------------------

UI_CONTRACT_VIOLATION_KINDS: Final[tuple[str, ...]] = (
    "terminal_after_terminal",   # §14.3 约束 3：终态之后仍有事件
    "duplicate_terminal",        # N-08：一条流恰有 1 个 terminal:true
    "terminal_missing_flag",     # §14.3 约束 1：终态事件未带 terminal=true
    # §14.3 约束 2：**非**终止事件（`degraded` 最容易犯）声称 terminal=true。
    # 刻意与上一条分开：两者修法在完全不同的代码路径上，混记一个标签
    # 会让值班人拿着"去查漏标志"的结论去看"多打标志"的代码 —— 排查方向直接反了。
    "non_terminal_claims_terminal",
    "stream_without_terminal",   # 流正常结束却没有终态帧
)

UI_CONTRACT_VIOLATION_TOTAL = register_metric(
    _MetricSpec(
        "ui_contract_violation_total",
        COUNTER,
        help_text="07 §15.3 契约行：**非零即 P0**。由 W7 的帧观测器在出口字节层独立复核 §14.3 序列约束",
        labels=("kind",),
        domains={"kind": UI_CONTRACT_VIOLATION_KINDS},
    )
)

# --- U-19 的 τ gauge（07 明文给定名字；W0 破例命名的遗留物，W7 并入统一注册表） ---

BINDING_TAU_CALIBRATED: Final[str] = "binding_tau_calibrated"

_BINDING_TAU_HELP: Final[str] = (
    "1 = BINDING_TAU 已绑定 model_id+prompt_version 且经冻结集校准；"
    "0 = 未校准（仅允许 APP_ENV!=prod，此时 L4 精排结果不具备生产判定效力）"
)

_BINDING_TAU_GAUGE = register_metric(
    _MetricSpec(BINDING_TAU_CALIBRATED, GAUGE, help_text=_BINDING_TAU_HELP)
)


def set_binding_tau_calibrated(calibrated: bool) -> None:
    """启动期写入。由 `app.main.lifespan` 在启动时调用（U-19 硬要求 ②）。"""
    _BINDING_TAU_GAUGE.set_value(1.0 if calibrated else 0.0)


def get_binding_tau_calibrated() -> int:
    """读回当前值（契约测试用；也可供后续窗口做启动自检）。"""
    return int(_BINDING_TAU_GAUGE.value())


# --- 事件循环延迟（A.8.2 的 `event_loop_lag_ms`；> 5s → liveness 503） -------

EVENT_LOOP_LAG_MS = register_metric(
    _MetricSpec(
        "event_loop_lag_ms",
        GAUGE,
        help_text="事件循环调度延迟（毫秒）。> 5000 时 /healthz/live 必须 503（附录 A §A.8.2）。"
        "数据源：app/obs/samplers.py 的心跳漂移采样",
    )
)


def set_event_loop_lag_ms(lag_ms: float) -> None:
    EVENT_LOOP_LAG_MS.set_value(float(lag_ms))


def get_event_loop_lag_ms() -> float | None:
    """`None` = 采样器还没跑出首个样本 → `/healthz/live` 必须回 `null` 而不是 0。

    A.8.2 的"阻塞 > 5s 判 503"在没有样本时**无法判定**，
    返回 0 等于宣称"已实现且健康"（W0 在 health.py 里为此留了 null）。
    """
    return EVENT_LOOP_LAG_MS.value() if EVENT_LOOP_LAG_MS.observed() else None


# --- 启动校验三态镜像（★ U-105，07 §18.4 / §15.3 纪律②的裁定项）---------------

STARTUP_ASSERTION_STATE = register_metric(
    _MetricSpec(
        "startup_assertion_state",
        GAUGE,
        help_text=(
            "启动断言当前态（1 = 该断言处于该状态；同一条断言在任一时刻只有一行是 1）。"
            "U-105：三态 PASS/PENDING/FAIL 里 PENDING 原先只有一条 WARN 日志 ⇒ "
            "'带着未就绪的前置条件跑起来'这件事在看板与告警上都是隐形的。"
            "标签 assertion(≤4) × assertion_status(≤3) ⇒ 系列上界 12"
        ),
        labels=("assertion", "assertion_status"),
        closed=("assertion", "assertion_status"),
        # ⚠️ 注册时**故意不给 domains**：见 `bind_startup_assertion_domains` 的 R-DEP-3 说明。
        #   未绑定前本族整族不输出（B 类，"没线"≠"0"）；绑定后 12 条 0 序列齐备（A 类）。
    )
)


def bind_startup_assertion_domains(
    assertion_names: Iterable[str], statuses: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """由**装配方**（`app/main.py` 的 lifespan）把封闭集取值域注进来。

    为什么不由本文件自己 `from app.repo.startup_assertions import ASSERTION_NAMES`：
    `.importlinter` 的 **R-DEP-3** 明令 `app/obs/**`（除 `audit.py`）不得依赖 `app/repo/**`
    —— 违反它拿到的不是"少一次 import"，而是"观测层可以在 DB 挂掉时把主链路带崩"这个失效面。
    而 U-105 又要求"取值从 `ASSERTION_NAMES` / `AssertionStatus` 导出，禁手抄"
    ⇒ 两面夹出来的唯一合规形态就是：**已经 import 得到源枚举的那一侧注入**。

    幂等性刻意**不做**：二次绑定给出不同域会当场抛 —— 同一进程内两套真相比不写更糟。
    """
    return (
        STARTUP_ASSERTION_STATE.spec.bind_domain("assertion", assertion_names),
        STARTUP_ASSERTION_STATE.spec.bind_domain("assertion_status", statuses),
    )


def startup_assertion_domains_bound() -> bool:
    spec = STARTUP_ASSERTION_STATE.spec
    return {"assertion", "assertion_status"} <= set(spec.domains)


def observe_startup_assertion(assertion: str, status: str) -> None:
    """记一条"断言 `assertion` 当前是 `status`"。取值越界 ⇒ **抛**，不静默丢弃（封闭集）。"""
    STARTUP_ASSERTION_STATE.set_value(1.0, assertion=assertion, assertion_status=status)


# ============================================================================
# 四、采集端 API（只收枚举，自由字符串进不来）
# ============================================================================


def status_class(status_code: int) -> str:
    """HTTP 状态码 → 状态类（`2xx`…`5xx`）。

    §15.3 给 `status` 的上限是 ≤10，而端点实际能吐出 8+ 种状态码；
    用状态类既守住上界又不丢判据（错误明细由 §14.5 的语义指标承载，不该由 HTTP 层重复计）。
    """
    if 100 <= status_code < 600:
        return f"{status_code // 100}xx"
    return "5xx"


def record_http_request(endpoint: str, response_status: int, duration_s: float) -> None:
    HTTP_REQUESTS_TOTAL.inc(endpoint=endpoint, status=status_class(response_status))
    HTTP_REQUEST_DURATION_SECONDS.observe(duration_s, endpoint=endpoint)


def inc_inflight(endpoint: str) -> None:
    HTTP_REQUESTS_INFLIGHT.set_value(
        HTTP_REQUESTS_INFLIGHT.value(endpoint=endpoint) + 1, endpoint=endpoint
    )


def dec_inflight(endpoint: str) -> None:
    HTTP_REQUESTS_INFLIGHT.set_value(
        max(0.0, HTTP_REQUESTS_INFLIGHT.value(endpoint=endpoint) - 1), endpoint=endpoint
    )


def inflight_total() -> int:
    """在途请求总数（§18.3 步 2 的 drain 判据）。"""
    return int(HTTP_REQUESTS_INFLIGHT.total())


def observe_stage(stage: Stage, duration_s: float) -> None:
    STAGE_DURATION_SECONDS.observe(duration_s, stage=stage.value)


#: W0 时代的公开常量是**指标名字符串**（既有契约测试据此拼接样本行）。
#: 保留该形态，但值取自注册表对象 —— 名字只有一处字面量，不会出现"改了对象没改常量"。
BINDING_STATE_TOTAL: Final[str] = BINDING_STATE.name
BINDING_LAYER_TOTAL: Final[str] = BINDING_LAYER.name


def observe_binding_state(state: BindingState) -> None:
    """binding 结果落一个 `state` 计数。形参类型即准入校验（自由字符串进不来）。

    ⚠️ 签名是 W0 定的、调用方是 W4 的 `MetricsBindingObserver`（N-27 约束⑤ 的计量端）——
    W7 只把实现换到统一注册表上，**不改名字也不改语义**。
    """
    BINDING_STATE.inc(state=state.value)


def observe_binding_layer(layer: BindingLayer) -> None:
    """binding 结果落一个 `layer` 计数（N-27 约束⑤ 的计量端）。"""
    BINDING_LAYER.inc(layer=layer.value)


def observe_outcome(outcome: Outcome) -> None:
    QUERY_OUTCOME_TOTAL.inc(outcome=outcome.value)


def observe_clarify(reason: ClarifyReason) -> None:
    CLARIFY_TOTAL.inc(reason=reason.value)


def observe_refuse(reason: RefuseReason) -> None:
    REFUSE_TOTAL.inc(reason=reason.value)


def observe_degraded(reason: DegradedReason, action_taken: ActionTaken) -> None:
    DEGRADED_TOTAL.inc(reason=reason.value, action_taken=action_taken.value)


def observe_gate_reject(gate_no: GateNo, rule_id: AstRule | None = None) -> None:
    """闸门拒绝计数。`rule_id` 缺位时落在 `rule_id=""` 序列（= 载体未给规则号）。"""
    GATE_REJECT_TOTAL.inc(gate_no=str(int(gate_no)), rule_id=rule_id.value if rule_id else EMPTY_LABEL_VALUE)


def observe_gate_reject_from_payload(gate_no: object, rule_id: object) -> bool:
    """从帧载荷（任意 `dict`）安全取值的入口。返回 `False` = 取值不合法、未计数。

    刻意不抛：帧载荷来自图内部，一个字段形状不对不该把观测器连带打挂，
    而"没计数"必须能被调用方记成一条日志。
    """
    try:
        gate = GateNo(int(str(gate_no)))
    except (TypeError, ValueError):
        return False
    rule: AstRule | None = None
    if isinstance(rule_id, str) and rule_id:
        try:
            rule = AstRule(rule_id)
        except ValueError:
            rule = None
    observe_gate_reject(gate, rule)
    return True


def observe_exec_failure(error_class: str) -> None:
    EXEC_FAILURE_TOTAL.inc(error_class=error_class)


def observe_retrieval_mode(mode: RetrievalMode) -> None:
    RETRIEVAL_MODE_TOTAL.inc(retrieval_mode=mode.value)


def observe_tokens(token_key: TokenKey, count: int) -> None:
    if count > 0:
        LLM_TOKENS_TOTAL.inc(float(count), token_key=token_key.value)


def observe_gen_sql_rounds(rounds: int) -> None:
    if rounds > 0:
        GEN_SQL_ROUNDS_TOTAL.inc(float(rounds))


def observe_json_parse_failure(prompt_version: str) -> None:
    """JSON 解析失败计数（§15.3 语义行）。

    ⚠️ 本期**无调用点**：网关的解析失败分支在 `app/llm`（W3A 域）内部，
    而 `MetricsSink` 只在成功时回调。函数留在这里是刻意的 —— 接线只需一行。
    """
    JSON_PARSE_FAILURE_TOTAL.inc(prompt_version=prompt_version)


def observe_ui_contract_violation(kind: str) -> None:
    UI_CONTRACT_VIOLATION_TOTAL.inc(kind=kind)


def observe_upstream_concurrency(model: str, occupied: int) -> None:
    LLM_UPSTREAM_CONCURRENCY.set_value(float(occupied), model=model)


def observe_feedback(reason_code: FeedbackReasonCode, count: int) -> None:
    """反馈计数由**采样器**给增量（数据源是 `feedback` 表，不是请求路径）。"""
    if count > 0:
        FEEDBACK_REASON_TOTAL.inc(float(count), reason_code=reason_code.value)


def observe_daily_cost_cny(cost_cny: float) -> None:
    DAILY_COST_CNY.set_value(cost_cny)


# ============================================================================
# 五、导出端（`/metrics` 的唯一渲染函数；不得另起第二个采集端点）
# ============================================================================

PROMETHEUS_CONTENT_TYPE: Final[str] = "text/plain; version=0.0.4; charset=utf-8"


def render_prometheus_text() -> str:
    """Prometheus text exposition（0.0.4）。

    样本行格式与 W0 原实现逐字一致（如 `binding_state_total{state="accepted"} 0`），
    既有契约测试据此不改动。
    """
    lines: list[str] = []
    for metric in _REGISTRY.values():
        # 三条序列来源，区别是刻意的：
        # · 标签全集已知（枚举即全集，**含"无标签"这一退化情形**）→ 未观测也补 0
        #   （W0 口径，看板不必处理"序列缺席"）；`daily_cost_cny` / `gen_sql_rounds_total`
        #   / `event_loop_lag_ms` 都属这一支 ⇒ **即使整条链路没接线也会各输出一条 0**；
        # · 已观测过 → 输出实际序列；
        # · 有标签但**无声明域**且从未观测（如 `llm_json_parse_failure_total{prompt_version}`、
        #   首次请求前的 `http_requests_total`）→ **整族不输出**。
        #   输出 0 等于宣称"采到了、值为 0"，而 W0 在 health.py 里正是用 null 拒绝做这个宣称。
        # ⚠️ 措辞纪律：只有**第三支**才该叫"序列不会出现"。把第一支也叫"未接线 ⇒ 序列不出现"
        #   会让 `== 0` 型告警条件在健康系统里恒真（文档与看板都踩过这一脚）。
        if metric.series_keys() or metric._declared_series() is not None:
            lines.extend(metric.render())
    return "\n".join(lines) + "\n"
