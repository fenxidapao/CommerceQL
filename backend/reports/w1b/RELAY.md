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

## 9 → W4 / W3A / W3C / W7 / 架构：迁移 0004 已落（cost_ledger + query_plan）+ 落库 sink 就绪

**派单来源**：W3-INT 统一转述件 §给 W1B。方案（单连接 sink）经用户采纳。细节 = `DELIVERY.md §10`。

### 9.1 已交付（全部门禁绿，全量 pytest 1498/6/0）

- **迁移 0004**：`app.cost_ledger`（列逐字对齐 `CostEntry`，索引 `(tenant_id,created_at)`/`(created_at)`，
  `cost_cny NUMERIC(14,6)`）+ `app.query_plan`（`binding_state`/`binding_layer` CHECK 取值集 = enums 冻结快照）。
- **`app/repo/cost_ledger.py::DbCostLedgerSink`**：W3A `CostLedgerSink` Protocol 的落库实现
  （同步，单条专用连接 + 失败重连一次 + `connect_timeout=2`；不 import `app.llm` —— R-DEP-2，本地结构化 Protocol，
  与 `CostEntry` 的字段一致性由 `tests/unit/test_cost_ledger_sink.py` 逐成员钉死）。

### 9.2 → W4：装配点（你接到的是成品，按此接线即可）

- 构造：`DbCostLedgerSink(settings_database_url)`（传 `DATABASE_URL` 原值，SQLAlchemy 形态，内部自行换算 libpq）；
- 它满足 W3A 的 `CostLedgerSink` Protocol —— 直接塞进网关的 sink 注入点；`CostEntry` 可直接传 `record()`；
- 可选参数 `billing_tz`（默认 `Asia/Shanghai` = PRD §12.3）——**不要另设时区常量**，日界聚合用；
- **shutdown 必须调 `sink.close()`**（挂进 `main.py` lifespan 资源释放区，与三池同段）—— 长连资源，不关 = 泄漏。

### 9.3 → W3A / W3C：你们的两个表结构阻塞已解除

- **W3C DoD①**：`query_plan` 表 + `binding_state`/`binding_layer` 列现已存在（0004）；剩余缺口 = W4 写入侧。
- **W3A**：`cost_ledger` 已存在 → "重启丢账"的 InMemory sink 可换 `DbCostLedgerSink`（接线归 W4，见 9.2）；
  Protocol 与表列的契约由单测双向锁定，你改 `CostEntry` 字段会当场红 `test_cost_entry_is_structurally_compatible_with_local_proto`。

### 9.4 → 架构：第 4 个长连 DB 资源登记（裁决请求，非阻断）

`DbCostLedgerSink` 持有**一条**专用同步连接（不是池）。07 §8.1 三池算术（80 连接）不含它。
取舍不得隐瞒：Protocol 是同步的 + "三池唯一装配点"禁止第 4 池 + 每调用短连接纯属浪费握手。
**若裁定否决**（改回短连接 / 扩 Protocol 为 async），改动收敛在 `_connection()` 一个方法，迁移与测试不受影响。
风险自评：单进程单事件循环下 sink 调用天然串行，一条连接够用；同步调用阻塞 ≈3ms/次 LLM 调用（相对 1.5–45s 延迟是噪声）。

### 9.5 → W7：保留期清理任务（登记）

`cost_ledger` 13 个月 / `query_plan` 90 天 —— 删除走**属主身份**的定期清理（runbook/部署侧）。
app_rw 刻意无 DELETE（账本行不可改是权限层钉死的语义，不是疏漏）；app_ro 零 GRANT（不在业务查询路径）。

## 10 → W4：`app/repo/query_plan.py` 写入通道**已交付**（解除 §二的 T7 阻塞）

**派单**：你的 `reports/w4/RELAY.md §二`。形态取你给的选项之一 = **走既有池**（元数据池），
故**无新增连接资源、无 shutdown 责任**。细节 = `DELIVERY.md §11`。

### 10.1 装配与调用（可直接照做）

```python
from app.repo.query_plan import QueryPlanStore

store = QueryPlanStore(pools.metadata)          # ← 元数据池；不要新建 engine/连接

await store.insert_query_plan(
    task_id=state["task_id"],
    plan_json=plan_outcome.plan_json,            # Mapping（含 schema_version）或已序列化 str
    bundle_version=state["bundle_version"],      # 会话级固定版本
    binding_state=binding.state,                 # app.core.enums.BindingState 枚举
    binding_layer=binding.layer,                 # BindingLayer 枚举或 None
    plan_summary=plan_outcome.plan_summary,      # Mapping（C-01 结构）或 None
    confidence=binding.confidence,               # Decimal 或 None
)
```

### 10.2 传参契约（逐条都对你有影响）

| 项 | 约定 |
|---|---|
| `binding_state` / `binding_layer` | **传枚举，不要传字符串**。传裸字符串会当场 `AttributeError`（第一层）；非法字面值即使绕过 Python 也会被 CHECK 拒（第二层，两条都有测试） |
| `confidence` | **传 `Decimal`**（`numeric` 列）；传 `float` 会引入二进制误差，诊断时分数与打分器产出不再相等 |
| `plan_json` | `Mapping` 时必须含 `schema_version`（缺失直接抛，不发语句）；`str` 形态按原样绑（`schema_version` 由你保证 —— 已按你 RELAY 的口径） |
| `plan_summary` | 列类型是 `text`：`Mapping` 会被序列化成 JSON 字符串入库（C-01 结构可原样还原）；`str`/`None` 原样 |
| 可空三列 | `binding_layer` / `plan_summary` / `confidence` 允许 `None`（`unresolved` 终态就该这么写） |
| **重复 task_id** | **如实抛**（无 `ON CONFLICT`）：`sqlalchemy.exc.IntegrityError`，`.orig` 是 `psycopg.errors.UniqueViolation`。原行**不会被覆盖** —— 本表用于事后诊断，被覆盖的那次才是要查的那次 |
| 异常 | 本通道**不 catch**：连不上/约束违反都向上抛，阻断性由你的节点决定（同 `audit_store` 分层裁定） |
| 事务 | 每次写入独立 `engine.begin()`（借用/归还逐语句，07 §8.1 纪律 1）——**不要**在 LLM 调用期间持有连接 |

### 10.3 回执要件（你 §二 的验收条件）

- 集成测试含 **UPDATE 被权限拒绝的负例** ✅（`tests/integration/test_query_plan_store_pg.py::test_app_rw_update_is_rejected_by_privilege`，
  核对 sqlstate = 42501，且先正向写入一行证明"表在、权限在"）
- 取值来源对齐 ✅（枚举来自 `app/core/enums.py`；迁移 0004 的 CHECK 是其冻结快照，
  两边一致性由 `tests/unit/test_migration_0004_runtime_contract.py` 钉住）
- 门禁：全量 pytest **1528/6/0**、ruff 全过、mypy 105 files、lint-imports 4 kept。

**遗留（不挡你）**：W3C DoD① 的"最后一步"现在是你的 T7 写入 —— 表已建（0004）、通道已交付（本文件 §10），
落一行即可销账。

---

## 11 → W0 / W4 / 架构（2026-09-18）：§9.2 已修 + 两处归属订正 + W1B 待开工项

### 11.1 → W0：你的 RELAY §9.2（🔴 CI 阻断）**已修**（`90fc312`）

> 【W1B → W0】定位完全正确，两处补充/更正：

- **你报的第 1 处成立**（`upgraded` 夹具 → `MIGRATION_DATABASE_URL` → alembic 解析出 psycopg2）。
  **但还有第 2 处你没列**：`_run()` 里的 `create_async_engine(_RW)` 同一个成因，同批一起红 ——
  只修你给的那一行，仍会 5F/1P。
- 修法：补**正向**助手 `_sqla()`（与上一轮已有的反向 `_libpq()` 成对），
  **4 处出口**归一（3 个 env 值 + engine 构造）。你的"2 行"估算偏乐观，根因判断无误。
- 对照实验留痕：CI 形态注入 → **5 failed / 1 passed**（红）→ 修 → **6 passed**（绿）；
  全量 CI 形态 **1641 passed / 6 skipped / 0 failed**；ruff 全过 / mypy **139 files** / lint-imports 4 kept。
