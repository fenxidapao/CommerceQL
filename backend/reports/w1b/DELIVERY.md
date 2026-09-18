# 阶段 1B · 骨架 —— W1B 交付与交接说明

> 生成时间：2026-09-16（本机实测）
> 归属窗口：**W1B**（`app/auth/**`、`app/repo/**`、`graph/build.py`、`graph/state.py` + 随附测试）
> 交付范围：docs/08 §3.3 的产出 ①–⑦ 与 DoD ①–⑤
> ⚠️ 本文件是**交付说明**，不是设计文档。设计归 `docs/07`；本文只写"盘上实际是什么状态"和"下一步谁做什么"。

---

## 0. 结论先行

| 项 | 状态 | 一句话 |
|---|---|---|
| 产出 ①–⑦ | ✅ 全部落码 | 认证链路 / TrustedContext / 审计两段式 / 图装配骨架 / checkpointer+三池 / 会话锁 / 限流分桶 |
| DoD① 空链路可跑通 | ✅ | 桩节点图可 `ainvoke`，checkpoint 落 `lg` 表族（T-A1 已证） |
| DoD② `/healthz/ready` → 200 | ❌ **503** | 硬依赖 3/4 已真；**卡在 `semantic_bundle_loaded`（归 W2A）**，不是本窗口缺陷 |
| DoD③ T-A1 20 并发压测 | ✅ | 见 `backend/reports/t-a1/`（`summary.json` / `op_timings.csv` / `samples.csv`） |
| DoD④ 三池互不串用 | ✅ | 装配期断言 + 集成侧 `application_name` 实测双证 |
| DoD⑤ `app_rw` 改删审计表必败 | ✅ | 权限层 4 动词逐项 + 触发器层（属主身份绕开权限）双证 |
| 门禁 `pytest` | ✅ **402 passed / 0 failed**（2026-09-16 19:55 终测） | U-39 已由 W0 修（`conftest.py` Selector fixture，commit `c63f67a`）；U-38 租户维度已由 W1B 接线关闭 |
| 门禁 `lint-imports` | ✅ 3 kept, 0 broken | ⚠️ 假绿调用形态（U-41）**已由 W0 在 CI 侧加存在性断言防复发**（同 `c63f67a`） |
| 门禁 `python scripts/assert_importlinter.py` | ✅ DoD② 通过 | 3 条契约均"注入→必红→还原→必绿" |
| 门禁 `ruff check .` | ✅ **All checks passed!** | 首次交付时的 5 条红（W0 在制品，U-44）**已由 W0 自行修复** |
| 门禁 `mypy app` | ✅ 54 files clean | 门禁范围是 `app`；`mypy app tests` 另有 14 条，全在 `tests/contract/*`（W0），非门禁范围 |
| **DoD④ 阻断项（密钥扫描）** | ✅ **已修** | `alembic.ini` / `env.py` 的兜底口令 DSN 已删，改读环境变量；全仓重放未放行命中 **0** 条（U-45，见 §4.11） |
| **启动容错 + 探针不再无限等待** | ✅ **已修**（B4 引入的两个回归） | 修复前 **CI 的 DoD③ job 每次都会红**、`/healthz/ready` 要 **35.8s**；详见 §4.12 |

**一句话**：本窗口的代码与断言**全绿（402 passed / 0 failed）**；唯一未达的 DoD② 是**上游未就绪**（W2A 语义包），不是本窗口缺陷。历史遗留红（U-39）已由 W0 关闭。

> **2026-09-16 19:55 提交说明**：W1B 全部产物以两个提交落库（W2A 开工的前置条件）——
> `feat(w1b)` 代码+测试、`docs(w1b)` 交付/转述件与 T-A1 数据。提交前补齐了 W0 在
> `c63f67a` 里指名归 W1B 的 **U-38 接线**（限流租户维度，注入对照已做）。

⚠️ **本轮（11:00–11:35）最重要的一条**：复核时发现 B4 让 `lifespan` 第一次做真 I/O，
于是"依赖连不上"被当成**致命** → **CI 的 `contract-tests` job（ubuntu，无 PG/Redis、无 DSN）每次都会红**。
这是本轮唯一一个**会让 CI 挂掉**的缺陷，且它**与 U-39 无关**（Linux 无事件循环问题），
所以不会被已有的 2 条红掩盖。已修（`app/repo/reachability.py` + 三态放行），
并用"无 DSN 条件 + Selector 循环"做了对照实验：修复前 2 failed → 修复后 2 passed。见 §4.12。

---

## 1. 交付物

### 1.1 本窗口新建（`git status` 显示为 untracked，尚未提交）

| 路径 | 内容 |
|---|---|
| `app/auth/context.py` `errors.py` `jwks.py` `revocation.py` `tokens.py` | 07 §13.1 七步认证链路 + `IdentityContext` 构造 + 吊销表 |
| `app/repo/dsn.py` `pools.py` `redis.py` | 两条 DSN 唯一入口 / 三池装配与互不串用断言 / Redis 唯一构造点 |
| `app/repo/migrations/` | `0001` 迁移（`app.audit_log` + `audit_log_supplement` + 权限 + 触发器） |
| `app/repo/startup_assertions.py` | 4 项启动断言（三态 PASS/PENDING/FAIL + prod env-gate） |
| `app/repo/health.py` | 3 个硬依赖探针（metadata / checkpointer / redis）**产出**（注册归组装根） |
| `app/repo/audit_store.py` | 审计落库（**只 INSERT**，列白名单，身份与 payload 结构分离） |
| `app/graph/build.py` `graph/state.py` | `GraphState` + 图装配骨架（节点用桩）+ `ensure_checkpoint_schema` |
| `app/cache/session_lock.py` | 会话串行锁（SET NX PX + 持有者校验 Lua） |
| `app/api/ratelimit.py` | 精确滑窗限流（ZSET + Lua，§9.2 分桶） |
| `app/api/deps.py` | 运行时装配 + 限流拦截 + 会话锁守卫 |
| `scripts/probe_checkpoint_pool.py` | T-A1 压测脚本（**已用 Selector 循环**，见 U-39） |
| `alembic.ini` | 迁移工具配置（**本轮已删 `migration_url` 字面量**，见 §4.11） |
| `tests/unit/`（10 个测试文件 + `_redis_fake.py`） | 离线断言 |
| `tests/unit/test_migration_dsn_hygiene.py` | **2026-09-16 新增**：DoD④ 的本机替身（全仓重放真实规则）+ 迁移 DSN 出处纪律（§4.11） |
| `tests/unit/test_reachability_and_startup_tolerance.py` | **2026-09-16 新增**：「连不上 ≠ 不合格」的区分 + `InterfaceError` 不得被误归（§4.12） |
| `tests/integration/test_audit_append_only.py` | 库侧无改删自证 + 三池 `application_name` |
| `tests/integration/test_real_redis_lock_and_ratelimit.py` | **真 Redis** 上的 Lua 语义自证（新增） |
| `reports/t-a1/` `reports/w1b/DELIVERY.md` `reports/w1b/RELAY.md` | T-A1 数据 + 本文件 + 逐窗口转述件 |

### 1.2 本窗口改写（`git status` 显示为 modified）

| 路径 | 改动 | ⚠️ 归属提示 |
|---|---|---|
| `app/main.py` | lifespan 六步顺序（日志→τ 告警→三池/Redis→启动断言→开池+建表族→注册探针） | `main.py` 是 Q-15 的"清单外必需文件"，**归属仍未登记**（U-42） |
| `app/obs/audit.py` | 实现 `AuditWriter`（两段式阻断性） | ⚠️ §4.1 把 `app/obs/**` 划给 **W0→W7**。本次是依**用户裁定 `2.b`/`3.a`**（审计写入落 `obs/audit.py`）而重写，**需 W0/W7 追认**，不得两边各留一份（U-43） |
| `.gitignore` | 忽略产物/密钥 | — |

---

## 2. 实测证据（可复现）

### 2.1 启动断言链（用 Selector 循环跑真实 I/O）

```
startup_assertion            analytics_dsn_is_read_only
  → PASS  角色 'app_ro'：非超级用户且 default_transaction_read_only=on
startup_assertion            audit_log_append_only_enforced
  → PASS  角色 'app_rw'：INSERT ✅ / UPDATE ❌ / DELETE ❌ / TRUNCATE ❌ 且触发器在位
startup_assertion_pending    embedding_dim_matches_vector_column
  → PENDING  向量列 app.embed_doc.embedding 尚不存在（归 W2A）
startup_assertion_pending    semantic_bundle_passed_five_step_validation
  → PENDING  五步校验器未接线（归 W2A）
startup_assertions_done      passed=2  pending=2
health_probes_registered     wired=[metadata_db, checkpointer, redis]
                             still_unwired=[semantic_bundle_loaded, llm, embedding]
```

