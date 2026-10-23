# W67-3｜评测面 `degradations` 口径变更说明（横比影响登记）

派单：TASK_BOARD §88.5 第五-3（QA → W8，2026-10-22 22:20）。
性质：**登记文档，零代码改动、零出站、不改任何既有产物文件。**

---

## 一、变更是什么

W66 起（commit `dee748e`），`eval/harness.py` 新增 `_EvalDegradationSink`：把**网关层**降级事件
（原先只进日志、不进 `GraphState`）转发到 `current_run_context_or_none()`，与生产侧
`SseDegradationSink`（落 `RunContext`）同形。此前 harness 传 `degradation=None` ⇒ 网关层降级
在评测面**完全不可见**。

该修法不改 `app/**`，方向正确（QA §88.4① 已收）；但它改变了**评测面 `records[].degradations`
的字段口径** ⇒ 跨 W66 边界的批次不可直接横比。

## 二、精确口径（比派单点句更细，两处定性修正）

QA 点句把 `llm_concurrency_exceeded` / `switched_to_weak_model` / `llm_unavailable` 并列为
"网关层降级"。按枚举精确定性（`backend/app/core/enums.py`）：

| 串 | 枚举身份 | W66 前评测面可见性 |
|---|---|---|
| `llm_concurrency_exceeded` | **DegradedReason**（reason，8 值之一） | ❌ 网关专属路径，W66 起才可见 |
| `switched_to_weak_model` | **ActionTaken**（action_taken，7 值之一）——不是 reason | 它依附的 reason（如 `llm_concurrency_exceeded`）W66 起才可见 |
| `llm_unavailable` | DegradedReason，**双路**：节点路径（`normalize.py:179` UnderstandUnavailable）一直可见；网关路径（模板兜底 `_template_or_refuse`）W66 起才可见 | ⚠️ 节点路径的 `llm_unavailable` 一直可见 ⇒ **旧产物含 `llm_unavailable` 不构成反例** |

**可检验特征**：W66 前的产物中 `llm_concurrency_exceeded` 应当**恒不出现**。
清单实测（见第四节）：152 个 `eval/results_*.json` 中 **0 个**含它；唯一含它的产物是 W66
自己的饱和串跑 `eval/results_r66_saturation_graph.json`（该文件无 `records[]` 结构，不在
清单正表内，单列于第五节）。

## 三、横比规则（供 RELAY 与最终报告引用）

1. **W66 前批次 vs W66 起批次**：`degradations` **不可直接横比**。任何"降级次数/降级原因
   分布"的跨批对比，必须先按本节口径归一（或只比较双方都可见的节点层 reason）。
2. **"零降级"结论的证据力变化**：W66 前产物中 `degradations` 为空/缺网关 reason，
   **不能**证明"当时没有发生网关降级"——那类事件当时根本进不了记录。
   反之，W66 起的非空网关降级记录是**新增观测能力**，不是行为变化。
3. **落库面口径**：本变更只影响**评测面**（eval 产物）。生产/落库面（`budget` 表、
   `llm_calls` 等）的降级记录口径不受影响——网关降级在落库面一直有行。
4. **匣带（cassette）不受影响**：匣带记录的是传输层请求/响应，与 sink 无关；
   旧匣带回放不受本变更影响。

## 四、受影响既有产物清单（W66 前缺网关层）

完整机器可读清单：**`eval/results_r67_degradations_cutover_inventory.json`**
（152 个文件逐一列出 `n_records` / `reasons_observed` / `has_gateway_new_reason`；由
`eval/w67_l4_diagnostics.py` 生成，只读盘点）。

分组摘要（按批次族）：

| 批次族 | 代表文件 | records 数 | 缺网关层？ |
|---|---|---|---|
| r44–r53 稳定性/修复族（stab_\*、f57、g2、ever、mdim、clean 等） | `results_a3_r44.json` … `results_r53g2_r4.json` | 1–57 | 是 |
| r54–r59 全量族 | `results_r54_full166.json`、`results_r56_full166.json`、`results_r57b_full166.json`、`results_r58*_full166.json`、`results_r59_full166.json` | 166 | 是 |
| r61 契约/城市族（live+replay） | `results_r61_city5_live.json`、`results_r61_contract3_live.json` 等 | 3–5 | 是 |
| r63–r65 全量/二轮/τ族 | `results_r63_full166.json`、`results_r65_tau_raw_replay.json` 等 | 3–166 | 是 |
| r66 τ 重放 | `results_r66_tau_raw_replay.json` | 166 | 是（该重放未发生网关降级，故观测无差异；口径上仍属新纪元） |
| 早期全量（2026-10-03 前后） | `results_v1.json`、`results_v1_live_20261003T1410Z.json`、`results_v2_live_20261003T1632Z.json`、`results_replay_after_l4fix_20261003T1722Z.json` | 92–166 | 是 |

例外与注意：

- `eval/results_r59_error_io.json`、`eval/results_r59_timeout_shape.json` 带 UTF-8 BOM
  （盘点脚本以 `utf-8-sig` 兜底读入，内容完好；仅提醒后续工具链）。
- `eval/results_r66_saturation_graph.json`：W66 饱和串跑产物，**含**
  `llm_concurrency_exceeded`（图级证据，U-127 闭环件）——它是新口径的**首个受益者**，
  不是受影响对象。

## 五、结论一句话

> 评测面 `degradations` 自 **W66**（`dee748e`）起才含网关层事件；W66 前的全部 eval 产物
> （152 个中的 151 个结构化批次 + 2 个 BOM 文件）在该字段上**系统性缺网关层**，
> 跨 W66 边界的降级横比必须先按第三节规则归一。本登记不改任何既有文件。
