# 【窗口提示词 · 阶段 5 前端窗口（W5）】

> 本文件沿用 `reports/w2-int/PROMPT.md` 的骨架（定位/纪律/任务清单/例外与边界），按"开发窗口"改写。
> 与收口窗口的根本差异：**你写功能代码**。收口窗口"不做功能开发"的禁令对你不适用；但"不伪造、不假绿"的红线完全相同。

---

你是 CommerceQL「阶段 5 前端窗口」（W5）的负责人。仓库：`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL`，分支 main，远程 `fenxidapao/CommerceQL`。

## 一、你的定位与特殊性

阶段 4 段的三个 LLM 窗口（W3A/W3B/W3C）已交付并经 W3-INT 收口（基准 `affad0b`）。你是**并行旁支**：`frontend/**` 全部归你独占，目前**从零起步**（目录尚不存在）。

三条特殊性决定了你的开发方式：

1. **你只依赖阶段 0 的契约冻结，不依赖任何后端实现**（08 §3.7 原文）。此刻后端**没有** `/query` SSE 端点——`app/api/routers/` 只有 `health.py`，SSE 路由归 W4（未开工）。**你全程对着契约开发，联调是后话**。
2. **你先于 W4 交付**。08 §5.1 第 5 段是"单窗口 W4（其余窗口停手）"——你收工后 W4 才开工。你的 RELAY 是 W4 的联调输入之一。
3. **你的 UI 行为规格不是你发明的**。`docs/06_UIUX设计文档.md`（**v1.2.2**，2691 行）是已评审定稿的实现基准：15 个组件的 Props 契约、S0–S10 状态覆盖矩阵、SSE 客户端骨架、Design Token 代码、QA Checklist。你的工作是**把 06 变成代码**，不是重新设计。

## 二、契约与纪律

- 契约优先级：**附录 A(02，v1.5) > PRD(01，v1.6) > 06 UIUX(v1.2.2) > 07 TDD > 08(v1.2)**。前端一切行为以附录 A 为唯一规范源；06 与附录 A 冲突时以附录 A 为准并登记。
- 红线：**前端零判断权**（PRD §8.6.4）——图表类型、口径文案、脱敏值、聚合结果全部来自后端载荷；前端**不计算任何业务指标**（含表格合计行）、不渲染后端没给的字段、不用本地缓存伪造历史结果。
- 红线：不伪造实现。Mock 数据只许出现在 MSW 层（开发/测试用），**不得混入构建产物**；06 §14.2 QA Checklist 里依赖真实后端的项，如实标 `BLOCKED（待 W4 联调）`，不得用 Mock 冒充通过。
- 红线：**不得调用契约里不存在的端点**，不得自创请求参数。觉得缺能力 → 写进 RELAY 转达，不擅自加。
- 动手前 `git status` 判断他人 in 制品（后端窗口可能仍在提交 docs/修复）；同文件多处编辑**串行改 + grep 复核**；`feat(w5)` / `docs(w5)` 前缀，只暂存本窗口文件；**未获明确指令不 push**。
- PROMPT.md 随本窗口一并入库（w3-int §8 裁决：所有窗口 PROMPT.md 一律入库）。
- 本机环境（Windows，实测）：Bash 需 PATH 前缀 `export PATH="/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:.../bin:$PATH"`（stderr 两行无害）；Node 用托管版 `C:\Users\林琪荣\.workbuddy\binaries\node\versions\22.22.2-3\node.exe`（系统 24.18.0 为后备）；**npm 包一律装进 `frontend/` 本地 node_modules，禁止全局安装**；PowerShell 输出会丢，落临时文件再读；dev server 端口 5173 当前空闲。

## 三、上游输入（开工前必读，按序）

