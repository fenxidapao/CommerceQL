# W5 RELAY · 转达与联调交接（前端窗口 → W4 / W7 / 上游）

- 窗口：**W5**（前端，独占 `frontend/**`）
- 日期：2026-09-17
- 阅读顺序：**§一 给 W4（联调必读）** → §二 给 W7（部署必读） → §三 给上游（未决项与裁决请求）
- 本文件只做转达：`deploy/**`、`docs/**`、`backend/app/**` 均**未落笔**。

---

## 一、给 W4（编排/SSE 端点）—— 联调清单

### 1.1 前端依赖的事件与字段（照 A.1.2，逐事件）

| 事件 | 前端消费的字段 | 前端动作（时序敏感） |
|---|---|---|
| `ack` | `task_id`（必需）、`session_id` | **`task_id` 必须在首帧尽快给**：用户点「停止」与 90s 看门狗超时都要用它调 `POST /query/{task_id}/cancel`；转异步后还用它轮询 |
| `stage` | `stage`、`elapsed_ms`、`plan_summary?`、`candidates_count?` | 追加语义（追加而非替换）；`stage=sql_ready` → **立即渲染 `SqlCard`，不等 `data`**（A.14#7） |
| `data` | `columns[].{name,type}`、`rows`、`row_count`、`truncated` | `truncated===true` 必渲染截断条；⚠️ **`filtered_rows` 等间接量前端一律不渲染**（A.1.5 红线 1，前端有探测器会记 `ui_contract_violation`） |
| `chart` | `chart_type`、`option`、`meta?` | `option` 里**不得出现函数字符串**（A.10）；前端会把 `option` 直接交给 ECharts |
| `insight` | `text`、`caveats[]`、`citations[]` | 前端对 `text` 做**格式降级**：命中 `因为…所以/导致/带动了/预计/下周将/是因为` → 展示「结论格式异常，请以数据为准」（合同要求前端拦截因果/预测措辞，请后端也确保合规） |
| `meta` | `latency_ms`、`cost_cny`、`bundle_version`、`trace_id`、`scope{level,disclosable,notice}` | `scope` 仅当 `disclosable===true && notice!==null` 才原样渲染（一字不改） |
| `degraded` | `reason`、`action_taken`、`partial_result?`、`task_id?`、`poll_url?`、`terminal` | **`degraded` 恒 `terminal:false`**：前端只加一条 Inline 条，**不停止阶段条**；`switched_to_async` 由随后的 `complete` 收尾 |
| `complete` | `terminal:true` | 流结束（前端解锁 `AskBox`）；若此前有 `action_taken=switched_to_async` → 就地升级为「后台执行中」卡片并启动 3s 轮询 |
| `clarify` | `clarify_id`、`question`、`options[]`、`reason`、`terminal` | 终态事件；用户选择后前端**新开一条 `POST /clarify` 流**（不是续原流）。选项 ≤4（超出前端记 `[ui_clarify_options_overflow]`） |
| `refuse` | `reason`、`message`、`suggestions[]` | 终态；前端**不给「重试」按钮**（§7.2），`suggestions` 可点击回填提问框 |
| `error` | `code`、`message`、`detail?`、`retryable` | 终态。⚠️ **`detail` 仅应在 `role ∈ {analyst, platform_admin}` 时返回**：前端 P0 无角色来源（无 `/me`，见 §三 D-H），**一律不展示 `detail`**（安全默认）。请后端保证不下发给无权角色 |
| `heartbeat` | 只需按 15s 送达 | **不驱动任何 UI 变化**（前端仅用于重置 90s 看门狗）。⚠️ 实测要求：**SSE 必须能撑 60s+ 不断流**（W3-INT 结论：L3+ 问句 50–60s 才返回） |

