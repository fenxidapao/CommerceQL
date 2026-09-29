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

---

## 14. 【U-67 执行】L3+ 生效档改回 flash 非思考（07 v1.0 §10.2 / §4.9，方向 B）

架构裁定原文（07 §4.9 U-67）：**P0 = 方向 B + deviation 登记；方向 A 否决；方向 C 列为 P1 候选**
（触发条件 = E-3 评测证明 flash 在 L3+ 准确率显著不足）。§10.2 已落笔："W3A 拿本裁定即可执行路由改回
（其索要的'明确指令' = 本条）"。本节记录执行。

### 14.1 路由表改动（`app/llm/router.py`，唯一一处实质变更）

| 字段 | 旧（PRD §12.2 第5行） | 新（07 v1.0 U-67/U-65） |
|---|---|---|
| `model_key` | `STRONG`（v4-pro） | **`FAST`**（deepseek-flash） |
| `thinking` | `True` | **`False`** |
| `budget_s` | `None`（07 当时无分配） | **`3.0`**（§16.1 表 6' 行，U-65 补，**标"经验值，首轮评测校准"**） |
| `output_tokens_hint` | 1536（保留） | 1536（⚠️ 该实测是 pro 思考档下量的；flash 非思考的输出分布待 E-3 复校） |

⇒ 改后路由表**没有任何** STRONG / 思考条目。对 PRD §12.2 构成 **deviation，待上游认账**（07 已登记转达项）。

### 14.2 刻意保留的东西（U-67 ②："45s 与 max_tokens 标定保留"）

- `MODEL_HARD_TIMEOUT_S[STRONG] = 45.0` **保留**（将来 pro 回归时直接可用；删掉 = 重新发明数字，违反 U-22）。
- `THINKING_HEADROOM_TOKENS = 8192` **保留**（当前无消费方 —— 这是有意的：它是 P1 重启 pro 思考的
  **前置条件**，删掉 = 将来重新踩一次"稳定空 content"）。
- 降级链 `pro → flash → 模板`（`degrade_target`）**原样保留** —— 07 §10.2 的链仍是契约。

### 14.3 测试重构（该红的红、该绿的绿，机制一个不丢）

| 变化 | 内容 |
|---|---|
| **翻转** | `test_only_the_complex_sql_task_uses_the_strong_model` / `..._thinks` → `test_no_task_uses_the_strong_model_u67` / `test_no_task_thinks_u67`（断言集合为**空**）+ 新增 `test_l3_effective_tier_is_flash_non_thinking` 正向钉住 `FAST + thinking=False + budget 3.0` |
| **预算表** | `_DOCUMENTED_BUDGETS` 增 `GEN_SQL_COMPLEX: 3.0`（U-65）；"无分配"清单只剩 `REPAIR`；`checked == 8 → 9` |
| **合成档** | 新增 `_strong_thinking_route()`：P1 前置形态（STRONG+thinking）。降级链、模型覆盖、思考余量、pro 饱和、pro→flash 成本结算这些**机制**测试改用它 + `monkeypatch.setitem(TASK_ROUTES, ...)` —— U-67 改的是**现状**，不是**机制**，机制一条不丢 |
| **标定组** | `test_total_max_tokens...` → `test_if_pro_thinking_is_reenabled_the_budget_still_covers_the_measured_worst_case`（hint+余量 9728 > 实测最坏 7672）—— 把"标定保留"本身钉成守卫 |
| **新增正向** | `test_max_tokens_on_l3_adds_no_headroom_u67`（非思考档不白加余量 = 成本口径污染的反向对照） |

### 14.4 门禁（实测）

```
cd backend（Docker 已起）
../.venv/Scripts/python.exe -m pytest -q                       → 1500 passed / 6 skipped / 0 failed / 0 errors
../.venv/Scripts/ruff.exe check .                              → All checks passed!
../.venv/Scripts/mypy.exe app                                  → Success: no issues found in 104 source files
../.venv/Scripts/lint-imports.exe                              → Contracts: 4 kept, 0 broken.
```

（mypy 102 → **104** files：W1B 的 `app/repo/cost_ledger.py` + W0 的 `app/obs/metrics.py` 扩充后纳入。）