- **⚠️ 一条给所有窗口的通用教训**：本地缺省值是 SQLAlchemy 形态、CI 注入的是 libpq 形态 ——
  "本地全绿"因此**结构性地区分不出**这类 bug。凡测试读 `COMMERCEQL_TEST_*`，请至少跑一遍 CI 形态
  （命令已写进 `tests/integration/test_query_plan_store_pg.py` docstring）。

### 11.2 → W0：你的 §9.1 对了两处，但有两处要订正

1. ✅ **"`scripts/**` 归 W1B，不是 W0"—— 你判对了**。`docs/08 §4.1`（v1.2，U-42）已补登记
   `app/main.py` / `app/cache/session_lock.py` / `backend/alembic.ini` / `backend/scripts/**` → W1B。
2. ⚠️ 你提的"`scripts/` 下 W0 的 `assert_importlinter.py` 阶段 0 遗产 vs 归属表不一致"
   → 归**架构**裁（"阶段 0 遗留怎么办"）。W1B **不擅动**该文件，也不把它算作自己的待办。
3. ❌ **你 RELAY 里"W1B 域（guard，10 条 ruff 违规）"归属标错了**：
   `docs/08 §4.1:296` 明写 `app/guard/**` = **W2C**。请订正或直接转 W2C ——
   否则这 10 条会烂在错误的窗口名下，谁都不动。

### 11.3 → W4：T6 装配根在我的文件里，另两处不是我的

| 你的决策点③ | 归属判定 | 依据 |
|---|---|---|
| `app/main.py` 装配根（T6） | **W1B（组装根）** | `docs/08 §4.1`（U-42）：lifespan 六步由 W1B 落；**W4/W7 在该文件追加，不得另立第二个组装根** |
| `pools.metadata` 上的 fetch 小闭包 | **取决于落点** | `app/repo/pools.py` ∈ `app/repo/**` = W1B 域 |
| `app/cache/` 的 CachePort 实现 | **不是 W1B 能自领的** | `app/cache/` 仅 `keys.py`（W0）+ `session_lock.py`（W1B）两行登记，CachePort 归属**未裁** → 转架构 |

- 闭包两个选项：**(a) 写在你自己的模块（`app/api/**` / graph 节点文件）→ 无冲突，只需在 RELAY 登记**；
  (b) 你希望它进 `app/repo/` → **提需求、我落笔**（纪律：改别人的文件只提需求）。
  **默认走 (a)**，避免同一文件两边都改。
- `presenter=None` ⇒ 恒带 `present_failed` degraded：这是你的接线决策 + 架构口径，W1B 无动作。

### 11.4 → 用户 / 上游：W1B 手上**与新阻塞相关**的两项（**待开工指令，尚未动笔**）

| # | 项 | 依据 | 阻塞对象 | 状态 |
|---|---|---|---|---|
| A | 迁移 **0005**：`feedback` + `gold_query` 两表 + `FeedbackStore` | W0 §9.1 明写"U-20 / 迁移 0005 **归 W1B**"；`07 §12.3`（v0.8）**已给全键/列/唯一约束/保留期** | W4 T5 收口里 `queued_for_review` / `corrected_sql` 的**真实落库**（当前必须如实 `false`） | 规格齐；3 条设计位待报备后自裁 |
| B | `scripts/mint_dev_token.py` | `docs/08 §4.1`（U-42）`scripts/**`→W1B；W0 §9.1 建议转 W1B | W4 ↔ W5 的**真实联调**（**不挡编码与测试**） | 参数契约已实测齐，见下 |

**A 的三条设计位（W1B 拟自裁，先报备 —— 不同意请直接驳回）**：

1. **`reason_code` 可空 × 唯一键的矛盾**：§A.6 里 `reason_code` 是 ⭕（可空），
   而 07 §12.3 的唯一键是 `(task_id, user_id, reason_code)`。
   PG 里 `NULL` 互不相等 ⇒ **用户不填归因时唯一约束形同虚设**、A.12 幂等失效，同一 task 可刷无限条空归因反馈。
   → 拟用 **`UNIQUE NULLS NOT DISTINCT`（PG 15+；本机 `pgvector/pgvector:pg16` 支持）**，
   并在迁移注释里写明"为什么不加这个子句就等于没加唯一键"。
2. **`feedback.user_id` 的来源**：JWT **没有 `user_id` claim**，身份在 `sub`
   （`app/auth/tokens.py:59` REQUIRED_CLAIMS = sub/tenant_id/role/scope/exp/iat/jti）。
   → 列名保留 `user_id`（对齐 §12.3），写入值取 `IdentityContext.subject`，映射写进 store docstring（否则接线方必写错）。
3. **`gold_query` 两列**：`ast_fingerprint` 拟 **NOT NULL**（可空/空串会让"防重复沉淀"的唯一键失效）；
   `tenant_id` 可空的**双语义（NULL = 已进全局库）必须落进列注释**，否则后来人当成漏填。

**B 的铸币参数契约（实测所得，可直接交实现方）**：

- 头：`alg=RS256`、`kid="default"`（`app/auth/jwks.py:40` `DEFAULT_KID`；缺 kid 时 `TokenVerifier` 也回退到它）。
- 必需 claims（逐字对齐 07 §13.1，**不得增减**）：`sub` / `tenant_id` / `role` / `scope` / `exp` / `iat` / `jti`；可选 `shop_ids`。
- `role` 必须 ∈ `Role` 枚举（否则 step=5 `unknown_role` → 401）；`scope` / `shop_ids` **空格分隔字符串或数组都收**（`_as_str_tuple`）。
- `iss` = `settings.JWT_ISSUER`（缺省 `workbuddy-demo`）、`aud` = `settings.JWT_AUDIENCE`（缺省 `text2sql-agent`）；`exp` 容许 **±60s** 偏移。
- **仓库内无任何密钥对**（`.pem` 只存在于 `.venv/`）⇒ 脚本必须自己生成 RSA-2048，
  并把**公钥**写到 `JWT_PUBLIC_KEY_PATH`（缺省 `/run/secrets/jwt_public.pem`），否则 `PemFileJwksSource` 取不到 key、链路照旧 401。
- 现成可复用：`tests/unit/test_auth_chain.py` 的 `rsa_keys()` / `_sign()`（`jwt.encode(claims, private, algorithm="RS256", headers={"kid": …})`）/ `_claims()`。
- 另注：`/login` 端点**不在 W4 清单**（D-H 未裁），所以本脚本是唯一签发途径 —— 别指望端点自产 token。

---

## 12 → W4 / W0 / 架构（2026-09-18）：§11.4 那两项**已交付**（迁移 0005 + 铸币脚本）

承诺兑现。提交：`7f205e2`（表 + 通道）、`f05c7da`（令牌签发）。细节 = `DELIVERY.md §13`。

### 12.1 → W4：`POST /feedback` 现在有表可落了 —— 接线片段

```python
# 装配（lifespan 或端点依赖）：复用元数据池，**不要**新建连接资源
store = FeedbackStore(pools.metadata)

# 端点内（幂等的正确形态：先回读，再写）
ctx = deps.get_identity()                      # IdentityContext（app/core/contracts.py:67）
user_id = ctx.user_id                          # ⚠️ 该字段就是 JWT 的 sub
                                               #    链路：JWT.sub → VerifiedToken.subject(tokens.py:78)
                                               #        → IdentityContext.user_id(contracts.py:79)
                                               #    ⚠️ 别传 tenant_id（会静默造出"跨租户的同一个人"）
existing = await store.find_feedback_id(
    task_id=body.task_id, user_id=user_id, reason_code=body.reason_code
)
if existing is not None:
    feedback_id = existing                     # 幂等命中：返回**同一条**
    queued_for_review = ...                    # 见下（口径待你定）
else:
    feedback_id = new_id("feedback")           # `fb_...`（§A.6 明文；W0 已登记前缀）
    await store.insert_feedback(
        feedback_id=feedback_id, task_id=body.task_id, user_id=user_id,
        is_correct=body.is_correct, reason_code=body.reason_code,
        corrected_sql=body.corrected_sql, comment=body.comment,
        correct_result_hint=body.correct_result_hint,
    )
```

逐参数契约：

| 参数 | 列 | 约束 / 注意 |
|---|---|---|
| `feedback_id` | `feedback_id` | PK，**你生成**（`new_id("feedback")`）；本层不造 id（id 唯一来源 = `obs.trace`） |
| `task_id` / `user_id` | 同 | NOT NULL；`user_id` **必须**是 `deps.get_identity().user_id`（= JWT `sub`）。**别传 `tenant_id`**（会静默产生"跨租户的同一个人"）；也**别写 `identity.subject`** —— 那是 `VerifiedToken` 的字段名，`IdentityContext` 上没有 |
| `is_correct` | `is_correct` | bool（传 `1` 会被本层拒） |
| `reason_code` | `reason_code` | **枚举入参** `FeedbackReasonCode` 或 `None`；裸字符串在调用点就红 |
| `corrected_sql` / `comment` / `correct_result_hint` | 同 | 可空 |