**顺序约束（前端侧的硬假设）**
1. 前端**不要求后端攒批**：收到 `data` 即可渲染结果块，`chart`/`insight` 后到再插入 —— 请保持"尽早发"的流式特性（这也是判定 Nginx 未缓冲的唯一手段）。
2. `stage` 的 6 个取值前端只映射中文段名，**不暴露内部节点名**；请严格只发 6 值（enums.py `Stage` 已锁）。
3. `terminal` 只能在 `complete`/`clarify`/`refuse`/`error` 上为 `true`，其余恒 `false`（**前端不按事件名白名单判断**，但契约仍需成立）。
4. **缺失 `terminal` 字段**：前端按 `false` 处理并打告警日志（不终止）→ 若因此出现"流不结束"，请优先查该字段是否漏发。

### 1.2 端点与状态取值

| 端点 | 前端用法 | 需 W4 确认 |
|---|---|---|
| `POST /query` | `Accept: text/event-stream`，body 见 A.1.1（前端恒传 `explain:true`、`chart_preference:'auto'`、`max_rows≤5000`、`allow_clarify:true`、`timezone:'Asia/Shanghai'`；**`max_candidates` 不传**，由后端决定） | — |
| `POST /query/{task_id}/cancel` | 90s 看门狗超时 / 用户点「停止」时调用 | 幂等：重复 cancel 不应 5xx（`TASK_NOT_CANCELLABLE` 属预期错误码，前端有专门中性文案） |
| `GET /query/{task_id}` | 转异步后 3s 轮询至 1h；标签页隐藏时暂停 | ⚠️ **状态取值两源不一致（必须裁决，见 §三-2）**：附录A A.2 = `queued/processing/complete/...`，`backend/app/core/enums.py::TaskStatus` = `pending/running/succeeded/...`。前端**按附录A实现**；若后端实发 `succeeded`/`refuse`，前端会当作"非终态"**继续轮询到 1h**（不会崩，但结果是空等） |
| `POST /session` | 首次提问前创建；**失败则阻止提问**（不降级本地会话） | 返回 `session_id` 即可 |
| `GET /session/{id}` | 刷新/切换会话时拉历史；**前端只渲染计划摘要** | 404 → `SESSION_NOT_FOUND`；前端渲染「该会话不存在或已删除」+「开始新会话」 |
| `POST /clarify` | 澄清应答（新流） | `selected_value` 与 `free_text` 二选一；`CLARIFY_INVALID_OPTION` 时前端**保留澄清卡**并 inline 报错 |
| `POST /feedback` | `{task_id, is_correct, reason_code?, comment?}` | `reason_code` 为 10 值枚举（与 `FeedbackReasonCode` 一致）；`REASON_TEXT` 前端有业务化文案映射 |
| `GET /healthz` | 60s 轮询（页面隐藏时暂停） | 软依赖失败请返回 **200 + `status:"degraded"`**（前端=琥珀空心点）；硬依赖失败 **503**（红点 + 禁用 AskBox）；**前端不调用** `/healthz/live|ready` |
| `GET /semantic/metrics`、`/semantic/assets` | 口径字典页（只读） | ⚠️ 附录A 只声明 `items/total`，前端按 `Paged<T>` 兼容（**只用 `items`/`total`**）；分页字段请确认 |
| `GET /admin/eval/{datasets,runs,runs/{id}}` | 评测列表/报告 | `grid.cells[].target` 在 `extra_hard` 行可能为 `null` → 前端已按 `number \| null` 兼容；`cases` 默认不拉（`include_cases=true&case_filter=failed` 才拉），且**A.9.4 `cases` 不含 SQL 文本** |

### 1.3 **CORS（dev 5173 → 8000）—— 最容易漏的两类头**

前端会发的**非 CORS 安全列表**请求头，必须在 `Access-Control-Allow-Headers` 放行：
- `Authorization`
- `Idempotency-Key`（A.12 必需）
- `X-Trace-Id`
- `Accept: text/event-stream`（`Accept` 属安全列表，但值含 `text/event-stream` 时个别网关会拦，联调时留意）