**两项 PASS 是"连真库跑出来的"**，不是离线自证：`app_ro` 真的只读、`app_rw` 真的改不动审计表且触发器在位。

### 2.2 `/healthz` 三端点的**实际**响应

| 端点 | 码 | 关键 payload |
|---|---|---|
| `/healthz/live` | **200** | `{"status":"ok","uptime_s":0,"event_loop_lag_ms":null}` |
| `/healthz/ready` | **503** | `checks={"redis":true,"checkpointer":true,"metadata_db":true,"semantic_bundle_loaded":false}` |
| `/healthz` | **503** | `degraded_dependencies=["llm","embedding"]`、`graph_compiled=false` |

**读法**（不要误读）：
- readiness 的 503 **只由 `semantic_bundle_loaded` 一个 false 造成** —— 另三个硬依赖已真。相比阶段 0 的"4/4 false"，这是实质进展；但仍**不是** DoD②。
- `/healthz` 的 503 是因为"硬依赖里有失败项"（语义包）。软依赖 `llm`/`embedding` 已正确分列在 `degraded_dependencies` —— 它们**没有**污染 readiness（N-21）。
- `event_loop_lag_ms: null`、`bundle_version: null`、`graph_compiled: false` 是**如实上报**，不是缺口掩盖（采样器归 W7、语义包归 W2A、图接线归 W4）。

### 2.3 测试计数

| 文件 | 条数 | 说明 |
|---|---|---|
| `tests/unit/test_startup_assertions.py` | 29 | 含"PENDING 仅在 prod 致命"的**双断言**钉死 |
| `tests/unit/test_audit_writer.py` | 26 | **本窗口新补**（见 §4.6） |
| `tests/unit/test_ratelimit.py` | 20 | 18 → **20**（U-38 接线：租户维度生效的存在性证明 + ADMIN 零租户上限；注入对照已做） |
| `tests/unit/test_deps_wiring.py` | 18 | **本窗口新补** |
| `tests/integration/test_real_redis_lock_and_ratelimit.py` | 15 | **本窗口新补**（真 Redis Lua） |
| `tests/unit/test_health_probes.py` | 15 | 10 → **15**（2026-09-16 加 §6「不得无限等待」5 条，见 §4.12） |
| `tests/unit/test_reachability_and_startup_tolerance.py` | 14 | **2026-09-16 新增**（「连不上 ≠ 不合格」的区分 + `InterfaceError` 不得被误归，见 §4.12） |
| `tests/unit/test_session_lock.py` | 13 | 离线（`FakeRedis`，控制流） |
| `tests/unit/test_migration_dsn_hygiene.py` | 7 | **2026-09-16 新增**（DoD④ 的本机替身 + 迁移 DSN 纪律，见 §4.11） |
| 其余（auth / pools / contract / redteam / graph_snapshot） | 231 | — |
| **合计** | **384 passed / 2 failed** | 两红见 U-39（2026-09-16 11:30 复测） |

真 Redis 用例里**最值钱的三条**（替身做不到）：
1. 10 个并发 `acquire(wait_ms=0)` → **恰好 1 个拿到锁**（`SET NX` 原子性直接检验）；
2. **A 的迟到 `release` 不得删掉 B 的锁**（先用真 TTL 到期造出"锁易主"状态，再让 A 释放）；
3. 限流时间戳来自**服务端 `TIME`**（与 `client.time()` 比对），且 `numkeys=2` 的**契约位序**直接调真脚本验证。

---

## 3. 门禁实测（原样记录，含一条假绿陷阱）

> 下表为 **2026-09-16 19:55** 终测值（提交前，含 U-38 接线）。历史复测值（10:36 / 11:30）保留在行内说明里。

| 命令 | 结果 |
|---|---|
| `pytest` | **402 passed, 0 failed**（18.31s，真 PG/Redis 在位；此前 384+2 failed 的两红 = U-39，已由 W0 关闭） |
| `lint-imports`（**console script**） | `Analyzed 52 files, 67 dependencies.` → `R-DEP-1 KEPT` / `R-DEP-2 KEPT` / `R-DEP-3 KEPT` → `Contracts: 3 kept, 0 broken.` exit 0 |
| `python scripts/assert_importlinter.py` | `DoD② 通过`（3 条契约均证明"脏了必红"）；跑完无残留探针文件（已核 `backend/app/`） |
| `ruff check .` | **`All checks passed!`**（首次交付时的 5 条红由 **W0 在并行窗口修复**，原记录见 §4.10；本轮的 8 条由 W1B 自行修净） |
| `mypy app` | `Success: no issues found in 54 source files` |
| `mypy app tests`（非门禁范围） | 14 条，全在 `tests/contract/{test_config_failfast,test_dependency_whitelist,test_contract_counts}.py`（W0 独占文件） |
| 全仓重放 DoD④ 规则（本机替身，见 §4.11） | 未放行命中 **0 条**；放行命中 11 条（均为路径/占位放行） |
| `ruff format --check`（**非门禁**，仅记录） | 32 files would be reformatted —— 与 HEAD 一致的历史状态，`ci.yml` 未把它列为门禁，本轮不动 |

### ⚠️ U-41：`python -m importlinter.cli lint-imports` 是**假绿**

实测（本次亲历）：

```
$ python -m importlinter.cli lint-imports     # ← 无输出、exit 0、什么也没验
$ lint-imports                                # ← 真结果：3 kept, 0 broken
```

根因：`site-packages/importlinter/cli.py` **没有 `if __name__ == "__main__"` 守卫**（实测 `grep -c "__main__"` = `0`），所以以 `-m` 形态运行时它只是被 import 然后退出。
**危害**：任何人把 `python -m importlinter.cli lint-imports` 写进 CI，会得到一条**永远绿、且永远不检查任何东西**的步骤 —— 正是"护栏自己坏掉"这一类最贵的故障。
**缓解**：`ci.yml` 已用的是 `lint-imports`（正确）；建议在 README/交付说明里明写"**禁止**以 `-m importlinter.cli` 形态调用"，并考虑给 CI 加一句"输出必须含 `Contracts: N kept`"的存在性断言。

---

## 4. 实测暴露的限制与未解决风险（**红线区，不得当已完成**）

### 4.1 U-39 —— Windows 宿主跑不了 async psycopg（**当前 2 条红测试的根因**）

- **现象**：`tests/contract/test_obs_audit_contract.py` 的 2 条用例（都 `TestClient(create_app())`）红：
  `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.`
- **根因**：B4 让 `lifespan` **第一次做真实 I/O**（启动断言 + 探针要用 psycopg async）。Windows 默认事件循环是 `ProactorEventLoop`，而 psycopg async 在 Windows **只支持 `SelectorEventLoop`**。`TestClient` 走 anyio 的默认循环 → 撞上。
- **已做的对照实验**：把策略设成 `WindowsSelectorEventLoopPolicy()` 后，**同一份代码完全正常**（§2.1/§2.2 的日志就是这么跑出来的）→ 排除断言逻辑本身的问题。
- **性质判定**：B4 **没有引入新缺陷**，它**暴露**了一个一直存在的环境不兼容 —— 附录 D `E-1` 早已写"开发期即用 Docker 跑后端"，但那条缓解措施**没有落到测试装置里**。
- **影响面**：Docker/Linux（`commerceql-api-1`）**不受影响**；T-A1 压测脚本 `scripts/probe_checkpoint_pool.py:786` 早已自行用 `loop_factory=SelectorEventLoop`，也不受影响。**唯一受影响的是"在 Windows 宿主直跑 API / 跑会触发 lifespan 的测试"**。
- **建议修法（归 W0，本窗口不动）**：`tests/conftest.py` 加一个会话级 autouse fixture，仅 `win32` 下 `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`。
  ⚠️ **刻意不做**的替代方案：把启动断言的 psycopg 连接改成 `asyncio.to_thread` 里的同步连接。那能让测试变绿，但会把"应用在 Windows 宿主根本跑不起来"这个事实**藏起来** —— 属于修症状留病因，不做。

### 4.2 U-38 —— 限流的 `per_tenant` 维度**未启用**（真实削弱）

