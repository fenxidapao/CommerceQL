# W3A 交付 —— 阶段 3 · LLM 网关（`app/llm/**`）

> 窗口：W3A｜日期：2026-09-17｜分支 `main`｜提交：`feat(w3a)` + `docs(w3a)`（见 §11）
> 依据：`reports/w3a/PROMPT.md`（T0–T6）｜规格：07 §10 全章、§14.2/§14.4.1、§16.1/§16.2、PRD §12.1–§12.3

---

## 1. 交付范围

| 文件 | 行 | 说明 |
|---|---:|---|
| `app/llm/egress_guard.py` | 473 | **N-12 出站白名单**（T1）：受控 dataclass + 三道防线 + 唯一请求体构造点 |
| `app/llm/errors.py` | 231 | 14 个本包独占异常 + `DEGRADABLE_LLM_ERRORS`（F2/F3 刻意不在内） |
| `app/llm/router.py` | 259 | **任务→(模型档,思考位,超时,输出规格) 唯一路由表**（T3/Q4） |
| `app/llm/budget.py` | 486 | 成本计量 + 双层预算熔断 + token 估算（T4） |
| `app/llm/client.py` | 423 | 出站客户端：并发信号量/退避/熔断/超时/解析（T3） |
| `app/llm/prompts/loader.py` + `__init__.py` | 312 | 版本化 prompt 加载器 + 前缀缓存四条硬规则的**加载期**校验（T2） |
| `app/llm/prompts/*_v1.txt` × 10 | 421 | 10 个 task 各一份资产（07 §10.3 `{name}_v{n}.txt`） |
| `app/llm/__init__.py` | 600 | **门面 = `LLMPort` 实现**（T5）：编排 + 降级链 + 两条侧信道 |
| `tests/unit/test_llm_*.py` × 6 + `_llm_fake_upstream.py` | — | **228** 条单测，**全离线** |

测试分布：`egress_guard 38`／`prompts 28`／`router 34`／`budget 51`／`client 33`／`gateway 44`。

**未落笔**（属他人范围，只出需求）：`app/core/**`、`app/cache/keys.py`、`app/repo/**`+migrations、`pyproject.toml`、`.importlinter`、`.github/**`、`app/obs/**`、`graph/**`、`api/**`。

---

## 2. DoD 逐条对照（08 §3.5 ①–⑤）

| # | 要求 | 实现落点 | 断言（可核对的测试名） |
|---|---|---|---|
| ① | 按模型 `asyncio.Semaphore`（**并发非 QPS**） | `client.py` `_acquire/_release`：**全局位 AND 按模型位**，两级 20s 等待上限 | `test_global_cap_limits_in_flight_requests`（6 并发 → 观测峰值恰 2）／`test_per_model_cap_is_applied_independently`（flash/pro 各 1 位 → 峰值 2，证明不是共用一个池）／`test_waiting_too_long_for_a_slot_is_saturation`（没拿到位 → 请求根本没发） |
| ② | 退避 / 熔断 / 预算熔断 | `client.py` 0.5/1/2s+jitter、5 次开路 30s、半开 1 探测；`budget.py` 80% 告警 / 100% 硬熔断 | `test_backoff_follows_the_documented_schedule_with_jitter`／`test_backoff_has_jitter_not_a_fixed_delay`／`test_circuit_opens_after_the_configured_failures`（开路期间 `sent` 不增）／`test_half_open_admits_exactly_one_probe`／`test_fuse_skips_every_model_call_and_goes_straight_to_template`（`sent == 0`）／`test_boundary_is_inclusive_ge_not_gt` |
| ③ | **出站白名单：录制 payload 不含任何明细键与值** | `egress_guard.py` 三道防线 + `build_wire_request` 为唯一构造点 | **`test_llm_gateway.py::TestOutboundAttachment`**：抓 `httpx.Request.content` 原始字节 → `set(body) == {model, messages, max_tokens, temperature, response_format, thinking}`（⊆ `ALLOWED_WIRE_KEYS`）；`test_user_scope_goes_only_to_the_user_parameter_never_into_messages`；`test_identity_context_never_reaches_the_wire`；`test_api_key_never_appears_in_the_body`。构造侧 38 条见 `test_llm_egress_guard.py`（含注入→必红→还原→必绿） |
| ④ | 前缀缓存布局（稳定内容前置） | `loader.py`：`=== SYSTEM ===`/`=== USER ===` 分段；`STABLE_PREFIX_VARS` 白名单在**加载期**校验；`history_block` 不在白名单 | `test_different_questions_share_the_same_prefix`（不同问题+不同 few-shot → 前缀哈希必须相同）／`test_bundle_version_change_does_change_the_prefix`（**反向**：该变的必须变，防"把语义包摘要删掉换 100% 命中率"作弊）／`test_injecting_a_request_level_var_into_system_makes_loading_FAIL`／`test_prefix_never_contains_history_or_question_text` |
| ⑤ | `prompt_version` 必录（N-19） | 版本 = **文件词干**（`gen_sql_v1`），随 `LLMResponse.prompt_version` 返回；模板路径给显式 `"template"` | `test_prompt_version_is_recorded_on_the_response`／`test_version_equals_file_stem`／`test_content_hash_is_recorded`（§10.3"版本号与内容哈希一并记录"） |

