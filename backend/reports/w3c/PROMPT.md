# 【窗口提示词 · 阶段 3C：四层字段绑定 + L4 精排（W3C）】

> ⚠️ **本文件由 W3C 窗口按实际执行过程重建**。原始开工上下文在前段会话中以**消息**形式给出（未落盘），
> 本窗口在收到"采纳并开工"后执行。重建目的是给收口窗口（W3-INT）一个**可追溯的任务定义**：
> 界定范围、契约、DoD 与边界。**不是**对上游文档的复述，凡与 `docs/**` 冲突以文档为准。
>
> 骨架沿用 `reports/w3a/PROMPT.md`（定位 → 契约与纪律 → 现状 → 任务清单 → 边界 → 决策点 → 交付）。
> 交付目录：`backend/reports/w3c/`。

---

你是 CommerceQL「阶段 3 · 字段绑定」窗口（**W3C**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"未接线/未联调"报告成"已实现"；跑不通就说卡在哪；决策点先"报告现状"再等指令，不自行扩大范围。

## 一、定位

- 独占范围：**`backend/app/binding/**`**（08 §4.1 归属权表第 300 行：`app/binding/**` → W3C，含 `four_layer.py`）。
- 交付 08 阶段 3C 的全部内容：**五步过滤 + 四层顺序判定 + 四态输出 + L4 精排兜底 + τ/ε 校准脚手架**。
- 依赖顺序：W3A（`app/llm/**`）是**前置**，已交付（`94ae6ea`+`2766f3c`）。你的 L4 精排**只能经注入的
  `LLMPort` 出站**，**禁止** `import app.llm`（R-DEP-2 由 CI 强制）。
- 你**不是**收口窗口：阶段 3 的收口（汇总/接线/全量门禁/裁决上呈）由 W3-INT 承担。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v0.9) > 08 实施计划(v1.2)**。
- 端口已冻结（W0 的 `app/core/contracts.py`，**不得改**）：
  - `BindingPort.resolve(concept, ctx, candidates) -> BindingResult`
  - `BindingResult{state, layer, bindings}`｜`CandidateRef{asset_id, score, layer}`｜`IdentityContext`
  - `LLMPort.call(task, payload, model) -> LLMResponse{text, model, prompt_version, tokens, cost_cny}`
  - 缺口即提需求（见 §七），**不得私改 core**。
- `app/binding/**` 是**确定性模块**（FR-3.2 / N-01）：**结构上禁 LLM**。
  依赖方向：可 import `app.core`、`app.semantics`、`app.obs`、`app.repo`；**不得** import `app.llm` / `planner` / `graph` / `api`。
- 动手前先 `git status` + `git diff --stat` 判"是否别人的在制品"；**同一文件多处 `Edit` 必须串行改 + grep 复核**。
- 提交：`feat(w3c)` / `docs(w3c)`，只暂存本窗口文件。
- 编号纪律：**不得自行开号**。新问题列"待架构窗口分配"，下一可用号 = **`U-65`**。

## 三、现状盘点（本窗口开工时实测）

| # | 事实 |
|---|---|
| 1 | `app/binding/` **不存在**（`app/llm/` 刚由 W3A 建好）；`tests/unit/test_binding_*.py` 亦不存在 → 从零建包 |
| 2 | 语义包 `semantic/bundle_2026.09.14.1.yaml` 可用（W1A 交付），含别名/维度/指标/`field_binding`/`policies`/`quality_gates` |
| 3 | `obs.metrics.BOUNDED_ALLOWED_LABELS` **已登记** `binding_state`(4) / `binding_layer`(4) → 指标标签有界基数已有前提 |
| 4 | 🔴 **`query_plan` 表在迁移 0001–0003 中不存在**，更无 `binding_state` / `binding_layer` 列 → 08 阶段 3C 的 DoD① "双双落库" **缺表结构**（详见 DELIVERY §2） |
| 5 | τ 配置键已在 `core/config.py`：`BINDING_TAU=0.20` / `BINDING_TAU_EPSILON=0.05` / `BINDING_TAU_MODEL_ID` / `BINDING_TAU_PROMPT_VERSION` / `BINDING_TAU_CALIBRATED_AT` / `BINDING_TAU_REPORT_REF` |
| 6 | `07 §16.1` 已给 `L4 精筛` 任务预算 **0.8s**；`PRD §12.9` 裁定 P0 打分器 = **LLM 精排（方案 C）**、`deepseek-flash` 非思考位 |
| 7 | 上游余量：pytest 全量基线可用；`lint-imports` 必须用**控制台脚本**（`python -m importlinter.cli` 是假绿） |

## 四、任务清单（实际执行序）

| 批 | 内容 |
|---|---|
| **T0** | 前置自证：读 W3A 交付面与 RELAY §给 W3B/W3C；实测 `LLMPort` 白名单键与 `EgressPayload` 严格模式；确认 `.importlinter` 现有 4 条契约 |
| **T1** | `context.py` + `errors.py` + `grain.py`：请求级上下文（`contextvars`）、只三类异常、粒度族索引（并查集推族，禁跨族比较） |
| **T2** | `scores.py` + `filters.py`：`RerankScore` 值对象（**拒裸 float**）+ 严格 JSON 解析 + 注入适配缝；五步过滤 |
| **T3** | `four_layer.py`：L1→L2→L3→L4 顺序判定 + 四态 + fail-safe（N-27 约束④）+ `classify_gap` 区间判据唯一实现 |
| **T4** | `l4.py`：L4 打分生产者（出站载荷 + 严格解析），**本包唯一异步入口** |
| **T5** | `service.py` + `__init__.py`：门面实现 `BindingPort` + 观测出口 + 包门面与接线须知 |
| **T6** | `calibration.py`：τ/ε 校准脚手架（六步 + E-5 稳定性机器判定），**不联网、不连库** |
| **T7** | 门禁全量：本包 pytest / `ruff check .` / `mypy app` / `lint-imports` / 全量 pytest |
| **T8** | 交付文档（本目录三件）+ commit |