**跨域一处（已改，请 W3B 复核）**：`tests/unit/test_planner_egress_contract.py` 的
`test_complex_task_hits_the_thinking_route` 断言旧 PRD 行为（pro+思考）→ 全量假红。
已按 U-67 改写为 `test_complex_task_hits_the_flash_non_thinking_route_u67`
（断言 flash + `thinking: disabled`，原断言见 git 历史）。

### 14.5 回执（对今日三份转述）

1. **→ 架构（U-67）**：已执行，见 §14.1。**deviation 转达确认**：PRD §12.2 第 5 行（L3+ → v4-pro 思考）
   在实现层已被 U-67 取代，等上游认账后 07 §10.2 的 deviation 标记可摘。
2. **→ W1B（cost_ledger sink）**：`app/repo/cost_ledger.py::DbCostLedgerSink` 与本窗口
   `CostLedgerSink` Protocol（`record` / `tenant_spent_cny` / `global_spent_cny`，同步三方法）**逐成员核对匹配**；
   `CostEntry` 列对齐关系维持（你本地结构化 Protocol 的处理方式正确，R-DEP-2 无违反）。
   **接线归 W4**（`build_gateway(..., ledger=DbCostLedgerSink(...))`）—— 本窗口不代接线。
   "重启丢账"（InMemory sink）在 W4 接线后自然消解。
3. **→ W0（12 条处置回执）**：① Retry-After 5s/30s 收到（`enums.RETRY_AFTER_DEFAULT_S` 是唯一入口，
   本窗口无硬编码）；② 空 key `min_length=1` 收到；③ `assert_importlinter.py` 并发根修收到（粘性残留
   问题关闭）；⑫ `LLM_TIMEOUT_SECONDS` 废弃标注**确认** —— 本窗口无消费方，建议直接删（07 §10.2 是唯一超时口径）。

### 14.6 待办（W3A 域，下一轮）

- **U-68 合并档资产**：`plan`+`gen_sql` 合并需**新 prompt 资产 + 新 `LlmTask` 取值**（W3A 域），
  W4 阶段 4 接线。约束（U-68）：必须 flash 非思考 + `plan_ready` 事件先发。
  **待开工指令**（新资产 = 契约面变更，且 W3B 窗口已收工，合并调用方未定）。

---

## §15 L4_SCORE 输出预算事故修复（2026-09-28，W7 报，零额度）

提交：`e1ea13a`（`fix(w3a): L4_SCORE 输出预算 512→2304 + 读 finish_reason 使截断在日志中可辨`）。
5 files changed, 240 insertions(+), 3 deletions(-)。**不占 U 号**（W7 定性：零额度、现在就能做）。

### 15.1 事故与缺口

W7 loadtest 健康态实测：`l4_score` **149 次调用里 96 次**被 `max_tokens=512` 截断
（`output_tokens` 恰=512，内容断在 1,213 / 1,279 / 1,310 字符）⇒ `app/binding/scores.py:256-259`
只能报 `invalid_json:*` ⇒ 下游 fail-safe（N-27 ④：失败 → 减候选继续）把 **L4 精排整层静默降级**
（96/149 = **64.4%**）。与 `degraded_total{llm_unavailable,reduced_candidates}` 逐格 1:1。

缺口的成因不是"没算这个字段"，而是**从没读过它**：全仓只有 `router.py:141` 的文档表格提过
`finish_reason`，没有任何代码读 ⇒ "被截断"与"写完了"在任何日志里同形。

**载体订正（W7 自报，我复核认可）**：`detail` 其实**有**出口 =
`app/audit_log_supplement.degradations`（`audit_supp.py:66-68`）。但 `supp` **只在走到 present
的 run** 才写 ⇒ 覆盖率 20/96 ≈ **21%**，失败路径仍无出口。⇒ ② 的收益正是这一格。

### 15.2 两条改动

| # | 文件 | 改动 |
|---|---|---|
| ① | `app/llm/router.py` | `L4_SCORE.output_tokens_hint` **512 → 2304**（512 是**未登记的经验值**，从未由实测推出） |
| ② | `app/llm/client.py` + `app/llm/__init__.py` | 读 `choices[0].finish_reason` → `Completion.finish_reason` → `CallRecord.finish_reason` → `llm_call` 日志行（**含成功路径**）；空 content 时同时进 `LlmEmptyContent.detail` |

**2304 的推导**（每一步都有实测来源，U-22 不发明数字）：