前端需要**读到**的响应头，必须在 `Access-Control-Expose-Headers` 暴露（否则跨源下 `headers.get()` 恒为 `null`，限流指示器等于失效）：
- `X-RateLimit-Bucket` / `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`
- `Retry-After`（`409 SESSION_CONFLICT` 的自动重试用；读不到时前端回退默认 3s）

### 1.4 限流（逐桶）

- 前端**只认 `X-RateLimit-Bucket === 'query'`** 喂 `QuotaIndicator`；`read`/`write`/`admin` 桶即使下发也**不更新** Header 数字（§4.14/§10.6 QA 项）。
- 请**逐桶都下发** `-Limit/-Remaining/-Reset`（缺失或非数字时前端静默忽略该次信息，不报错）。
- `409 SESSION_CONFLICT` 响应**不要带** `X-RateLimit-*`（前端据此保证不进限流禁用态；带了也不会用，但会让联调判定困难）。

### 1.5 `meta.scope` 三级各一例的真实触发路径（联调需要）

| `level` | 期望触发路径（请 W4 提供可复现问句或夹具） | 前端期望的字段组合 |
|---|---|---|
| `unrestricted` 或最高可见档 | 平台管理员/分析师问自己全可见的指标 | `disclosable` 与 `notice` 的组合**请给两例**：① `disclosable=true, notice!=null`（前端渲染 pill）② `disclosable=false` 或 `notice=null`（前端**不渲染任何范围提示**） |
| `role_limited` | 运营角色问超出其行权限的时间区间，且结果为空 | `notice` 文案由后端定：前端**逐字渲染**，不改写/不加语气词 |
| `tenant_isolated` 或跨租户档 | 用 T_B 的账号问 T_A 专属口径 | **存在性泄露专项**：`tenant_isolated` 空结果与"真无数据"空结果，前端渲染路径**完全相同**（文案/图标/颜色/按钮/布局），需后端保证 `message` 与 `suggestions` 也同形 |

### 1.6 联调时请一并确认的既有约定

- **幂等键**：同一会话 + 同一问题复用同一 `Idempotency-Key`（改问题换新键）；`SESSION_CONFLICT` 重试**复用同键**（A.12）。若后端对"同键不同 body"返回 `IDEMPOTENCY_CONFLICT`，前端会**静默忽略该错误码**（不弹卡）。
- **多响应域**：`2xx 但 code !== 'OK'` 前端按错误处理 → 请保持 `code` 语义一致。
- **`_raw` 容错**：单事件 JSON 解析失败时前端**不终止流**（降级为忽略该事件）；若联调中出现"事件丢失但流继续"，请先查事件体是否合法 JSON。

---

## 二、给 W7（部署/Nginx）—— 转达（`deploy/**` 归 W7，W5 不落笔）

### 2.1 SSE 必配（附录 A §A.13，06 §10.1 第 12 条）

```nginx
proxy_buffering off;              # 必须关闭：否则 SSE 被攒批，前端看不到流式进度
proxy_cache off;
proxy_read_timeout 300s;          # SSE 连接最长 5 分钟（A.13）
proxy_set_header Connection '';
chunked_transfer_encoding on;
```

补充建议：
- **`gzip` 不要作用于 `text/event-stream`**（压缩+缓冲会放大"攒批"现象）；如启用 gzip，请对 `text/event-stream` 排除。
- 应用侧若返回 `X-Accel-Buffering: no` 亦可，但**不能替代** `proxy_buffering off`。

### 2.2 SPA 路由回退（前端为 History 模式）

- 需要 `try_files $uri $uri/ /index.html;`：深链 `/chat/{session_id}`、`/eval/reports/{run_id}`、`/403`、`/404`、`/500` 刷新时必须回退到 `index.html`（否则 Nginx 直接 404）。
- `index.html` 建议 `Cache-Control: no-cache`（带 hash 的 `assets/*` 可长缓存）。