---

## 3. 门禁实测输出（2026-09-17，本机，`.venv`）

```
$ cd CommerceQL/backend && ../.venv/Scripts/python.exe -m pytest -q
1020 passed, 6 skipped, 1 warning in 65.47s
# 6 skip = tests/integration/test_retrieval_fts_pg.py：夹具 DSN 无 DDL 权限（既有的如实 skip，非本窗口引入）

$ ../.venv/Scripts/python.exe -m ruff check --output-format=concise .
All checks passed!

$ ../.venv/Scripts/python.exe -m mypy app
Success: no issues found in 87 source files

$ ../.venv/Scripts/lint-imports.exe          # ⚠️ 必须用控制台脚本，见 §8-U41
Analyzed 130 files, 473 dependencies.
R-DEP-1 分层依赖（只能依赖严格更低层） KEPT
R-DEP-2/N-01 确定性模块与 binding 禁止 import app.llm KEPT
R-DEP-3 obs 内除 audit 外禁止依赖 repo（U-18 代价约束） KEPT
R-DEP-4 retrieval 禁 LLM（refine 唯一豁免，P0 未实现） KEPT
Contracts: 4 kept, 0 broken.

$ ../.venv/Scripts/python.exe scripts/assert_importlinter.py    # CI 同款 DoD② 注入实验
[baseline] 干净状态 lint 通过（Contracts: 4 kept, 0 broken.）
[probe] ✅ r-dep-2-no-llm-in-deterministic / r-dep-1-layers / r-dep-3 / r-dep-4
[restored] 还原后 lint 重新通过（Contracts: 4 kept, 0 broken.）
DoD② 通过 —— 4 条契约均已证明「脏了必红」

$ ../.venv/Scripts/python.exe -m app.core.enums
enums.py 契约自检通过；取值集基数 = {stage: 6, error_code: 28, ..., action_taken: 7, degraded_reason: 8, ...}
```

本包范围另跑：`ruff check app/llm tests/unit/` → All checks passed；`mypy app/llm` → 8 files clean；`mypy` 7 个 W3A 测试文件 → clean。

---

## 4. 决策点 Q1–Q5 落定

| # | 落定 | 代价 / 风险（写明，不隐瞒） |
|---|---|---|
| **Q1** | 采纳 (a)：`llm/` 内定义 `CostLedgerSink` Protocol + `InMemoryCostLedgerSink`，**未建 migration、未报"已落库"**。`CostEntry` 字段**逐列对齐** 07 §12.3 的 `cost_ledger`（W1B 建表时可直接照写 INSERT，不必两边各定义一遍列） | 内存 sink **进程一退出就丢**：重启后当日累计归零、**熔断在重启面前不成立**；单进程语义（扩多 worker 会把总预算放大到 worker 数×预算）。两条都已在 §6 具名登记 |
| **Q2** | 解读为"**全局上限 AND 按模型上限**"——两个配置值**都生效**，不猜语义、不忽略任何一个 | ⚠️ 这是**解读**而非文档明文。若 `LLM_MAX_CONCURRENCY=50` 的真实语义是"上游契约上限"，那我们把有效并发压到 8/2 会低估吞吐。**请 W0/架构裁决**（§8-需号③） |
| **Q3** | 以 07 为准：`MODEL_HARD_TIMEOUT_S = flash 15s / pro 45s`，并**按 §16.1 派生更短的 task 级预算**；`LLM_TIMEOUT_SECONDS=60` **未被使用**（07 §10.2 是权威） | 任务级超时偏紧会推高"超时→降级"比例。**本窗口无法给出实测超时率**（真机只做了行为探测，未跑压测）→ 标 UNVERIFIED，交阶段 3 联调测 |
| **Q4** | 路由表落 `router.py` 的 `TASK_ROUTES` 常量（唯一真相，来源写在每行 `budget_source`） | 改路由需重发版。P0 可接受；将来要热改应挪进 config（归 W0）而不是散进调用方 |
| **Q5** | **标准库 `string.Template`**（`$name`）。不用 jinja2（依赖白名单没有，要加须走 ADR-20）；**不用 `str.format`**（prompt 里必然大量出现 `{}`：JSON Schema、SQL、few-shot 样例，一用就炸） | `$` 在 SQL/JSON 里是稀有字符，唯一要躲的是 `$schema` —— 本目录资产刻意不写它，且加载器会拦裸 `$` |

---

## 5. 本窗口实测到的上游行为（**文档没写，写错不报错只出坏结果**）