**DoD（08 第 232 行，逐条落地）**：

| # | 原文 | 本窗口落地 |
|---|---|---|
| ① | 四层判定四态可观测（`binding_state` + `binding_layer` 双双落库） | 判定恒产出 `(state, layer)` 对 + 观测出口 `BindingEvent`；**落库链路缺表结构**（见 DELIVERY §2 / RELAY §给 W1B） |
| ② | L4 fail-safe：解析失败 / 分差落在 τ 邻域 → 必判 `ambiguous`（N-27） | `four_layer._level4` 四条路径全部偏 `ambiguous`，含负向对照 |
| ③ | τ/ε 校准脚手架（含 E-5：n ≥ 3 排名一致性 + 分差 std） | `calibration.py` 六步 + 稳定性门槛（未过**禁止定稿** + 升级方案 A 动作） |
| ④ | `RerankScore` 类型不接受裸 `float` | `scores.require_rerank_scores` 拒非 `RerankScore` 入参 |

## 五、必读清单（精确到章节）

1. `07 §6.8` 全节（含 §6.8.1 抽取失败、§6.8.2 五条硬约束、§6.8.3 诊断表）、`07 §12.9`（PRD）、`07 附-1`（端口签名）。
2. PRD `§6.3.1`（四态 + "唯一是结果描述不是判据"）、`§12.9`（方案 C + 5 条硬约束）。
3. 附录 C `§C.4.6`（校准六步 + 5 条硬约束，**权威来源**）、`§C.4.5`（澄清率上限 NFR-7.1）。
4. `04 附录C §C.4.6`、`08 §3.5`（DoD）、`08 §4.1`（归属权）。
5. `core/contracts.py`（`BindingPort`/`BindingResult`/`CandidateRef`）、`core/enums.py`（`BindingState`/`BindingLayer`）、`.importlinter`。
6. `reports/w3a/{DELIVERY,RELAY}.md`（调用面与出站白名单）。

## 六、边界（这些目录归他人，只能提需求）

| 路径 | 归属 | 需求 |
|---|---|---|
| `app/core/**` | W0 | `CandidateRef` 补"分数来源"/"打分器标识"字段 |
| `app/repo/**` + `migrations/**` | W1B | `query_plan` 表 + `binding_state`/`binding_layer` 列（DoD① 硬前置） |
| `app/obs/**` | W0/W1B | 观测适配器（指标 + 日志）实现 |
| `semantic/**` | W1A | 排序键缺"血缘完整/成本"字段；实测新鲜度 |
| `app/graph/**`、`app/api/**` | W4 | 接线（装配 / 设上下文 / `insights.caveats`） |
| `pyproject.toml` / `.importlinter` | W0 | 新依赖须走 ADR-20 |

## 七、动手前必须"报告现状 + 拿指令"的决策点（实际落定见 DELIVERY §4）

| # | 决策点 | 落定 |
|---|---|---|
| **D1** | L4 分数怎么进判定：在线打分 or 注入？ | **(a) 双入口**（唯一适配缝 `adopt_l4_candidates`） |
| **D2** | 端口签名没有问句，而 L2/步③ 需要它 → 从哪来？ | **(a) 请求级 `contextvars`**，取不到即"不判"并如实标记 |
| **D4** | `disclosure`/`clarify_prompt`/`reason` 进不了三字段端口 → 去哪？ | 各自归属（`caveats[]` / 澄清节点 / 观测 sink），经 `resolve_detailed` 旁路 |
| **D6** | L4 **上游故障**（非解析失败）要不要转 `ambiguous`？ | **原样上抛**（不用产品结论掩盖系统故障），代码用 AST 扫描钉死"无 `except LlmError`" |
| **D7** | 端口 `candidates` 语义未定义 | 只消费显式 `layer is L4` 的条目，其余**计数上报**不静默丢弃 |
| **D8** | 校准选点并列怎么破？ | 取 `(准确率更大, τ 更大)`，均在保守侧 |

## 八、交付物

- `backend/app/binding/**`（10 个模块）+ `backend/tests/unit/test_binding_*.py`（7 个文件）。
- `backend/reports/w3c/DELIVERY.md`：DoD 逐条对照 + 门禁**实测**输出 + 缺陷清单 + 已知限制具名登记。
- `backend/reports/w3c/RELAY.md`：逐窗口可粘贴的转述件（W0 / W1B / W4 / W6 / W2B / 架构 / W3-INT）。
- commit：`feat(w3c)` / `docs(w3c)`。

## 九、本机环境坑

1. 一律用 `CommerceQL/.venv/Scripts/python.exe`（系统 Anaconda 3.11 的 pydantic 是 1.x，不合格）。
2. `lint-imports` 用**控制台脚本**（`../.venv/Scripts/lint-imports.exe`）；`python -m importlinter.cli` 假绿。
3. `ruff check` / `mypy app` 的**工作目录是 `backend/`**（CI 用 `working-directory: BACKEND_DIR`）；在仓库根跑会 `E902`。
4. CI 门禁还含 `python -m app.core.enums`（枚举契约自检）与 `python scripts/assert_importlinter.py`（DoD② 注入实验）。
5. `pytest` **无 `pytest-timeout` 插件** → 不要传 `--timeout=`；全量约 2.5 分钟，前台会超时，用后台跑并落日志。
6. Docker Desktop **不会自启** → PG/Redis 相关**集成**用例会连不上（本窗口单测全离线，不受影响）。