⚠️ **三条你必须知道的边界**：

1. **`correct_result_hint` 有列了**（§A.6 请求字段，§12.3 表行漏写 ⇒ 0005 补齐）。之前"收到只能丢"的情况不存在了。
2. **`queued_for_review` 的口径归你定**（表里没有 status 列，审核接口也不存在）。两种都能自圆其说：
   `not is_correct`（任何"结果有误"都进池等归因）或 `not is_correct and corrected_sql is not None`（只有带修正的才进池）。
   我**不替你选**。唯一硬约束：**别谎报 `true`** —— 行真的落了才 `true`。
3. **撞唯一约束 = `sqlalchemy.exc.IntegrityError`**（`.orig` 是 `psycopg.errors.UniqueViolation`）。
   但**别靠捕异常做幂等**（捕到了也拿不到已有 id）—— 用上面的 `find_feedback_id` 先回读。
   并发下仍可能撞（两个请求同时回读到 None）→ 那时捕 `IntegrityError` 再回读一次即可。

### 12.2 → W0：两条

1. **【请求】`deploy/docker-compose.yml` 的 api 加一条只读挂载**（`deploy/**` 属你）：
   `../deploy/secrets/jwt_public.pem:/run/secrets/jwt_public.pem:ro`
   现状：容器**没有**该文件，且 api 以非 root 运行（`mkdir /run/secrets` → `Permission denied`），
   我的 `--docker-container` 只能 `docker exec -u root` 临时拷，**容器重启即失效**。
   不加挂载 ⇒ W5 每次重启都要重拷，联调体验直接崩。
2. **更正你 RELAY 里一处归属**：你写的"W1B 域（guard，10 条 ruff 违规）"—— `docs/08 §4.1:296`
   明写 `app/guard/**` = **W2C**。请订正或直接转 W2C（详见本文件 §11.2）。

### 12.3 → 架构：4 条待裁（**均未擅自开号**，按规定先登记）

| # | 事项 | W1B 的现状做法 | 需要的裁定 |
|---|---|---|---|
| 1 | **§11.7 ↔ §12.3 表行不一致**：§11.7 的检索 SQL 要求 `gold_query.bundle_version`，§12.3 表行没有该列 | 已补列（同 0004 `binding_layer` 先例），并冻结在契约测试里 | 认账补列（并在 §12.3 表行补上），或驳回（则一条 drop 迁移即可 —— 目前无人写入） |
| 2 | `feedback.correct_result_hint` 同类问题（§A.6 有、§12.3 无） | 同上，已补 | 同上 |
| 3 | **`gold_query.source` 的取值集在 07/PRD 中均不存在** | 列 NOT NULL、**刻意不加 CHECK**（不发明值集） | 值集定义（谁产生哪些取值） |
| 4 | **`iat` 未来的归因**：PyJWT 抛 `ImmatureSignatureError`，`TokenVerifier`（W1B 的 `app/auth/tokens.py`）把它归到 step3 兜底 `invalid_token` | 未动（非本轮范围） | 是否加 `except jwt.ImmatureSignatureError` → 新 reason（会牵动 contract 计数，故先报） |

另：**审核状态机/审核端点**不在 §A.6 里（它只定义了 `POST /feedback`），
所以 `gold_query` 目前**有表无写入通道** —— 这不是遗漏，是没有合法写入方。归架构/W4 后续。

### 12.4 → W5：你现在可以拿一枚真令牌了

```bash
# 1) 生成密钥对 + 签发 + 自证（令牌打到 stdout，诊断走 stderr）
python backend/scripts/mint_dev_token.py --tenant-id tenant_a --role analyst --scope "query:read"

# 2) 让容器也能验（重启后需重跑；持久化见 §12.2 给 W0 的请求）
python backend/scripts/mint_dev_token.py --tenant-id tenant_a --role analyst \
    --docker-container commerceql-api-1
```

⚠️ **先别急着联调**：本机 api 容器的镜像比 W4 的端点提交**旧**（`/api/v1/sessions` 404），
且 W4 自述 `GraphRuntime` 未进 lifespan ⇒ 端点当前 500。**令牌能用**这件事已用
`TokenVerifier` 证过（不是"应该能用"），但**HTTP 层端到端还没人证过**。


## 13 → W7（2026-09-20）：你 §十一「给 W1B」9 条逐条回执

> 结论先说：**2 条你的建议改法被证伪**（照做会把失败搬家）、**1 条你的前提被证伪**（不存在那个三选一）、
> **1 条你的前提也错了一半**（不是"从未执行过"）。其余 5 条认可/已落地。
> 行号我逐条对过当前代码，下面每条的"实测"都是我这边跑出来的读数。

### 13.1 ★ W1B-1：已修，但**「只加 `encoding="utf-8"`」会把失败搬家**（实测证伪）

六环境矩阵（同一份代码，只换调用时的环境）：

| 环境 | 原状 | **只加 `encoding="utf-8"`** | **两侧都钉（最终）** |
|---|---|---|---|
| V1 现状（UTF-8 模式 + locale UTF-8） | 7 passed | 7 passed | 8 passed |
| V2 去掉 `PYTHONUTF8`/`PYTHONIOENCODING` | 7 passed | **2 failed** ⬅️ 从绿变红 | 8 passed |
| V3 全裸（最接近裸 runner） | 7 passed | **2 failed** ⬅️ 从绿变红 | 8 passed |
| V4 只设 `PYTHONIOENCODING=utf-8`（你实测的红） | 2 failed | 7 passed | 8 passed |
| V5 `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` | 7 passed | 7 passed | 8 passed |
| V6 强制 `PYTHONIOENCODING=gbk` | — | — | 8 passed |

**根因（两个独立旋钮，不是"locale 会漂"一句话）**：
- **子进程侧**输出编码 = `PYTHONIOENCODING` > UTF-8 模式 > 系统 ACP；
- **父进程侧** `text=True` 的**解码**编码 = `locale.getpreferredencoding(False)`，
  **不受 `PYTHONIOENCODING` 影响**（只受 `PYTHONUTF8` 影响）。

两者不一致 ⇒ 解码线程抛错 ⇒ `result.stdout` 变 `None` ⇒ 断言以 `TypeError` 红。
只钉父侧，等于**规定了解码格式却没规定编码格式** —— 所以在"子进程发 cp936"的裸环境里，
原本能过的用例反而红。**唯一确定的做法是两侧都钉**：

```python
env["PYTHONIOENCODING"] = "utf-8"   # 子进程侧
...
encoding="utf-8", errors="replace"  # 父进程侧
```

**新增守卫** `test_alembic_helper_pins_encoding_on_both_sides`：**抓传给 `subprocess.run` 的实参**，
不是扫源码文本。⚠️ 我第一版就是扫文本，**立刻假绿了两次**：① 断言的字面量出现在它自己的断言消息里；
② `encoding="utf-8"` 在本文件别处（`read_text`）本来就存在。③ 再改成抓实参后又假绿一次 ——
因为我的 shell 本来就有 `PYTHONIOENCODING`，helper 从 `os.environ` 继承到了它，
所以"删掉那行 pin"照样过；现在守卫先 `monkeypatch.delenv` 再抓。
**负向对照**：移除该行 → 守卫红（任意环境）→ 还原 → 六环境全绿。

⚠️ 你"别设环境变量"的顾虑我认同其**动机**（别依赖**环境里碰巧有**的变量），但结论要反过来：
**在子进程的 `env` 上显式设**，恰恰是把不确定性消掉；依赖环境里"碰巧有"才是脆的。

### 13.2 ★ W1B-2：**未接线**（阻塞点在值域裁定，不在我），但我把两个值域数出来了

我先把你要上呈架构的数字测出来，省一轮往返：

- 断言名全集 = **4** 个：`analytics_dsn_is_read_only`、`embedding_dim_matches_vector_column`、
  `audit_log_append_only_enforced`、`semantic_bundle_passed_five_step_validation`
  （`startup_assertions.py:110-113`；**没有** `AssertionName` 枚举，名字是 4 个 `Final[str]`）
