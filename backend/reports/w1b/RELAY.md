# W1B → 各窗口 转述件（逐条可直接复制）

> 生成：2026-09-16 ｜ 归属窗口：W1B ｜ 配套交付说明：`backend/reports/w1b/DELIVERY.md`
>
> **用法**：每一节就是一个"整块可粘贴"的消息，收件人在标题里写明了。直接复制该节的引用块即可，不需再加工。
>
> ⚠️ **本文件刻意不写任何 DSN 字面量**（连示例都不写）。原因：`test_migration_dsn_hygiene.py` 会全仓重放 DoD④ 的规则，
> 写进来就会让"修复本身"变成新的命中项 —— 这不是假设，本轮已经踩过一次。需要描述形态时一律写成
> 「`postgresql+psycopg://` + 用户名 + `:` + 口令 + `@` + 主机」。
>
> **编号说明**：本文件新登记 **U-45 / U-46**。⚠️ 本工作区有并行窗口在用 U-23~U-36，**号码冲突时以架构窗口登记表为准**。

---

## 1 → W0：DoD④ 阻断项已修完，可解除（**回你的阻断消息**）

> **W1B 回 W0「DoD④ 密钥扫描阻断」**
>
> 你指出的两处已按你的要求处理完，**没有走 allowlist**：
>
> | 位置 | 原状 | 现况 |
> |---|---|---|
> | `backend/alembic.ini` | `migration_url` 键持有带属主口令的 DSN | **整键删除**（不是留空 —— 没有消费者的键就是下一个 U-23 形态） |
> | `backend/app/repo/migrations/env.py` | `_DEFAULT_MIGRATION_URL` 常量 | **删除**；`_migration_url()` 只读 `MIGRATION_DATABASE_URL`，取不到即抛 `RuntimeError`，**且不尝试连接** |
>
> **复核方式（请你按同法验收，别信我的结论）**：把 `.gitleaks.toml` 里那条 `commerceql-dsn-with-password` 的正则
> 连同 `[allowlist]` 的三层语义（`paths` / `regexes` / `stopwords`）在本地重放，逐文件标"放行 / 会红"：
> 修复前 `alembic.ini:29` 与 `env.py:33` 均命中且未被放行（**会红**）；修复后全仓 **未放行命中 = 0 条**。
>
> **行为验证（三条已实测）**：
> ① `alembic history` / `alembic heads` 不设变量仍可用（撤默认值没有把 alembic 弄坏）；
> ② `MIGRATION_DATABASE_URL` 指向属主时 `alembic current` 返回 `0001 (head)`；
> ③ 不设变量 `alembic upgrade head` → 非 0 退出、错误点名缺失变量、**输出里没有任何 psycopg 连接错误**
> （证明是 fail-fast 而不是"先连了再失败"）。
>
> **新增护栏**：`backend/tests/unit/test_migration_dsn_hygiene.py`（7 条），其中两条是给你的原则做的：
> · 全仓重放 DoD④ 规则（**本机没装 gitleaks**，`gitleaks version` → command not found，所以 DoD④ 目前只存在于 CI，本机提交前零反馈）；
> · **allowlist 不得放行属主凭据** —— 把"不要用 allowlist 消红"从口头原则变成会红的断言。
> 注入-还原对照已跑：把字面量加回 `alembic.ini` → 该用例红；还原 → 绿；文件 sha256 前后一致。
>
> **⚠️ 但这还留两个同类问题，按你的原则它们也该被处理，请你定口径**（我没有越权改你的文件）：
> 1. `.gitleaks.toml` 的 `allowlist.paths` **整文件放行** `deploy/.env.example`，而该文件的 `DATABASE_URL` /
>    `ANALYTICS_DB_URL` 是**可用口令形态**的值。也就是说：**它对扫描器不可见，而不是它安全**。
>    同理 `allowlist.regexes` 里的两条 `app_rw` / `app_ro` 放行，属于同一类"合法化"。
>    两种收口方式请择一，**并把选择写进文件注释**（现在两种都没写，下一个人无法判断这是有意的还是漏的）：
>    (a) 把 `.env.example` 的两条 DSN 改成**键留空** + 上一行注释（推荐，与 `DEEPSEEK_API_KEY=` 同形）；
>    (b) 明确写下"示例值放行是有意的例外"，并给出边界（哪些形态可以放行、哪些绝不可以）。
> 2. `backend/app/repo/migrations/versions/0001_...py:77–78` 有带默认口令的 DSN。
>    **我刻意没动**：它是**已执行过的冻结制品**，改它会让"从零重建的库"与"已建成的库"得到**不同的角色口令** ——
>    比现状更坏。若要根治，正确做法是**新增**一个迁移或改为强制读环境变量，**不要编辑已应用的迁移**。请你确认这个取舍。

