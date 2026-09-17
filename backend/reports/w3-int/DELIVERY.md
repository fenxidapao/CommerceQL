# W3-INT 交付 —— 阶段 3 收口窗口

> 窗口：W3-INT｜日期：2026-09-17｜基准 commit：`affad0b`（远端 = 本地，收口期间无并发提交进入门禁）
> 定位：汇总 / 核验 / 接线 / 全量门禁 / 裁决上呈 / 交付 —— **不做功能开发**。
> 逐窗口转述件（可直接转发）：同目录 `RELAY.md`。任务定义：同目录 `PROMPT.md`。

---

## 1. 收口动作清单（已执行）

| # | 动作 | 结果 |
|---|---|---|
| T0 | 环境自证：git 状态 + 复核 PROMPT §三 8 条 | ✅ 全部成立（§2） |
| T1 | 读三家 DELIVERY/RELAY（含勘误节/追加节），合并收口总表 | ✅（§6 + RELAY） |
| T2 | 抽查"已落地"声称的可核对位置 | ✅ 全部实锤（§4） |
| T3 | 接线判断 | **本阶段无接线动作**（§5） |
| T4 | 全量门禁（Docker 已运行） | ✅ 六道全绿，数字与 W3A 基线一致（§3） |
| T5 | 端到端验证 | 大部分 BLOCKED，如实登记（§7） |
| T6 | 裁决上呈 + 统一上游转述 | ✅ 合并去重成单一文档（RELAY §给架构） |
| T7 | 交付 + PROMPT.md 惯例裁决执行 | ✅（§8） |

---

## 2. PROMPT §三 现状复核（动手前逐条）

| # | PROMPT 声称 | 复核结果 |
|---|---|---|
| 1 | HEAD=基线、提交链如述 | ✅ HEAD = `affad0b`（= PROMPT.md 自身的落库提交，比文中 `672fdf4` 多 2 个 docs 提交，均为收口前既有）；`git ls-remote origin main` = 本地一致 |
| 2 | 门禁基线 1471/6/0/0 等 | ✅ 本次复跑完全一致（§3） |
| 3 | Docker 未起 = 1F+6E+55S 假红 | 未复测该形态（Docker 本已在运行）；三家 DELIVERY 均有同形态记录，采信 |
| 4 | 6 skip = `test_retrieval_fts_pg.py` 夹具无 DDL 权限 | ✅ 本次输出同因（`permission denied for database ecom`） |
| 5 | `graph/**`、`api/routers/**` 空/占位，三包零调用方 | ✅ 未变 |
| 6 | DoD 达成度 | ✅ 与三家 DELIVERY §2 一致：W3A ①–⑤ 全✅；W3B ②③✅、①部分；W3C ②③④✅、①部分 |
| 7 | W3B 两处报数被 W3A 勘误 | ✅ 勘误节在位（`w3b/DELIVERY.md §八`、`w3b/RELAY.md 末节`）；本收口引用 W3B 数据一律以勘误节为准 |
| 8 | PROMPT.md 入库惯例漂移 | ✅ 属实（`w3a` 未入库、`w3b`/`w3c` 已入库）；裁决见 §8 |

工作区脏件（**均非本窗口所有，未暂存**）：`backend/reports/w2-int/e2e_stage2_check.py`（1 行修改，他人）、`_gs.txt`、`reports/arch/`、`reports/w0/`、`reports/w3a/PROMPT.md`（untracked，本窗口按 §8 裁决入库）。

---

## 3. 全量门禁实测输出（2026-09-17，`.venv`，Docker 已运行，原样）

```
$ ../.venv/Scripts/python.exe -m pytest -q
1471 passed, 6 skipped, 1 warning in 70.67s (0:01:10)
# 6 skip = tests/integration/test_retrieval_fts_pg.py：夹具 DSN 无 DDL 权限（permission denied for database ecom）

$ ../.venv/Scripts/python.exe -m ruff check .
All checks passed!

$ ../.venv/Scripts/python.exe -m mypy app
Success: no issues found in 102 source files

$ ../.venv/Scripts/lint-imports.exe          # 控制台脚本
R-DEP-1 / R-DEP-2·N-01 / R-DEP-3 / R-DEP-4 全部 KEPT
Contracts: 4 kept, 0 broken.

$ rm -f app/guard/_probe_violation.py && ../.venv/Scripts/python.exe scripts/assert_importlinter.py
[probe] ✅ r-dep-2 / r-dep-1 / r-dep-3 / r-dep-4
[restored] 还原后 lint 重新通过（Contracts: 4 kept, 0 broken.）
DoD② 通过 —— 4 条契约均已证明「脏了必红」

$ ../.venv/Scripts/python.exe -m app.core.enums
enums.py 契约自检通过；取值集基数 = {stage:6, error_code:28, sse_event:12, degraded_reason:8,
binding_state:4, binding_layer:4, ast_rule:20, ...（32 个取值集齐全）}
```