1. 项数上界 = **30**。来源 = 契约硬顶 `app/retrieval/search.py:92 column_top: int = 30`。
   **现读**（`inspect.signature(RetrievalService.__init__)`）而非抄字面量 —— 上游调大硬顶时测试要红。
   W7 实测 42 题分布：min 8 / **p50 17.0** / p95 22 / max 25 ⇒ 打满硬顶才是"任何合法载荷都不被截断"的判据。
   ⚠️ 归档件 `probe_l4_candidate_bound.txt` 的 `p50=15.8` 是 `mean` 印错位（W7 已自纠：
   订正后 p50=17.0 / mean=15.81）⇒ **本推导不受影响**（只吃硬顶 30 与每项 164 字符）。
2. 每项字符上界 = **164**（W7 实测区间 52–164）。
3. 正文上界 = 30 × 164 = **4,920 字符**。
4. 字符→token 取**最保守**实测比 = **2.369**（512 token 只写出 1,213 字符；另一端 1,310 字符
   ⇒ 2.559 更"省字符"，不取它）⇒ 正文 ≤ ceil(4,920 / 2.369) = **2,077**。
5. + JSON 信封（外层数组与键名的括号/引号/逗号）**32** = 2,109。
6. 向上对齐 256 的倍数 ⇒ **2,304**（余量 9.2%；对齐是工程惯例，不冒充精度）。

交叉校验：W7 独立夹逼给 620–1,900 token（**乐观端**换算），本值在悲观端之上 —— 一致。

⚠️ 放大 `max_tokens` **不增加成本**（计费按实际 token），但会抬高 `budget.estimate_for_payload`
的 pre-flight 估算 —— 那是**修正**：旧值把 L4 的输出成本估小了。若它让 §10.4 成本闸更常告警，
那是真实成本的显形，不是回归。

### 15.3 有意未做：不 raise `LlmTruncated`

`app/binding/l4.py` **刻意没有** `except LlmError`（`:179-180`；`:209` 预留"裁定后改 3 行"）。
在 client 层 raise 会穿过 `l4.py` → `bind.py:96` 的 `except LlmError` → 终态 `error`，
**把 L4 的 fail-safe（N-27 ④）变成硬失败** = 产品行为变更，得先由 W3C 那 3 行接住。
⇒ 本轮只做**零控制流风险**的可观测性。raise 版归 **W3C + 架构**（见 `RELAY.md` 同节）。

### 15.4 判据与正向对照（**不靠"现状绿"**）

新增 `tests/unit/test_llm_router.py::TestL4ScoreBudgetIsCalibratedFromMeasurement`（6 条）：

- 覆盖断言：`hint >= 最坏所需`（实测 2304 ≥ 2109）；
- **正向对照**：`512 必须过不了上面那条` ⇒ 本组具备"注入违规 → 必须红"的判别力；
- 契约硬顶**真是 30**（否则前两条会在错误的宽松前提上继续变绿）；
- 对齐粒度、上限不失控（≤ 4 倍）两个反向对照；
- **前提守卫**：L4 **非思考** ⇒ `hint` 就是全部预算（若将来开思考位，`THINKING_HEADROOM_TOKENS`
  会自动叠加、把覆盖断言**悄悄放宽** ⇒ 这条先红）。

正向对照探针 `reports/w3a/_probe_l4_budget_positive_control.py`（内存注入，不碰磁盘、不连网）：

```
注入 512 → 1 failed（正是覆盖断言）→ 探针 exit 0 = 判别力 OK
不注入   → 6 passed
```

探针自身也只认 `pytest.ExitCode.TESTS_FAILED`（=1）：把"零收集 / 收集错误"这类非 0 退出
排除在"如期被拦住"之外 —— 否则探针会用"测试根本没跑起来"骗过自己。

### 15.5 门禁（本窗口职责）

```
../.venv/Scripts/python.exe -m ruff check .      → All checks passed!
../.venv/Scripts/python.exe -m mypy app          → Success: no issues found in 147 source files
../.venv/Scripts/lint-imports.exe                → Contracts: 4 kept, 0 broken.
pytest tests/unit tests/contract tests/redteam tests/eval tests/graph_snapshot
                                                  → 2204 passed
```

