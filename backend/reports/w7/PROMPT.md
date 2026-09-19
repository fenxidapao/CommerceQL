# 【窗口提示词 · 阶段 7 · 观测与部署（W7）】

> 骨架沿用 `reports/w4/PROMPT.md`（定位 → 契约与纪律 → 现状 → 任务清单 → 必读 → 边界 → 决策点 → 交付 → 环境坑）。
> 产出：阶段 7 观测部署收口窗口（受用户指令，与 **W6 评测并行**）｜日期：2026-09-18｜基准 commit：**`10d810f`**（远端 = 本地，W4 收口后）。
> **W7 与 W6 并行**（08 §5.1 第 6 段"W6 ∥ W7"）：两窗口同一条 `main`，提交前必看父链（§十一-5），只 stage 本窗口文件；与 W6 就"评测报告 ↔ 压测结果"的接口对表。
> 交付目录：`backend/reports/w7/`（你的 DELIVERY.md / RELAY.md 落这里）。

---

你是 CommerceQL「阶段 7 · 观测与部署」窗口（**W7**）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 `main`，远程 `fenxidapao/CommerceQL`。

【开工方式】**先输出执行计划，等确认后再动手**。需求不明确先提问，不要猜。
【红线】不伪造实现；不把"指标接了但没看板/没告警"报告成"观测已落地"；压测**先报告再跑批**（PRD §13.5）；软依赖失败必须 `200 + degraded`，不得把 embedding/LLM 不可用搞成 `503`（N-21）。

## 一、定位

- 独占范围（08 §4.1 / §3.9）：**`app/obs/**` 的指标本体**（W0 已落骨架与 `audit.py`，你写指标/采样器部分）· **`deploy/**` · **`app/api/routers/health.py`（三探针）**。
- 追加权（不得另立第二个组装根）：`app/main.py` 是组装根（lifespan 六步已由 W1B 落，U-42）——你的**指标注册/优雅停机/启动校验**在该文件**追加**，资源释放挂同一 shutdown 段。
- 交付 08 §3.9 全部产出：① 指标接入（§15.3 清单 + **标签基数上限**）② 看板 ③ 告警规则 ④ 压测（§16.5 四场景）⑤ 优雅停机 ⑥ runbook 六条 ⑦ 启动校验全量。
- 你是 G-6（P95 ≤8s）压测数据的**唯一产出方**，W6 的评测门禁判定依赖你的压测结果。

## 二、契约与纪律

- 契约优先级：**附录 A(02) > PRD(01) > 06 UIUX > 07 TDD(v1.0) > 08 实施计划(v1.2)**。
- **指标三纪律（§15.3 强制）**：① **禁止 `user_id`/`task_id`/`session_id` 作标签**（基数爆炸 = 监控自杀）② 每个标签有显式基数上限并纳入评审 ③ 标签**枚举值来自 `core/enums.py`**，禁止自由字符串。
- **计量端已存在，别重复登记**：`obs.metrics.observe_binding_state/layer` 已由 W0 落（`1c24f14`），binding/编排层的调用已就位——你只做**采集端与导出端**，不得另立同名 Counter。
- **三探针语义（§18.2）**：`/healthz/live`（进程存活）、`/healthz/ready`（**只含硬依赖** DB/Redis/语义包）、`/healthz`（聚合详情，**软件依赖 embedding/LLM 失败必须 200 + `degraded_dependencies`**）。`/healthz` payload 是附录 A §A.8.4 契约，**不得私增字段**（C-13）。
- 端口冻结：观测接 `EventEmitterPort`/日志接 `app/obs/logging`，不得改 W0 的 `app/core/contracts.py`。
- 提交：`feat(w7)` / `docs(w7)`，只暂存本窗口文件（`app/obs/**` 指标 + `deploy/**` + `health.py` + `main.py` 追加段 + `reports/w7/**`）。
- 编号纪律：**不得自行开号**。U-88~U-103 已被 W4 用尽；新问题列"待架构窗口分配"，下一可用号由架构窗口定。

## 三、现状盘点（2026-09-18；动手前复核）