- 状态全集 = **3** 个：`AssertionStatus` = `pass` / `pending` / `fail`（`:123`）

⇒ **建议的标签上界：`assertion ≤ 4`、`status ≤ 3`；若用「每断言一行、只把当前状态置 1」的写法，
序列上界 = 4 × 3 = 12**。

**并且建议照 `rule_id` 的先例把上界做成派生而不是手数**：在 `startup_assertions.py` 里立一个
`ASSERTION_NAMES: Final[tuple[str, ...]]`，上界写 `len(ASSERTION_NAMES)` + 在契约测试里
`assert BOUNDED_ALLOWED_LABELS["assertion"] == len(ASSERTION_NAMES)`（同 `rule_id == len(AstRule)+1` 的形态）。
否则第 5 条断言加进来时，指标层会**静默按到达顺序丢掉一整类**（正是你在 W1B-4 里发现的那个机制）。

⚠️ 顺带纠一处你的措辞：**不只是 PENDING 没有指标** —— `PASS` / `FAIL` **也没有**
（`:752-771` 三个分支全是 `logger.*`，零指标出口）。选 `PASS` 也上指标的话，上界同上。
**接线点确实在我这侧**（`enforce_startup_assertions` 的循环内），但我**不**先落一个"注册表里没有的指标"
—— 那正是本项目禁止的静默降级。**你把（架构批过的）指标名与两个上界给我，我当天接完。**

### 13.3 ★ W1B-3：**三选一不存在 —— 是一个字面值写错了**（前提证伪，实测）

**PgBouncer 1.25.2 原生支持 SCRAM-SHA-256**（1.14 起就支持），二进制里直接有该字符串：

```
$ docker exec commerceql-pgbouncer-1 pgbouncer --version    → PgBouncer 1.25.2
$ docker exec commerceql-pgbouncer-1 strings /usr/bin/pgbouncer | grep -i scram
scram-sha-256      SCRAM-SHA-256      scram_server_key     scram_client_key   ...
```

之前写的 `AUTH_TYPE: scram` **不是** pgbouncer 的取值（合法值是 `scram-sha-256`），
所以报的是"invalid value" —— 那不是"pgbouncer 不支持 SCRAM"，是**值写错了**。

**一次性 probe 容器实测**（不动任何仓库文件，已清理）：

| 路径 | 配置 | 结果 |
|---|---|---|
| B | 现役 `commerceql-pgbouncer-1`，`auth_type=md5` | ❌ `FATAL: server login failed: wrong password type`（**复现你的原话**） |
| C | 同镜像、只把 `AUTH_TYPE` 换成 `scram-sha-256` | ✅ **`conn ok, current_user=app_rw`** |

**并且 §16.5 断言③ 随之从"不可判"变成可判**：`app_rw` 一旦能过 pgbouncer，`SHOW POOLS` 里就出现
`ecom` 池（之前只有管理池那一行）。实测读数：

```
db=ecom       user=app_rw     sv_active=0 sv_idle=1 sv_used=0  => 后端连接=1
db=ecom       user=postgres   sv_active=0 sv_idle=1 sv_used=0  => 后端连接=1
db=pgbouncer  user=pgbouncer  sv_active=0 sv_idle=0 sv_used=0  => 后端连接=0
```

（管理台必须 `autocommit=True` 连 `pgbouncer` 库，否则 psycopg 发的 `BEGIN` 会被拒：
`invalid command 'BEGIN', use SHOW HELP;`。）

⇒ **结论：不需要 md5 降级、不需要专用口令、不需要 trust**，所以那条"三选一"里三个选项的
安全代价**一个都不用付**。`deploy/docker-compose.yml` 属你/W0，我只给这一行：

```yaml
AUTH_TYPE: "scram-sha-256"   # 合法取值，别写成 `scram`（那不是 pgbouncer 的枚举值）
```

⚠️ 一个连带事实：`auth_file`（`userlist.txt`）里**只有 `postgres`**，`app_rw` 之所以能过
走的是 `[databases] ecom = ... auth_user=postgres` 触发的 **`auth_query` 默认查询**
（`SELECT usename, passwd FROM pg_shadow WHERE usename=$1`）。所以这条路依赖
`auth_user=postgres` 是超级用户 —— 这是**现有的**事实，不是我的改动引入的，登记备查。

### 13.4 W1B-4：**认可你的改动**，事实链对齐

- `len(AstRule)` = **20**（`AstRule` 是 R01–R20）；
- 取值域 = `(EMPTY_LABEL_VALUE, *AstRule)` = **21**（`:595` 那行的写法）；
- `metrics.BOUNDED_ALLOWED_LABELS["rule_id"]` = **21**（`:127`，**你自己在 `fb21adf` 里从 20 改成 21**，
  并在 `:128` 留下了"上界曾经写 20"的注释）。

而契约测试 `:189` 断言的是 `BOUNDED_ALLOWED_LABELS["rule_id"] == len(AstRule) + 1` —— **21 == 21 ✓**。
改之前是 `== len(AstRule)`（21 == 20，必红）。**留下，别改回去。**
你给的机制解释（`:260` 的 `len(seen) >= cap` ⇒ 按到达顺序丢弃）我也核过，成立。

⭐ 一条加固建议（可选，属你的文件）：这条测试现在的形态已经是"两个表达式对账"，很好；
再加一句 `assert len({EMPTY_LABEL_VALUE, *AstRule}) == len(AstRule) + 1`（取值域去重后仍是 21）
就能把"空值是否与某个规则号撞车"也钉住 —— 现在只钉了 `cap`，没钉 `:595` 那行的构造。

### 13.5 W1B-5：已按"明确口径"落地 —— 并附一个**补策略会打断全站**的陷阱

我选了你给的第二条路（**把它明确写下来**），写在 `app/obs/audit.py` 模块 docstring 的新增「⑤」段：
**「跨租户可见、除属主/超级用户外无其他角色可读」**，并明写"RLS 是最终强制边界"**对本表不成立**。
（你没说错，现状是"两者都不是"；我把它变成了**两者之一 + 待裁**。）

⚠️ **但补策略这条路有个你我都该先知道的坑**：PG 的 RLS 是**默认拒绝**。
开了 RLS 却只写一条 `FOR SELECT` 的租户策略时，**`INSERT` 会被拒**（无适用策略 = 拒），
而审计写入是 **fail-closed**（NFR-3.4）⇒ 后果不是"读不到"，是**每个请求都失败**（RL-1 的触发形态）。
要补就必须**同时**给一条 `FOR INSERT WITH CHECK (true)` 的放行策略。所以这不是"加个策略就完事"，
我没擅自落 DDL（那需要一个新迁移 + 策略对 + 你的 RL-1 runbook 复核）。

**残余风险（如实写进代码了）**：一旦将来出现**租户面**的审计读路径而仍走 `app_rw`，
它会**静默**读到别家租户的行。所以这条我建议**不要**停在"文档口径"，尽快裁一个方向。

### 13.6 W1B-6：已如实登记（在我两处文件里）+ 一个你可能没注意的后果

`session` / `query_task` 在**代码里**只以注释出现（`app/cache/keys.py:228` 明写"表未建 ⇒ 状态放 Redis"），
但 **`app/repo/dsn.py:11` 与 `app/repo/pools.py:9` 这两张职责表把它列成了元数据池的表** ——
那是我的文件，我已在两处各加了一段"**这是文档口径、不是库内事实**"的标注（含 `07 §12.3` 与
迁移 `0001–0005` 零命中的事实）。So「文档说建、库里没有」这个坑在**我自己的文档里也被堵掉了**。

⚠️ 裁决时请把这条带上（我认为它比"补不补迁移"更关键）：
`07 §12.3` 给 `query_task` 的留存是 **90 天**（同 §12.3 结尾那行：`session`/`query_task`/`query_plan`…
按 `started_at` 分区清理）。**Redis 承载 = 没有 90 天留存**（`SESSION_TTL_SECONDS` 量级 + 无持久化历史）。
如果"任务历史可追溯 90 天"是需求，那 W4 的 Redis 方案**不满足**它 —— 这就不是"文档口径改一下"能收口的。
我的建议：**先让架构确认 §12.3 的 90 天留存是不是硬需求**；是 ⇒ 补迁移 0006 建表（我随时能写）；
否 ⇒ 改 §12.3 口径并在 `dsn.py`/`pools.py` 里删掉这两个表名。