### 2.3 环境变量（05 §D.3）

- 生产构建：`VITE_API_BASE_URL=/api`（相对路径，同源）；`VITE_APP_ENV=prod`；`VITE_ENABLE_DEBUG_PANEL=false`。
- 前端代码固定拼 `${VITE_API_BASE_URL}/api/v1`，**不要**把 `/api/v1` 再写进变量值。
- **`VITE_*` 会被编译进静态产物 → 禁放任何密钥**（红线）。
- ⚠️ 本窗口另用到一个开发态开关 `VITE_ENABLE_MSW`（**仅 `DEV` 且为 `'true'` 时**才动态 `import()` MSW；生产构建产物不含 mock 代码）。05 §D.3 只登记了 3 个 `VITE_*`，请 04/05 侧按需补登（已列 §三-8）。

### 2.4 部署后自检（判定 Nginx 是否在缓冲）

```bash
curl -N -H 'Accept: text/event-stream' -X POST "$HOST/api/v1/query" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: probe-1' \
  -d '{"question":"上个月华东区 GMV","options":{"explain":true}}'
```
逐条事件**应立即逐行打印**（不是最后一起出现）；差异过大即 `proxy_buffering` 未关。

### 2.5 产物目录里的 `mockServiceWorker.js`（如实说明）

- 实测：`npm run build` 后 `dist/` **含** `mockServiceWorker.js` —— 这是 Vite 原样拷贝 `public/` 目录所致（**静态文件拷贝**，非代码引用；grep 全量产物，msw 相关内容仅命中该文件自身，主 bundle 为 0）。
- 影响面：**无功能影响** —— bundle 内不存在 `worker.start()` 调用（MSW 走 `import.meta.env.DEV` 双门控 + 动态 `import()`），该文件不会被注册、不代理任何请求。
- 若安全/合规上要求产物目录"零 mock 痕迹"，两种做法：① 部署时删掉 `dist/mockServiceWorker.js`；② 由 W5-INT 加构建后清理步骤（**本窗口未擅自改动 `vite.config.ts` 的 `publicDir` 策略**，因 `public/` 目录还承载 favicon 等资源）。已列 §三-13 请上游定调。

---

## 三、给上游（未决项 / 裁决请求）