| # | 事实 | 实测方式 | 落点 |
|---|---|---|---|
| 1 | 两模型**默认开思考**；关闭的**唯一**有效写法是 `thinking={"type":"disabled"}`。`thinking:false` → **400**；`enable_thinking:false` / `chat_template_kwargs` → **被静默忽略**（仍产 reasoning token） | 真机（`deploy/.env` 有真 key，见 §9） | `egress_guard.build_wire_request` 统一写入；断言 `test_thinking_off_uses_the_only_spelling_the_upstream_honours`（并断言 `enable_thinking` 等变体**不在**请求体里） |
| 2 | **`max_tokens` 会被 reasoning 吃掉 → `content=''` 且 HTTP 200**。实测 `max_tokens=32` → 32 个 completion token 全进 reasoning；`max_tokens=48` 才有 content | 真机 | 双保险：`router.max_tokens_for()` 给思考档留 2048 余量 + `client._parse` 仍检测空 content → `LlmEmptyContent`（余量值是经验值，不能只靠它） |
| 3 | `response_format=json_object` 要求**消息里出现 "json" 字样**，否则 400 `Prompt must contain the word 'json'` | 真机 | `build_wire_request` **构造期**断言 + 每份资产的 system 段必须含 "json"（`test_prefix_makes_json_possible`） |
| 4 | `usage` 直接给 `prompt_cache_hit_tokens`（DeepSeek 专有）**且** `prompt_tokens_details.cached_tokens`（OpenAI 兼容） | 真机 | `client._cache_hit_tokens` 优先前者、缺则退后者、**都没有就如实 0**（不用别的量近似 —— 近似会让命中率变成假数） |
| 5 | `message.reasoning_content` 存在（flash 126 / pro 116 字符） | 真机 | **丢弃**，只留长度 `reasoning_chars`。三条理由：N-17（可能复述 prompt = 回流通道）、N-12（可能含 PII）、非确定性文本（存下来就会在下游被当成可消费内容）。断言 `test_reasoning_content_is_discarded_only_its_length_is_kept` |
| 6 | 上游 400 的 `error.message` **会回显我们 prompt 里的原文片段** | 真机 | `client._parse` **只取结构化标识**（`status`/`error.type`/`error.code`），**绝不带 message**。断言 `test_upstream_message_text_never_leaves_the_client`（在 `str(exc)`/`repr(detail)` 里都搜不到原文） |
| 7 | ⚠️ **空 `DEEPSEEK_API_KEY` 能通过 `Field(...)` 必填校验**：`DEEPSEEK_API_KEY=''` + 有效 DSN → settings 构造**通过** | 本机实测 | **本窗口未改 config**（归 W0）。⇒ "必填"当前只是"键必须存在"，不是"值必须非空"，fail-fast 被削弱。需求已入 `RELAY.md §给 W0` |
| 8 | PROMPT §三-8 声称 `deploy/.env` 没有 `DEEPSEEK_API_KEY` → **已过期**：实测第 35 行有，且可用 | 本机实测 | 故本窗口的上游行为探测是**真机**做的，不是纯推断 |

---

## 6. 已知限制（具名登记，不得含糊）

1. **模板层是空的**：`NullTemplateProvider` 恒返回 `None` → 默认降级链实际是 `pro → flash → 拒答`。
   这不是"实现了模板降级"，是"**给模板层留了口子并如实说明它空着**"。真正落地需 Gold Query 库（`gold_query` 表，归 W1B/W6）。
   已把"空着"钉成断言 `test_default_template_provider_is_a_declared_gap_not_an_implementation` —— 哪天接上了它会红，提醒同步本文档。
2. **降级事件只到日志**：`DegradationSink` 默认实现写结构化日志。到 SSE 的那一跳在 L4（`graph/events.py`），R-DEP-1 禁止本层 import。**W4 未接线前，前端看不到 `degraded`**。
3. **`LlmRefused` 未接线时会落成 `500 INTERNAL`** —— 那是**错的终态**（07 §14.2 F1 明确 refuse 不是 error）。W4 必须先捕获它。本窗口无法单方面解决。
4. **计量不持久**：`cost_ledger` 表不存在 → 内存 sink。**重启后熔断被重置**；单进程语义（扩多 worker → 总预算放大到 worker 数×预算，与"总并发 = 进程数×8"同类缺陷，07 §10.1 runbook 已记并发那条）。
5. **`reduced_candidates` 是建议不是动作**：payload 归调用方所有，网关**无法**把候选从 N 路减到 1 路。实物动作是换到并发位更多的 flash（8 vs 2）。故 detail 里明写 `advisory: True`，并断言"出站请求体里没有 candidates 字段"。
6. **07 未给 `gen_sql_complex` / `repair` 的任务级延迟预算** → `timeout_s=None` → 退化为模型级 45s/15s。**不许发明数字**（U-22 纪律），需求见 §8-需号①。
7. **07 §16.1 `gen_sql`=1.3s 与 PRD §12.2 "L3+ 走 pro 思考" 物理冲突**：真机实测 pro 一次**最简**调用 1.42s > 1.3s。两者不能同时成立，需架构裁决（§8-需号②）。
8. **超时率 UNVERIFIED**：本窗口只做了行为探测（单次调用），**未做压测**，Q3 的"任务级超时过紧会推高降级比例"这个风险**尚未量化**。
9. **`Semaphore`/`CircuitBreaker` 是进程内状态**：多进程部署下"每 worker 8/2 位"= 有效并发乘 worker 数；熔断也按 worker 独立。P0 单进程（07 §10.1）可接受。
10. **两个侧信道回调都是同步的**（`DegradationSink.on_degraded` / `MetricsSink.on_call`）：这是**刻意的** —— 它保证"发事件"这一跳永远不会阻塞 LLM 调用路径（不会吃掉 0.6–1.5s 的任务预算）。
    代价：W4 若要把事件送进 async 的 SSE emitter，必须自己桥接（`asyncio.Queue.put_nowait` 等），**不能在回调里 `asyncio.run`（在运行中的 loop 里必炸）或阻塞**。已写进 `RELAY.md §给 W4`。