⚠️ **范围诚实**：`tests/integration/**` **未跑**。7 个文件要求一次性 DSN env
（`COMMERCEQL_TEST_SUPER_DSN` / `COMMERCEQL_TEST_RW_DSN`；U-114 防线①：缺 env 必须 error、
禁止 skip），本机不指向共享库 ⇒ 留给 CI。本改动面 = `app/llm/**`（L1，无下游 import 面），
集成面理论上与本次无关；**但这是"未验证"，不是"已验证无关"。**

⚠️ 同一工作树里还躺着**别的窗口未提交的在制品**（W4 的 `U-129`：`app/graph/build.py` +
`tests/contract/test_graph_timeout_contract.py`）。本次提交**逐路径暂存**，未扫入它们；
上面 2204 passed 是在**含**这些在制品的树上跑的 ⇒ 它们的用例也是绿的，但其正确性归 W4。

### 15.6 活体验收（W7 第十八轮，镜像 `0928r10`，`71c0461`）—— ✅ 通过

W7 热臂 `c=50/n=120` 对 `e1ea13a`+`1036295` 的验收读数：

| 判据 | 读数 | 判 |
|---|---|---|
| `llm_call` 完成原因 | **225/225 `finish_reason=stop`** | ✅ 无截断 |
| `l4_score` 单请求最大输出 | **775 tok**（旧 512 档这一格**必截**） | ✅ 2304 有余量 |
| 命中上限档 | `@2304 = 0`、`@512 = 0` | ✅ 两侧都不贴顶 |
| `bind.l4` 降级行（13:40Z 之后） | **0**（全库累计 20 行**全属修复前**） | ✅ |

⚠️ **口径边界（W7 与我一致）**：`bind.l4` 那个出口**只覆盖跑到 `present` 的请求** ⇒
"降级行为 0"是在一个**低覆盖**载体上读的；其余判别力由 ② 的 `llm_call`
成功路径承担（**225/225 覆盖**）—— 两条合起来才是 100%。**单独引用任一条都会高估或低估。**

⚠️ **且这个覆盖率本身要带臂别，别用一个数概之**（两个臂、两个值，都已实测）：

| 臂 | 口径 | 覆盖 |
|---|---|---|
| 修复前（W7 第十七轮） | 有资格走 present 的 run 数 / 总 run | `20/96 ≈ 21%` |
| 修复后热臂（W7 第十八轮） | `admitted 86` 里**只有 8 条**有资格 | `8/86 ≈ 9.3%` |

⇒ 引"降级行 = 0"时**必须同时写臂与覆盖率**（W7 已按此写进它的 README §三.0.1o/§三.0.1p）。

**两处输入订正（都不影响本改动）**：

1. W7 上轮给的 `p50 15.8` **标签错**（那行打的是 `mean`）⇒ 真值 **p50 17.0**。
   `p95 22` / 硬顶 `30` 不变。⇒ **2304 的推导不受影响** —— 它只吃"硬顶 30"与"每项 164 字符"，
   p50 在推导里**只作背景描述、从不参与运算**。已同步订正 `router.py` 注释与本文上一节。
2. 新 `H ≈ 6.18s`（+3.2%）已由 W7 交架构 `U-126` 配平表 —— **归架构，不在本窗口。**

### 15.7 移交：**"L4 在场"已验，"L4 更准"没有窗口在测**（→ W3C / 评测侧）

W7 明确只验了前者（对，它的窗口边界就到"在场"）。补一句**已核过的事实**，
免得下游以为要从零建载体（**结论：不需要新建任何载体，即不需要改契约、不需要架构裁定**）：

| 要素 | 现状 | 位置 |
|---|---|---|
| **实际绑出的列** | ✅ 已落库 | `query_plan.plan_summary` 的 `dimensions` / `metrics`（`repo/query_plan.py:44-48` 定义其结构） |
| **整查询的绑定态/层** | ✅ 已落库，**生产路径真装配** | `deps.py:782` `query_plan_writer = QueryPlanStore(pools.metadata)`；`bind.py:153` 写入 `result.state` / `result.layer` |
| **分布计数器** | ✅ W0 已落、W4 已接 | `binding_state_total{state}` / `binding_layer_total{layer}`（`deps.py:563-564`） |
| **标准答案** | ✅ 已有 | `eval/gold_query_seed_v1.json` + `eval/build_gold_seed.py` |