| # | 事实 | 位置 |
|---|---|---|
| 1 | **W4 编排已收口**（`10d810f`）：端点 `POST /query`（SSE）、`/query/{id}/cancel`、`/query/{id}`、`/session`、`/clarify`、`/feedback` 已实现；SSE 帧结构/错误码映射/限流头已就位，是你的压测与探针的**在线底** | `reports/w4/DELIVERY.md` |
| 2 | **W0 已落指标骨架**：`obs.metrics` 计量端（`observe_binding_state/layer` 等）、Prometheus 采集口基本位 | `app/obs/` |
| 3 | **W1B 已落组装根**：`main.py` lifespan 六步（τ gauge → 三池+Redis → 语义包 runtime → 启动断言 → checkpointer → 探针注册），你的追加在其后 | `app/main.py:50-204` |
| 4 | **Docker 已手动启动**（用户 2026-09-18 确认）：PG/Redis/pgbouncer 栈可起，压测与健康检查可连真库 | 本机 Docker Desktop |
| 5 | `app/api/routers/health.py` 归你（W4 未动），当前可能只有 W0 骨架，需补三探针语义 | `app/api/routers/health.py` |
| 6 | 探针消费者诚实现状：liveness 无自动重启消费者（附录 A 已标注）、readiness 供 `depends_on: service_healthy`/LB 摘流量 | 附录 A / §18.2 |

## 四、任务清单（建议执行序，可按依赖调整）

1. **T0 环境自证**：venv = `CommerceQL/.venv`；`git status` 判在制品；起 Docker 栈（PG/pgbouncer/Redis）；复跑门禁钉基线（W4 后全量 pytest 应 1674P/87S，唯一红 = 未起 PG 的集成——你起了 PG 后应变绿）。
2. **T1 读输入**：§五必读清单逐份读完，重点 **§15.3（指标清单 + 三纪律）**、**§16.5（压测四场景）**、**§18（探针/停机/校验/runbook）**。
3. **T2 指标接入**：按 §15.3 清单逐条落 Counter/Histogram/Gauge，每个标签写死基数上限；枚举值接 `core/enums.py`。
4. **T3 三探针**：`health.py` 实现 `/healthz/live`、`/healthz/ready`（只硬依赖）、`/healthz`（聚合 + 软依赖 `degraded_dependencies`，失败 200+degraded）。
5. **T4 优雅停机**：`main.py` 追加 shutdown 段，实现 §18.3 六步（摘 readiness → drain SSE 30s → 超时发 `error(INTERNAL)`+`terminal` → 释放锁/连接 → 写审计 failed → 退出）。
6. **T5 启动校验全量**：§18.4 清单逐条 fail-fast（必填 env、`default_transaction_read_only`、`EMBEDDING_DIM`、语义包五步、`audit_log` 权限、结果缓存显式确认、`CORS_ALLOWED_ORIGINS` prod 为空、τ 校准 env-gate）。
7. **T6 压测**：§16.5 四场景（稳态 50 并发 10min / 突发 100 并发 30s / 单会话并发 / 同租户并发），用**合成数据集全量**（附录 C 规格），断言 checkpoint 无等待 + `SET LOCAL` 复位 + pgbouncer ≤30 + **P95 ≤8s**；**先报告再跑批**。
8. **T7 看板 + 告警**：§15.5 五块面板（含"准确率与门禁"屏接 W6 结果）+ §15.4 告警规则（P0：危险 SQL 放行/跨租户/`ui_contract_violation`；P1：P95>15s/澄清率>15%/成本 80%）。
9. **T8 runbook 六条**：§18.7 逐条落地（审计库故障 fail-closed / Ollama 不可用 / checkpoint 变慢 / 上游 LLM 故障 / 危险查询 / 成本异常）。
10. **T9 DoD 自验 + 门禁 + 交付**：08 §3.9 三条 DoD 逐条对照（§八）；`reports/w7/{DELIVERY,RELAY}.md` + commit + push。

## 五、必读清单（精确到来源）

1. **07 v1.0 §15 全章**：§15.1 结构化日志、§15.2 Trace 传播、**§15.3 指标清单（标签基数上限）**、§15.4 告警规则、§15.5 最小看板。
2. **07 v1.0 §16.5**：压测方案与验收口径（四场景 + 必测断言 + 工具 + "先报告再跑批"）。
3. **07 v1.0 §18 全章**：§18.1 进程模型、§18.2 健康检查、§18.3 优雅停机、§18.4 启动校验（含 §18.4.1 τ 校准 env-gate）、§18.5 灰度、§18.6 备份、§18.7 runbook 六条、§18.8 开发环境约定。
4. **08 §3.9**（DoD 原文）· §4.1（归属权表——`app/obs/**`、`health.py`、`deploy/**` 归你，`app/main.py` 只追加）。
5. **附录 A §A.8.4**（`/healthz` payload 契约）· 附录 D（环境变量/压测与 Ollama 宿主配置）。
6. `reports/w4/RELAY.md` §九（U-88~U-103，涉及 SSE 帧/错误码现状，压测与探针的底层契约）。

## 六、接线硬约束（接漏就是坏的；细节以原文为准）