### 经验值清单（**没有上游依据的推导，必须由阶段 3 实测替换**）

| 常量 | 值 | 依据状态 |
|---|---|---|
| `THINKING_HEADROOM_TOKENS` | 2048 | 经验值。仅防"空 content"的下限（实测 32 就吃光，但真实 SQL 生成需要多少**未标定**） |
| `output_tokens_hint`（10 个 task） | 128–1200 | 经验值。量级取自 PRD §12.3"一次查询输出 ≈2.4K token"按调用点拆分 |
| `BACKOFF_JITTER_RATIO` | 0.25 | 经验值。07 只写"+ jitter"**没给幅度** |
| `USD_CNY_RATE` | 7.1 | 半经验值。PRD §12.3 只有**一个**换算数据点（$0.0071→¥0.05 ⇒ ≈7.04），误差 +0.9%。**全仓无汇率配置项**（§8-需号⑤） |
| `DEFAULT_TENANT_DAILY_BUDGET_CNY` | 10 | **纯经验值**（取全局的 1/10）。07 §10.4 只说"双层预算"**没给租户级的数**（§8-需号④） |
| `estimate_for_payload` 缺省 `output_tokens` | 800 | 经验值（PRD §12.3 量级） |
| `MAX_RAW_QUESTION_CHARS` / `MAX_ERROR_DIGEST_CHARS` / `MAX_SEMANTIC_SUMMARY_CHARS` / `MAX_FEW_SHOT_TURNS` / `MAX_CANDIDATES` / `MAX_CANDIDATE_CHARS` | 2000 / 1000 / 40000 / 8 / 200 / 120 | 经验值。防"明细数据借合法字段出站"的量级界 |

> **有依据、不算经验值**：任务级超时（07 §16.1/§16.2/§6.8.2）、模型级 15s/45s（07 §10.2）、退避 0.5/1/2s（07 §10.1）、开路 30s + 半开 1 探测（07 §10.2）、信号量 8/2（07 附-6）、等待上限 20s（07 §10.1）、温度 0（PRD §12.9）、价表（PRD §12.3）、高峰时段（PRD §12.3）。

---

## 7. 交付期发现并修掉的缺陷（含**被推翻的根因推断**）

### 7.1 `model` 覆盖被静默忽略 —— 真实缺陷，已修

`resolve_model_name()` 校验并返回了覆盖值，但门面出站用的 `model` 取自 `route.model_key` —— **覆盖只影响了预算估算**。
后果：调用方以为换了模型，账单与延迟却按另一个模型走，且**没有任何日志能看出来**（正是 N-21 禁止的静默行为）。
修法：入口档改为按覆盖值解析（`entry_key`），降级链从**该档**继续；降级事件 detail 增 `model_override` 字段以便审计。
断言（三条，含反向对照）：
`test_model_override_is_an_auditable_escape_hatch`（覆盖到快档生效）／`test_override_to_the_strong_model_also_takes_effect`（**反向**：只断言"降档"方向的话，"永远按 route 走"的实现也能过）／`test_override_does_not_silently_disable_the_degrade_chain`（覆盖到强档后仍能降级到 flash）。

### 7.2 半开探测标志的复位耦合 —— 设计缺陷（**不是故障**），已改为局部不变量

原写法用 `if breaker.opened_at is not None` 当复位条件。探测**成功**会把 `opened_at` 清成 `None` → 那一轮 `finally` 不复位，标志残留 `True`。

⚠️ **我的第一版根因推断是错的，必须更正**：我最初断言这会导致"该模型永久锁死（所有请求都不发出）"。
**探针实验（真跑状态机）推翻了它** —— 下一次失败触顶时 `opened_at` 恰好又非空，那次的 `finally` 顺手把标志清掉了。
所以旧写法在**当时的代码**下不构成故障，正确性建立在"两处不相干分支的巧合交互"上。

处置（两面都做了，且**不谎报根因**）：
- 修法：复位由**放行探测的那次调用**自己负责（`probe_admitted`），不变量变成**局部**的、不依赖别的分支做什么；
- 断言：`test_half_open_flag_is_cleared_by_the_admitting_call_itself` 是**白盒不变量**断言（读私有字段），因为这条因果关系**黑盒断言不出来** —— 黑盒只能看到"恰好又正常了"；
- **负向对照实测**：把修复还原 → 该断言**红**（`half_open_probe_in_flight=True` 残留），两轮周期测试仍绿（印证它不具判别性，docstring 已如实写明）。

### 7.3 清理了他人残留（跨窗口通报）

交付期发现 `backend/app/guard/_probe_violation.py`（被 `.gitignore` 忽略、由 `scripts/assert_importlinter.py` 自动创建/删除）**残留**，导致**全仓 import 契约基线本地变红**。
判定依据：mtime 连续 30s 不变（活动运行不可能停这么久）+ 内容为脚本模板 → 判定为**中断残留**，非他人活动在制品。
处置：备份内容（sha256 `17d4eff1dd5451a917e3dffe88a82ed78816fe744688dab543dfdea97d7737e2`）后删除；清理后基线恢复 `4 kept, 0 broken`，`assert_importlinter.py` 跑通且无残留。
**⚠️ 给并行窗口**：若你的 `assert_importlinter.py` 运行被中断（Ctrl-C / 工具超时），请检查并清理该探针，否则别人的基线会红。