四个桶的**租户级**上限（`100/1200/300/min`）当前**无人执行**。原因：`app/cache/keys.py`（W0 持有、§11.2 硬规则 3 禁止裸拼键）**没有租户级键构造函数**。
`app/api/ratelimit.py` 用 `UNENFORCED_DIMENSIONS` 显式登记，并**主动拒绝**"启用租户维度却复用用户键"（那会让脚本在同一 ZSET 上判两次 → 限流忽然变极严且不报错）。
**必须说清**：这不是"降级"（租户级配额**从未生效过**），但它**是**一条真实的安全面削弱。

### 4.3 `GLOBAL_CONCURRENCY` 桶**未实现**，且**刻意不提供近似值**

`check()` 遇该桶直接抛 `LimiterNotImplemented`。理由：它的语义是**并发租约**（§9.5，依赖 SSE 生命周期 → W4），用 60s 滑窗近似会把"100 个长连接挂着不结束"判成正常 —— 而那正是该桶要防的。**P0 期间该桶的保护事实上不存在**。

### 4.4 软依赖探针**未接线**（`llm` / `embedding` / `semantic_bundle_loaded`）

未接线槽位由 `health._unwired_probe` **如实上报 `healthy=false`**，不谎报健康（N-21）。
⚠️ 这带来一个**必须让 W7 知道**的效果：`/healthz` 此刻恒为 `degraded` 或 `unhealthy`。这是如实状态，不是缺陷。

### 4.5 探针**不做任何日志**（信息损失，已登记）

`app/repo/health.py` 在 L0，不得 import `app.obs`（L1，反向依赖）。因此失败时 `detail` 只放**异常类名**，完整异常正文留在端点层。
代价有二，都需 W7 收口：① 排查时服务端看不到探针失败的根因；② 这是**刻意**的（避免 psycopg 报错把 DSN/用户名回显到可能未鉴权的 `/healthz`，N-11 精神）。

### 4.6 `tests/unit/test_audit_writer.py` 此前**根本不存在**（影子承诺，本次兑现）

`app/obs/audit.py` 与 `app/repo/audit_store.py` 的文档字符串都写着"由 `tests/unit/test_audit_writer.py` 静态断言"，**盘上没有这个文件**。同型事故在本项目已发生第二次（第一次记录在 `tests/conftest.py` 的文档字符串里）。
→ 本次补齐 26 条，覆盖两个文件：无改删 SQL（`ast` 扫描）、无改删方法（动词词根）、**白名单与绑定同源**、身份列结构上不可覆盖、段 1 fail-closed（保留异常链）vs 段 2 永不抛 —— 含"两段刻意不同"的钉死用例。

### 4.7 `audit_log` 仍是**普通表**而非分区表

迁移 `0001` 出于"P0 数据量远达不到归档量级 + 分区会引入『下月分区谁建』的运维依赖"**刻意未做**，且写明了触发条件与连带改动（PK 必须含分区键 → 段 2 的 FK 要改）。`repo/audit_store.py` **不假设分区存在**。属**已知缺口**，不是遗漏。

### 4.8 `/healthz.ready` 与 DoD② 的判定时序（U-40，需架构窗口确认）

DoD② 的原文是"`/healthz/ready` 转 200"。但 `semantic_bundle_loaded` 是**硬依赖**（`DEPENDENCY_KIND` 定死），而语义包归 W2A。**结论：在 1A 交付语义包之前，DoD② 物理上无法达成。**
→ 需要架构窗口一句话裁定：**DoD② 在阶段 1B 应记为"被 1A 阻塞（已符合预期）"，还是必须等 1A 完成后才结项？**（用户此前已口头裁定 `1.b`：接受部分达成，但该裁定**尚未落进 docs/08**。）

### 4.9 任务归属未登记的文件（U-42）

以下**清单外必需文件**由本窗口创建/改写，§4.1 归属表中**查不到**，需补登记（否则出现第二个"谁都能改"的文件，U-18 的教训立刻重演）：

`app/api/deps.py`、`app/api/ratelimit.py`、`app/cache/session_lock.py`、`app/repo/redis.py`、`app/main.py`、`backend/alembic.ini`、`backend/scripts/**`、`backend/reports/**`。
其中 `deps.py` / `ratelimit.py` 已在文件头写明"归属待裁定，若归 W4 则整体移交，不得两边各留一份"。

### 4.10 `ruff check .` 当前 5 条红在 **W0 的在制品**里（U-44）

`backend/tests/contract/test_dependency_whitelist.py` 工作区版比 HEAD 多 **156 行**（HEAD 209 行 → 365 行），新增内容是关于"一次性扫出 5 个传递依赖冒充直接依赖"的检测。
**取舍已核实**：`git show HEAD:<该文件> | ruff check -` → `All checks passed!`，即这 5 条**是那 156 行引入的**，不是历史遗留。同时 `git status` 显示该文件与 `backend/pyproject.toml` 均为 modified。
→ **W1B 一行未碰**（这是 W0 的独占文件，且正在被改；此刻落笔就是 U-18 场景）。仅登记：**若以当前工作区跑 CI，`ruff check .` 会是红的。**
→ **2026-09-16 10:36 复测：W0 已在并行窗口修完，`ruff check .` = `All checks passed!`。U-44 可关闭**（本窗口未参与修复，保持"不动别人在制品"的纪律）。

### 4.11 ✅ 已修复：`alembic.ini` / `migrations/env.py` 的兜底 DSN（**原为 DoD④ 阻断项**，U-45）

**问题（W0 转达，本窗口复核成立）**：两处各有一个**带属主口令**的 DSN 字面量 ——
`alembic.ini` 的 `migration_url`、`env.py` 的 `_DEFAULT_MIGRATION_URL`。
它不是占位符：与 `deploy/docker-compose.yml` 的 `POSTGRES_USER/POSTGRES_PASSWORD` **同值、可用**。
两文件都在 `.gitleaks.toml` 的 DSN 规则命中范围内且**未被放行** → 一旦提交，CI 的 DoD④ 必红。

**复核方式（不靠读代码下结论）**：把 `.gitleaks.toml` 里那条 `commerceql-dsn-with-password`
的正则 + `[allowlist]` 语义（路径 / 正则 / 停用词三层）**在本地重放**，逐文件标注"放行 / 会红"。
修复前实测：`alembic.ini:29`、`env.py:33` 均命中 gitleaks 的 DSN 规则且**未被放行** → **会红**
（形态 = `postgresql+psycopg://` + 属主名 + `:` + 口令 + `@` + 主机；本文档**刻意不复述具体值** ——
第一版在这里把原值抄了一遍，新增的全仓重放护栏立刻把**本文档**标成 DoD④ 命中项。文档是最容易漏的一处）。

**修法（按 W0 明确要求：删字面量、只读环境变量，不走 allowlist）**：

| 文件 | 改动 |
|---|---|
| `backend/alembic.ini` | 删除 `migration_url` 键（**整键删除，不是留空** —— 没有消费者的键就是下一个 U-23）；顶部改为声明"本文件刻意不含默认 DSN"及两条理由 |
| `backend/app/repo/migrations/env.py` | 删除 `_DEFAULT_MIGRATION_URL`；`_migration_url()` 只读 `MIGRATION_DATABASE_URL`，取不到即抛 `RuntimeError`（**fail fast**，不尝试连接） |

**两条设计取舍（值得写下来，否则会被"优化"回去）**：
1. **为什么不留一个"看起来像占位符"的默认值**：任何 DSN 形态的字面量都会被规则命中；
   要让它不红就只能进 allowlist —— 而那正是"把可用口令合法化"，等于把 DoD④ 从检查降级成装饰。
2. **为什么删默认值反而更安全**：忘了设变量时，**安静地连上"某个"库**比连不上更贵 ——
   本迁移要 `CREATE ROLE` / `GRANT`，**不可逆**。宁可起不来。

**行为验证（三条，均已实测）**：

| 场景 | 结果 |
|---|---|
| `alembic history` / `heads`（**不需要 DSN**） | 仍可用 ✅（撤默认值没有"把 alembic 弄坏"） |
| `MIGRATION_DATABASE_URL=<属主 DSN> alembic current` | 返回 `0001 (head)` ✅（正常路径未受影响） |
| 不设变量跑 `alembic upgrade head` | **非 0 退出 + 点名缺失变量**，且**未尝试连接**（输出无任何 psycopg 连接错误）✅ |

