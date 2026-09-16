# W2-INT RELAY —— 逐窗口回执 + 裁决上呈 + 下一阶段提示词

> 日期：2026-09-16 ｜ 窗口：W2-INT（收口）｜ 配套：`reports/w2-int/DELIVERY.md`
> 用法：每节一个收件人，整块可粘贴。

---

## §1 逐窗口回执

### → W2A（app/semantics）：三项接线请求全部收口 ✅

> W2A：你的 RELAY §1 三项已由收口窗口落地并实测：
> ① `startup_assertions` 已注入 `validate_bundle_path`（组装根闭包注入，repo 层零新依赖，R-DEP-1 实测仍 3 kept）——启动断言实测 PASS；
> ② `semantic_bundle_loaded` 探针已注册，**/healthz/ready 实测 200**、`bundle_version=2026.09.14.1`；
> ③ 0002 已核验在 versions/ 目录（compose/CI 无迁移步骤是 W0 缺口，与你的交付无关）。
> 六步演练：materialize 197 docs 复现、指针切换/回滚 PASS；`with_policy=True` 如预期 BLOCKED 在 `UndefinedTable: v_order_paid`（U-55/56，证据已在 DELIVERY §5 留档）。tokenizer 注入点（`materialize(..., tokenizer=...)`）等你与 W2B 的 U-54 裁决后接。

### → W2B（app/retrieval）：lint 债回执（不阻断，但 CI 先行会挂）

> 全仓 `ruff check .` 34 条中 15 条在你窗口（含 `reports/w2b/recall_report.py` 4 条）；`mypy app` 22 条中 1 条在 `app/retrieval/dense.py:273`（`Mapping` 未导入——W2D 转达属实，`__future__ annotations` 下不炸运行时但 ruff F821/mypy name-defined 必红）。清单已在 DELIVERY §4，请自行收口。另：全量 pytest 你的范围 0 failed（dense 断言债已解）；4 个 `--check` 未挂 CI 归 W0。

### → W2C（app/guard）：lint/类型债回执 + U-64 已上呈

> `ruff` 34 条中 8 条在 `app/guard/**`（UP035×4 / RUF034×2 / UP037 / RUF100）；`mypy app` 22 条中 19 条在 guard（ast_gate 15 / cost_gate 4）。全部为 lint/类型级，行为未动，清单见 DELIVERY §4，请自行收口。你的 U-62/63/64 已合并进裁决上呈单（RELAY §2），W2A 三号（U-54~56）未与你撞号。

### → W2D（app/exec/mask）：交付确认 + 两件事

> ① 你的 91 条测试全量复跑通过；executor/mask 的 ruff/mypy 在全仓扫描中 0 归属——债务归属核对（W2B/W2C）与你 DELIVERY §5 的判断一致。
> ② **你的代码当前 untracked 未提交**。收口基于工作区实测（结论有效），但你提交后建议通知收口窗口重跑门禁复核一次。
> ③ 你给 W4 的装配说明已列入接线总表（DELIVERY §3.1#4），阶段 4 移交。

### → W0：两条部署面缺口（你的归属，未越权修）

> 1. `deploy/docker-compose.yml` 与 `.github/workflows/ci.yml` **无 alembic 步骤**——迁移链是手动的，"迁移先于 api"（07 §18.2）无机器保证；0002 已在 versions/ 会被 `upgrade head` 纳入。
> 2. api 服务**未挂载 `../semantic`** → 容器内 `/semantic/bundle_2026.09.14.1.yaml` 不存在，bundle 在容器内永远加载失败（readiness 持续 503）。
> 3. `deploy/.env` 含行内注释（`KEY=value  # 注释`），compose env_file 与 pydantic-settings 实测都会把注释并进值（本机 Settings 校验 15 项报错）。
> 另：W2B 的 importlinter 新契约提案（retrieval 禁 LLM + httpx 例外）待你落笔 `.importlinter`。

---

## §2 裁决上呈（→ 架构窗口，单一文档；编号占用现状已附，未替你选方案）

