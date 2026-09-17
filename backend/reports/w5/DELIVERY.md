# W5 交付件 · 前端窗口（阶段 5 · P0-7 前端）

- 窗口：**W5**（前端，独占 `frontend/**`）
- 交付时间：2026-09-17
- 规范源优先级：**附录 A v1.5（唯一契约源）> PRD > 06 v1.2.2 > 07 > 08**
- 只写两个目录：`frontend/**`、`backend/reports/w5/**`（本次交付未触碰其它目录）

---

## 一、DoD 逐条达成表（依据 08 §3.7）

| # | DoD 原文 | 结论 | 证据 |
|---|---|---|---|
| ① | SSE 跨 chunk 半行缓冲 / 心跳忽略 / **`terminal` 唯一判据** | ✅ | `src/api/queryStream.ts`：跨 chunk 以 `\n\n` 为界 + buffer 残留；`heartbeat` 只 `markAlive` 不驱动 UI；终止判据仅 `data.terminal === true`（**无事件名白名单**），`terminal` 缺失 → 视为 `false` + `[contract] missing_terminal` 告警日志。vitest `src/api/queryStream.test.ts` **15/15 全绿** |
| ② | `truncated` 不被静默丢弃 | ✅ | `data.truncated === true` → `TruncateBar`（C8）必然渲染（结果块上方，§5.3 第 5 段）；`TruncateBar` 文案含「结果不是全量，请勿据此判断总量」 |
| ③ | 前端零判断权（图表类型 / 口径 / 脱敏值全部来自后端） | ✅ | 全量 grep：无 `metric === 'gmv'` 类推断、无脱敏/掩码函数、无单位换算；`chart_type` 未知值 → 降级表格 + `[ui_unknown_chart_type]`；`CHART_TYPE_CN` 仅做中文名映射；评测页 grid/attribution **零聚合**（直接渲染后端 `cells`/`attribution`） |
| ④ | 06 §14.2 的 QA Checklist 全过 | 🔴 **部分 BLOCKED** | 见第三节两栏清单：**A/B(代码部分)/C/E(代码部分)/F(代码部分) 已过**；**D 组（流式体验）与 B 组截图项、G 组截图项需真实后端 / 浏览器手测 → BLOCKED（待 W4 联调）**，未用 Mock 冒充 |

---

## 二、门禁实测（本机实跑，命令与输出均为原文回显）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 类型检查 | `npx tsc --noEmit` | ✅ **exit 0**（`noUnusedLocals`/`noUnusedParameters` 开启） |
| 单测 | `npm test`（vitest run） | ✅ **15 passed / 1 file**（`src/api/queryStream.test.ts`） |
| Lint | `npm run lint`（eslint . --ext .ts,.tsx） | ✅ **0 error / 0 warning** |
| 生产构建 | `npm run build`（`tsc -b && vite build`） | ✅ **exit 0**，3706 modules，产物 `dist/assets/index-*.js 2194.60 kB / gzip 717.06 kB`（Vite 提示 chunk > 500 kB，属已知项，见 RELAY 未决项） |

> 说明：`npm run build` 的 **JS bundle 内含 0 处 msw 引用**（`main.tsx` 中 MSW 为 `import.meta.env.DEV && VITE_ENABLE_MSW==='true'` 双门控 + 动态 `import()`，生产模式下条件常量折叠后被摇掉）。
> ⚠️ 一处如实说明：`dist/` 下**存在** `mockServiceWorker.js`（Vite 原样拷贝 `public/` 目录，是**静态文件拷贝**而非代码引用，grep 命中仅此文件自身）。因 bundle 内无 `worker.start()` 调用，该文件不会被注册、不产生任何 mock 行为；但**产物目录里确实躺着这个文件**，是否需在构建后删除或改到 dev-only 目录，已列 RELAY 供上游/W7 决定。

---

## 三、QA 两栏清单（06 §14.2 逐条）

### ✅ 已过（Mock/代码可验证，附证据）