**新增护栏** `backend/tests/unit/test_migration_dsn_hygiene.py`（7 条，含一次注入-还原对照）：
① 两个配置制品对**项目自己的规则**零命中（不套 allowlist，比 CI 更严）；
② `alembic.ini` 保持纯 ASCII（GBK 宿主上非 ASCII 会让 alembic 起步即崩）；
③ **allowlist 不得放行属主凭据**（把"不要用 allowlist 消红"这条原则本身钉成可执行物）；
④ `alembic history` 无需 DSN（正向对照）；
⑤ 无 DSN 时 `upgrade` 必失败且**不得已尝试连接**；
⑥ 全仓重放 DoD④ 规则 —— 本机 `gitleaks` **未安装**（实测 `command not found`），
   而这是 DoD④ 目前**唯一**的本机可跑替身。

> **这道护栏立刻证明了它的价值**：第一版被测文件自己把样本 DSN 写成了字面量，
> 全仓重放当即将它标为"**唯一的**未放行命中" —— 即"修完两个文件、又在新加的文件里种回同一个问题"。
> 若只跑单文件的断言（我最初就是这么写的，而且是绿的），这件事**根本看不见**。

**⚠️ 仍未解决的两处同类问题（如实登记，不在本次修）**：
- `deploy/.env.example` 的 `DATABASE_URL` / `ANALYTICS_DB_URL` 是**可用口令**形态的值，
  且该文件被 `.gitleaks.toml` 的 `allowlist.paths` **整文件放行** ——
  即"它对扫描器不可见"，而非"它安全"。归 **W0/W7**（`deploy/**`）。
- `migrations/versions/0001_...py:77–78` 有带默认口令的 DSN，但它是**已执行过的冻结制品**：
  改它会让"从零重建的库"与"已建成的库"产生不同角色口令 —— 那比现状更坏。**故刻意不动**。
  若要根治，正确做法是**新增**一个迁移或改为强制读环境变量，而不是编辑已应用的迁移。

---

### 4.12 ✅ 已修复：启动期「连不上」被当成致命 + 探针无限等待（**B4 引入的两个实质回归**）

> 2026-09-16 11:00–11:35。触发方式：复核 B4 时发现 `tests/contract/test_obs_audit_contract.py`
> 有 **2 条红**，追下去才发现它们指向两个**只有 CI 才会暴露**的问题。

#### 问题 A：CI 的 DoD③ job 每次都会红（**这是本轮最严重的一条**）

读 `.github/workflows/ci.yml` 的 `contract-tests` job：`runs-on: ubuntu-latest`，
**没有 PG/Redis 服务、也没有注入任何 DSN**。此时 `tests/conftest.py` 的占位 DSN
（指向 compose 服务名 `pg` / `redis`，在 runner 上**不可解析**）成为唯一来源。

B4 之前：`lifespan` 不做真 I/O，探针全为"未接线" → 这两条测试绿。
B4 之后：启动断言第一次真连库 → **连不上被当成致命** → 构造 `create_app()` 的用例全红。

**对照实验（决定性）**：

| 条件 | 结果 |
|---|---|
| 有 DSN + Selector 循环 | 2 passed |
| **无 DSN（= CI 真实条件）** + Selector 循环 | **2 failed** ← 修复前 |
| **无 DSN（= CI 真实条件）** + Selector 循环 | **2 passed** ← 修复后 |

→ 也就是说：**修复前，每次 push 的 CI 都会红**；而 Linux runner 与 U-39 无关，
所以这条**不会**被 U-39 掩盖。

**修法**：引入「连不上」与「答了但不合格」的**唯一分类点** `app/repo/reachability.py`，
并让三条 I/O 断言在"连不上"时判 **`PENDING`**（而非 `FAIL`）：

| 情形 | 判定 | 依据 |
|---|---|---|
| 依赖**答了**，但配置不合格（超级用户 / 审计表可写 / 维度不匹配） | **`FAIL`** → 拒绝启动，任何环境 | 07 §18.4 |
| 依赖**连不上**（未部署 / DNS 不通 / 池超时） | **`PENDING`** → 非 prod 放行 + `/healthz/ready`=503；**prod 拒绝启动** | 07 §18.2（摘流量不重启）+ §18.4.1（`live=200` 且 `ready=503` **必须可达**） |

**⚠️ 刻意没有归类"环境不兼容"**：`psycopg.InterfaceError`（Windows `ProactorEventLoop` 的典型报错）
**不是** `OperationalError` 的子类，且**故意不收进**「连不上」——
收进去会让 U-39 伪装成"库没起"：测试变绿、病因消失。
这条已有专门断言（`test_interface_error_is_deliberately_not_treated_as_unreachable`
与 `test_live_probe_does_not_hide_a_non_connectivity_failure`），
**即"U-39 必须继续红着"被写成了可执行断言**。

#### 问题 B：`/healthz/ready` 实测 **35.8s** 才作答（平台 5s 就超时）

根因是**同一个**：`pool.connection()` 未给 `timeout` → `psycopg_pool` 默认 **30s**。
两处各付一次：

| 位置 | 修复前实测 | 修复后实测 |
|---|---|---|
| `lifespan`（`ensure_checkpoint_schema` 取连接） | **33.11s** | **5.08s** |
| `GET /healthz/ready` | **35.84s** | **7.82s** |
| CI 条件下那 2 条契约测试 | **139s** | **28.9s** |

取值依据（**不是随手挑的**）：附录 D 的 `api.healthcheck` 写死 `timeout: 5s` ——
平台到点就把 `curl` 杀掉，**消费者只看到超时，读不到那个诚实的 503 体**。
故 `POOL_ACQUIRE_TIMEOUT_S = 2.0`（= 5s ÷ 3 个硬依赖，向上取整），
只作用于**探针与启动检查**的调用点，**不改池的构造默认值**（那会连带改变业务借用语义）。

**⚠️ 诚实边界（未解决，不粉饰）**：
1. **7.82s 仍 > 5s**。拆开看：2.0s（池等待）+ 2.92s + 2.92s（后两项是 **Windows `getaddrinfo` 失败本身的代价**，
   实测 `connect_timeout` 约束不了它，恒 2.92s）。也就是说 **5.84s 是环境代价，任何常量取值都消不掉** ——
   **证明这个常量不是达成 5s 契约的正确杠杆，`_collect` 并行化才是**。
   而 `app/api/routers/health.py` 归属 **W7**（文件头明确标注），故只登记、不越权修改（见 §7）。
2. **查询路径的池超时 / 重连策略刻意没动**：07 §14.4.1 已自述 `DB_UNAVAILABLE` 的 `Retry-After = 5s`
   **无机制推导**，并把"补 §8 的池超时与重连规则 → 复核该值"记在**架构窗口**名下（07 §20.1 第 8 项）。
   本窗口只在"必须快速作答"的调用点收口，不去改池的构造默认值。
3. `pool.close()` 在依赖不可达时有 **2s** 关停延迟（`退出 lifespan 2.00s`）。未追（关停路径，不在探针预算内）。

#### 本轮新增的护栏 —— 以及**负向对照抓到的两次假绿**

新增 `tests/unit/test_health_probes.py` §6（5 条）+ `tests/unit/test_reachability_and_startup_tolerance.py`（14 条）。
对 4 处注入全部做了「注入 → 必红 → 还原 → **比对 sha256** 必绿」，其中**两次抓到护栏本身无效**：

| 注入 | 第一次的结果 | 根因 | 修法 |
|---|---|---|---|
| 去掉 `app/graph/build.py` 的 `timeout=` | **绿 ❌** | 我在测试里也给**池构造器**传了 `timeout=2.0` → 测的是池的默认值，**不是调用点参数** | 夹具**不得**提供与调用点同名的参数值；改后注入必红 |
| 去掉 `app/repo/health.py` 的 `timeout=` | 红 ✅（侥幸） | 同上，只是恰好被"替身记录到 `None`"那条断言拦下 | 同上，一并改掉 |
| 掐掉三个 `_guarded` 之一 | 红 ✅ | — | — |
| 把 `InterfaceError` 收进「连不上」 | 红 ✅（2 条） | — | — |

→ **纪律**：凡断言"某参数被传下去了"，夹具/替身就**不得**给同一个参数提供值。
否则用例会**通过一个与被测对象无关的原因**，而负向对照是唯一能发现这件事的手段。

#### 该修复**没有**改变的东西（防止被读成"更宽松了"）