| 顺序 | 文档 | 你要拿什么 |
|---|---|---|
| 1 | `docs/02_附录A_接口契约详解.md` **v1.5** | 唯一规范源：A.1.2 事件表（12 事件含 `terminal`）、**A.1.4 终止判定唯一规则**、**A.1.5 `meta.scope` 三级披露 + 三条防泄露红线**、A.0.6 四桶限流与 `429` 语义边界、A.5.1–A.5.4 会话端点、A.4 澄清、A.6 反馈、A.7 语义层只读端点、**A.8 三探针（UI 只用 `GET /healthz`）**、A.9.2–A.9.5 管理端点、**A.11 全 28 错误码**、A.12 幂等、A.13 超时（澄清 5 分钟 / SSE 心跳 15s）、A.14 前端集成 14 条注意事项 |
| 2 | `docs/06_UIUX设计文档.md` **v1.2.2** | 实现基准：§3.7 Design Token 代码（**直接复制落 `frontend/src/theme/tokens.ts`，不重写**）、§4 组件规范 C1–C15、§5 会话页、§6 结果呈现、§7 四态对照、§8 状态覆盖矩阵 S0–S10、§9 契约对齐表、**§10 SSE 客户端实现骨架（§10.2 TypeScript 代码可直接采用）**、§11 次级页面、§13 埋点、**§14.2 QA Checklist（你的 DoD④）**、附录 B 待确认项（尊重其中已登记的默认方案） |
| 3 | `docs/05_附录D_环境依赖与部署清单.md` §D.3 | 前端依赖清单（版本锁定照抄）、环境变量三个 `VITE_*`、**`VITE_*` 禁放密钥**红线 |
| 4 | `docs/08_编程实施计划...md` §3.7 | 你的 DoD 原文与范围 |
| 5 | `backend/reports/w3-int/RELAY.md` §给 W4 | 后端将怎么发事件：装配方式、降级双通道、`LlmRefused`→`refuse` 终态、§16.2 占位符先推（W4 责任）、**SSE 必须撑 60s 不断流** |
| 6 | `backend/app/core/enums.py` | 枚举对齐基准（**只读**）：自检输出已锁 `stage:6 / error_code:28 / sse_event:12 / degraded_reason:8`——你的 TS 类型必须与这些取值集**逐字一致**，后端加值会触发你的未知值兜底分支（§8.4） |

后端现状速览（2026-09-17，`affad0b`）：全量门禁 1471/6/0；`app/api/routers/` 仅 `health.py`；`app/auth/` 已落 JWT+JWKS 验签链路（`tokens.py`/`jwks.py`/`revocation.py`）；`app/core/enums.py` 已锁 28 错误码。

## 四、任务清单（按序执行）

### T0 · 脚手架（半天）
`frontend/` 从零：Vite + React 18 + TS（≥5.5）+ AntD 5 + `react-router-dom` 6 + `@tanstack/react-query` 5 + `echarts` 5 + `echarts-for-react` + **`@microsoft/fetch-event-source`**（SSE over POST 的关键依赖，原生 `EventSource` 不可用——A.14 第 1 条）+ vitest + `@testing-library/react`。样式用 **AntD 自带 + CSS Modules**（D.3.2 方案 A，不引 Tailwind，避免与 AntD 优先级冲突）。包管理 npm（≥10）或 pnpm（≥9）二选一，锁定后不换。落 `06 §3.7` 的 tokens.ts + `ConfigProvider` 接线。ESLint + prettier 就位。

### T1 · 契约层与 Mock（先于一切 UI）
1. **类型**：以附录 A 为唯一规范源手写 `src/api/types.ts`（事件 payload、28 错误码、`meta.scope`、限流头）；`openapi-typescript` 从后端 OpenAPI 生成仅作交叉校验——**两者冲突以附录 A 为准并登记**（后端 OpenAPI 由 W4 产出，现阶段可能缺失，缺失则只用手写类型）。
2. **MSW mock**：按 A.1.2/A.1.3 的事件序列 mock `POST /query`（SSE over POST 的 mock 用 `ReadableStream` 拼装 `event:`/`data:` 帧）。**必mock 的场景**：成功全链（含 `data.truncated`、`chart`、`insight.caveats`）、澄清、拒答、错误（各语义色至少 1 码）、**降级但成功**（`degraded` → 继续 `data` → `complete`）、**转异步**（`degraded(switched_to_async)` → `complete(terminal:true)`）、`409 SESSION_CONFLICT`、`429 RATE_LIMITED`、空结果（`row_count:0` + `scope` 三级各一例）。**禁止 mock 契约里没有的字段**——mock 超出契约 = 联调必翻车。
3. mock 场景清单落 `frontend/src/mocks/scenarios.md`，与 T5 QA 一一对应。