---

## 2 → W0：U-39 **仍未修**（当前 2 条红测试的唯一根因，最高优先）

> **W1B → W0：U-39 还没落地，它现在是唯一红**
>
> 2026-09-16 10:36 复测 `tests/conftest.py`：**里面仍无任何 win32 / Selector / event_loop 处理**。
>
> **现象**：`tests/contract/test_obs_audit_contract.py` 两条用例（都做 `TestClient(create_app())`）在 Windows 宿主上必红：
> ```
> psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
> Please use a compatible event loop, for instance by running
> 'asyncio.run(..., loop_factory=asyncio.SelectorEventLoop(selectors.SelectSelector()))'
> ```
> 失败点在 `app/repo/startup_assertions.py::_fetch_analytics_role`（B4 让 lifespan 第一次做真实 I/O）。
>
> **已做的对照实验（排除"是断言逻辑写错了"）**：把事件循环策略换成 `WindowsSelectorEventLoopPolicy()` 后，
> **同一份代码完全正常**（`/healthz/live` 200、`/healthz/ready` 503、四个硬依赖明细均如实返回）。
> 也就是说 **B4 没有引入新缺陷，它只是让附录 D `E-1`（本机用 Docker / Linux）之外的那个不兼容第一次暴露在测试里**。
>
> **建议修法**（归你，`tests/conftest.py` 是你的独占文件，我一行未碰）：
> 在 `conftest.py` 加一个**会话级** fixture，win32 下设置 `WindowsSelectorEventLoopPolicy`，非 win32 为 no-op。
> **请不要**用 `asyncio.to_thread` 同步连接去"修"它 —— 那能让测试变绿，但会把"Windows 宿主上这条路径根本跑不起来"藏起来，
> 而那正是我们要知道的事实。
>
> **另（可顺手）**：`python -m importlinter.cli lint-imports` 是**假绿**（无输出、exit 0、什么都没检查；
> 根因 `site-packages/importlinter/cli.py` **没有 `__main__` 守卫**，`grep -c "__main__"` = 0）。
> `ci.yml` 用的 `lint-imports` 是对的，建议在 README/CI 注释里明写"**禁止**以 `-m importlinter.cli` 形态调用"，
> 并给 CI 加一句"输出必须含 `Contracts: N kept`"的存在性断言 —— 否则哪天有人改成 `-m` 形态，这条门禁就永久静默绿了。
> 顺带：`ruff check .` 你已经修好了（`All checks passed!`），U-44 我这边标记为可关闭。
>
> ---
>
> ### ⚠️ 追加（2026-09-16 11:30）：**这 2 条红只能靠修 conftest 消掉，不要用别的方式**
>
> W1B 本轮修了另一个问题（"依赖连不上"被当成致命 → CI 红），过程中引入了一个**诱人的错误修法**，
> 我把它直接写成会红的断言堵住了，请你也别走这条路：
>
> **错误修法**：把 `psycopg.InterfaceError` 也归进"依赖不可达"，从而让那 2 条测试变绿。
> **为什么不行**：`InterfaceError` 表达的是「**你用错了**」（事件循环不兼容），不是「依赖不在」。
> 归错类会形成一条完整的掩盖链：本机跑不起来 → 判"无法判定" → dev 放行 → **测试变绿** →
> 所有人以为"只是库没起" → 而真相是这台机器的事件循环不兼容。**U-39 会从视野里消失。**
>
> 已有的两条断言会把这条路变红（`tests/unit/test_reachability_and_startup_tolerance.py`）：
> · `test_interface_error_is_deliberately_not_treated_as_unreachable`
> · `test_live_probe_does_not_hide_a_non_connectivity_failure`
>
> → 换句话说：**这两条红是"设计上应该红"的**，它们的转绿只能来自 `conftest.py` 的 Selector fixture。
>
> **另一件要你知道的事**：本轮修复后，这 2 条用例在 **Linux CI 上已经是绿的**（我用"无 DSN + Selector"的
> 条件实测过：修复前 2 failed → 修复后 2 passed）。所以现在的状态是
> **"CI 绿、本机 2 红"**，与修复前的 **"CI 红、本机 2 红"** 不同 —— 别按老印象判断。