---

## 8. 待架构窗口分配编号的问题（**本窗口未自行开号**，下一可用 = `U-65`）

| 候选 | 问题 | 现状 / 影响 |
|---|---|---|
| ① | **07 缺 `gen_sql_complex` / `repair` 的任务级延迟预算** | 其余 6 个阶段都有 0.6–1.5s 的预算，这两个没有 → 本窗口退化为模型级 45s/15s。P95 契约体系因此**这两档没有约束** |
| ② | **07 §16.1 `gen_sql`=1.3s 与 PRD §12.2 "L3+ 用 pro 思考" 物理冲突** | 真机实测 pro 最简调用 1.42s > 1.3s。要么给 pro 档独立预算，要么承认 L3+ 必然超 P95 |
| ③ | `LLM_MAX_CONCURRENCY=50` 与 07 §10.1 "按模型 8/2" 的**语义关系未定义** | 本窗口按"全局 AND 按模型"实现（两个值都生效）。若 50 另有含义（如上游契约上限），当前实现会低估吞吐 |
| ④ | **租户日预算无 config 键** | 07 §10.4 要求双层预算，config 只有全局 `DAILY_BUDGET_CNY`。本窗口用经验值 10 元 |
| ⑤ | **`USD_CNY_RATE` 全仓无配置项** | PRD §12.3 只有 1 个换算数据点。本窗口取 7.1 并标经验值 |
| ⑥ | **`EgressPayload.candidates` 需正式登记进 07 §10.5** | 本窗口**唯一**新增的出站字段（依据 §10.5 ① 的"同义词"子集） |
| ⑦ | **`LLMPort.estimate_cost(payload)` 的 payload 结构端口未定义**（签名只有 `Mapping`） | 本窗口自行定义并登记（`budget.estimate_for_payload` docstring + RELAY §给 W3B/W3C） |
| ⑧ | **`LLMResponse` 装不下 `degraded`/`refuse`** → 本窗口用两条侧信道绕开 | 侧信道是妥协：需架构裁决是否扩端口字段（扩则 W4 不再依赖回调约定） |

---

## 9. 与 PROMPT §三 现状盘点的差异（**上游可能已变，动手前复核**）

| PROMPT 条目 | 实测 | 差异 |
|---|---|---|
| §三-1 `app/llm/` 只有 `__init__.py` | 一致（本窗口从零建包） | — |
| §三-8 `deploy/.env` **没有** `DEEPSEEK_API_KEY` | **第 35 行有** | 🔴 **已过期**。故本次的上游行为探测是真机做的 |
| §三-4 `LLM_TIMEOUT_SECONDS=60` vs 07 的 15/45 | 一致存在该差异 | 按 Q3 以 07 为准（见 §4） |
| §三-11 `Retry-After` 仍是 2/5（07 要求 5/30） | 未复核（属 W0） | 需 W0 落码，见 RELAY |
| §三-5 依赖白名单含 `tenacity` | 未使用 | 退避**自己实现**（`client._backoff`）：`tenacity` 无法表达"总预算做减法"，而那是 Q3 的核心（见 `test_retry_count_is_truncated_by_the_task_budget`）。**依赖未被移除**（归 W0/ADR-20） |

---

## 10. 复现指引（给 W3-INT）

```bash
# 全部门禁（与 CI 对齐）
cd CommerceQL/backend
../.venv/Scripts/python.exe -m pytest -q
../.venv/Scripts/python.exe -m ruff check .
../.venv/Scripts/python.exe -m mypy app
../.venv/Scripts/lint-imports.exe                 # ⚠️ 控制台脚本，-m 形态假绿（U-41）
../.venv/Scripts/python.exe scripts/assert_importlinter.py
../.venv/Scripts/python.exe -m app.core.enums

# 只看本包
../.venv/Scripts/python.exe -m pytest tests/unit/test_llm_*.py -q
```

测试**全离线**：假上游 = `tests/unit/_llm_fake_upstream.py`（`httpx.MockTransport`，把 `Request.content` 原样交给回调 —— DoD③ 的录制就在这里）。
不用 `respx` 的理由：本项目只有一个 URL，不需要"路由到不同 URL"，而"线缆上到底是什么字节"需要零中间层。
**真机联调可选**：`deploy/.env` 有可用 key；本窗口只做了行为探测，**未跑集成测试**。

---

## 11. 提交

| commit | 内容 |
|---|---|
| `feat(w3a)` | `app/llm/**`（含 `prompts/`）+ `tests/unit/test_llm_*.py` + `_llm_fake_upstream.py` |
| `docs(w3a)` | `reports/w3a/{DELIVERY.md, RELAY.md}` |

只暂存本窗口文件（工作区另有 W2-INT/其他窗口的在制品，见 `git status`）。
push：本会话用户已明确授权"可以直接 push，不一定要等我指令"。

---

## 12. 【追加·2026-09-17 下午】阶段延迟预算被当作硬超时 —— **真实阻断缺陷，已修**

提交：`fix(w3a): 解耦阶段延迟预算与传输 deadline` + `docs(w3a): §12 缺陷记录与跨窗口影响`（附在本节所属的推送里）。