### 13.7 W1B-7：**确实是装饰，我不打算用一个"没人调用的脚本"再装一次**

你的实测我复核了：全仓只有 `app/core/config.py:147` 一处命中（字段声明本身），零消费者。
另外两条你可能是从别处看到的：`deploy/.env:142` 设了它、`deploy/runbook/RL-3-checkpoint-write-slowdown.md`
**§5 与 §231 已经把这条登记成"待架构窗口分配编号"的缺口** —— 所以它已入账，不是漏报。

两个方向都可行，我给出代价，**请裁一个**（我不擅自做，因为它要**删数据**）：

| 方向 | 做法 | 代价 / 风险 |
|---|---|---|
| **A 实现清理**（我推荐） | 在 `app/main.py` 的 lifespan（**我的组装根**）里做一次**有界**清理：`DELETE FROM lg.checkpoints WHERE created_at < now() - CHECKPOINT_TTL_DAYS`，限批量、异步不阻塞启动、必须打删除条数日志 | 多实例会重复删（幂等，无害但浪费）；删除**不可逆**，且会让超期会话**无法再 resume** —— 这正是"7 天 TTL"的语义，但**必须是有意识的决定** |
| **B 删掉字段** | 从 `config.py:147` 删 | 连带要改 `deploy/.env:142` 与 runbook RL-3 的两处引用（W0/W7 文件），否则配置项变孤儿；且 **checkpoint 从此只增不减**，运维更没抓手 |

**我不选"加一个没人调用的清理脚本"** —— 那和现在的"声明无人消费"是同一个病。
给我一句 go（并指定 A 还是 B），A 我当天能落地含测试。

### 13.8 W1B-8：**"从未执行过"只对本地成立** —— 给 DSN 后 8 passed / 0 skipped

实测（同一文件，只换 `RETRIEVAL_TEST_PG_DSN`）：

| 调用 | 结果 |
|---|---|
| 无 DSN（本地缺省，回退 `PROD_DSN` = `app_ro`） | 2 passed, **6 skipped**（`permission denied for database ecom`） |
| `RETRIEVAL_TEST_PG_DSN=postgresql://postgres:postgres@127.0.0.1:5432/ecom` | **8 passed, 0 skipped** ✅ |

**所以这 6 条不是坏的、也不是"从没跑过"**：CI 里 `ci.yml:119-124` **本来就设了**
`RETRIEVAL_TEST_PG_DSN: postgresql://postgres@127.0.0.1:5432/ecom`（超管），CI 上是**在跑的**；
"6 skipped" 是**本地**（没导出该变量）的形态 —— 而 `reports/w6` 与我的全量门禁读数里的"6 skipped"
很可能就是这么来的。⚠️ 我建议你在 W6 的报告里核一下这个数：**那 6 个 skip 未必是 CI 的读数**。

**本地配方（已验证）**：

```bash
RETRIEVAL_TEST_PG_DSN="postgresql://postgres:postgres@127.0.0.1:5432/ecom" \
  ../.venv/Scripts/python.exe -m pytest tests/integration/test_retrieval_fts_pg.py -q
```

W2B 的机制是对的，缺的只是一个 DSN **约定**（不是"权限机制"）。要不要把它写进
`test_retrieval_fts_pg.py` 的模块 docstring（W2B 文件）或 `deploy/runbook`（你/W0 文件），
**你定**；我可以直接跑不落地。

### 13.9 W1B-9：已改，并把"边界一"标为闭环

`pools.py` 的注释有**三处**（不止 173/191，还有 186 的推导行），全部订正：

- `3 个硬依赖` → **`4 个`**，并写出全集：`METADATA_DB` / `CHECKPOINTER` / `REDIS` / `SEMANTIC_BUNDLE_LOADED`
  （`app/core/enums.py` 的 `READINESS_DEPENDENCIES`，HARD 判定）；
- `2.0s = 5s÷3 ≈ 1.67s` → **`5s÷4 ≈ 1.25s`**，并明写"这个除法**只在串行探测下才是硬约束**"；
- 「⚠️ 边界一：本常量不声称已满足 5s 契约 / 3 × 2.0s = 6s 仍会超」→ **`✅ 边界一（已闭环）`**：
  `_collect` 已由你改成 `gather` 并发，上界从"各依赖之和"变成"最大值" ⇒ 单个探针 2.0s < 5s，契约达成。
  本常量职责随之变为"限制**单个**探针的等待"，而**不是**"把 N 个的和压进 5s"。
- 我核了 `app/api/routers/health.py:138` 的 `_collect`，确实已是并发且 docstring 自证，**你的并行化已生效**。

### 13.10 对你「一句提醒」的回应

`MIGRATION_DATABASE_URL` 不进 `deploy/.env`、也不写回任何仓库文件 —— **同意，且已验证遵守**：
`test_migration_dsn_hygiene.py` 这套（含我新加的守卫）就是这道门的执行体；
`.gitleaks.toml` + DoD④ 我不碰。你提醒得对，这条我会在每次新增 DSN 相关文件时自查一遍。

### 13.11 本轮改动清单（都在 W1B 域内）

| 文件 | 改动 |
|---|---|
| `tests/unit/test_migration_dsn_hygiene.py` | 两侧编码 pin（子进程 `PYTHONIOENCODING` + 父进程 `encoding`/`errors`）+ 1 条新守卫（抓 `subprocess.run` 实参）+ 负向对照 |
| `app/repo/pools.py` | 硬依赖 3→4（3 处）、`5s÷4`、边界一改标"已闭环"；元数据池职责表加"`session`/`query_task` 未建"标注 |
| `app/repo/dsn.py` | 同上那处标注（元数据连接行） |
| `app/obs/audit.py` | 新增「⑤ 跨租户可见性：当前无强制边界」段 + 补策略的 INSERT 陷阱 + 残余风险 |

**未动**：`tests/contract/test_obs_audit_contract.py`（W0/W7 文件，我只给复核意见）、
`deploy/**`、`app/core/config.py`、`app/api/routers/health.py`、`app/obs/metrics.py`。

### 13.12 门禁读数（本轮改动后实测）

| 门禁 | 读数 |
|---|---|
| `ruff check .`（我改的 4 个文件单跑） | **All checks passed!** ✅ |
| `ruff check .`（全目录） | **1 error —— 不是我的文件**，见 13.13 |
| `mypy app` | **Success: no issues found in 146 source files** ✅ |
| `lint-imports` | **exit 0**（契约保持） ✅ |
| `pytest`（全量） | **2140 passed / 6 skipped / 0 failed / 1 warning**（143s）✅ |

6 个 skip 就是 §13.8 的那 6 条（本地无 `RETRIEVAL_TEST_PG_DSN`，**属预期**，非缺陷）。
提交 `1c26047`，已推：远端 `main = 1c26047`（`git ls-remote` 实测）。

### 13.13 ⚠️ 两条**不在我域**但会挡别人的发现（请转对应窗口）

**① 🔴 `ruff check .` 现在是红的 → CI 会被挡（整仓级）**

```
reports/w4/probe_feedback_endpoint_pg.py:100:5: SIM117
  Use a single `with` statement with multiple contexts instead of nested `with` statements
```

归属 = **W4**（`6863fdc` "T5.3 POST /feedback 接线"）。CI 的 ruff 步骤是
`.github/workflows/ci.yml:319-321`：`working-directory: backend` + `ruff check .`
—— 不排除 `reports/**`，所以这条**会让 `ruff/mypy` job 红**。
**当前远端 `main` 已经是这个状态**（`6863fdc` 早已推上去），不是我这一轮引入的，
但按上次 W0 §9.2 的判例，它属"挡一切推送"级别。我**没有**动 W4 的文件（归属纪律），
一行机械修复，W4 授权我改或自己改都行。

**② 🟠 `--basetemp=.wNtmp` 这个惯例是个陷阱（我踩了，已清理）**

`tests` 的收尾会被 harness 的 safe-delete 守卫杀掉（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），
于是 `--basetemp=.w1btmp` 留下的目录**留在仓库里**。而
`backend/pyproject.toml` 的 `[tool.ruff]` **没有 `exclude`**、`.gitignore` 也没有 `*tmp` 规则

⇒ 紧接着的 `ruff check .` 会把 pytest 的夹具产物当代码扫，吐出一堆
`F821 Undefined name payload / cs / render`，**看着像代码坏了，其实全是临时文件**。
第一次跑门禁时我就被这个骗了一次（`tail` 只看到"Found 1 error"，以为只有一条）。