| 组 | 条目 | 证据 |
|---|---|---|
| A | 语义色取自 §3.2 | 四态/品牌/文本/中性色全部 `tokens.color.*`；无散落语义硬编码（`#fff` 卡面见下方观察项） |
| A | 字号 7 档 / 字重仅 400/500 | `tokens.font.weight` 仅 regular/medium；代码中无第三档字重；`fontSize` 取自 `tokens.font.size.*`（12/13/14/16/20/28） |
| A | 无数值型硬编码色 + 无渐变/发光/彩色投影 | grep 全量 `src/**`：唯一 `linear-gradient` 为骨架屏 `cq-shimmer`（§5.2 明确要求 shimmer），`shadow` 仅 tokens 两档中性投影 |
| A | 数值 `tabular-nums` | 数据表格（C5）、KPI（C5）使用 `.tabular-nums`；见观察项 ② 的范围说明 |
| B | 四态语义色 / 图标 / 头部标签 / aria-live 与 §7.2 一致 | 拒答=中性灰 + `QuestionCircleOutlined` +「系统无法回答这个问题」+ `role=status`；澄清=紫 + `CommentOutlined` +「需要确认一下」+ `role=alert`；降级=琥珀 + `WarningOutlined`（**本次修正：原为 ThunderboltOutlined，不符 §7.2「空心三角惊叹」**）+ `role=status`；错误=红 + `CloseCircleOutlined` +「出错了/已被拦截」+ `role=alert` |
| B | 拒答卡**没有**「重试」按钮 | `RefuseCard` 仅渲染替代问法按钮，无 retry 分支 |
| B | 四态都无「空白无说明」 | 四卡均有头部标签 + 正文 + 动作区；`InsightCard` 空文案、`CaveatBar` 空口径、`ResultBlock` 空结果均有显式文案 |
| C | 无图表/口径推断逻辑 | grep 全量，无 `metric ===` 比较；`chart_type` 只做未知值降级 |
| C | 无脱敏正则 / 掩码函数 | grep 全量 `mask|desensiti|replace(/`，零命中 |
| C | `truncated === true` → `TruncateBar` | `ChatPage.TurnView` 第 5 段以 `data.truncated` 驱动 |
| C | `caveats` 为空 → 提示而非静默 | `CaveatBar`：空 → degraded 行「本次未返回口径说明，数值请谨慎使用」 |
| E | 分母为 0 → `—` | `fmtCell`：非有限数值/`NaN`/`Infinity`/null/空串 → `—`；整列全 null → info 行「该指标在当前条件下无法计算」；含 `NaN` → degraded「数值异常，可能因分母为 0」 |
| E | 未知 `error.code` / 未知 `chart_type` 降级有提示 | `ErrorCard` 27 码映射 + 未知兜底（`KNOWN_ERRORS` Set）；`ResultBlock` 未知 `chart_type` → 表格 + 日志 |
| E | 每张错误卡展示 `trace_id` 且有复制按钮 | `ErrorCard`：强制展示 `trace_id`（monospace）+ 复制按钮 `aria-label="复制错误编号"` |
| E | 空结果不渲染 `ErrorCard`/`RefuseCard` | 空结果走 `EmptyBlock`（「该条件下没有数据」+ 可能原因 + 建议），不进入错误/拒答分支 |
| E | `scope.disclosable===false`/`notice===null` → 不渲染任何范围提示 | `CaveatBar` 的 scope pill 仅当 `disclosable === true && notice !== null` 渲染，且文案逐字取 `notice` |
| E | 全站无「被过滤行数 / 过滤前后差 / 可见比例」 | grep 命中仅 2 处**探测器**（`ChatPage.registerContractWatch`、`CaveatBar.onContractViolation`），二者只记埋点/拦截渲染，**不展示数值** |
| E | 澄清倒计时可注入、超时禁用 + 「重新提问」 | `ClarifyCard` 支持注入 `expiresAt`（测试可传 10s）；≤60s 切 degraded 加粗；归零 → 选项禁用 + 「澄清已超时」+「重新提问」；倒计时 `aria-live="off"`，仅 60s 阈值时 sr-only 播报一次 |
| E | 转异步：`degraded(terminal:false)` → `complete(terminal:true)` → 「后台执行中」卡片 + 3s 轮询 | `ChatPage.startPolling` 3s 轮询至 1h；`AskBox` 转异步期间解锁；**无任何"3 秒内"定时启发式** |
| E | 评测报告页 `cross_tenant` 必显提示 / `draft` 置灰 / 不渲染 SQL | `EvalReportPage`、`EvalRunsPage` 已实现（子代理交付，本次复核通过 grep 与 tsc） |
| E | 健康点三级映射（软依赖 200+degraded=琥珀空心 / 硬依赖 503=红+禁用 AskBox / 断网=灰） | `HealthIndicator`：`role=status` + `aria-live=polite`；只调 `GET /healthz`（**未调用** `/healthz/live|ready`）；llm/embedding 展开明细**分列** |
| F | 图表下方有可切换的数据表 | `ChartCard role="img"` + aria-label，「查看数据表」切换（§13.1 硬要求）；图表渲染失败 → ErrorBoundary 降级为表格 |
| F | `prefers-reduced-motion` 下无动画 | `index.css` 关闭 `cq-breathe`/`cq-skeleton` 并压掉 transition |
| F | 键盘可完成「提问 → 读结果 → 点反馈」 | 全部交互为原生 `button`/antd 组件（无 div+onClick 替代按钮）；`AskBox` Enter 提交、Shift+Enter 换行、↑ 回溯 |
| G | 演示脚本三条路径可复现（成功/澄清/拒答） | MSW 场景可驱动：`successFrames()` / `clarifyFrames` / `refusePiiFrames`、`refuseNoAssetFrames`（场景清单见 `src/mocks/scenarios.md`） |