触发：`reports/w3b/RELAY.md` §给 W3A-1（W3B 转述：`plan`/`gen_sql` 在真机上 **100% 失败**）。

### 12.1 一手复现（真 key，同进程 / 同 payload / 同模型，**唯一变量 = deadline**，n=3×5）

| task | 07 §16.1 预算 | 当硬 deadline 用（修复前） | 用 §10.2 上限（修复后） | 修复后实测延迟中位 |
|---|---|---|---|---|
| `normalize` | 0.6s | **0/3**（失败耗时 608/606/605 ms） | **3/3** | 1.45s |
| `intent` | 0.6s | **0/3**（604/611/602 ms） | **3/3** | 1.39s |
| `normalize_intent` | 1.2s | **0/3**（1311/1202/1213 ms） | **3/3** | 1.56s |
| `plan` | 1.0s | **0/3**（1004/1003/1003 ms） | **3/3** | 1.49s |
| `gen_sql` | 1.3s | **0/3**（1304/1311/1315 ms） | **3/3** | 1.60s |

**0/15 → 15/15。** 失败耗时**恰好等于各自预算值** —— 是"卡在 deadline 上死"，不是上游不可用。
探针与原始 JSON：工作区根目录 `_w3a_budget_probe.py` / `_w3a_budget_result.json`（未提交）。

### 12.2 对 W3B 报数的两处修正（**范围比它报的更大**）

- W3B 报 `plan` 2756ms / `gen_sql` 1939ms；本窗口实测 **1.49s / 1.60s**。口径不同（W3B 走 `PlannerEngine`，含语义包与 prompt 组装；本窗口直连网关），**结论一致**，数值以本表为准。
- W3B 报 `normalize_intent` **5/5 通过**（939ms）；本窗口 **0/3 失败**（真机 1.2–1.6s）。它在悬崖边 ⇒ **"只有 plan/gen_sql 坏"是低估**：`rerank` 0.8s / `l4_score` 0.8s 同样罩在这条坑里，`present` 1.5s 未实测（未知）。**8 个有 §16.1 分配的任务全部受影响**。

### 12.3 根因（**逻辑错误，不是"调大一点"**）

`TaskRoute.timeout_s` 字段文档写着"任务级**软**超时"，`client.invoke` 却把它当 `deadline`。而：

- **P95 是分位数，不是上界** —— 拿它当硬上限，系统完全健康也必然砍掉约 5%；分配值低于真机中位时即为 100%。
- **07 §10.2 才是"单次调用超时"的出处**（flash 15s / pro 45s）—— 全项目唯一。
- **07 §16.1 的标题就是"延迟预算分解（P95 ≤ 8s）"**，且该表自己写明串行合计 9.2s **超预算**、要靠"压缩手段"解决 —— 它从未主张"超了就该失败"。
- **07 §16.2 兜底写明**超预算应"先推 `stage=intent` 占位"（降级 UX），**不是失败**。
- **PRD §12.2 的路由表根本没有超时列**（只有 任务/模型/模式/理由）。

外部前提已全部核对到原文行号，不是转述。

### 12.4 修法（3 处，面很小）

| 位置 | 改动 |
|---|---|
| `router.py` | `TaskRoute.timeout_s` → **`budget_s`**（§16.1 阶段分配，**元数据**，文档明写"不参与任何超时判定"）；删 `effective_timeout_s`，加 **`hard_timeout_s(model_key)`** → §10.2（**刻意不看 task**，docstring 写明理由） |
| `client.py` | `invoke(timeout_s=)` → **`deadline_s`**（切断与"任务预算"的词汇联想）；两处残留文案（"任务预算耗尽"）改掉 |
| `__init__.py` | line 417 改用 `hard_timeout_s`；`CallRecord` 增 **`budget_s` / `over_budget`**，并把两项加到 `_LoggingMetricsSink` 输出 |

**刻意不做**：超预算**不发 `degraded` 事件**。降级事件的含义是"这份答案来自降级路径"（N-21）；延迟超标并不改变答案，发它等于撒谎。§16.1 的一致性改由 `over_budget` 度量，判定责任移交上层（推占位符 = W4 的 SSE）。

### 12.5 守卫测试 + **注入对照**（本次最该留的东西）

- `test_llm_router.py::TestTimeoutIsTheModelTierNotTheBudget`：逐 task 断言超时取模型档；反向对照"**阶段预算 ≠ 超时**"（检查 8 个有预算的 task）；把"预算低于实测"这条事实按**只量过的 5 个 task** 钉住（未实测的 `present`/`rerank`/`l4_score` 刻意不写进断言 —— 对没量过的值作延迟断言就是编造；这条**我自己先写错了一次，被测试抓红后收窄**）。
- `test_llm_gateway.py::TestStageBudgetIsNeverTheDeadline`：用记录 `deadline_s` 的传输层 spy 断言"传给传输层的是 15.0s 而非 1.0s"；行为面断言"慢于预算的调用仍成功且被标 `over_budget`"；**含一条永久负向对照**。
- **正向对照实测（注入 → 必红 → 还原 → 必绿）**：把旧接线临时注入 `__init__.py:417` → 守卫 **2 条变红**（`seen == [1.0] != [15.0]`、`[1.3] != [1.0]`）→ 还原 → **90 passed**；残留已 grep 确认为零。
- ⚠️ **诚实记录一条鉴别力边界**：**行为测试在注入下没有变红**。原因是 `asyncio.timeout` 量的是**真实时间**，假时钟把"耗时"拉到 1.75s 并不能让计时器触发。所以对这一缺陷有鉴别力的**只有参数级断言**——这一点已写进 `_spy` 的 docstring，避免后人误以为行为测试足够。
- 另记一个夹具坑：浮点截断。`clock.t += 1.8` → `(1001.8-1000.0)*1000` 截断成 **1799**。已改用二进制可精确表示的步长（1.75）。