---

## 3 → W7：`MIGRATION_DATABASE_URL` 需登记（**这是 §1 那个改动的直接后果**）

> **W1B → W7：`deploy/.env` / `deploy/.env.example` 需新增一个键**
>
> 背景：`alembic.ini` 与 `app/repo/migrations/env.py` 里原本各有一个兜底 DSN，其中带着**可用的属主口令**
> （与 `docker-compose.yml` 的 `POSTGRES_USER/POSTGRES_PASSWORD` 同值），会命中 CI 的密钥扫描（DoD④）。
> 已按 W0 的要求改为：**迁移连接只从 `MIGRATION_DATABASE_URL` 取，没有默认值，取不到即拒绝执行**。
>
> **需要你做的（`deploy/**` 归你）**：
> 1. `deploy/.env` 加入该键，值 = 形态与 `DATABASE_URL` 相同、但用户名/口令换成**属主（超级用户）**那一组
>    （迁移 0001 要 `CREATE ROLE`，而运行时的 `app_rw` **故意**没有 `CREATEROLE`）。
> 2. `deploy/.env.example` 加同名键，**值留空**，注释里写明"执行 alembic 前需载入当前 shell"。
>    ⚠️ **不要**在这里填任何可用口令：该文件正被 `.gitleaks.toml` 的 `allowlist.paths` 整文件放行，
>    填了就是又一次"用 allowlist 把口令合法化"（W0 本轮刚明确的原则）。
>    ⚠️ 该文件顶部有"**值留空的行不得写行尾注释**"的硬规则（`C=  # cmt` 会让注释变成值）——
>    本键必须遵守。
> 3. 若要写进部署步骤，注意 `alembic history` / `heads` **不需要**该变量，只有 `upgrade` / `current` / `revision` 需要。
>
> **另**：`deploy/.env.example` 里的 `DATABASE_URL` / `ANALYTICS_DB_URL` 目前是可用口令形态的值，
> 而该文件被整文件路径放行 —— 建议与 W0 一起定口径（改成键留空，或在注释里明写这是有意的例外）。
> 同一条我也转给了 W0，你们任一方定了就行，**不要两边各改一半**。
>
> ---
>
> ### ⚠️ 追加（2026-09-16 11:30）：⭐ **`app/api/routers/health.py::_collect` 需要并行化**
>
> 这个文件**归你**（文件头写着 `W0 交付空骨架 → W7 接管实现`），所以本窗口**只登记、一行未改**。
>
> **问题**：`_collect` 现在是 `for dep in targets: results[dep] = await _PROBES[dep]()` ——
> **串行**遍历硬依赖。于是 `/healthz/ready` 的耗时 = 三个硬依赖耗时之**和**。
> 而附录 D 给这个端点的平台预算是 **`healthcheck.timeout: 5s`**（到点 `curl` 被杀），
> 意味着**消费者只会看到"超时"，读不到那个诚实的 503 应答体** —— 恰恰在你最需要它的时候。
>
> **实测数字（依赖不可达时）**：
>
> | | 修复前 | 修复后（本窗口只收口了池等待） |
> |---|---|---|
> | `GET /healthz/ready` | **35.84s** | **7.82s** |
> | `lifespan` 进入 | 33.11s | 5.08s |
>
> **7.82s 的拆解 —— 这就是为什么必须并行，而不是继续调小超时**：
>
> ```
> 2.00s   ← 池取连接上限（本窗口新设的 POOL_ACQUIRE_TIMEOUT_S，只作用于探针/启动调用点）
> 2.92s   ← metadata 探针：Windows getaddrinfo 失败本身的代价
> 2.92s   ← redis    探针：同上
> ```
>
> 后两项实测**约束不了**：`connect_timeout=1/2/3` 下耗时恒为 2.92s。
> 也就是说 **5.84s 是环境代价，任何常量取值都消不掉** ——
> 把上界从"**和**"变成"**最大值**"（`asyncio.gather`）才是唯一出路。
>
> **建议**（你做判断，我只给证据）：
> 1. `asyncio.gather(*[_PROBES[d]() for d in targets], return_exceptions=True)`，
>    再把 `BaseException` 结果统一转成 `healthy=False` + `detail=f"探针异常：{type(e).__name__}"`
>    —— 现有那层 `try/except` 的**语义要原样保留**（它保证"探针炸了不把 503 变成 500"）。
> 2. 顺带一条措辞：现在 `PoolTimeout` 会被写成 `detail="探针异常：PoolTimeout"`，读起来像"实现有 bug"；
>    它其实是"**池在预算内没给出连接**"这一**预期的未就绪**，值得单独一条 detail。
> 3. 别忘 `_collect` 的调用方：`_checks_payload` 只读 `healthy`，`results` 是 dict 按 key 取，
>    **顺序无关**，所以改并发不会改变响应体结构。
>
> 本窗口**不预先占位**这个改动 —— 文件归你，判断也归你。