**判定：0 红 0 错，与 W3A §12.6/§13.5 基线（1471/6/0/0）完全一致。** 无回归、无新问题。
（本次跑 `assert_importlinter.py` 前按惯例先 `rm -f app/guard/_probe_violation.py`，一次通过、无残留——W0 的并发安全问题仍未修，见 RELAY §给 W0-3。）

---

## 4. T2 抽查核验（"已落地"声称 → 可核对位置）

| 窗口 | 声称 | 核验位置 | 结果 |
|---|---|---|---|
| W3A | `TaskRoute.budget_s`（元数据）/ `hard_timeout_s(model_key)`，`effective_timeout_s` 已删 | `app/llm/router.py:53-54,171-173`；`effective_timeout_s` 全文 **0 命中** | ✅ |
| W3A | `THINKING_HEADROOM_TOKENS=8192`、`GEN_SQL_COMPLEX.output_tokens_hint=1536` | `router.py:148`、`router.py:224` | ✅ |
| W3A | `CallRecord.budget_s`/`over_budget` | `app/llm/__init__.py:259-262,479-483` | ✅ |
| W3B | `_report_and_raise`（死代码修复） | `app/planner/engine.py:773` | ✅ |
| W3B | 修复轮 `repair_schema=RepairResult`（schema 错配修复） | `app/planner/engine.py:627` | ✅ |
| W3B | `INTENT_MAP` 单表映射 | `app/planner/schemas.py:143`（⚠️ 报告写 `:102`，该处是章节注释——**行号小漂移，实现属实**） | ✅（位置修正） |
| W3B | 170 条用例可独立复跑 | 收口全量 1471 passed 内含；`test_planner_*.py` 随全量绿 | ✅ |
| W3C | `four_layer._level4` 四条 `ambiguous` fail-safe 路径 | `app/binding/four_layer.py` 模块头读法 3/4 + L4 区间 docstring（:290 起） | ✅ |
| W3C | `assess_stability` n≥3 硬校验 | `app/binding/calibration.py:100-102`（`ScoreSample` 构造期 `ValueError`，`MIN_REPEATS`） | ✅ |
| W3C | `require_rerank_scores` 拒裸 `float` | `app/binding/scores.py:129,138`（`BindingScoreMisuse`） | ✅ |
| W3C | enums 自检两基数 = 4 | 本次 enums 输出 `binding_state:4, binding_layer:4` | ✅ |
| 债务 | `query_plan`/`cost_ledger` 表不存在 | `grep -rn "query_plan\|cost_ledger" app/repo/migrations/` → **0 命中** | ✅（现状属实） |

---

## 5. 接线判断（T3）

**本阶段无接线动作。** 依据：

1. 三包（`app/llm`/`app/planner`/`app/binding`）**零调用方**，所有装配面（lifespan、每请求上下文、SSE 侧信道）都在 W4 的 `graph/**`/`api/**` —— 未开工，接了也是空转（PROMPT §一"特殊性"已预判）。
2. `main.py` / `startup_assertions.py` / health 探针：阶段 3 三包**不引入新的 readiness 探针需求**——LLM 是软依赖（软失败 = 200 + degraded，不计 readiness），binding 的 τ gauge 与观测出口由 W4 装配时接。硬依赖集（DSN×3）与阶段 2 无差异，本次 enums 输出 `readiness_dependencies:4` 未变。
3. 无架构裁决落在三包内的单点修改需求（收口期间无裁决下发）。

---

## 6. 收口总表（三类；逐条可粘贴版 = RELAY.md）

### 6.1 接线类（全部 BLOCKED，等 W4）
W4 开工输入已整理成 RELAY §给 W4（装配 / 事件侧信道 / 预算责任 / 入参契约四组，合并自三家 RELAY，含 W3A 两轮追加的更新）。要点：§16.2 占位符先推与 SSE 60s 不断流是**阶段 3 收口后新增的 W4 责任**。

### 6.2 裁决类（单一上呈文档 = RELAY §给架构）
三窗口候选合并去重后 **24 组**（W3A 11 → 9 组、W3B 10 → 与 W3A 合并 2 组 + 独立 6 组 + 1 组已被勘误吸收撤下、W3C 9 → 7 组独立 + 2 组同源合并），全部"待架构分配编号"，下一可用 = `U-65`。**本窗口未替架构选方案**（⑬ 的 A/B/C 三方向原样呈报）。