- **探针**：`/healthz/ready` **只含硬依赖**（DB/Redis/语义包已加载）；embedding/LLM 是**软依赖**，失败 `200 + degraded`（N-21）——把软依赖写进 readiness 导致 `503` = 摘了一台"其实还能服务"的机器。
- **优雅停机**：SSE 在途流**不得静默断连**（超 30s 发 `error(INTERNAL, message="服务重启中，请重试")` + `terminal:true`）；取消也要写审计 `outcome=failed`。
- **启动校验**：`ANALYTICS_DB_URL` 角色须 `default_transaction_read_only`（N-02）；`audit_log` 表 `app_rw` **无 UPDATE/DELETE 权限**（N-09 前提）；τ 校准 env-gate：prod fail-closed、非 prod 放行但 `binding_tau_is_calibrated` 如实返回 false + 启动 WARN + 暴露 gauge（不得塞进 `/healthz`，C-13）。
- **指标**：`ui_contract_violation` 非零即 P0；作为标签的枚举一律 `core/enums.py`；`reason`(4)/`action_taken`(7)/`rule_id`(≤20) 等基数上限照 §15.3 写死。

## 七、动手前必须"报告现状 + 拿指令"的决策点

1. **压测工具选型**：k6 vs locust（§16.5 说二者皆可，**串行发**）；本机是否已装、要不要加进 dev 依赖——先报候选。
2. **压测是重资源操作 + 可能动真库**：四场景全量跑（尤其稳态 50 并发 10min）会持续占用 CPU 与连接池，且"先报告再跑批"是硬纪律——**先出压测方案（场景/并发/时长/工具/数据），等确认后再跑**。
3. **与 W6 的接口对表**：G-6 判定输入 = 你的 P95 结果，和 W6 定"压测报告放哪、评测报告如何引用、取数时点"。
4. **`app/obs/**` 指标本体的采集器/导出器**：W0 落了哪些、Prometheus 端点在哪、还是要新增——先摸清 W0 骨架再决定补什么，别重复造。
5. 其余"文档没写、实现要选"的点：列候选 + 倾向 + 代价，**等指令**。

## 八、DoD（08 §3.9 原文，交付时逐条对照）

① **四场景压测通过 + P95 达标**（≤8s）② **runbook 六条可执行** ③ `/healthz` 三探针语义正确（**软依赖失败必须 200 + degraded**）。

**收口结论必须如实写的三条**：① liveness 无自动重启消费者（附录 A 诚实标注），不要把"探针就位"写成"自愈已闭环"；② 压测结果与评测结果**分开归档**（PRD §13.5），不得把压测 P95 达标转写成"准确率达标"；③ 若压测因环境/额度未跑全，如实记 UNVERIFIED，不编数字。

## 九、边界（这些目录归他人，只能提需求）

`app/core/**`（W0）｜`app/repo/**`+migrations、`app/auth/**`、`app/cache/session_lock.py`、`app/main.py` **已有部分**（W1B）｜`app/graph/**`、`app/api/**`（**除 health.py**，W4）｜`app/{llm,planner,binding,guard,exec,mask,semantics,retrieval}`（W2*/W3*）｜`eval/**` 执行器（W6）｜`frontend/**`（W5）。

## 十、交付物

| commit | 内容 |
|---|---|
| `feat(w7)` | `app/obs/**` 指标 + `deploy/**` + `app/api/routers/health.py` + `app/main.py` 追加段（指标注册/优雅停机/启动校验）+ `tests/**`（探针/停机/校验的契约测试） |
| `docs(w7)` | `reports/w7/{DELIVERY.md, RELAY.md, 压测报告.md, runbook.md}`（RELAY 含给 W6 的压测结果回执 + 给架构的上呈） |

## 十一、本机环境坑（沿用 W4 §十一，逐条都会浪费半小时）

1. Docker Desktop 已由用户手动启动；压测/探针连真库前确认 `pg`/`pgbouncer`/`redis` 三栈 `healthy`。
2. `lint-imports` 用控制台脚本 `.venv/Scripts/lint-imports.exe`；`python -m importlinter.cli` 是假绿（U-41）。
3. `pytest` 无 timeout 插件（传 `--timeout=` 会 exit 4）；全量约 70s，后台跑并落日志。
4. venv = `CommerceQL/.venv`（从 `backend/` 用 `../.venv/Scripts/...`）；Bash 命令加 PortableGit PATH 前缀；别用 PowerShell（零回显）。
5. **并行窗口同一条 `main`**：提交前 `git log --oneline -5` 看父链，`git ls-remote origin main` 判分叉；`git add` 只暂存本窗口文件；与 W6 撞 `app/main.py`/`app/obs/**` 时**先报告再动**。
6. `w2-int/e2e_stage2_check.py` 未暂存修改与 `reports/{arch,w0}/` 未跟踪件是**他人的**，不碰。