### 🔴 BLOCKED（未过，如实列出，**未用 Mock 冒充**）

| 组 | 条目 | 阻塞原因 / 归属 |
|---|---|---|
| B | 四态**灰阶截图**两两可分 | 需真实渲染截图 → 需浏览器手测（本窗口无浏览器渲染证据，不臆断通过）；代码侧四态在图标/标签/圆角/布局上均已分化，**颜色之外的差异已具备**，但截图证据**BLOCKED（待 W4 联调）** |
| D | 真实域名下 `SqlCard` 2–3s 先出现（证明 Nginx 未缓冲） | **BLOCKED（待 W7 部署 + W4 真实 SSE）**；已转达 Nginx 配置要求，见 RELAY §二 |
| D | 心跳不引发 UI 变化（DevTools EventStream 观察） | 代码侧已保证（`heartbeat` → 只刷新 `lastEventAt`，无任何渲染分支）；**运行时观察 BLOCKED（待 W4 真实流）** |
| D | 断网 90s 出现「连接异常」+ 发出 `cancel` | 代码侧已实现（看门狗 `NO_EVENT_TIMEOUT_MS=90_000` → `abort` + `POST /query/{task_id}/cancel`）；**真实断网复现 BLOCKED（待 W4）** |
| D | 点停止 → 阶段条「已停止」+ 解锁 + 服务端 cancel（后端日志确认） | UI 侧已实现；**服务端日志确认 BLOCKED（待 W4）** |
| D | 四种 `terminal:true` 事件逐一验证解锁 | 「解锁与终止严格同源」代码已保证（单一 `onTerminal`，非白名单）；**逐事件运行时验证 BLOCKED（待 W4 真实流）** |
| D | 人为构造 `data` 缺 `terminal` 字段 | 已有单测用例（「缺 `terminal` 不终止 + 告警日志」在 15 个用例内）；**真实端点复现 BLOCKED（待 W4）** |
| D | 限流四桶：`read`/`write`/`admin` 不驱动 `QuotaIndicator` | 代码侧只认 `X-RateLimit-Bucket === 'query'`（已有单测）；**真实读口径字典后核对 Header 数字不变 BLOCKED（待 W4/W6）** |
| E | `409 SESSION_CONFLICT` 四项行为（复用同一幂等键 / 不进限流禁用态 / 不喂 Quota / 走 degraded 语义） | 代码侧已实现（重试 1 次 + `Retry-After`，复用同一 `Idempotency-Key`）；⚠️ **一处偏差需上游裁决**：当前 409 自动重试 1 次后仍失败 → 渲染 `ErrorCard(SESSION_CONFLICT)`（degraded 语义色、无倒计时、不喂 Quota）；**联调时需确认这是否满足"走 degraded 语义"** |
| E | `422 EXEC_RESOURCE_EXCEEDED` 文案「已被中止」vs `COST_TOO_HIGH`「未执行」 | `ErrorCard` 已按码给不同主文案与动作；**真实触发 BLOCKED（待 W4）** |
| E | 存在性泄露专项（跨租户空结果 vs 真无数据逐字段不可区分） | MSW 已备两套几乎同形 fixtures（`emptyTenantIsolatedFrames` / `emptyUnrestrictedFrames`）+ `emptyRoleLimitedFrames`；**「逐字段截图比对」BLOCKED（待 W4 真实 RLS + 浏览器）** |
| E | `role_limited` 空结果时 pill 文案与后端 `notice` 逐字一致 | 代码侧逐字渲染 `notice`（不改写、不加语气词）；**真实 `notice` 取值 BLOCKED（待 W4）** |
| E | `truncated` 仅由 `LIMIT` 截断置位（RLS 过滤未触顶→不出现截断条） | 契约侧行为，前端只消费 `truncated`；**BLOCKED（待 W4 构造场景）** |
| F | `axe-core` 扫描 0 critical | 未安装该依赖（**不擅自新增依赖**）→ **BLOCKED**；建议 W5-INT 或联调窗口按批准流程引入 `@axe-core/cli` 或浏览器插件 |
| F | 焦点环可见 | 依赖 antd 默认 `:focus-visible` 样式，**未经运行核对 → BLOCKED（待手测）** |
| G | §6.9 十二条**逐条截图核对** | mock 侧已过最低门槛（见下）；**截图核对本身 BLOCKED（待真实 seed 数据 + 浏览器）** |
| G | 四态在演示脚本中各出现一次 | 场景齐备（含 degraded 成功形态），**运行时截图 BLOCKED** |