⇒ **口径建议**：以 gold 的期望列为准，与实际 `plan_summary` 比对，**按 `binding_layer=L4` 分桶**
得出"L4 在场但绑错"率 —— 这才是"L4 更准"，与"L4 在场率"是两个量。

🔴 **必须同时写下的粒度限制（否则该口径会被误用）**：

- `binding_state` / `binding_layer` 是**每查询一个标量**（`task_id` 是主键、一行一任务；
  `bind.py:153` 传的是 `resolve_detailed` 的**聚合**结果）⇒ **无法把某个具体错列归因到 L4**，
  只能到"整查询"粒度。
- `CandidateRef` **没有打分器标识字段**（`bind.py` 模块 docstring §15–18 自己写明）⇒
  绑定之后再看候选，**分不出它是 L1 命中的还是 L4 打分的**。⇒ 想做概念级归因，
  得先动 `CandidateRef`（**契约变更 ⇒ 需架构裁定**，本窗口不擅动）。

⇒ **本条属 W3C / 评测侧的交付面**（`eval/**` 不归 W3A）。本窗口只交出上面的事实与边界，
**不代建**（跨窗越界建 eval 口径会与 W3C 的 harness 设计撞车）。

⚠️ **上面这段的第 2 句已被 §15.8 订正**（路由要精确到 W6/W1A，且"不需要新建"只对观测侧成立）。

### 15.8 订正：§15.7 的"现成件"**只覆盖观测侧**，**期望侧是空的**（→ W6 执行器 + W1A 内容）

§15.7 我写过"载体全部已存在 ⇒ 不需要新建指标、不需要契约变更"。**那句只对一半**，
按红线当场订正：它说的是**观测侧**（L4 **做了**什么），**没有覆盖期望侧**（L4 **应该**做什么）。

**期望侧实测为空**（全仓 grep，2026-09-29）：

| 查法 | 结果 |
|---|---|
| `grep -rn "expected_bind\|expected_column\|gold_binding\|expected_concept"`（`eval/` + `backend/`） | **0 命中** —— 全仓**没有"期望绑定"这一概念** |
| `eval/*.json` 的 `expected_*` 字段全集 | 只有 `expected_behavior`(191) / `expected_outcome`(66)，都是**行为类**（`execute`/`clarify`/`refuse`），不是绑定 |
| 冻结集里最接近的两样 | `must_contain` / `must_not_contain` = **SQL 文本子串**；`gold_result_cols` = **结果列** |

⇒ 这三者**都表达不了**"概念 X 应绑到列 Y"，也**都归不到 L4**。`must_contain` 只能**间接**抓错列
（错列 ⇒ 必要的 SQL token 缺席），是**弱代理**且**整查询**粒度 —— 拿它当绑定质量口径会**高估**覆盖。

**⇒ 路由订正**（§15.7 写的"W3C / 评测侧"太粗，实际是两半、归两个窗口）：

| 半边 | 归谁 | 依据 |
|---|---|---|
| **执行器**（怎么跑、怎么比对、怎么出报告） | **W6**（阶段 6 评测与门禁；`eval/**` 的**执行器**部分唯一所有者，唯一有权出 G-1…G-8 判定） | `reports/w6/PROMPT.md` §一 |
| **内容**（"期望绑定"这份 ground truth） | **W1A**（内容资产所有者；`gold_query_seed_v1.json` / `dataset_v1_frozen.json` 带 `content_hash`） | `gold_query_seed_v1.json` 头部的 `derived_from_content_hash` |

🔴 **且这是一次"内容 + 冻结"决策，不是"写个比对脚本"**：gold 资产是
`derived_from` 冻结集、且带 `content_hash` 的（N-13 —— **任何一处改动都会让"冻结集"不再是冻结集**）
⇒ 新增"期望绑定"必须走**新资产 / 新冻结版本**，**不能就地改冻结件**。
**这才是"L4 更准"至今没有窗口在测的真正成本** —— 不是没人想测，是**缺 ground truth**。

⚠️ **另有一处口径未定，留给认领方定（别默认）**：`plan_summary.dimensions`/`metrics` 是
**语义计划的概念名**，而"期望绑定"若写成**物理列名**，两者**不是同一套词汇表**
⇒ 需要一份"概念 → 物理列"映射，**或**把期望直接写成概念级。**这个选择本身是设计决策**，
本窗口不代选。
