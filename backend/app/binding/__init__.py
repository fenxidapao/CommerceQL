"""CommerceQL 字段绑定：四层判定（结构上禁 LLM，FR-3.2）。

层号：L2｜归属窗口：W3C（docs/08 §4.1 文件归属权表）｜禁依赖：``llm``（R-DEP-2，CI 强制）

## 模块布局（07 §6.8 / §6.8.2 / 附-1）

| 文件 | 职责 |
|---|---|
| ``context.py`` | 请求级上下文（`contextvars`）：归一化问句 / 粒度词 / 时间语义 / 包版本 |
| ``errors.py`` | 只三类异常：包刻度矛盾、τ 绑定不匹配、裸 float 误用 —— **都不是"这次没绑上"** |
| ``grain.py`` | 粒度族索引：并查集推族 + 词汇表 + 问句→粒度（禁跨族比较） |
| ``scores.py`` | L4 分数值对象（`RerankScore`）+ 严格 JSON 解析 + 注入式适配缝（`adopt_l4_candidates`） |
| ``filters.py`` | 五步过滤：概念解析 ① + 权限 ② + 粒度可服务 ③ + 时间语义 ④ + 排序 ⑤ |
| ``four_layer.py`` | **核心**：L1→L2→L3→L4 顺序判定 + 四态 + fail-safe（N-27 约束④） |
| ``l4.py`` | L4 打分生产者：经注入的 `LLMPort` 出站 + 严格解析（本包**唯一**的异步入口） |
| ``service.py`` | 门面：装配上述各层，实现 ``core.contracts.BindingPort`` + 观测出口 |
| ``calibration.py`` | τ / ε 校准脚手架（冻结集扫描 + E-5 稳定性机器判定）；**不联网、不连库** |

## 给 W4（接线）—— 四件事，漏一件就有东西是坏的

**1. 装配（lifespan）**

```python
from app.binding import BindingService, set_binding_scope   # 观测适配器由你实现

service = BindingService.from_settings(reader=semantic_runtime, settings=settings,
                                        observer=MyBindingObserver())   # 见下第 3 条
calibrated = service.assert_usable_tau()      # 坏配置 → ConfigError，拒绝启动
metrics.set_binding_tau_calibrated(calibrated)   # U-19 §18.4.1 硬要求 ②
if not calibrated:
    logger.warning("binding_tau_uncalibrated", ...)   # 非 prod 放行但**不得隐瞒**
```

**2. 每次请求设问句上下文 —— 否则 L2 与步③ 静默失效**

```python
set_binding_scope(BindingRequestScope(normalized_question=q, time_semantics=ts))
try:
    result = service.resolve(concept, ctx, candidates)      # 端口面（同步）
finally:
    clear_binding_scope()                                   # 长生命周期 worker 必须清
```
不设也能跑（fail-open），但 `question_grain=None` → 步③ 与 L2 **都不判**，
且 `BindingOutcome.scope_was_set=False` 会如实标出来。**绝不默认某个粒度。**

**3. 观测出口必须有实现** —— N-27 约束⑤（`binding_layer` 分布可观测）要求它。
默认 `NullBindingObserver` **什么都不做**：不接线时这条指标面是**缺的**（不是"已满足"）。
`binding_state` / `binding_layer` 两个标签已在 `obs.metrics.BOUNDED_ALLOWED_LABELS` 登记（各 4 值）；
`BindingEvent.reason` / 概念名**只进日志，不进标签**（无界基数）。

🔴 **但标签只是"允许用"——指标本体还没有**：`obs/metrics.py` 里**没有任何 Counter 构造**
（实测 `grep -n "Counter" app/obs/metrics.py` 零命中，只有 `binding_tau_calibrated` 这一个 gauge）。
而 07 §15.3 明确要求两个 Counter：`binding_state` 分布（`state`=4）与 `binding_layer` 分布（`layer`=4）。
⇒ 你的适配器要么自行登记这两个 Counter，要么向 W0 提需求。**本窗口不越界改 `app/obs/**`。**

**4. L4 的两条路，选一条（D1(a) 双入口）**

- **在线**（推荐）：在 `bind` 节点里 `await score_l4(port=llm_port, ...)` → 拿 `ScoreOutcome`，
  再把**同一批**候选与分数喂给 `decide(...)`。注意 `score_l4` 需要**归一化问句**与**语义包摘要**。
- **注入**（离线/评测/回溯）：把分数做成 `CandidateRef(asset_id=…, score=…, layer=BindingLayer.L4)`
  传进 `resolve(concept, ctx, candidates)` —— 只有显式带 `L4` 标记的条目会被消费（D7）；
  非 `L4` 条目会被**计数**（`BindingOutcome.ignored_candidates`），不会静默丢弃。
  🔴 走这条路时 `model_id` / `prompt_version` 只能取 **τ 自己那一组**（`CandidateRef` 没有
  打分器标识字段）→ **τ 绑定校验在这条路上恒通过**，分数的来源一致性由**调用方**保证。
  在线路径（`score_l4`）才是真校验（标识来自 `LLMResponse`）。对照表见
  `service.BindingService._split_candidates`。

## 消费 `BindingResult` 的正确姿势（读法 1）

``ambiguous`` 态下 ``bindings`` 是**澄清选项**，不是已绑定字段。真正要用的判别是：

```python
outcome = service.resolve_detailed(concept, ctx, candidates)
if outcome.bindings_are_options:      # 等价于 state is ambiguous
    ... # 走澄清，把 outcome.clarify_prompt 与 outcome.result.bindings 交给澄清节点
elif outcome.result.state is BindingState.RESOLVED_DEFAULT:
    ... # 必须把 outcome.disclosure 写进 insight.caveats[]（U-26 的唯一载体）
```

``disclosure`` / ``clarify_prompt`` / ``reason`` **装不进** ``BindingResult``（端口三字段），
只能从 ``resolve_detailed`` 拿 —— 这是 D4 的既定分工。

## 校准脚手架（`calibration.py`）—— **离线**，不在请求路径上

唯一消费方是评测 / 收口窗口（W6 的执行器）：它**只吃已打好的分**，不联网、不连库、不打分。
请求路径（W4）**不应该** import 它 —— 它在这里导出只是为了给离线侧一个统一入口。

```python
from app.binding import ScoreSample, calibrate          # 离线脚本
report = calibrate(samples, epsilon=0.05, accuracy_target=0.8,
                   model_id="deepseek-flash", prompt_version="l4_score_v1",
                   calibrated_at="2026-09-17T00:00:00Z", holdout_separated=True,
                   layer_distribution=layer_counts)      # 分布只能由运行时观测带入
if report.is_finalizable:                                # 不满足就别贴进 .env
    print("\n".join(report.config_lines()))
else:
    print(report.blocking_actions)                       # 缺什么，逐条给
```
"""