### 6.3 债务类（等依赖）
等 W1B：`cost_ledger`、`query_plan` 两表（本次 grep 复核 0 命中，现状属实）｜等 W0：12 条（RELAY §给 W0）｜等 W6：τ 校准｜等 W4：全部接线｜等架构：预算三题（⑪⑫⑬）+ 合并档 2。

---

## 7. 端到端验证状态（T5，如实登记）

| 项 | 状态 |
|---|---|
| SSE 全链路 / 降级事件到前端 / `refuse` 终态 / L4 双入口选择 / §16.2 占位符先推 | 🔴 **BLOCKED（等 W4）** |
| L3+ pro 档（候选 ⑬，A/B/C 未裁）；§16.1 预算重裁（⑪⑫） | 🔴 **BLOCKED（等架构）** |
| `binding_state`/`binding_layer` 落库（缺表）；τ 校准（真跑前 `is_finalizable` 必为 `False`，设计使然） | 🔴 **BLOCKED（等 W1B / W6）** |
| 三包单测独立复跑（228 + 170 + 265 = 663 条，全离线） | ✅ 随全量绿 |
| `lint-imports` 全仓基线 | ✅ 4 kept, 0 broken |
| `cost_ledger`/`query_plan` 表不存在现状复核 | ✅ 0 命中（§4） |
| `l4_score` 真机延迟代量 | ⛔ 未做（真机 key 费用/限流不在本窗口授权内，转 W3C/W6，见 RELAY §给架构-尾） |

---

## 8. PROMPT.md 入库惯例裁决与执行（T7-附）

**现状**：`w2-int` ✅入库｜`w2a`/`w2c`/`w3a` ❌未入库｜`w3b`/`w3c` ✅入库。同一阶段两种惯例并存（W3C `91b8bd3` 具名请裁决）。

**裁决：判"开发者窗口 PROMPT.md 一律入库"**，理由：

1. PROMPT.md 承载各窗口的开工上下文与 Q 系列决策点定义，是 DELIVERY 里"决策点落定"一节的可追溯上游，入库的审计价值大于仓库膨胀代价（每份 100–200 行）；
2. `w3b`/`w3c` 已入库成为事实，回删（`git rm --cached`）会让两份已登记的报告与 git 历史脱节，且 `w3c` 的重建件文件头有防漂移声明，删它丢信息；
3. 阶段 2 的 `w2a`/`w2c` 属已关闭窗口的历史状态，本窗口不回溯改动（跨阶段改历史正是要避免的漂移）。

**执行**：`git add backend/reports/w3a/PROMPT.md`（唯一缺失件，本就在工作区）。此后惯例一句话：**所有窗口（开发 + 收口）的 `PROMPT.md` 一并入库**——已写入 RELAY §给架构-非编号裁决②，请架构窗口知悉（若架构否决，反向操作由下一窗口执行）。

---

## 9. 收口结论（PROMPT §八 四条，逐条如实）

1. **W3B DoD① 只记部分达成**：合并档 1 已实测（省 ~0.80s，数值口径以 W3A §12.1 为准）；`plan`/`gen_sql` 实测超 §16.1 分配（两口径均超）；**合并档 2 未实现**；**§16.1 预算执行点现在空缺**——网关已修（预算≠超时），但 §16.2"超预算先推占位符"目前**无人执行**，等架构裁决 + W4 落 SSE 占位符。**NFR-1.2（首字节 ≤1.5s）当前没有执行者。**
2. **W3C DoD① 只记部分达成**：`(state, layer)` 二元组与观测出口已备（本次核验 `binding_state:4`/`binding_layer:4` 实锤），但 **`query_plan` 表不存在 ⇒ "双双落库"未达成**（迁移 0001–0003 零命中，本次复核）。
3. **L3+ 的 pro 档从未生效**（候选 ⑬ 未裁）：真机实测 pro 97–138s，每次被 45s 上限掐断后降级 flash——用户在 L3+ 拿到的是 flash 的答案、代价 50–60s/请求。**"L3+ 慢"不是回归，是 ⑬ 的既有事实。**
4. **三包零调用方**：阶段 3 的"可用"是**模块级可用**（663 条新增单测全绿 + 网关行为真机探测），端到端要等 W4。本报告不使用"链路已通"类表述。

---

## 10. 提交

| commit | 内容 |
|---|---|
| `docs(w3-int)` | `reports/w3-int/{PROMPT.md(已入库), DELIVERY.md, RELAY.md}` + `reports/w3a/PROMPT.md`（§8 裁决执行） |

只暂存本窗口文件；`w2-int/e2e_stage2_check.py` 的他人修改与 `_gs.txt`/`reports/arch/`/`reports/w0/` 等未跟踪件**不碰**。push：用户已授权直接推。