| # | 事项 | W5 现状（未擅自扩权） | 请求 |
|---|---|---|---|
| 1 | **D-H 登录端点未裁决** | `/login` 为壳（OIDC 重定向形态 + 「登录方式待架构裁决（D-H）」提示）；本地 stub token 入口仅在 `VITE_ENABLE_DEBUG_PANEL==='true'` 时可见；token 只放内存 | 裁决后 W5-INT 接真实流程；**DELIVERY 已标 BLOCKED** |
| 2 | **`AsyncTaskStatus` 两源不一致** | 附录A A.2：`queued/processing/complete/clarify/refused/failed/cancelled/degraded`；`backend/app/core/enums.py::TaskStatus`：`pending/running/succeeded/clarify/refuse/degraded/failed/cancelled`。前端**按附录A**实现（唯一契约源优先），差异写在 `types.ts` 注释 | **请裁决唯一取值集**（否则后端若发 `succeeded`，前端会空转轮询到 1h） |
| 3 | **`KpiCard` 同环比无字段来源** | 契约 `chart.meta` 无 `compare` 数值字段 → 组件仅保留**可选 prop 未接线**（不凭空造数） | 若要展示同环比，请补契约字段 |
| 4 | **抽屉里指标 `definition_note` 未拉取** | 需 A.7.1（按指标）→ 结果为 N 个指标即 N 次请求（N+1）。**为避免 N+1，抽屉用链接跳口径字典页**，并在抽屉内注明原因 | 确认该取舍，或提供批量端点 |
| 5 | **§5.1 空状态底部「数据范围：{当前租户店铺} ｜ 数据截至 {新鲜度}」无契约来源** | 全量检索附录A/附录B：**无**租户店铺名与数据新鲜度端点字段（`semantic/assets.freshness_sla` 是 SLA 不是"数据截至"）。现渲染**不含数值的边界声明**：「数据范围：本租户（店铺级隔离）｜ 数据截至时间以每次结果的口径条为准」 | 请裁决：① 新增端点/字段 ② 或修订 06 §5.1 文案（**QA 已记 BLOCKED，未用假值顶替**） |
| 6 | **§2.5 隐私立场 vs §4.11 刷新恢复** | §4.11 要求"用 `sessionStorage` 记录未完成 `task_id` 并恢复轮询"（已实现，最长跨 1 次刷新）；为渲染用户气泡，该记录**含提问原文**（仅当前标签页、刷新后单次消费、完成即清除） | 确认是否允许存提问原文；若不允许，请给出"恢复轮询但不落提问原文"的期望交互 |
| 7 | **`409 SESSION_CONFLICT` 的 UI 语义** | 已实现：自动重试 1 次（复用同键、`Retry-After`）、**不进限流禁用态**、**不喂 `QuotaIndicator`**；重试后仍失败 → 渲染**错误卡**（但语义色=`degraded` 琥珀、无倒计时） | §14.2 要求"走 `degraded` 语义"：请确认"降级语义色的错误卡"是否满足，还是要求做成 Inline 降级条 |
| 8 | **`VITE_ENABLE_MSW` 未登记** | 开发态专用（生产构建不含）；05 §D.3 只登记 3 个 `VITE_*` | 请补登 |
| 9 | **`axe-core` 未纳入依赖** | §14.2-F 要求 axe 扫描 0 critical；D.3 清单无该依赖，W5 **不擅自新增** | 批准依赖或改由联调窗口以浏览器插件完成（**QA 已记 BLOCKED**） |
| 10 | **`#fff` 卡面白 / 页面底 `#FAF9F5` 无 token** | §3.2 语义色板只定义语义色，`tokens.ts`（§3.7 逐字复制）无 surface/bg 项；代码中 `#fff` 16 处，`index.css` 骨架屏渐变另有 `#f1efe8`（与 `neutral.bg` 同值）与 `#faf9f5`（**无对应项**） | 建议补 `color.surface` / `color.bg`；W5 未擅自扩 token |
| 11 | **`scope` 间接量探测器** | 前端**主动探测** `meta.scope` 与 `data` 中的 `filtered_rows/total_before/visible_ratio/hidden_count`，命中即不上屏 + 记 `ui_contract_violation`（A.1.5 红线 1 的防线） | 若后端另有"间接量"字段名，请补充清单 |
| 12 | **B 系列沿用项已执行** | B-5 静态示例 5 条、B-10 不展示 `denied_columns`、B-16 不做角色分叉、B-17 不做深色模式、B-18 移动端仅保 §12.3、B-23 healthz 60s、B-24 硬依赖失败禁用 AskBox | 如上游推翻请书面裁决，W5 按裁决改 |
| 13 | **构建产物含 `mockServiceWorker.js`（`public/` 静态拷贝）** | 无功能影响（bundle 内 0 处 msw 引用，不会注册）；但产物目录确实存在该文件，详见 §二-2.5 | 请定调：① 部署时删除 ② 或由 W5-INT 加构建后清理 ③ 或认可现状 |

---

## 四、给 W5-INT / 二轮迭代的接口

- **T5 遗留**：`axe-core`、灰阶截图、D 组流式运行时项（见 `DELIVERY.md` §三 🔴 栏）。
- **联调起手式**：`VITE_ENABLE_MSW=false` + 后端 8000 up → 前端 5173，先跑 §2.4 的 curl 自检，再走 `DELIVERY.md` §三 🔴 栏逐条销项。
- **两条不可协商的红线**（沿用）：**Mock 不得冒充联调通过**、**前端零判断权**。