---

## 4 → PRD 窗口（上游）：docs/05 附录 D 步骤 11 需补一句

> **W1B → PRD 窗口：附录 D 的迁移步骤缺一个前置（U-46）**
>
> `docs/05_附录D_环境依赖与部署清单.md` 步骤 11 目前只写：执行数据库迁移 → 验证方式 `alembic upgrade head` 无报错。
>
> 但实现已定：**迁移连接必须由属主/超级用户提供，且唯一来源是 `MIGRATION_DATABASE_URL` 环境变量，没有默认值**
> （理由：迁移 0001 要建角色 / 授权，而运行时角色 `app_rw` 故意没有 `CREATEROLE`；
> 留默认口令会同时造成"可用口令进仓库"与"忘了设变量时安静地连上某个库"两个问题，后者不可逆）。
>
> **请求**：步骤 11 补一句前置 —— 该命令运行前必须先在 shell 中提供 `MIGRATION_DATABASE_URL`
> （键名已登记进 `deploy/.env.example`，归 W7）。
> 同时建议步骤 6 的"复制 `.env.example` → `.env`"处，把该键一并点到，否则照附录 D 走的机器会在第 11 步失败且原因不直观。
>
> ⚠️ 我**没有**直接改 docs/05（归属 PRD 窗口，改了就是 U-18/§4.7.1 那个"同一事实写两遍"的老坑）。
> 需要改动文本的话我可以出 diff 供你采用。

---

## 5 → 架构窗口：3 条登记 / 裁定请求