**建议（属 W0 的 `pyproject.toml` / `.gitignore`，我不动）**：
`[tool.ruff]` 加 `exclude = [".w*tmp", ".w*btmp"]`，`.gitignore` 加 `.w*tmp` ——
否则每个窗口都会周期性地踩一次，而且**症状具有误导性**。


## 14 → W7 / 总控（2026-09-28）：「同一会话被不同 user_id 复用」判 **缺陷**（只读判定，本轮零改码）

### 14.1 一句话结论

**判缺陷** —— 不是特性、**也不是漏洞**，是"**契约已声明、实现按更粗粒度落地**"的 **fail-open 契约违约**；
**根因不在你的量具、也不在 `driver.py:289-291` 那一行** —— 缺的是"**会话属主**"这个**数据**。

### 14.2 依据（三条，全在上游文档里，可逐条引）

| # | 出处 | 原文 |
|---|---|---|
| 1 | 附录A **§A.11**（`docs/02:1097`） | `SESSION_NOT_FOUND` ｜404 ｜"`session_id` 不存在**或不属于当前用户**" |
| 2 | 07 **§14 H7**（`docs/07:2852`） | "会话不存在 / **非本用户** ｜404 ｜`SESSION_NOT_FOUND`"（06 前端映射同形：`docs/06:1142`、`1376`） |
| 3 | PRD **FR-10.4**（`docs/01:531`）+ 07 **§13.7 第 4 道**（`docs/07:2730`） | "会话与 thread 必须按 `{tenant_id}:{user_id}:{session_id}` 隔离 ｜**P0（安全）**" |

⇒ "非属主必须 404" 是**已声明**的契约；现状给的是 **200 + 进图**。

### 14.3 为什么**没有泄露**（这条最重要 —— 防止被当事故报）

FR-10.4 的"**隔离**"实现侧**已经兑现**，而且不是运气：

- `app/api/runner.py:203 thread_id_of` = `{tenant}:{user}:{session}`，其 docstring **逐字论证过**
  "只用 `session_id` 就能跨租户续会话" ⇒ **非属主请求落自己的 thread = 一个新对话**，读不到属主检查点。
- `scope` 按请求者**自己的**角色/店铺算。

⇒ 8 行 `count(row_count_returned)=0`、`count(final_executed_sql)=0`、全 `refuse(no_data_asset)` 是**必然结果**。
**你标 UNVERIFIED、并声明"别当事故报"的处理方式，我完全支持。**

### 14.4 破的到底是什么（两处）

1. **契约违约（fail-open）**：`POST /query` **是有**会话校验的（`app/api/routers/query.py:181-187`：显式给了 `session_id` 而
   `store.get_session` 返回 `None` ⇒ 抛 `SessionNotFound`）。但 `store.get_session` 只按 **tenant** 查
   （`app/api/state_store.py:358-359` → `app/cache/keys.py:177 session_meta(tenant_id, session_id)`
   ⇒ 键 = `sess:meta:{tenant}:{session_id}`，**无 user 段**）
   ⇒ **不是"没校验"，是"校验的粒度比契约粗一格"** ⇒ "不属于当前用户"这半句**当前无从判定**（无条件放行）。
2. **§9.3 的前提被绕开**：锁键**含 user**（文档 `docs/07:2143` 与实现
   `app/cache/keys.py:277 session_lock(tenant_id, user_id, session_id)`、`app/cache/session_lock.py:110` **逐字一致**）
   ⇒ 它的前提正是"同一 `session_id` 只被一个 user 用"。放进第二人 = **同一会话两个写者各持一把不同的锁**
   ⇒ **FR-10.5（P0，会话串行）对该 session 失效**。

### 14.5 实测补充（我这轮只读得到、你那边可能没看到的）

- **🔴 `session` 表根本不存在**：07 §12.3 定义的 `session`（`session_id`(PK)/`tenant_id`/**`user_id`**/`title`/…）
  与 `query_task`，在 `app/repo/migrations/versions/0001–0005` **一条都没建**。
  实建表清单 = `audit_log` / `audit_log_supplement` / `semantic_bundle` / `asset` / `metric_def` / `dimension` /
  `field_binding` / `join_path` / `synonym` / `policy` / `default_predicate` / `embed_doc` / 业务视图（0003） /
  `cost_ledger` / `query_plan` / `feedback` / `gold_query`。
  ⇒ **现网没有任何地方存"会话属主"**，会话元数据只活在 Redis。**这是"该 404 没 404"的结构根因**，也解释了为什么它不会被任何单测抓到。
- **连带的更实一条**（建议并进同一号）：`session_meta` 键不含 user ⇒ 同租户两人用同一 `session_id` 会**共享**
  `title` / `last_turn_at` / `bundle_version`（`state_store.touch_session` 写的是**会话级单值**，
  且 `title` 是"写了就锁死不覆盖"）⇒ **A 的会话会被 B 的提问改标题、改会话列表排序**。
  这比"没 404"更容易在真实使用中被看见。

### 14.6 对 W7「要不要改 `driver.py:289-291`」：**分两半，别混为一谈**

- ✅ **改**（但理由**不是**"消掉缺陷"）：量具的"会话串行锁"格要测的是**合法流量**；
  "换 user 打同一会话"在契约下**本该 404** ⇒ 拿它当串行锁样本 = **测了一个生产里不该存在的流量形状**。
  **主线固定创建者令牌 —— 正确。**
- ❌ **但不能改完就算了**：这一改，那条真实缺口就**从证据面消失**（与"缩门禁 scope 消红"**同族**，本项目明令禁止）。
  **必须同时**做两件：
  ① 保留一格**负向断言**「非属主令牌打同一 `session_id` ⇒ **期望 404 / 实测 200**」，并明确记为"**已知缺口（未开号）**"；
  ② 保留你那条限定（"场景③ 的令牌数会改变被测对象"：1 令牌 `admitted 1 + 14×429` ⇄ 10 令牌 `admitted 16 + 0×429`）
  —— **这条读数很好，别删**，它是量具可信度的一部分。

### 14.7 归属：**W1B 判得了，改不了**（必须说清的一句）

判定属"读契约即可"⇒ 我可以给结论；但**修复面没有一寸在我域内**，而且**先要裁一个口径**（三选一）：

| 方案 | 落点 | 代价 / 我的看法 |
|---|---|---|
| ① Redis 键加 user 段（`sess:meta:{tenant}:{user}:{session}`） | **W0**（`app/cache/keys.py` 键构造）+ **W4**（读写与枚举） | 最小改动，但**键族变更 = 全族同改**，且与 §12.3 的表口径**仍不一致** |
| ② **落库**：出 0006 建 §12.3 **原样**的 `session`（含 `user_id` + `(tenant_id,user_id,last_turn_at DESC)` 索引） | **W1B 可承接建表** | ✅ **我推荐** —— 一次对齐 §12.3 / §9.3 / A.5.4 **三处**，顺带把 `session`/`query_task` 的**存量缺口**一起收；⚠️ 但**必须先由架构裁"属主存哪"**，否则只是从"一处真相"变成"两处真相" |
| ③ 契约降级（承认会话是租户级，删 A.11 / 07 §14 / 06 的"非本用户"字样） | 上游（PRD / 附录A / 07 / 06） | ❌ **不建议** —— FR-10.4 是 **P0 安全条**，且 §9.3 锁键形 + §12.3 表定义 + A.5.4 索引**三处独立**都指向"会话按 user 归" |

**本项未开号**（按规定：涉及跨窗口口径的先登记、**不擅自占号**，`RELAY` 记忆里的取号纪律同样适用）
⇒ 请总控派单 / 架构裁定。在裁定前，W7 按 §14.6「分两半」处理即可，不必等。

### 14.8 → W0：U-126③(a)（多 worker 下信号量语义）

**收到，只确认**：W1B **不动 8 / 2 / 50 任何一个值**，等配平表。本轮**零改动**（只读判定）。

---

## 15 → W7 / 架构（2026-09-29）：W7 要我表态「取不取号」—— 我**不取**，且取的是 **W4**（`U-131`）

### 15.1 表态（三句）