### T2 · SSE 客户端（06 §10 骨架落地 + 单测）
以 §10.2 代码为起点，**逐条实现并测试**（这是你 DoD① 的主体，也是 06 标注"最脆的一环"）：
- 跨 chunk 半行缓冲（`split('\n\n')` + buffer 残留）；
- **终止判定唯一规则：`data.terminal === true`**（A.1.4；**禁止事件类型白名单**——`degraded` 恒 `terminal:false` 不终止；`terminal` 缺失视为 `false` + 告警日志）；
- `heartbeat` 只保活不驱动 UI；
- **90s 无任何事件 → 主动中止 + `POST /query/{task_id}/cancel`**（A.1.4；不要自作主张收紧成 35s，v1.2 已纠正过一次）；
- `Idempotency-Key`：同会话+同问题复用（A.12；`SESSION_CONFLICT` 重试**必须**复用同一 key）；
- **`409 SESSION_CONFLICT`：自动重试 1 次（`Retry-After`，默认 3s），禁止进限流禁用态、禁止喂 `QuotaIndicator`**（06 §4.12 辨析 #4）；
- 限流头四桶：只认 `X-RateLimit-Bucket === 'query'` 喂 `QuotaIndicator`；
- 单事件 JSON 解析失败不终止流（§10.2 末）。
每条至少 1 个 vitest 用例（用 mock stream 驱动，不依赖后端）。

### T3 · 组件 C1–C15（06 §4 逐个实现）
按 §4.0 清单顺序：AskBox / SessionRail(P1) / StageBar / SqlCard / ResultBlock / InsightCard / CaveatBar / TruncateBar / ClarifyCard / RefuseCard / DegradeBar / ErrorCard / FeedbackBar / QuotaIndicator / **HealthIndicator（§4.15，v1.2.2 新增——别漏，08 §3.7 写"14 个组件"是旧数，以 06 的 15 个为准）**。
硬要求：
- Props 契约照抄 06 各节代码块；`data-testid="c{n}-{name}"` 全覆盖；
- **§8.2 状态矩阵 S0–S10 逐格落实**（组件 × 11 态），每个组件至少覆盖：空 / 加载 / 正常 / 一种异常；
- 四态语义色**逐字用 §7.2 对照表**（拒答=中性灰、澄清=紫、降级=琥珀、错误=红），§14.2-B 的"灰阶可分性"自查通过；
- `ClarifyCard` 的 5 分钟倒计时（**测试把超时改 10s，别真等 5 分钟**）；`DegradeBar` 的 Inline 条 / 后台卡片两形态；`ErrorCard` 覆盖 28 码全矩阵（§4.12）+ 未知码兜底；
- `HealthIndicator` 只调 `GET /healthz`（**不是** `/healthz/ready`），软依赖 `200`+`degraded` = **琥珀**不是红（§4.15 红线）。

### T4 · 五页组装（08 §3.7 范围）
1. **登录页**：UI 按 06 §9.1 做壳（OIDC 重定向形态）。真实 IdP 流程属架构未决项（07 的认证方案 D-H 未裁）→ **本地 stub token 开发**（W1B 的 `app/auth/` 已落 JWKS 验签，测试 token 生成方式查 `app/auth/tokens.py` 与 tests 夹具），DELIVERY 标 `BLOCKED（待 D-H 裁决）`。
2. **会话问答页**（核心，06 §5）：P0 = 单栏 + 右抽屉（**三列 grid 轨道预埋、会话列表 P1 再开**——PRD §4.4 分期）；每轮完整走 §5 的 运行态/完成态/四异常态；历史轮次只渲染计划摘要（**禁止本地伪造完整结果**）。
3. **口径字典页**：**纯只读**（`GET /semantic/metrics` + `/semantic/assets`）；`denied_columns` **不展示**（附录 B-10 默认方案，存在性泄露）。
4. **评测运行列表 + 评测报告页**：数据源 `GET /admin/eval/*`（A.9.2–A.9.4 已齐）；4×3 网格与归因分布**后端已聚合，前端一行聚合代码都不许写**；`scope:"cross_tenant"` 必显提示（A.9.4）；页脚两条合成数据诚实声明照渲染。
5. 路由表按 06 §2.1（含 `/403`/`/404`/`/500`）；移动端只保 §12.3 降级边界；深色模式不做（附录 B-17）。