> **W1B → 架构窗口：3 条待办**
>
> **① U-40（裁定）**：DoD② 的原文是"`/healthz/ready` 转 200"，但 `semantic_bundle_loaded` 是**硬依赖**，
> 而语义包归 W2A。**在 1A 交付语义包之前，DoD② 物理上无法达成**（当前实测 503，四个硬依赖
> `{redis:true, checkpointer:true, metadata_db:true, semantic_bundle_loaded:false}`，只差这一项）。
> 用户此前已**口头**裁定 `1.b`（接受部分达成），但**该裁定尚未落进 `docs/08`** ——
> 请补一句，否则下一个窗口会把它读成"W1B 没做完"。
>
> **② U-42 / U-43（登记 + 追认）**：
> · U-42：以下**清单外必需文件**由 W1B 创建/改写，§4.1 归属表里**查不到**，需补登记
>   （否则出现"谁都能改"的文件，U-18 的教训立刻重演）：
>   `app/api/deps.py`、`app/api/ratelimit.py`、`app/cache/session_lock.py`、`app/repo/redis.py`、
>   `app/main.py`、`backend/alembic.ini`、`backend/scripts/**`、`backend/reports/**`。
> · U-43：`app/obs/audit.py` 被 W1B **重写**（依用户裁定 `2.b`/`3.a`：审计写入落 `obs/audit.py`），
>   但 §4.1 把 `app/obs/**` 划给 W0→W7 → **需追认**，且必须明确"只有一份实现"，不得两边各留一份。
>
> **③ U-45（补设计）**：`07 §12.6 迁移策略` 那张表应补一行 ——
> "迁移连接**必须**为属主/超级用户；**唯一**来源是 `MIGRATION_DATABASE_URL`（**无默认值**，取不到即拒绝执行）"。
> 这条规则目前**只存在于 `alembic.ini` 的注释里**，属于"实现了但设计文档没有"；
> 按本项目此前的教训（W0/W1A 提的 17 条里没有一条是'文档没写'——全是'写了但写不到能实现'或'写了但自相矛盾'），
> 这类"实现先于设计"的规则如果不回填，下一个人会照 §12.6 重新加一个默认值回来。
>
> **④ ⭐ 07 §8 的"池超时与重连规则"现在有实测输入了（2026-09-16 11:30 追加）**
>
> 07 §20.1 第 8 项把这件事记在**本窗口**名下：
> > "`DB_UNAVAILABLE` 的 `Retry-After` **无机制推导**（§14.4.1 已标为**经验值 5s**）：
> > 07 **至今未定义 DB 层的重连/池超时策略** —— 而'等多久'必须由它决定 →
> > **本窗口（补 §8 的池超时与重连规则）→ 补齐后必须回来复核该值**"
>
> 所以这不是新增请求，是**给你补三个可直接用的数字**（全部本机实测，可复现）：
>
> 1. **`psycopg_pool` 的默认取连接等待 = `30.0s`**（实例默认值，从 `__init__` 签名读出）。
> 2. **该默认值用在探针/启动检查上时，实测代价**：启动被卡 **33.11s**、`GET /healthz/ready` **35.84s**
>    —— 而附录 D 给该端点写的平台预算是 `healthcheck.timeout: 5s`。**平台侧看到的是超时，不是那次的 503。**
> 3. **本窗口只在探针/启动调用点收口**为 `POOL_ACQUIRE_TIMEOUT_S = 2.0`
>    （推导：附录 D 的 5s ÷ 3 个硬依赖），**刻意未改池的构造默认值** ——
>    因为那会连带改变**业务借用**的语义，而"查询路径该等多久"正是 §8 要定义的东西。
>
> **⚠️ 请你注意这条自洽性缺口**（与 W0 刚修的那类完全同源）：
> 现在是 **30s 的池等待 vs 5s 的 `DB_UNAVAILABLE` Retry-After** ——
> 在 5s 时重试，**必然撞上仍在阻塞的池**，也就是"重试指令保证失败"。
> 这与 W0 修 `LLM_UPSTREAM_ERROR` 从 5s 改 30s 是**同一类缺陷**
> （当时的判据原话："熔断开路 30s 内重试**必然失败**，给 5s 等于保证失败"）。
> 两种自洽方向都成立，**但必须选一个并写进 §8**：
> (a) 池等待压到 < 5s（则 5s 的 `Retry-After` 有意义）；
> (b) 保留 30s 池等待，则 `Retry-After` 必须抬到 > 30s。
>
> **本窗口不预先占位这个裁定**，只交出推导链与实测值。
>
> ---
>
> **⚠️ 编号占用与用尽**：W1B 本轮用 **U-45 / U-46**；此前 W1B 已占 U-38~U-44 →
> **`U-38~U-46` 九个号已全部用尽**，而 `U-47~U-50` 按 §4.8 属 **W0**。
> 因此本轮新增的 3 条未决项**本窗口不自行开号**（详见 §7 的"待分配"表）——
> 按 §4.8 的纪律，不能把"最后一个号 +1"当成本窗口的号。
> 本工作区另有并行窗口在用 U-23~U-36 → **有撞号风险，请以你的登记表为准**。