### 12.6 门禁实测（2026-09-17，全部在本机 `.venv`，Docker 起来后）

```
pytest -q                                  → 1467 passed / 6 skipped / 0 failed / 0 errors (67s)   ← §13 加 4 条守卫后 = 1471，见 §13.5
ruff check .                               → All checks passed!
mypy app                                   → Success: no issues found in 102 source files
lint-imports.exe                           → Contracts: 4 kept, 0 broken.
python -m app.core.enums                   → 契约自检通过（32 个取值集基数齐全）
python scripts/assert_importlinter.py      → DoD② 通过（4 条契约均已证明"脏了必红"）
```

- 6 skip = `tests/integration/test_retrieval_fts_pg.py` 夹具 DSN 无 DDL 权限（既有如实 skip，非本窗口引入）。
- ⚠️ **首次全量跑出 1 failed + 6 errors + 55 skipped 全部是 Docker Desktop 未启动**（`集成环境不可用（ConnectionError/ConnectionTimeout）`），**不是回归**；Docker 起来后复跑即全绿。这正是 W3B RELAY §给 W3-INT-1 提醒的那件事，已当场验证。

### 12.7 交付期发现的第 4 个缺陷（**W0 的脚本，非本窗口文件，仅通报**）

`backend/scripts/assert_importlinter.py`（W0）**不是并发安全的**，且残留会**污染全仓基线**：

- 现象（本次实测，两次会话各一次同 sha256 `17d4eff1…7737e2` 的残留）：`app/guard/_probe_violation.py` 被留下 → **所有窗口**的 `lint-imports` 报 `R-DEP-2 BROKEN`、`assert_importlinter.py` 直接 `FATAL: 注入任何探针之前，lint 就已经失败`。
- 机制：探针清理只在 `finally` 里（**信号杀死时不执行**）；且脚本**拒绝覆盖已存在的探针**（`_run_probe` 的存在性分支）⇒ 一旦残留就是**粘性的**。
- 另一路径：**两个窗口同时跑**该脚本时会互相踩 —— 一方的 step-0 基线检查会看到另一方的探针。本次取证：我删除并验绿后**数秒内**该文件又被写下（mtime 15:56:44 → 15:57:44），而"删完立刻跑"（最小竞态窗口）**DoD② 一次通过、无残留** ⇒ 竞态，不是本窗口改动引起。
- 建议（转 W0）：探针文件名带 PID（或加锁）以支持并发；区分"并发中的临时文件"与"陈旧残留"；并把 `finally` 清理改为对 `SIGPIPE`/`SIGTERM` 也生效的形态。

---

## 13. 【追加·2026-09-17 下午】`gen_sql_complex` 的双重故障 —— max_tokens 已标定，**但真正的阻断在 45s 上限**

触发：`reports/w3b/RELAY.md` §给 W3A-2（pro 档 2/3 返回空 content）。

### 13.1 实测：`max_tokens` 是**确定性**失败，不是 2/3（真 key，真实资产，n=3）

出站体由**生产同一条装配路径**构造（`load_prompt` + `render_messages` + `build_wire_request`），
只变 `max_tokens`；直发上游以读到网关会丢弃的 `finish_reason` / `reasoning_tokens`。

| `max_tokens` | `finish_reason` | content | `reasoning_tokens` | 耗时 |
|---|---|---|---|---|
| **3248**（旧生产值 = 1200 + 2048） | **`length` ×3** | **空 ×3** | **3248 ×3**（全部被思考吃光） | 68–80s |
| 16384（放宽观察） | `stop` ×3 | ✅ 合法 JSON ×3 | 4900 / 5619 / **6719** | **97–138s** |

⇒ 旧余量 2048 **差 3.3 倍**；旧"成功过一次"应是更简问句下的偶然（本窗口用带环比 + 品类排名的 L3+ 问句复现为 **3/3 失败**，比 W3B 报的 2/3 更差）。

### 13.2 已做的标定（**必要但不充分**）

| 常量 | 旧值 | 新值 | 依据 |
|---|---|---|---|
| `THINKING_HEADROOM_TOKENS` | 2048 | **8192** | 实测 reasoning 上界 6719 向上取 2 的幂（×1.22） |
| `GEN_SQL_COMPLEX.output_tokens_hint` | 1200 | **1536** | 实测 content 545–**1223** ⇒ **旧值低于实测需求** |
| 合成 `max_tokens` | 3248 | **9728** | 实测最坏总计 7672 ⇒ 余量 27% |