- **prod 仍然 fail-closed**：`PENDING` 在 `APP_ENV=prod` 下依旧致命，双断言已钉死
  （`test_unreachable_pending_obeys_the_same_prod_env_gate`）。
- **`FAIL` 仍无条件致命**，env-gate 只作用于 `PENDING`。
- **重写 `app/obs/audit.py` 那类越权事一次也没做**：本轮全部改动落在
  `app/repo/**`、`app/graph/build.py`、`app/main.py`（W1B 自有）+ 本窗口新建的测试。

#### 该修复**没有**解决的东西（→ 后续已解决）

- ~~**U-39 仍然红**~~ → **W0 已在 `c63f67a` 修复**（`conftest.py` 会话级 Selector fixture，
  且未走"吞 `InterfaceError`"的歪路 —— W1B 那条钉死断言通过）。
  终测 **402 passed / 0 failed**（2026-09-16 19:55，真 PG/Redis 在位）。

---

## 5. 已确认为 W0 完成、W1B 不再重复的工作

`git diff` 实测，以下已由并行窗口落地（对应此前裁定 `6.都钉` 与依赖显式化请求）：

- `langgraph==1.2.11`、`langgraph-checkpoint-postgres==3.1.2`（**已钉版本**）
- `psycopg-pool>=3.2` 显式声明（直接 import 点：`repo/pools.py`、`repo/health.py`、`graph/build.py`）
- `starlette>=0.40`、`python-dotenv>=1.0`、`pyyaml` 等 5 项"传递依赖冒充直接依赖"修复

→ **本窗口不再提交任何 `pyproject.toml` / `.importlinter` 变更**，也不重复登记。

---

## 6. 本窗口**刻意没有做**的事（范围边界）

| 没做 | 为什么 |
|---|---|
| 未改 `tests/conftest.py`（U-39 的修法） | W0 独占文件。本窗口只交出根因与建议 diff |
| 未改 `tests/contract/**` 的任何文件（含 5 条 ruff 红） | W0 独占，且正在被并行修改 |
| 未改 `pyproject.toml` / `.importlinter` / ADR | 归 W0；且 W0 已自己落地 |
| 未在 `core/errors.py` 里加 `RateLimited` | 归 W0；本窗口的 `RateLimited` 定义在 `api/deps.py` 并注明"若裁定应收进 core，则整体迁走，不得留两份" |
| 未实现 `GLOBAL_CONCURRENCY` 桶 / 未启用 `per_tenant` | 前者依赖 SSE 生命周期（W4），后者缺 W0 的键构造函数。**宁可抛 `NotImplementedError` 也不给假实现** |
| 未接线软依赖探针 | 归 W2A / W7（N-21 要求它们**不得**进 readiness） |
| 未做停机六步（摘流量 / drain SSE / 锁与审计收尾） | 归 W4/W7。`main.py` 的 shutdown 只释放本窗口创建的连接资源，**不替后续窗口假装做完** |
| 未给 `uvicorn` 加 Windows 循环策略兼容 | 那是部署形态问题（附录 D E-1 已定"用 Docker"）；在应用里偷偷改全局事件循环策略会改变所有窗口的运行时语义 |
| 未改 `deploy/.env.example`（`DATABASE_URL` / `ANALYTICS_DB_URL` 含可用口令形态） | 归 W0/W7（`deploy/**`）。且它被 `.gitleaks.toml` 的 `allowlist.paths` **整文件放行** → 属"扫描器看不见"而非"已安全"，口径要先由上游定 |
| 未改 `migrations/versions/0001_*.py` 的默认口令 | 它是**已执行过的冻结制品**。改它会让"从零重建的库"与"已建成的库"产生**不同的角色口令** —— 比现状更坏。根治应另开迁移，不改已应用的那个 |
| 未给 `.env` / `.env.example` 加 `MIGRATION_DATABASE_URL` 键 | 归 W7（`deploy/**`）。**但这条是 §4.11 改动的直接后果**：现在跑迁移必须先有该变量，见 §7 的 W7 待办 |

---

## 7. 交接给下一窗口（可直接粘贴的说辞）

> **给下一个窗口的开工说明（W1B → W2A / W4 / W0）**
>
> W1B（阶段 1B 骨架）已完成并冻结以下**稳定接口**，可直接依赖，除非有编号的裁定请求，否则不会变更：
>
> 1. `app/repo/pools.py` → `build_three_pools(settings)`，返回 `ThreePools(metadata, analytics, checkpoint)`；`checkpoint` 是 `psycopg_pool.AsyncConnectionPool`，**不是** SQLAlchemy 引擎。
> 2. `app/repo/startup_assertions.py` → `live_probes(settings, metadata_engine=...)` 返回 `StartupProbes`；`enforce_startup_assertions(settings, probes, logger)` 在失败时抛 `ConfigError`。**W2A 接语义包时，只需替换 `evaluate_semantic_bundle(validator=...)` 的注入点**（现有实现返回 PENDING 并指明归 W2A），**不要另写一份五步校验**。
> 3. `app/repo/health.py` → `build_probe_table(...)` 返回 **3 个硬依赖**探针；`semantic_bundle_loaded` / `llm` / `embedding` 三个槽位**归 W2A / W7**。注册动作在 `app/main.py`（组装根），L0 不得 import L5。
> 4. `app/api/deps.py` → `AppRuntime` / `get_identity()` / `check_rate_limit(req, bucket, ctx)`（抛 `RateLimited`）/ `session_lock_guard(req, ctx)`（`async with`，**释放点在 `finally`，含客户端断连**）。
> 5. `app/cache/session_lock.py` → `RedisSessionLock`；锁 value = `task_id`，持有者校验在 Lua 里；冲突抛 `SessionLockConflict`（**409，不是 429，且不带 `X-RateLimit-*`**）。
> 6. `app/repo/audit_store.py`（SQL，只 INSERT）+ `app/obs/audit.py`（策略，段 1 fail-closed / 段 2 不阻断）。**审计字段名漂移会当次报错**，不静默丢弃。
>
> **W2A 的开工前置（当前唯一阻塞 DoD② 的事）**：物化 `app.embed_doc.embedding`（pgvector 扩展当前**未安装**）+ 交付五步校验器。这两件事一落，启动断言的两项 PENDING 会自动转为可判定，`/healthz/ready` 才有机会转 200。
>
> **W0 的待办（2 条）—— ✅ 均已在 `c63f67a` 完成，此处留档**：
> ~~① **U-39**：`tests/conftest.py` 加 win32 Selector 循环策略 fixture~~ → **W0 已修**，
> 且修法正是 W1B 建议的会话级 fixture、**没有**走"吞 `InterfaceError`"的歪路
> （W1B 那条钉死断言 `test_interface_error_is_deliberately_not_treated_as_unreachable` 通过）。
> ~~② **U-41**：CI 加 lint-imports 输出存在性断言~~ → **W0 已加**（"输出必须含 `Contracts: `"）。
> ~~③ U-44（在制品 5 条 ruff 红）~~ → **已由 W0 自行修复**。
>
> **✅ 回复 W0 的阻断消息（DoD④ 的 DSN 字面量）**：已按你的要求处理完毕，**未走 allowlist**。
> `alembic.ini` 的 `migration_url` 键整键删除、`env.py` 的 `_DEFAULT_MIGRATION_URL` 删除，
> 迁移连接改为**只读 `MIGRATION_DATABASE_URL`**，取不到即抛 `RuntimeError` 且不尝试连接。
> 复核用你的规则 + 你的 allowlist 语义全仓重放：**未放行命中 0 条**（修复前 2 条）。
> 新增 `tests/unit/test_migration_dsn_hygiene.py`（7 条）钉住该纪律，其中一条就是
> "allowlist 不得放行属主凭据"，把"不要用 allowlist 消红"变成可执行断言。**阻断可解除。**
>
> **W7 的待办（2 条）**：
>
> ① `deploy/.env` 与 `deploy/.env.example` 需新增 `MIGRATION_DATABASE_URL` 键
> （`.env.example` 里**留空**并注明"执行 alembic 前载入 shell"，**不要**填任何可用口令 —— 该文件正被路径放行，填了就是又一次"用 allowlist 合法化口令"）。
> 同一处上游缺口：**docs/05 附录 D 步骤 11** 只写 `alembic upgrade head`，
> 未说明该命令现在**必须**先有 `MIGRATION_DATABASE_URL` —— 归 PRD 窗口（U-46）。
>
> ② ⭐ **`app/api/routers/health.py::_collect` 需要并行化**（该文件归属 W7，本窗口**只登记不修改**）。
> 现状是 `for dep in targets:` **串行** `await`，于是 `/healthz/ready` 的耗时 = 三个硬依赖之和。
> 实测（依赖不可达时）：**修复前 35.84s → 修复后 7.82s**，但附录 D 给该端点的平台预算是
> **`healthcheck.timeout: 5s`** —— **7.82s 仍超出，消费者只会看到 curl 超时，读不到那个诚实的 503 体**。
>
> 拆解这 7.82s 可以看清**为什么必须并行、而不是继续调小超时**：
> `2.0s`（本窗口设的池取连接上限）+ `2.92s` + `2.92s`。
> 后两项是 **Windows `getaddrinfo` 失败本身的代价**（实测 `connect_timeout=1/2/3` 都恒为 2.92s，**约束不了**）
> —— 也就是说 **5.84s 是环境代价，任何常量取值都消不掉**。
> 只有改成 `asyncio.gather` 让三者并发，上界才从"和"变成"最大值"，才有机会进 5s。
>
> 顺带一条语义建议（**属 W7 的判断**，本窗口不越权）：`_collect` 目前把 `PoolTimeout`
> 归为 `detail="探针异常：PoolTimeout"`，读起来像"实现有 bug"；
> 而它其实是"池在预算内没给出连接"这一**预期的未就绪**。措辞值得单独给一条 detail。
>
> **架构窗口的待办（4 条）**：① **U-40** 裁定 DoD② 的判定时序（是否记为"被 1A 阻塞"）；
> ② **U-42/U-43** 补登记 §4.9 的清单外文件归属，并追认 `app/obs/audit.py` 由 W1B 依用户裁定重写；
> ③ **U-45**：07 §12.6「迁移策略」应补一行"迁移连接**必须**为属主/超级用户，且**唯一**来源是 `MIGRATION_DATABASE_URL`（无默认值）"——
> 这条规则目前只存在于 `alembic.ini` 的注释里，属于"实现了但设计文档没有"。
> ④ ⭐ **07 §8 的"池超时与重连规则"现在有了实测输入**（07 §20.1 第 8 项把这件事记在本窗口名下：
> "`DB_UNAVAILABLE` 的 `Retry-After` = 5s **无机制推导** → 本窗口补 §8 的池超时与重连规则 → **补齐后必须回来复核该值**"）。
> 可直接用的三条数字：**(a)** `psycopg_pool` 默认取连接等待 = **30s**；
> **(b)** 依赖不可达时，本窗口实测启动被卡 **33.11s**、`/healthz/ready` **35.84s**；
> **(c)** 本窗口只在**探针/启动检查**的调用点收口为 `POOL_ACQUIRE_TIMEOUT_S = 2.0`
> （推导 = 附录 D 的 5s ÷ 3 个硬依赖），**刻意未改池的构造默认值** —— 那会连带改变业务借用语义，
> 而"查询路径该等多久"正是 §8 要定义的、且**必须与 `DB_UNAVAILABLE` 的 `Retry-After` 自洽**
> （现状 30s 池等待 vs 5s `Retry-After`：**在 5s 时重试必然撞上仍在阻塞的池**，
> 与 W0 修 `LLM_UPSTREAM_ERROR 5s → 30s` 是同一类缺陷）。
> **本窗口不预先占用该裁定**，只交出这条推导链。
>
> **可直接复跑门禁的命令**（`cd backend`，先导出 `DATABASE_URL` / `ANALYTICS_DB_URL` / `REDIS_URL` 指向本机 compose 端口）：
> ```
> pytest
> lint-imports                      # ⚠️ 不要写 python -m importlinter.cli
> python scripts/assert_importlinter.py
> ruff check .
> mypy app
> ```