---

## 6 → W2A：唯一的 DoD② 前置（内容与首次交付相同，此处保留以便一并复制）

> **W1B → W2A：解除 DoD② 的唯一前置**
>
> `/healthz/ready` 当前 503，四个硬依赖里**只差 `semantic_bundle_loaded`**（其余三项已实测为 true）。
> 需要两件事：
> 1. **物化 `app.embed_doc.embedding`** —— 本机实测 **pgvector 扩展尚未安装**（`pg_extension` 里只有 `plpgsql`），
>    所以该列不存在，启动断言正确地保持 `PENDING`（不是缺陷）。
> 2. **交付语义包五步校验器**（`semantics/loader.py`）。
>
> 对接点已冻结，请勿另写一份：`app/repo/startup_assertions.py` 的 `evaluate_semantic_bundle(validator=...)`
> 就是注入位置（现返回 `PENDING` 并指明归 W2A）；`app/repo/health.py` 的 `build_probe_table(...)`
> 只产出 3 个**硬依赖**探针，`semantic_bundle_loaded` 槽位留给 W2A/W7
> （⚠️ 软依赖 `llm` / `embedding` **不得**进 readiness，N-21）。

---

## 7 编号汇总（本文件涉及的）

| 编号 | 事项 | 归属 | 状态 |
|---|---|---|---|
| U-38 | 限流 `per_tenant` 维度未启用 | W0 | 未修（缺 `cache/keys.py` 租户级键构造函数） |
| U-39 | Windows 宿主需 Selector 循环 fixture（**当前 2 条红**） | W0 | **未修** |
| U-40 | DoD② 判定时序需落进 docs/08 | 架构 | 待裁定 |
| U-41 | `python -m importlinter.cli` 是假绿调用形态 | W0 | 待处理 |
| U-42 / U-43 | 清单外文件归属补登记 / `obs/audit.py` 重写追认 | 架构 + W0/W7 | 待处理 |
| U-44 | 在制品 5 条 ruff 违规 | W0 | **已由 W0 修复，可关闭** |
| U-45 | 迁移 DSN 出处纪律（**已修**）+ 07 §12.6 补行 + `.env.example` 键登记 | 架构 / W7 | 修复完成，文档待回填 |
| U-46 | docs/05 附录 D 步骤 11 缺 `MIGRATION_DATABASE_URL` 前置 | PRD 窗口 | 待上游 |

### 待分配编号（本轮新增，**W1B 区间已用尽，请架构窗口分配**）

⚠️ 按 07 §4.8：W1B 区间 `U-38~U-46` **九个号已全部用尽**；`U-47~U-50` 属 **W0**。
故下列三条**不自行开号**（"最后一个号 +1" 正是 §4.8 立规要治的行为）。