守卫：`test_llm_router.py::TestThinkingBudgetIsCalibratedFromMeasurement`（余量盖住实测 reasoning / 提示盖住实测 content / 总值盖住最坏总计 / **反向对照**防"把余量调到 10 万让测试变绿"）。

**诚实交代收益边界**：在当前 45s 传输上限下，这个修正的**可达收益很窄** —— 只有"思考 + 内容需要 3248–约 3560 token 且能在 45s 内生成完"的问句才真正从来不空答案变成拿到 pro 答案。绝大多数 L3+ 问句落在 45s 之外（见 13.3）。它的主要价值是**成为真正修复的前置条件**（上限一旦放宽，旧值立刻是"稳定空 content"）。

### 13.3 🔴 真正的阻断：实测 **97–138s** vs 07 §10.2 的 pro **45s**

按要求做了端到端验证（新标定后过**网关**跑 `gen_sql_complex`，n=2）：

| run | 终态 | 输出模型 | 耗时 | 降级事件 |
|---|---|---|---|---|
| 1 | ✅ 有内容（2092 字符） | **`deepseek-flash`** | 49071 ms | `llm_unavailable` / `switched_to_weak_model`，`from_model=deepseek-v4-pro`，`error=LlmTimeout` |
| 2 | ✅ 有内容（1876 字符） | **`deepseek-flash`** | 59998 ms | 同上 |

⇒ **pro 档在真实 L3+ 问句上从未生效**：每次都白等 45s 被传输层掐断，然后降级到 flash。
用户拿到的是 **flash 的答案**（且 `degraded=True`），代价是 **50–60s/请求** —— 既不是 pro 的质量，也远不是 8s 的 P95。

**这不是我能在 `app/llm` 单方面修的**：
- 45s 是 **07 §10.2 明文**的 pro 单次调用上限（"思考模式耗时显著更长"，但 45s 仍低估 2–3 倍）；
- "L3+ 走 v4-pro 思考"是 **PRD §12.2 明文**（契约优先级 PRD > 07）；
- 两者与 8s 端到端 P95 目标**三者不可同时成立**。本窗口早前已把这条矛盾登记在 `router.py` 模块 docstring（"物理上不可能"），本次给出了**量级证据**。

⇒ 已作为候选 ⑬ 上呈架构（见 `RELAY.md §给架构`）。**本窗口不擅自改路由表或 §10.2 的值**（那是替架构发明产品决策）。

### 13.4 三个可选方向（供裁决，本窗口不预设立场）

| 方向 | 内容 | 代价 |
|---|---|---|
| A | 允许 L3+ 长耗时（pro 上限提到 ~150s） | 与 8s P95 彻底冲突；需要异步/后台 + SSE 分段（产品形态变化） |
| B | L3+ 也走 **flash 非思考**（放弃 pro 质量） | 与 PRD §12.2 直接冲突，需改需求或说明 deviation |
| C | L3+ 走 pro 但**异步生成 + 先返回计划占位** | 工程量大（W4/W5 都要动），但唯一同时满足质量与感知延迟的形态 |

> 若选 A 或 C，本窗口已做的 max_tokens 标定即为其前置条件；若选 B，`gen_sql_complex` 路由应改回 FAST 非思考（本窗口可立即执行，但**需明确指令**）。

### 13.5 门禁实测（本次标定的收尾）

```
cd backend（Docker 已起）
../.venv/Scripts/python.exe -m pytest -q                       → 1471 passed / 6 skipped / 0 failed / 0 errors (67s)
../.venv/Scripts/ruff.exe check .                              → All checks passed!
../.venv/Scripts/mypy.exe app                                  → Success: no issues found in 102 source files
../.venv/Scripts/lint-imports.exe                              → Contracts: 4 kept, 0 broken.
../.venv/Scripts/python.exe scripts/assert_importlinter.py     → DoD② 通过（4 条契约「脏了必红」）
../.venv/Scripts/python.exe -m app.core.enums                  → 契约自检通过
```

- `pytest` 由 §12 的 **1467** 增至 **1471**（+4 = 本节新增的 `TestThinkingBudgetIsCalibratedFromMeasurement`）。
- 本次改动**只**动 `app/llm/router.py` 两个常量与 `tests/unit/test_llm_router.py` 一个测试类，不碰任何集成路径 ⇒ 集成测试数字与 §12 一致。

**🔁 并发竞态再次实测（追加证据，转 W0）**：跑门禁时 `assert_importlinter.py` **又一次**在 step-0 报
`FATAL: 注入任何探针之前，lint 就已经失败`。取证序列：
- `ls` 确认**无**残留 →（数秒后）脚本 step-0 红 → `ls` 显示文件 mtime **16:22:08**，内容 sha256 与前次**同一份**；
- 5 秒后 mtime **未再变**、`tasklist` 无 python 进程 ⇒ **不是活跃写者，是残留**（写者被中断，`finally` 未执行）；
- `rm -f` + **同一条命令内**立刻复跑（闭环、无工具往返间隙）⇒ **DoD② 一次通过、无残留**。

⇒ 与 §12.6 结论一致：**外部写者存在**（另一个窗口/会话在跑同一脚本），且脚本的清理对中断不鲁棒。
本窗口未改该脚本（属 W0），仅提供证据；跑门禁时**先 `rm -f app/guard/_probe_violation.py` 再跑**可绕开。