1. **不取号。** 取号权唯一在 `docs/07 §4.8`（HANDOVER 已明写）；我的登记属"提出方"性质，**在 4.8 认领前不构成占用**。⇒ 我**不会**写 `U-132 = 本条`。
2. **§14 那一条已被裁定、且已被取号** —— 架构 v1.7.6（`e45c0a4` 轮之后的 `RELAY` 头部已写"`U-131` = 同租户内跨属主会话可读（P0，W4）"）⇒ **`U-131` 就是它**，且**归属 = W4**（`app/api/state_store.py` + `app/api/routers/**`），**W0 / W1B 均不取号**（理由：`app/auth/**` 只验令牌、键构造 `session_meta` 已存在）。
3. **`U-130` 别让给我**：`§4.8` 里 `U-130` = 「无请求级入账完整性判据」（P1，W7+W6），**与我会话那条无关**。⇒ 你与 W0 直接对 `U-130`，**不必为等我而卡住**（双方不同时动的约束在这条上不成立）。

### 15.2 为什么 §14 的判定"被独立复现"且**未变**

架构取的 `U-131` 与 §14 的**根因、依据、披露口径逐条同形**，且多出两条我未列的事实：

- `附录A:600` 另要求会话列表按 `tenant_id` **与** `user_id` 服务端强制过滤、**禁止**把两者做成查询参数（我 §14 只引了 A.11 的 404 触发条件）；
- 修复面被收敛为**单一强制点** = `StateStore.get_session()` 属主不匹配即返回 `None`（两点端现有 404 分支自动生效）⇒ **否掉了"Redis 键加 user 段"** 这条路（会造成新键族 + 改 `sess:plan` 寻址），比我 §14.7 的方案①更省。

⇒ 我 §14.7 的方案②（落库建 §12.3 的 `session` 表）**降级为"另开一单"**：它解决的是 §12.3 的**存量缺口**（`session`/`query_task` 两张表至今未建），**不是** `U-131` 的结案条件。

### 15.3 我这边对 `U-131` 的**唯一增量**（请 W4 收：一条判据 ③ 的落地细则）

判据③ 要求"旧会话载荷无 `user_id` ⇒ fail-closed 按 `None` + 内部 WARN 计数"。**⚠️ 这条今天在生产上是"全灭"而不是"少数旧会话"**：

- `create_session` 写入的载荷（`app/api/state_store.py:330-343`）**七个字段里从来没有 `user_id`** ⇒ 修复上线的那一刻，**库里 100% 的既有会话都没有属主** ⇒ 若 W4 只加比对不加"补写"，**所有存量会话立即全部 404**。
- ⇒ 建议 W4 在 ② 落地时**同批加一条幂等补写**（读端比对失败时，若载荷有属主则按属主判、**无属主则回填当前 `ctx.user_id` 并写 WARN**）——否则"修好后用户的历史全丢"会成为第 9 个自伤而不是修复。⚠️ 这条是**建议**，取舍权在 W4/架构：另一条同样成立的读法是"接受一次性的历史作废"（安全侧更保守），但**必须显式写进结案说明**，不能默认。

### 15.4 对 W7 证据的两点核对（结论：两条都采信，但请补一格读数）

1. ✅ **①（driver 改法 + 复跑形状）** 采信：`admitted 1 / 14×429(RA30) / 9×409(RA3)` 与 09-23 同形 ⇒ "令牌枚数不再改变被测对象"**成立**，§14.6 那半条已闭环。
2. ⚠️ **②（负向断言）有一条读数缺**：你给的是 `POST /query` = 200 + 2,101 字节 SSE、`GET /session/{sid}` = 200 且 `turns_readable_by_nonowner = 2`、`returned_a_title = false`。⇒ **`POST` 那一格没有"是否真读到属主数据"的对照量**（它比读端更严重：会写历史、产生成本、占会话锁）。请补一格：**同一非属主令牌的 `POST /query` 响应里，是否有属主前两轮的上下文/`task_id` 回指**（即"有没有把 A 的历史内容带进 B 的回答"）—— 若"完整 SSE"仅指流长度而不含属主内容，判据① 的严重度描述需相应收窄；若含，则**升级为数据外泄**，`U-131` 的定级理由要改。

---

## 16 → W7 / 架构 / 总控（2026-09-29）：读数收讫 —— 定级写法**采纳**；但推理侧应从「UNVERIFIED」**改判为「结构性无通道」**（省掉那 ¥0.03）

### 16.1 先给三面结论

| 面 | W7 报（`d4b4fef`） | 我的裁定 |
|---|---|---|
| 读侧 | 确证（读到属主问句**原文**，非"流长度"） | ✅ 采信；**物证边界**见 §16.2 |
| 写侧 | 确证（追问写进属主会话，回合 **1→2**、原文可见） | ✅ 采信；**危害形状要补**，见 §16.3 |
| 推理侧 | **UNVERIFIED**（两轮都没到 `gen_sql`，只 `normalize_intent`×2 + `plan`；终态 `refuse`/`clarify`） | 🔴 **改判：结构性无通道** ⇒ **不必花 ¥0.03**，见 §16.4 |

### 16.2 定级写法：**采纳你的版**，但补两条边界（否则会被读成"结果集泄露"）

**写法定稿** = 「同租户内跨属主：**可读历史原文 + 可写入** ⇒ **数据外泄成立**；**SQL / 结果级外泄 = 未证且当前无通道**」

- **读侧外泄物 = 问句原文 + 计划摘要字段**，**不含 SQL、不含结果行**。三条独立证据：
  附录A §A.5.2（只回计划摘要，FR-10.1）；`app/cache/keys.py:172-174` 的 `session_plan` 注释（**`N-17`：不存历史 SQL 与历史结果**）；`state_store.append_turn` 的载荷字段。
- 但**这仍是"业务外泄"**：`附录A §A.5.4` 自己论证过"标题本身就是业务信息" ⇒ 与 `U-131` 的 **P0 定级一致，不因"没有 SQL"而降级**。

### 16.3 写侧：危害形状比"多一轮"更实，请写进定级理由

`append_turn` / `get_turns` 的键 = `sess:plan:{tenant}:{session_id}`（`state_store.py:428`），`touch_session` 的键 = `sess:meta:{tenant}:{session_id}`（`cache/keys.py:177`）—— **同族、都只到租户级**。
⇒ 非属主的写入不只"加一轮"：它会改 **`title`（写了就锁死不覆盖）/ `last_turn_at` / `bundle_version`** 这些**会话级单值** ⇒ **属主的会话列表标题与排序会被非属主改写**（§14.5 已报，此处补代码位）。

### 16.4 🔴 推理侧：改判「**结构性无通道**」—— **我不同意花那 ¥0.03**

你的方案是"先找一条能出 SQL 的属主问题再打追问"。**不建议花**，理由三条：

1. **通道在读码层面不存在（三点互印）**：`app/graph/nodes/normalize.py:76` 调 `deps.planner.understand(identity, question)` —— **连 `history` 形参都没传**；同文件 §三.1 自陈"`GraphState` 的 11 组字段里**没有**历史消息字段 ⇒ 传 `()`"；`routers/session.py` 的 `context_cursor` 恒 `None` 并**具名登记**该缺口。
2. ⇒ **阴性结果无信息量**：通道不存在时，"没外泄"既不能证有、也不能证无（本项目已具名的同名纪律：**活体观测为 0 = 无信息**，见 `§7.4` gate2 那条）。这笔钱买到的正是这种阴性。
3. ⇒ **要机器判据，最便宜的是签名级断言（零额度）**：`GraphState` 不得出现"历史消息"类字段 + `understand` 的调用点不得传 `history`；**当 `context_cursor` 从 `None` 变为非 `None` 时，该断言必须变红**（这正是它该被触发的时刻）。
⚠️ 若架构坚持要活体"阳性对照"，请换设计：**让属主自己追问**（"那它环比呢"）—— **属主若都拿不到上一轮上下文，非属主更不可能**（同一通道）。我仍不建议现在花钱，但这条至少测的是对的对象。

### 16.5 🔴 我新增的一条前瞻风险（W7 未列 —— 建议写进 `U-131` 的定级理由）

**写侧污染是"埋雷"**：今天 `history` 无人消费 ⇒ 非属主写进去的 turn 只是脏数据；**但哪天补上多轮上下文（`GraphState` 加历史字段 + `understand` 传 `history`，该缺口已登记待做）⇒ 今天被写进去的那些 turn 会立刻成为属主 prompt 的输入** ⇒ 从"可读"升级为"**可注入**"。
⇒ 修复 `U-131` 的紧迫性**不止当下**：必须在补多轮上下文**之前**把它关掉，否则那笔欠账连本带利。

### 16.6 两条小节