---

## 8. 编号汇总（本窗口新登记）

| 编号 | 事项 | 归属 |
|---|---|---|
| U-38 | 限流 `per_tenant` 维度未启用（缺 `cache/keys.py` 租户级键构造函数） | W0 |
| U-39 | Windows 宿主：`tests/conftest.py` 需 Selector 循环策略 fixture（当前 2 条红） | W0 |
| U-40 | DoD② 与 1A 语义包的判定时序，需落进 docs/08 | 架构 |
| U-41 | `python -m importlinter.cli lint-imports` 是假绿调用形态 | W0 —— **已在 CI 加存在性断言防复发**（`c63f67a`） |
| U-42 | 清单外文件归属补登记（§4.9 列表） | 架构 |
| U-43 | `app/obs/audit.py` 由 W1B 重写，需追认（依用户裁定 `2.b`/`3.a`） | W0/W7 + 架构 |
| U-44 | `tests/contract/test_dependency_whitelist.py` 在制品引入 5 条 ruff 违规 | W0 —— **已由 W0 自行修复，可关闭** |
| U-45 | 迁移 DSN 出处纪律：`alembic.ini`/`env.py` 的兜底口令（**已修**）+ 07 §12.6 缺"属主/环境变量唯一来源"一行 + `.env.example` 未登记该键 | 架构（07）/ W7（`deploy/**`） |
| U-46 | docs/05 附录 D 步骤 11 未说明 `alembic upgrade head` 现在**必须先有** `MIGRATION_DATABASE_URL` | PRD 窗口 |

⚠️ **编号撞号风险**：本工作区当前**有并行窗口在改** `pyproject.toml` / `test_dependency_whitelist.py`（§4.10）。若该窗口同期也分配了 U-39 以后的编号，**以架构窗口的登记表为准**，本文档的编号仅作占位。

### 8.1 本轮（11:00–11:35）新增的未决项 —— **编号待分配，本窗口不自行开号**

> ⚠️ **为什么这里不给编号**：07 §4.8 登记 W1B 的区间是 **`U-38~U-46`，九个号已全部用尽**；
> 而 `U-47~U-50` 属 **W0**（07 §4.8 的撞车裁定结论）。
> 按编号纪律"一个编号只允许一件事"+"提新号前先查区间"，
> 本窗口**不得**把 `U-47+` 当成"最后一个号加一"来占用 —— 那正是 §4.8 立规要治的行为。
> 下列三条请**架构窗口**分配编号后再回填本节。

| 待分配 | 事项 | 归属 | 证据位置 |
|---|---|---|---|
| ? | `/healthz/ready` 的平台预算是 5s，而 `_collect` **串行**遍历硬依赖 → 实测 7.82s，**仍超**；须改并发（`asyncio.gather`） | **W7** | §4.12 / §7 |
| ? | 07 §8 缺"池超时与重连规则"，导致 `DB_UNAVAILABLE` 的 `Retry-After = 5s` 与池的实际等待（默认 30s）**不自洽**（07 §20.1 第 8 项已把补齐记在架构窗口名下） | **架构** | §4.12 / §7 架构待办 ④ |
| ? | 依赖不可达时 `pool.close()` 有 **2s** 关停延迟（实测 `退出 lifespan 2.00s`），未追 | **W1B**（后续） | §4.12 |

**另有两条"确定性事实"供上游判断，不构成待办**：
- 本轮的 8 条 `ruff` 违规（`RUF036` ×4 / `RUF100` ×2 / `UP047` / `SIM300`）**全部由 W1B 本轮新代码引入并已修净**，
  `pyproject.toml` 的 `select` 与 HEAD **逐字一致**（已 `git show HEAD` 对比）—— 不是规则集变更所致，无需上游动作。
- `ruff format --check` 显示 32 个文件会被重排；该命令**不在 `ci.yml` 门禁内**（门禁只有 `ruff check .`），与 HEAD 状态一致，**本轮不动**。

---

## 9 本轮追加（2026-09-17）：U-56 迁移 0003 + U-53 关停延迟修复

> 触发：W2-INT 转达的 U-56 迁移请求（DoD③ 端到端当前唯一硬阻塞）；
> 顺带收掉本窗口名下的 U-53（§8.1 第三条待办）。**本节只记事实与证据**，转述见 `RELAY.md` §8。

### 9.1 U-56 —— 迁移 0003：8 基表 + 8 v_* 视图（`app/repo/migrations/versions/0003_business_views.py`）