from __future__ import annotations

from app.binding.calibration import (
    MIN_REPEATS,
    TAU_SWEEP_STEP,
    CalibrationReport,
    SampleStability,
    ScoreSample,
    StabilityReport,
    StabilityVerdict,
    TauPoint,
    assess_stability,
    calibrate,
    kendall_tau_b,
    sweep,
)
from app.binding.context import (
    UNSET_SCOPE,
    BindingRequestScope,
    clear_binding_scope,
    current_binding_scope,
    set_binding_scope,
)
from app.binding.errors import (
    BindingBundleInconsistency,
    BindingError,
    BindingScoreMisuse,
    BindingTauScorerMismatch,
)
from app.binding.filters import (
    BindingAttribution,
    ConceptResolution,
    FilterOutcome,
    filter_candidates,
    resolve_concept,
)
from app.binding.four_layer import MAX_CLARIFY_OPTIONS, LayerDecision, TauConfig, decide
from app.binding.grain import GrainFamily, GrainIndex, GrainMatch, GrainRef, SemanticReader
from app.binding.l4 import (
    L4_CONSTRAINTS,
    L4_OUTPUT_SCHEMA,
    L4_TASK,
    MODEL_AUTO,
    build_l4_payload,
    score_l4,
)
from app.binding.scores import (
    L4_SCORE_ITEM_KEYS,
    RerankScore,
    ScoreOutcome,
    ScoreParseError,
    adopt_l4_candidates,
    parse_scores_json,
    require_rerank_scores,
)
from app.binding.service import (
    NULL_BINDING_OBSERVER,
    BindingEvent,
    BindingObserver,
    BindingOutcome,
    BindingService,
    NullBindingObserver,
)

__all__ = [
    "L4_CONSTRAINTS",
    "L4_OUTPUT_SCHEMA",
    "L4_SCORE_ITEM_KEYS",
    "L4_TASK",
    "MAX_CLARIFY_OPTIONS",
    "MIN_REPEATS",
    "MODEL_AUTO",
    "NULL_BINDING_OBSERVER",
    "TAU_SWEEP_STEP",
    "UNSET_SCOPE",
    "BindingAttribution",
    "BindingBundleInconsistency",
    "BindingError",
    "BindingEvent",
    "BindingObserver",
    "BindingOutcome",
    "BindingRequestScope",
    "BindingScoreMisuse",
    "BindingService",
    "BindingTauScorerMismatch",
    "CalibrationReport",
    "ConceptResolution",
    "FilterOutcome",
    "GrainFamily",
    "GrainIndex",
    "GrainMatch",
    "GrainRef",
    "LayerDecision",
    "NullBindingObserver",
    "RerankScore",
    "SampleStability",
    "ScoreOutcome",
    "ScoreParseError",
    "ScoreSample",
    "SemanticReader",
    "StabilityReport",
    "StabilityVerdict",
    "TauConfig",
    "TauPoint",
    "adopt_l4_candidates",
    "assess_stability",
    "build_l4_payload",
    "calibrate",
    "clear_binding_scope",
    "current_binding_scope",
    "decide",
    "filter_candidates",
    "kendall_tau_b",
    "parse_scores_json",
    "require_rerank_scores",
    "resolve_concept",
    "score_l4",
    "set_binding_scope",
    "sweep",
]