| 事项 | 归属 | 证据 |
|---|---|---|
| `/healthz/ready` 平台预算 5s，而 `_collect` 串行 → 实测 7.82s **仍超**，须改并发 | **W7** | `DELIVERY.md §4.12`、本文件 §3 追加段 |
| 07 §8 缺"池超时与重连规则" → `DB_UNAVAILABLE` 的 `Retry-After=5s` 与池默认等待 30s **不自洽** | **架构** | `DELIVERY.md §4.12`、本文件 §5 待办 ④ |
| ~~依赖不可达时 `pool.close()` 有 2s 关停延迟（未追）~~ | **W1B**（后续） | **已修**（2026-09-17，U-53 关闭）：根因 = 连接参数缺 `connect_timeout` → worker 的连接尝试无限挂起 → `pool.close()` 等满默认 5s。修复 = `checkpoint_connect_kwargs()` 加 `connect_timeout=2`（`pools.py` 第 ⑤ 参数）；复现与实测数字见 `backend/scripts/probe_pool_close_u53.py` + `DELIVERY.md §9.2` |

---

## 8 → W2A / W2-INT：U-56 已落（迁移 0003 全绿），但 `UndefinedTable` 还有**第二层** = search_path

> 本节可直接复制转达。对应 `DELIVERY.md §9`（细节与证据都在那里）。

### 8.1 已交付

| 事项 | 落点 | 验证 |
|---|---|---|
| **迁移 0003**：8 基表 + 8 `v_*` 视图 + 6 索引，列名/类型 = bundle 逐字、列序/可空性/主键/索引名 = `data/schema.sql` 逐字、**属主 = app_rw** | `backend/app/repo/migrations/versions/0003_business_views.py` | 单测 8 条（bundle↔迁移、schema.sql↔迁移双向比对）+ 真库集成 6 条全绿 |
| **DoD③ 直接证明**：真库 `alembic upgrade head` 全链 → `materialize(with_policy=True)` 通过 → `assert_grant_policy_consistency` = **consistent=True** → 6 租户基表各有 `p_{基表}_tenant`、公共维表零策略 | `backend/tests/integration/test_migration_0003_views.py` | w2-int 六步演练 step② 的 `UndefinedTable` **层①（视图不存在）已被解除** |

### 8.2 ⚠️ 但 step② 真正复跑还会撞**第二层**：materialize 派生语句是非限定名

- **证据**：U-56 让 `views_ready` 翻成 True 后，`tests/integration/test_semantic_materialization.py::TestPolicyAndConsistency` 的 3 条用例
  从 skip 变执行，当场报 `UndefinedTable: relation "v_order_paid" does not exist`，断点在
  `materialize.py:468` 执行 `REVOKE ALL ON "v_order_paid" FROM PUBLIC;`。
  连接（`_RW`）没带 `search_path` → 非限定名解析不到 `app.v_order_paid`。**此前不是没有这个问题，是 skip 把它盖住了。**
- **两个修法（归 W2A 裁量，W1B 不越权改 `app/semantics/**`）**：
  - **推荐（根修）**：`derive_policy_statements()`（materialize.py:129-160 附近）把派生语句改成 schema 限定名
    （`REVOKE ALL ON app."v_order_paid"` / `ALTER TABLE app.order_paid ...`）—— 调用侧从此不必依赖 search_path；
  - 备选：约定所有 `materialize` 调用方（含 `tests/integration/test_semantic_materialization.py` 的 `_RW`、w2-int 的 e2e 脚本）
    连接串必须带 `options=-c search_path=app,public` —— 但这是把同一前提散到每个调用点，漏一处就复现。
- **给 W2-INT**：收口复跑六步发布前，请确认上述任一修复已落，否则 step② 会在同一位置再红。
- **单测事实同步**：materialize 派生语句的形状若有变，`tests/unit/test_materialize_derivation.py` 需同步（W2A 名下）。

### 8.3 附带说明

- 迁移 0003 **不含** RLS/POLICY/GRANT（ADR-10：全部由 materialize 派生；迁移只提供派生的对象基础，且属主=app_rw）。
  若 W2A 决定派生语句改限定名，0003 无需任何改动。
- 本轮 W1B 的测试文件里，属主 DSN 一律**运行时拼接**（DoD④ 全仓重放的教训：修好配置文件，别在自己新加的测试里种回同一问题）。