| 事实 | 落点 |
|---|---|
| 8 基表（`order_paid`/`order_refund`/`product`/`shop`/`region`/`campaign`/`traffic_daily`/`dim_date`，无 `v_` 前缀）+ 8 视图（`v_{基表}`，显式列清单）+ 6 索引 | `_ASSETS` 数据结构（列 = `(name, pg_type, nullable)` 三元组） |
| 列名与 PG 类型 = **bundle 逐字**（含 `int` 等别名**不归一化**——首版曾映射成 `integer`，被单测当场打回）；列序/可空性/主键/索引名 = **`data/schema.sql` 逐字**（SQLite 方言，只取形状不取类型） | 单测 `tests/unit/test_migration_views_contract.py`（8 条，**双向比对**：bundle↔迁移、schema.sql↔迁移；含"tenant_scoped 必有 tenant_id / 公共维表必无""shop_id 只在三张表"两条口径护栏） |
| **属主 = app_rw**（表与视图都 `OWNER TO app_rw`）—— materialize(with_policy=True) 以 app_rw 执行 ALTER/POLICY/GRANT（U-55(a) 硬前提，无属主身份发布期必失败） | `upgrade()` 内逐对象 `ALTER ... OWNER TO app_rw`；集成测试逐对象断言属主 |
| **刻意不做**：RLS/POLICY/CLS 不在迁移里（ADR-10：由 materialize 派生，迁移只给"派生的对象基础"）；`app_ro` 对基表**零 GRANT**（U-55(a) 前提 2，集成测试断言）；无 `downgrade`（§12.6 口径）；不装数据（数据装载另行裁定） | 0003 文件头 docstring 逐条写明 |
| `region`/`dim_date` = 公共维表（无 tenant_id 列、tenant_scoped=false），与其他 6 张租户表在断言里分组对待 | 单测 + 集成测试的 `_PUBLIC_BASES`/`_TENANT_BASES` |

**★ DoD③ 解锁的直接证明**（`tests/integration/test_migration_0003_views.py`，6 条全绿，真库）：
真实执行 `alembic upgrade head`（0001→0002→0003 全链）→ 16 对象存在且属主 app_rw →
**`materialize(with_policy=True)` 通过** → `assert_grant_policy_consistency` = **consistent=True**
→ 6 张租户基表各有 `p_{基表}_tenant`、公共维表零策略 → app_ro 走视图可查、碰基表 `InsufficientPrivilege`。
即：w2-int 六步演练 step② 的 `UndefinedTable: relation "v_order_paid" does not exist`（层①"视图不存在"）已被本迁移解除。

### 9.2 U-53 —— 关停延迟根因修复（`app/repo/pools.py::checkpoint_connect_kwargs` 第 ⑤ 参数）

- **根因**（复现脚本 `backend/scripts/probe_pool_close_u53.py`，可复跑）：
  依赖不可达时，池 worker 的一次连接尝试**无限挂起**（连接参数没带 `connect_timeout`），
  `pool.close()` 只能等 worker 收工，实测等满默认上限 **5.0s** 并打
  `couldn't stop task 'pool-1-worker-0' within 5.0 seconds`。
  arch 当年实测的"退出 lifespan 2.00s" = 同一机制：那次连接尝试恰好在 ~2s 处失败，close 等了多久 = 尝试挂了多久。
  对照组：依赖可达时 close = 0.000s；`redis.aclose()` / 两个 engine `dispose()` 均 0.000s —— 延迟**只在** checkpoint 池。
- **修复**：`checkpoint_connect_kwargs()` 增加第 ⑤ 参数 `connect_timeout = 2`（取值推导对齐
  `POOL_ACQUIRE_TIMEOUT_S`：5s 预算 ÷ 3 硬依赖 ≈ 2s）。复测：不可达时 close 从 5.0s 降到 **3.5s**
  （本机双栈 ::1+127.0.0.1 各算一次尝试；生产/compose 单主机名 = 一次 ≈2s）。
  单测护栏：`tests/unit/test_pools.py::test_checkpoint_connect_kwargs_carry_connect_timeout`（锁"参数在"；
  "close 变快"是时间性事实，只记在探针脚本，不写会抖动的断言）。
- **边界**：它只管单次连接尝试的生死；重试节奏（`reconnect_timeout`/backoff）属池超时/重连规则（架构窗口 U-52 名下），不越权。

### 9.3 全量门禁实测（诚实记录，含 3 条**已知红**）

| 门禁 | 结果 |
|---|---|
| `pytest`（全量） | **786 passed / 6 skipped / 4 failed**（跑于修复 DSN 字面量之前） |
| 迁移相关 5 文件（单测 8 + 集成 6 + hygiene + pools + 0003） | **全绿**（修复后复验 21~28 passed） |
| `ruff check .` | All checks passed |
| `mypy app` | Success: no issues found in 80 source files |
| `lint-imports` | 4 kept, 0 broken |

4 条 failed 的去向：
1. `test_migration_dsn_hygiene.py::test_repo_wide_replay...` —— **我的问题，已修**：新测试文件里写了属主 DSN 完整字面量，
   被自家 DoD④ 全仓重放当场抓到（"修 A 造 B"再次现形）。修法 = 运行时拼接（同 hygiene 测试自己的示范），源码不落完整字面量；
   `app_rw`/`app_ro` 已在 allowlist，可直写。
2. 其余 3 条 = `tests/integration/test_semantic_materialization.py::TestPolicyAndConsistency/*` —— **W2A 文件，不越权**，
   根因 = materialize 派生语句**非限定名** + 调用侧连接未带 `search_path`（详见 `RELAY.md` §8，转 W2A/W2-INT）。
   这 3 条此前一直 skip（`views_ready=False`）；**U-56 让视图存在后 skip 翻成执行，把 W2A 侧的 search_path 前提暴露了出来** ——
   这不是迁移引入的回归，而是 DoD③ 链路的第二层阻塞现形（w2-int 的 e2e step② 复跑时也会撞上同一层）。

## 10 本轮追加（2026-09-17）：U-56 续 —— 迁移 0004（cost_ledger + query_plan）+ 落库 sink

**派单来源**：W3-INT 统一转述件 `reports/w3-int/RELAY.md §给 W1B`（两张表在 0001–0003 零命中，
收口窗口已复核）。方案（单连接 sink）已由用户采纳后开工。

### 10.1 交付物

| 文件 | 内容 |
|---|---|
| `app/repo/migrations/versions/0004_cost_ledger_and_query_plan.py` | 两表 DDL：`cost_ledger`（列逐字对齐 `CostEntry` 落库字段 + 索引 `(tenant_id,created_at)`/`(created_at)`，`cost_cny NUMERIC(14,6)` 无损容纳 `Decimal("0.000001")` 量化）+ `query_plan`（§12.3:2292 + §6.8.3:1540，`binding_state`/`binding_layer` CHECK 取值集 = enums 冻结快照）。DDL 提为模块级常量供契约单测 import。无 downgrade（§12.6） |
| `app/repo/cost_ledger.py` | `DbCostLedgerSink` —— W3A `CostLedgerSink` Protocol 的落库实现（同步，单条专用连接 + 失败重连一次，`connect_timeout=2`） |
| `tests/unit/test_migration_0004_runtime_contract.py` | 7 条：CostEntry 字段 ↔ 0004 列双向、enums ↔ CHECK 字面逐字、DDL 常量直读 |
| `tests/unit/test_cost_ledger_sink.py` | 8 条：结构兼容逐成员、INSERT 列序 = CostEntry 字段序、SQL 形状（绑定参数/N-04）、W3A Protocol 签名同构、conninfo 换算 |
| `tests/integration/test_migration_0004_runtime.py` | 11 条：全链 upgrade、属主断言、app_ro 零 GRANT、app_rw INSERT/SELECT 通而 UPDATE 权限拒、CHECK 真实拒非法值、sink 往返 + **Asia/Shanghai 日界** + Decimal 精度 + 主键撞重 fail-loud + 不可达 DSN 快速抛（connect_timeout 复验） |
| `scripts/drill_0004_contract_injection.py` | 护栏注入对照演练（见 10.3） |

### 10.2 关键设计裁定（§12.3 未写明处的 DDL 决定，全部注册）

1. **R-DEP-2 是硬契约** → sink **不 import `app.llm`**：repo 侧本地声明结构化 Protocol
   （`LedgerEntryProto`/`CostLedgerSinkProto`），W4 装配传 `CostEntry` 天然结构兼容；
   "CostEntry ↔ 本地契约"一致性由 `test_cost_ledger_sink.py` 逐成员钉死（tests 层可 import 两边）。