---

## 四、QA 观察项（通过但需上游知悉，非阻塞）

| # | 观察 | 说明 |
|---|---|---|
| ① | 卡面白 `#fff` 共 16 处硬编码；`index.css` 骨架屏渐变含 `#f1efe8`/`#faf9f5` | §3.7 色板只定义**语义色**，未定义"卡面/面白/页面底"token（`tokens.ts` 无 surface 项；`#F1EFE8` 与 `neutral.bg` 同值，`#FAF9F5` 无任何对应项）。未擅自扩 token（tokens 为 §3.7 **逐字复制**，加一项即偏离），已列 RELAY 供上游决定是否补 `color.surface` / `color.bg` |
| ② | `tabular-nums` 覆盖范围 | 数据值（表格/KPI）已覆盖；12px 辅助信息行（耗时/成本/任务号）未加该 class（其为元信息非数据值）。若上游要求"所有数字"，一行即可补 |
| ③ | `StageBar` 首事件 3s 提示与 5s 静默提示 | 实现为 `now - lastEventAt > 5000`（`lastEventAt` 含 heartbeat 刷新）——与 §5.2「静默 = 连续 5s 无新事件」一致；`heartbeat` 15s 一次不会误触发 |
| ④ | 澄清有效期起算点 | `clarify` 事件无时间戳字段（A.4），`expiresAt = 前端收到时刻 + 5min`；与服务端 `CLARIFY_EXPIRED` 存在 ±RTT 误差（已在 RELAY 登记） |

## 五、§6.9 十二条对 mock 数据的核对（mock 侧）

> ⚠️ §6.9 的 12 条**责任主体是数据生成脚本（附录 C `seed_generator.py`）**，UI 侧义务是"联调阶段逐条截图核对"。此处只核对 **MSW mock 形状**，**不代替真实数据核对**（已列 BLOCKED）。

| # | mock 表现 | 结论 |
|---|---|---|
| 1 | 成功场景 GMV 数值非零且各区不同（1823.45 万 / 1200.30 万 / 980 万） | ✅ 非全 0 |
| 2–4、6–7、9–12 | 属真实 seed 数据侧（大促尖峰、类目幂律、SKU 长尾、退款率、除零、NULL、租户同构、大额单） | 🔴 **mock 不覆盖，联调核对（待 W4/数据侧）** |
| 5 | 区域 **3 个**（华东/华南/华北），非 7 个大区 | ⚠️ mock 仅 3 类，用于演示柱图与表格；真实数据需 7 大区（已在 RELAY 提醒） |
| 8 | 空结果三套 fixtures（真无数据 / 跨租户隔离 / 角色受限） | ✅ 存在且**结构同形** |
| — | 饼图近似均分 | 无饼图 mock（不构成"一眼假"风险；真实数据需满足 ≤8 分类且分布不均） |
| — | 「Top-N 表格」重复名 / 并列金额 | mock 表数据为 3 行地区 GMV，无重复名 |

**结论**：mock 侧**无"GMV 全 0""饼图只剩一条""分类数 < 3"** 这类一眼假画面；§6.9 中依赖真实数据分布的条目**未验证、已列 BLOCKED**。

---

## 六、本次交付的代码边界（自查）

- 写入目录：`frontend/**`（新增 `src/components/*`、`src/pages/*`、`src/api/client.ts`、`src/store/chatStore.ts`、`src/utils/analytics.ts`、`App.tsx`、`main.tsx` 局部）与 `backend/reports/w5/**`（本文件）。
- **未改动**：`docs/**`（只读）、`deploy/**`（归 W7）、`backend/app/**`（只读）、`package.json` 依赖集合（**未新增任何依赖**）。
- 未 push（按纪律：**未获明确指令不 push**）。
- 未做的分期项（显式声明，非疏漏）：`SessionRail` 左栏（P1，**三列 grid 轨道已预埋**、宽 0）、`/admin/audit`（P1）、`/settings`（P1）、深色模式（B-17）、移动端仅保 §12.3 降级边界（B-18）、角色分叉（B-16）。