> **阶段 2 收口窗口裁决请求汇总**（去重合并，共 9 条；终局以 07 §4.8 登记为准）
>
> 编号占用现状：U-01~53 已用；W2A 已提案 **U-54/55/56**（`reports/w2a/RELAY.md §5`）；W2B 候选 U-58~61（`reports/w2b/RELAY.md §5`）；W2C 已定 **U-62/63/64**（两次让号后，`reports/w2c/RELAY.md §1`）。下一可用号 = U-65。
>
> | 号 | 主题 | 选项摘要 | 裁决影响面 |
> |---|---|---|---|
> | U-54 | TokenizerPort 落点（合并 W2B 候选 U-58，同一件事） | (a) 契约在 contracts、实例由装配根注入两侧（W2A/W2B 均倾向）；(b) tokenizer 移 L1 | W2A/W2B/W0 |
> | U-55 | RLS 不适用于 v_* 视图（PG WrongObjectType 实测） | (a) RLS 落基表视图透传；(b) security_invoker 视图+基表 RLS；(c) 放弃 DB 侧 RLS 走执行层注入 | W2A/W4/W6，安全语义与审计面不同 |
> | U-56 | v_* 业务视图 PG 侧 DDL 归属（compose init / 迁移 / 数据窗口） | 归属不明 → GRANT/一致性检查无对象可比 | W2A/W0 |
> | U-59 | CandidateRef 装不下列级富结果 | 端口面升级 vs 维持 search_full 旁路 | W0/W3B/W3C |
> | U-60 | `tenant_id='*'` 公共哨兵未契约化 | 07 §12.2 回填 | W2A/W2B/架构 |
> | U-61 | to_tsquery 需显式 `&` | 07 §6.4 举例更正（若有空格形态） | 架构 |
> | U-62 | GuardPort 缺改写类出参通道 | (a) W4 直接调 run_gate1 模块函数；(b) 扩 GuardPort | W0/W4 |
> | U-63 | gate3 EXPLAIN 执行归编排层 | 确认"W4 gate3_cost 节点跑 EXPLAIN 传计划 JSON"为正式契约 | W4 |
> | U-64 | 红队冻结集 vs 07 §7.2/§7.3 六处口径冲突（LIMIT ALL / SET 消歧×2 / JOIN 归因 / R14 vs R17 / RT-LIM-003 deny-execute 互斥） | 红队集是 DoD① 基准且冻结；若裁定反向，改动集中在 ast_gate.py | W1A/W4/W6 |
>
> **阻塞提醒**：U-55+U-56 不裁决，`materialize(with_policy=True)` 永远 BLOCKED（实测 UndefinedTable），DoD③ 端到端无法收口，语义包无法从 candidate 转正式发布——这不是写代码能解决的。

---

## §3 给下一阶段的提示词（阶段 3 收口模板复用）

> 开阶段 3 收口窗口（W3-INT）时，以 `backend/reports/w2-int/PROMPT.md` 为骨架，替换以下变量：
> 1. 四包归属：W2A/W2B/W2C/W2D → **W3A（llm）/W3B（planner）/W3C（binding）**（+ 阶段 3 新增窗口以 08 §4 计划为准）；
> 2. reports 目录：`backend/reports/{w2a,w2b,w2c,w2d}` → `{w3a,w3b,w3c}`；
> 3. 依赖的裁决号：U-54~64 中**已裁决**的号从"裁决类"移入"前置事实"；未裁决的继续上呈并标注升级；
> 4. 迁移名：0002 之后若有 0003+，同样核验"versions/ 在位 + 本机执行 + compose/CI 缺口"三态；
> 5. 接线三件套语义不变：启动断言注入 / readiness 探针 / 迁移链——探针注册表此时应只剩 LLM/embedding（W7）未接线；
> 6. 红线不变：收口窗口永远不做功能开发；"能修的修"以归属权为界（本窗口实际执行口径：只修自己接线文件引入的红，其余走 RELAY 回执）。

---

## §4 给 W7 的一句话

语义包探针/断言已接，探针注册表剩 `llm`/`embedding` 两槽（软依赖）；`event_loop_lag_ms` 采样器、embedding 回填（索引已建）、探针边界日志（repo/health.py 已登记缺口）仍归你。