2. **权限**：app_rw 恰好 `INSERT/SELECT`（UPDATE/DELETE 刻意不给 —— 账本行不可改、计划行一次写入，
   用权限层钉死）；app_ro 零 GRANT（两表不在业务查询路径，N-02）；**保留期清理（13 个月/90 天）走属主身份**
   —— 这是运维动作不是 DDL，登记为 W7 部署侧/runbook 任务（同文件头"刻意不做 #1"）。
3. **可空性**：`plan_json`/`binding_state`/`bundle_version` NOT NULL（表存在的理由）；`plan_summary`/
   `binding_layer`/`confidence` 允许 NULL（unresolved 等态没有判定层/置信度可言，DB 不猜）。
4. **CHECK 字面 = 冻结快照而非 import**：迁移会被 alembic 子进程独立执行，且 enums 属 W0 可能被并行改
   —— 迁移要的是落库那一刻的值；漂移由契约单测当场抓（它两边都读）。

### 10.3 护栏注入对照（正向对照纪律）—— 演练抓到两个真问题

`drill_0004_contract_injection.py` 注入 → 必红 → 还原 → sha256 复核，三轮演练：

1. 列解析器的 `\b` 在 `NUMERIC(14, 6)` 右括号后不成立 → `cost_cny` 整行漏掉（护栏盲区，已修为 `(?=\s)`）；
2. `test_ddl_embedding_of_check_literals` 原是**恒真断言**（拿 `_BINDING_STATES` 渲染的文本比对同一个元组，
   两边同源永远不可能红）→ 重写为从 DDL 文本**独立解析**字面值再比对。
3. sink 单测首跑抓到**真实类型漂移**：本地 Proto 的 `created_at: date` vs `CostEntry.created_at: datetime`
   （timestamptz 本就该 datetime）—— Proto 错，已修。

### 10.4 门禁实测

| 门禁 | 结果 |
|---|---|
| 全量 `pytest` | **1498 passed / 6 skipped / 0 failed**（6 skip 全是 retrieval FTS 的 DSN 权限 skip，与本批无关；上轮的 3 条 W2A search_path 红已由 W2A 修复） |
| `ruff check .` | All checks passed（本批引入 10 条已修净：UP017×5/E741×4/I001） |
| `mypy app` | Success: no issues found in 104 source files |
| `lint-imports` | 4 kept, 0 broken（R-DEP-2 实证 KEPT —— sink 无 llm import） |

本批新增测试 26 条（7 契约 + 8 sink + 11 集成）全绿；集成测试含真实 `alembic upgrade head` 全链。

### 10.5 本轮暴露的测试自身缺陷（诚实记录，均已修）

- `get_type_hints(Protocol)` 只收集**类级注解**，拿不到 `@property` 返回注解 → 返回空 dict，
  使首版结构比对**空转**（循环体零次执行 + 覆盖断言红才现形）—— 与本项目"恒真护栏"教训同类，已改为从 `fget` 提取。
- 模块级 `rw` 连接未开 autocommit：CHECK/权限拒绝把事务打 Abort 后，aborted 状态**污染后续所有用例**
  （`InFailedSqlTransaction`）—— 已开 autocommit 并写明原因。

## 11 本轮追加（2026-09-18）：`app/repo/query_plan.py` 写入通道（W4 §二 点名阻塞 T7）

**派单来源**：`reports/w4/RELAY.md §二`（阻塞 T7 `query_plan` 落库 = W3C DoD① 最后一步；
W4 原文允许"走既有池并注明池名"）。方案已获用户采纳后开工。

### 11.1 交付物

| 文件 | 内容 |
|---|---|
| `app/repo/query_plan.py` | `QueryPlanStore(engine)` + `insert_query_plan(...)`：**只写**通道，逐字覆盖 0004 列集；类型化签名（`BindingState` / `BindingLayer \| None` / `Decimal`）；`plan_json` 走 `CAST(... AS jsonb)` 且 `Mapping` 形态校验 `schema_version` 在场；`plan_summary` 的 `Mapping` 序列化为 JSON 文本；纯 INSERT（无 `ON CONFLICT`）；不 catch |
| `tests/unit/test_query_plan_store.py` | 15 条离线契约：源码层（剥 docstring 后）无改删语句/无 `ON CONFLICT`、公开面只有 `insert_query_plan`、列集与迁移 DDL **双向一致**、jsonb CAST、枚举注解、写入值形态、必填缺失报字段名、异常不吞 |
| `tests/integration/test_query_plan_store_pg.py` | 6 条真库：往返（jsonb 对象/JSON 文本/枚举字面值/Decimal 精度/NULL 三列）、**`app_rw` UPDATE 被权限拒（42501）**、主键撞重抛且原行未被覆盖、非枚举在发语句前失败、CHECK 拒非法字面值 |
| `scripts/drill_query_plan_guards.py` | 4 组注入负向对照（见 11.3） |

### 11.2 关键设计裁定

1. **复用元数据池，不新开连接**：`QueryPlanStore` 收 `AsyncEngine`（形态同 `AuditStore`），
   W4 装配时传 `pools.metadata` ⇒ **零新增长连资源、零 shutdown 责任**
   （避开 U-86 轮 `DbCostLedgerSink` 那条"第 4 资源待架构裁"的老路）。
   调用方在 async 图节点里，通道本身即 async。
2. **类型化签名而不是 dict 白名单**：本表只有 7 列，枚举直接进签名 ⇒ 拼错取值在调用点红；
   CHECK 仍是数据库侧最后防线（两层不互替，两层都有测试）。
3. **不做 upsert**：`task_id` PK 撞重如实抛（SQLAlchemy 包成 `IntegrityError`，`.orig` 是 psycopg 的
   `UniqueViolation`）—— upsert 会把"同一任务走了两次 plan 节点"静默成最后一次覆盖，
   而本表存在的意义就是事后诊断（被覆盖的那次才是要查的）。
4. **`plan_summary` 存 JSON 文本**（列类型 = `text`）：C-01 的结构化摘要序列化入库，
   保证读回可解析；不引入"dict 的 `str()`"这类不可解析脏数据。

### 11.3 护栏注入对照（4/4 必红，还原 sha256 一致）

| # | 注入 | 必红断言 |
|---|---|---|
| ① | 加 `update_query_plan` 方法 | `test_only_insert_method_is_exposed` |
| ② | 去掉 `CAST(:plan_json AS jsonb)` | `test_plan_json_binds_as_jsonb_cast` |
| ③ | 写入面加一列（迁移没有） | `test_columns_match_migration_ddl_bidirectionally` |
| ④ | `_INSERT_SQL` 追加 `ON CONFLICT DO NOTHING` | `test_module_source_has_no_on_conflict` |

⚠️ 首版列解析器写成了"只认已知 7 列"的正则 —— 那会让**迁移新增列**变成假绿
（匹配不到 → 两份清单仍相等）。已改为通用解析（行首标识符 + 类型，跳过约束行），
并由注入 ③ 验证解析器不瞎。

### 11.4 门禁实测

| 门禁 | 结果 |
|---|---|
| 全量 `pytest` | **1528 passed / 6 skipped / 0 failed**（81.35s；6 skip = retrieval FTS 夹具 DDL 权限，既有） |
| `ruff check .` | All checks passed（本批 2 条 I001/SIM300 已修净） |
| `mypy app` | Success: no issues found in **105** source files |
| `lint-imports` | 4 kept, 0 broken（R-DEP-1 实证：repo 收 core 枚举合法，未引入新依赖方向） |

### 11.5 本轮踩到的坑（可复用，均已落注释/记录）

1. **`pytest-asyncio` 1.4 自建事件循环不认 `set_event_loop_policy`** —— 4 条 async 用例全撞
   `psycopg.InterfaceError: cannot use the 'ProactorEventLoop'`。仓库既有惯例是
   **不用 `async def test_`**、改在同步用例里 `asyncio.run(...)`（`test_auth_chain.py` 30+ 处），
   本批照此重写即可（首版按 `asyncio_mode=auto` 写 async 用例是错的）。
2. **经 `AsyncEngine` 执行时异常被 SQLAlchemy 包装**：撞主键得到的是
   `sqlalchemy.exc.IntegrityError`（`.orig` 才是 psycopg 的 `UniqueViolation`）。
   已写进 store docstring —— 调用方（W4）的捕获点用 SQLAlchemy 类型。
3. **列解析器不得内嵌"已知列名"**：见 11.3 ⚠️（同一类"护栏假绿"已在 0004 轮踩过一次）。