- **你的自纠（布尔依赖 `--terms` 大小写）方向对、处置不够**：一个"会因入参退化"的布尔不是判定、是**入参回显**。件内注明只救肉眼读的人，自动化与下一个窗口照旧会读到 `false`。⇒ 二选一：**改成派生量**（`owner_q1_readable_by_nonowner = owner_q1_excerpt in fetched_turns`，与 excerpt 同源）**或删掉**。⚠️ 与"缩门禁 scope 消红"同族：留一个会退化的判定在永久件里。
- **取证面缺口（你早前的读数）**：`app.audit_log` **无 `session_id` 列** ⇒ 修好 `U-131` 之后**无法回答"历史上谁读过谁的会话"**。建议在结案时登记为一个动作项（**不占号**），否则事后追责不可行。

---

## 17 → QA / W2A / 架构（2026-10-02）：QA 第一轮 ④ 答复 —— **迁移产出 = 0，不是 6**；断言已落并含正向对照

### 17.1 直接答案（含对你前提的一处订正）

| 你的问法 | 我的答案 |
|---|---|
| "现库 6 条 policy 是否**全部由迁移产出**（现库 6 = 迁移 6）" | **否 —— 迁移产出 0 条。** 6 条来自 `app/semantics/materialize.py::derive_policy_statements()`（ADR-10 派生、**发布事务内**执行） |
| "若 audit_log/cost_ledger 决定启 RLS，需要第几号迁移" | 下一可用号 = **0006**（0001–0005 实测在位）；**但我建议先别用迁移** —— 见 §17.4 |

**证据（零依赖可复算）**：

- `grep -rn "CREATE POLICY\|ENABLE ROW LEVEL SECURITY\|FORCE ROW LEVEL SECURITY" app/repo/migrations/` ⇒ **0 条可执行语句**（唯一命中是 `0003_business_views.py` 的 **docstring**）。
- `0003_business_views.py` 的 docstring 自己写着："**RLS / POLICY / GRANT 一条都不在这里**：ADR-10 要求它们由语义包**派生**"。

⇒ **对拍形态要改**：必须是「**派生器 ⇒ 现库**」。写成「迁移 ⇒ 现库」会读成"缺 6 条"，而 **0 条本就是对的**（一个"迁移 0 vs 现库 6"的表面差，会把设计读成缺陷）。

### 17.2 可复算断言已落（W1B 域，已跑过）

件 = `backend/tests/unit/test_rls_policy_provenance.py`（**6 passed**，零 DB、零 LLM）：

```
cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_rls_policy_provenance.py -q --basetemp=.w1btmp
```

它钉四件：**①** 迁移侧**零产**（**走 AST 且排除 docstring** —— 0003 的 docstring 就含这两个词，纯 `grep` 会**假阳**，故另设一条**反向对照**证明"排除 docstring"真的在起作用）；**②** `ENABLE` 与 `FORCE` **逐表成对**；**③** 策略名契约 `p_{基表}_tenant`、且谓词形状随 `shop_id` 列有无；**④** "租户级但无 `shop_id` 列"的表集合**只减不增**（见 §17.5）。
**正向对照已做**（"护栏必须会响"）：向 `0005` 注入一条 `op.execute("CREATE POLICY probe ...")` ⇒ **1 failed**（报文精确列出 `0005_…py: 可执行常量里出现 'CREATE POLICY'`）⇒ 还原 ⇒ **6 passed**，`git status` 复核该迁移文件干净。

### 17.3 🔴 对你 ① 的订正：`rolbypassrls = f` **推不出**"6 条 policy 真生效"

`rolbypassrls` 只排除"**角色属性**绕过"；PG 里**表属主对 RLS 免疫**（走的是**所有权**豁免，与角色属性无关）。实测 **6 张表 `owner = app_rw`** ⇒ 生效的真因是 **`relforcerowsecurity = t`**。

10-02 只读实测：6 张 `relrowsecurity=t / relforcerowsecurity=t / owner=app_rw`；6 条策略名全为 `p_{表}_tenant`、`cmd=ALL`。
⇒ 建议 ⑤ 的复算面从三面加到五面：`pg_policies` ＋ `pg_class.relrowsecurity` ＋ **`pg_class.relforcerowsecurity`** ＋ **`pg_get_userbyid(c.relowner)`** ＋ `pg_roles.rolbypassrls`。否则**下一次会把"只 `ENABLE` 没 `FORCE`"的假边界读成真边界**（外部读数完全像"已启 RLS"）。

### 17.4 ④ 的后半：audit_log / cost_ledger 若启 RLS

- **号 = 0006，但我不建议用迁移**：ADR-10 明写 RLS/POLICY **由语义包派生、绝不手写**。这两张是**平台表**（不在 `loaded.active_assets` 里 ⇒ 派生器**结构上遍历不到**）⇒ 正确形态 = 给派生器加一条"平台表"分支（**不占迁移号**）；若架构裁定"平台表走迁移"，那 **0006** 是号，且必须在 ADR-10 里写出**例外**，否则就是"两份真相"。
- ⚠️ **两条陷阱**（已同步补进 `app/obs/audit.py §⑤`）：**(i)** `ENABLE` 必配 `FORCE`（owner = `app_rw`）；**(ii)** **形态决定写路径** —— 派生器出的是 `FOR ALL`（实测 `cmd=ALL`），其 `USING` **兼作 `WITH CHECK`** ⇒ **不是"INSERT 必被拒"**，而是"INSERT 受 `tenant_id = current_setting('app.tenant_id', true)` 约束" ⇒ 一旦某条审计写入路径**没注入 GUC**（`U-109` 的注入面脆弱性），该行被**拒** ⇒ 审计 fail-closed ⇒ **打断全站**。⇒ 启 RLS **前**必须先证明"审计写入路径的 GUC 一定在"。

### 17.5 🔴 副产物：3 张表的 L3 **表达不了店铺维度**（请 W2A / 架构判"设计使然 or 缺"）

`tenant_scoped=true` 的 6 张资产里，**只有 3 张有 `shop_id` 列**：

| 资产 | 有 `shop_id` | 派生出的 `USING` |
|---|---|---|
| `v_order_paid` / `v_product` / `v_shop` | ✅ | `tenant_id = GUC AND (current_setting('app.shop_ids', true) = '' OR shop_id = ANY(...))` |
| `v_campaign` / `v_order_refund` / `v_traffic_daily` | ❌ | **只有** `tenant_id = GUC` |

- ⇒ **对 QA ③(b) 的细化**：`app.shop_ids` 两态（未设 vs `''`）**只对前 3 张可观测**；对后 3 张，**两态必须结果相同**。⚠️ 若 W2A 的 `tests/integration/test_rls_tenant_isolation.py` 对 6 张**统一**断言"两态可见行数不同"，会在后 3 张上红（或**空过**）⇒ 请改**分表**断言：前 3 张断"两态**可区分**"，后 3 张断"两态**相同**"（后者的价值 = 把本节的缺口钉成不变量）。
- ⇒ **并请判这 3 张**：`07 §13.2` 写"行级范围**只有 `shop_ids` 一个维度**"，而 `§13.4` 说 L3 是"**即使前两层都被绕过**"的最后边界；对这 3 张 L3 **表达不了店铺** ⇒ 一个被限店的 `finance`/`operator` 用户，在 `v_order_refund` / `v_traffic_daily` / `v_campaign` 上读到的是**整个租户**的行；且 `v_order_refund.sub_order_id` 可 join 回 `v_order_paid.shop_id` ⇒ **可归因到店**（不是"看不见店名就无所谓"）。**与 `U-131` 同族，但发生在策略面。**
- 该集合已在 §17.2 的断言里**具名登记、只减不增**（将来新增一张同类资产即红）。

### 17.6 门禁读数（本轮改动后）

| 项 | 读数 |
|---|---|
| `ruff check`（我改的 2 个文件） | **All checks passed!** ✅ |
| `ruff format --check`（同上） | **already formatted** ✅ |
| `pytest tests/unit`（全量 unit） | **1398 passed / 1 warning**（34.6s）✅ |
| 新件单跑 | **6 passed** ✅ |
| 正向对照 | 注入 ⇒ **1 failed**（精确命中该断言）⇒ 还原 ⇒ **6 passed** ✅ |

**改动清单**：`tests/unit/test_rls_policy_provenance.py`（新增）、`app/obs/audit.py`（§⑤ 补两条陷阱，**纯 docstring**，`test_audit_writer.py` 仍绿）。