### T5 · QA 自查与可访问性（DoD④）
- 逐条过 **06 §14.2 QA Checklist**，产出两栏：✅（Mock 可验证，附实测证据）/ 🔴 `BLOCKED（待 W4 联调）`（如实列：真实 SSE 时序、Nginx `proxy_buffering off` 下的流式、真实限流头等）。**禁止用 Mock 冒充 BLOCKED 项通过。**
- 无障碍：§7.2 的 `aria-live` 映射、健康点与倒计时的播报规则（§4.15/§4.9）、灰阶可分性。
- 演示数据最低视觉要求：用 06 §6.9 的 12 条检查你的 mock 数据形状（GMV 不能全 0、饼图不能只剩一条）——**mock 数据也要像真的**，联调后换真数据时同一套检查复跑。

### T6 · 联调交接与交付
1. **给 W4 的联调清单**（写进 RELAY）：你依赖的事件字段与顺序（照 A.1.2 逐事件）、`ack.task_id` 时机、心跳间隔实测要求、`cancel` 端点、CORS（dev 5173 → 8000）、`X-RateLimit-*` 头逐桶下发、`meta.scope` 三级各一例的真实触发路径。
2. **给 W7 的转达**：Nginx `proxy_buffering off` + `proxy_read_timeout 300s` + `try_files` 回退（06 §10.1 第 12 条）——deploy/nginx.conf 归 W7，你只转达不落笔。
3. 交付 `backend/reports/w5/{PROMPT.md(本文件), DELIVERY.md, RELAY.md}`：DELIVERY 含 DoD 逐条达成表（✅/BLOCKED）、门禁实测（`npm run build` 零错、vitest 全绿、eslint 零错）、QA 两栏清单；RELAY 含给 W4/W7/上游三节 + 未决项（D-H、B 系列沿用项）。
4. 提交 `feat(w5)` 系列 + `docs(w5)` 交付件；**未获明确指令不 push**。

## 五、例外与边界

- **只写 `frontend/**`**；`backend/**` 只读（enums.py 类型对齐、auth token 夹具参考）；`deploy/**` 归 W7；`docs/**` 归上游窗口——发现文档问题写 RELAY 转达，不落笔。
- 不引入 D.3 清单之外的重依赖（状态库、UI 库、CSS 框架均不加；确有需要 → RELAY 说明理由待批）。
- 上游若在你们期间更新契约（附录 A v1.6+）：**停下，按 diff 重核 06 引用点再继续**——v1.2→v1.5 的教训是"按摘要改必漏"（上游报 1 处实际 8 处），必须全文 grep 自己的实现。
- 06 附录 B 已登记的默认方案（B-5 静态示例问题、B-10 不展示 denied_columns、B-16 不做角色分叉、B-17 不做深色模式、B-18 移动端边界、B-23 healthz 60s 轮询、B-24 硬依赖失败禁用 AskBox）**直接沿用，不重新决策**；若上游后续推翻，按其裁决改。
- 已知事实勿当 bug 报：**L3+ 问句 50–60s 才返回是既有实测**（W3-INT 收口结论 3），你的超时/加载态设计必须容忍它；**"降级但查询成功"是最常见的降级形态**（换小模型/命中缓存），不是边缘场景。

## 六、给后续窗口的复用说明

本模板骨架（定位/特殊性/纪律/任务清单 T0–T6/例外）与阶段无关。若开 W5-INT 收口或二轮迭代窗口：替换任务清单主体、reports 目录与依赖的裁决号；**"Mock 不得冒充联调通过"与"前端零判断权"两条红线不可协商**。
