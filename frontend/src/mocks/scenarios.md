# MSW Mock 场景清单（T1）

> Mock 只存在于 MSW 层（`src/mocks/**`），由 `VITE_ENABLE_MSW=true` + `import.meta.env.DEV` 双重门控，
> 生产构建产物不含 mock 代码。所有端点严格来自附录 A 契约，不 mock 契约外端点。

## 触发方式

- 默认按 `question` 关键词匹配（见下表）
- 测试/调试可用请求头 `X-Mock-Scenario: <场景名>` 强制指定

## POST /api/v1/query（SSE）场景

| 场景名 | 触发关键词 | 覆盖点 | 语义色 |
|---|---|---|---|
| `success`（默认） | 任意其他问题 | 成功全链 ack→stage×6→data→chart→insight→meta→complete；meta.scope=role_limited 带中性提示 | — |
| `clarify` | 含「城市」 | 澄清事件（terminal:true），options 含 asset 绑定 | 紫 |
| `refuse_no_data_asset` | 含「竞品」 | 拒答 no_data_asset + suggestions | 灰 |
| `refuse_pii` | 含「手机号/身份证」 | 拒答 pii_blocked | 灰 |
| `error_gate_ast` | 含「非法表」 | error GATE_AST_REJECTED（retryable:false） | 红 |
| `degraded_success` | 含「降级」 | degraded(cost_too_high/reduced_candidates, terminal:false) 后流继续至 complete | 琥珀 |
| `switched_to_async` | 含「转异步/慢查询」 | degraded(switched_to_async, terminal:false, 带 poll_url) → complete(terminal:true) | 琥珀 |
| `session_conflict` | 含「409」 | HTTP 409 + `Retry-After: 3`，**无** X-RateLimit-* 头 | — |
| `rate_limited` | 含「429」 | HTTP 429 + query 桶限流头 + `Retry-After: 30` | — |
| `empty_role_limited` | 含「空结果」 | 0 行 + scope=role_limited（notice 非空） | — |
| `empty_tenant_isolated` | 含「跨租户」 | 0 行 + scope=tenant_isolated（**notice=null，disclosable=false**） | — |
| `empty_unrestricted` | 含「无限制空」 | 0 行 + scope=unrestricted | — |

正常 SSE 响应统一携带 `X-RateLimit-Bucket: query` 系列头，供 QuotaIndicator 消费。

## 其他端点

| 端点 | Mock 行为 |
|---|---|
| `POST /clarify` | 返回成功全链 SSE（澄清后重新走完整链路） |
| `GET /query/{task_id}` | 第 1 次 `processing`，第 2 次起 `complete`（含 sql/data/chart/insight/meta/audit_ref） |
| `POST /query/{task_id}/cancel` | 返回 `cancelled` |
| `POST /session` / `GET /sessions` / `GET /session/{id}` / `DELETE /session/{id}` | 会话 CRUD（turns 只含 plan_summary，不含 SQL） |
| `POST /feedback` | 返回 `queued_for_review: true` |
| `GET /semantic/metrics` / `GET /semantic/assets` | 口径字典数据（assets 含 denied_columns，但字典页不得展示） |
| `GET /healthz` | `status: ok`，全部依赖可达 |
| `GET /admin/eval/datasets` | 1 frozen + 1 draft（draft 前端置灰） |
| `GET /admin/eval/runs` | 列表含 headline 摘要 |
| `GET /admin/eval/runs/{id}` | 完整聚合（grid.cells / attribution / gate.items 均为后端聚合结果）+ `scope: "cross_tenant"` |
| `POST /admin/eval/run` | 返回 `queued` |

## 未覆盖（故意）

- `heartbeat` 帧的真实 15s 间隔 —— 由 T2 单测以假定时器覆盖
- 90s 无事件超时 —— 由 T2 单测覆盖
- 登录/鉴权端点 —— 契约无登录端点，登录页为 stub（D-H 待裁决）
