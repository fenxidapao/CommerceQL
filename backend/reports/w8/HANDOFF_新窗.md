# HANDOFF 新窗 —— W8（开发窗）｜ 上一任「W8 收口 P0-A」交棒 ｜ 2026-10-16

> 🔴 **本件是交接快照，不是规程**。常驻规程仍以 [PROMPT.md](backend/reports/w8/PROMPT.md) 为准；
> 当期派单以 `backend/reports/qa/TASK_BOARD.md` **最新末节**（现读 = `## 67 · 项目收口主线`／`### 67.2` 粘贴块，行 `:4067`／`:4103`）为准。
> 一切易变读数**以新窗开工现读为准**，不得照抄本件。

---

## §0 🔴 粘贴给新窗的提示词（**总控复制这一段即可**）

```text
你是 CommerceQL 项目的【W8 开发窗】（唯一开发窗 ＋ 判据/取号裁定权）。不继承任何旧对话，一切事实以盘上现读为准。

第 0 步：先读 backend/reports/w8/HANDOFF_新窗.md（＝交接快照＋待办，先读 §1/§2/§3），
        再读 backend/reports/w8/PROMPT.md（§0′/§1/§2/§3/§5 是常驻规程：写面、禁令、开工必读、交付模板）。

第 1 步：现读开工 —— git fetch ＋ git status --porcelain ＋ git rev-parse --short HEAD。
        🔴 工作树里那批 P0-A 未提交改动是上一任留下的（见 HANDOFF §1/§6），**别 add -A、别顺手整理**；
        先按名 stage → 一笔 commit → push → 复核 local==remote，把基线坐实再动手。

第 2 步：读 QA 派单 —— backend/reports/qa/TASK_BOARD.md 最新末节（现读 = §67 项目收口主线，
        `67.2 给 W8 的项目收口主块` 可整段复制）＋ backend/reports/qa/PROMPT_新窗.md §14。

第 3 步：先跑离线全量确认基线绿 —— 必须用**仓库 venv**：
        .\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests --ignore=backend/tests/integration -q
        （应 = 2524 passed / 0 failed；用 PATH 上的 anaconda python 会因缺 redis 出 72 collect ERROR）。

第 4 步：接续 P0-A 的两处 UNVERIFIED（HANDOFF §2/§3）——
        ① U-131 活体三面：跨属主读 GET /session/{id} → 404；跨属主写 POST /query/clarify 不得进属主会话；推理侧不得读他人上下文；
        ② U-129 属主同会话第 2 轮 API 端到端（不得崩、不得复用第 1 轮终态）。
        用**一次性** PG/Redis，跑完 DROP ＋ 现查 ecom% 残渣；脚手架见 HANDOFF §3.2（已迁出仓库）。

硬规矩（血泪，逐条照做）：
 · 凭据只从 deploy/.env 读，**不打印、不入库**；新增入库文件先做凭据字面量包含检查；
 · 集成测试**只打一次性库**（禁共享 ecom）；跑完 DROP＋查残渣（尺 = datname like 'ecom%'）；
 · git：禁 add -A / add . / reset --hard / clean；**按名 stage**，提交后 git show --stat 复核再推；
 · 不写 reports/qa/**、不改冻结集/阈值、不改判据措辞、零取号（现读 U-143）；
 · 每项交付给 文件:行号 ＋ before/after ＋ 命令 ＋ 原始输出 ＋ 时点 ＋ HEAD；**未跑一律写 UNVERIFIED，不得写"应该可以"**；
 · 复算入口三纪律：带时点(轮次/HEAD) ＋ 附实跑输出并点名口径 ＋ 禁自指。

回执 ≤250 字（模板见 PROMPT.md §5）。
```

---

## §1 现读快照（2026-10-16，本件落笔时）

| # | 查项 | 现读 |
|---|---|---|
| 1 | 仓库 | 分支 `main`｜HEAD **`311e9e5`**｜`git rev-list --count HEAD` = **566** 笔 |
| 2 | 工作树 | **dirty**（P0-A 一轮改动**未提交**，见 §6）；`?? .workbuddy/` |
| 3 | 台账 | `app.cost_ledger` **逐位不动** = `1830\|3.025849\|2026-10-07 04:28:00.872275+00`（harness 不落库 ⇒ 本项目账面 ≠ 实际花费，两把尺都要报） |
| 4 | 取号 | `grep -n "^> \*\*下一个可用号" docs/07_*.md` ⇒ **`U-143`**（`docs/07_技术设计文档_TDD.md:1094`）；本轮**零取号** |
| 5 | 门禁 | `backend/reports/w6/eval_metrics.json` 仍 `rev 88f3500 / dirty false` = **PASS 1/8**（对外任何场合不得写"门禁通过"） |
| 6 | 容器 | 上一任的一次性 PG/Redis 子代理**被中止**，未确认已清；**新窗开工先 `docker ps -a` 自查残渣** |

**上一任在主线上做的事**：W8 收口 **P0-A**（核心正确性与安全）＝ QA `TASK_BOARD §67` 的第一阶段。
本件落笔时：**P0-A-1 与 P0-A-4 已完成并出读数**；**P0-A-3 载体+接线已完成、API 端到端未跑**；**P0-A-2（U-131 三面）未验证**。

---

## §2 P0-A 四项逐条状态（done｜UNVERIFIED｜file:line）

| 项 | 状态 | 证据 / 缺什么 |
|---|---|---|
| **P0-A-4** 失败可观测性：`llm_error_update` 保留 `exc.detail` | ✅ **done** | `backend/app/graph/nodes/_shared.py:195-220`；新增单测 `test_llm_error_detail.py`（**6 passed**）；真图活体探针 `%TEMP%\w8r47\p4_live.py` 实跑 = `terminal_error_detail={"model","kind","task"}`（零出站）。读数见 `RELAY.md §46.1` |
| **P0-A-1** `normalize` 残留租户自指：**确定性**剥离 | ✅ **done** | `backend/app/planner/payloads.py:145-188`（`strip_tenant_self_reference`）＋ `backend/app/graph/nodes/normalize.py:120-131`（收口）；单测 `test_tenant_self_reference_strip.py`（**18 passed**）。**after 活体**：G-2 前 5 条 **5/5 complete**（`E-VER-04` 由 refuse→success）；**57 条自指误拒族**：`refuse→complete 41 / →refuse 12 / →clarify 4`、`n_unscored=0`。读数见 `RELAY.md §46.2／§46.5` |
| **P0-A-3** U-129＋U-142 多轮闭环 | ⚠️ **部分 / UNVERIFIED** | **已完成**：组 1 新增 `history_questions`（`state.py:283-289`／`:126-129`／`:218-221`／`initial_state:512-515`）＋ `runner.py:_read_session_history`（读 `store.get_turns`、只取 question、反序、读失败不抛＋告警）＋ `normalize.py:73-84` 传 history；单测 `test_session_history_carrier.py`（**7 passed**）；零成本真图接线证明（载荷含历史，`RELAY.md §46.3②`）。**未闭**：① 属主同会话**第 2 轮 API 端到端** = **UNVERIFIED**（子代理被中止）；② `gen_sql` **拿不到**历史文本（两资产**无 `$history_block`** 占位符，被 `test_llm_prompts.py:295-320` 钉住）⇒ 历史对 gen_sql 是**间接**影响，**有意未改资产** |
| **P0-A-2** U-131 活体三面（同租户非属主） | 🔴 **UNVERIFIED（未跑）** | 三面**均无任何读数**：① 非属主 `GET /session/{id}`→`404 SESSION_NOT_FOUND`；② 非属主 clarify 写入不得进属主会话；③ 推理侧不得读他人上下文。执行该任务的子代理**被中止（killed）**。脚手架已落并**迁出仓库**（见 §3.2）。契约面已有测试（QA §67.3 = 14 passed），但**不得**把契约测试当活体验收 |

**另**：`_shared.py` 的 `llm_error_update` 只搬 `detail`（无 PII），不搬 message／原始报文。`state.py` 组 1 自 11→**12** 个字段（`trusted_context.py:59-63` 注释已同步）。

---

## §3 待办（按优先级；新窗接续）

### 3.1 收口与提交（**第一件事**）
1. **提交本轮 P0-A**（工作树当前脏）：按名 stage 下列文件 → 一笔 commit → push → `git show --stat` 复核 → 验 `local==remote`。
   - `git add` 名单（**按名，禁 -A**）：`backend/app/api/runner.py`、`backend/app/graph/nodes/_shared.py`、`backend/app/graph/nodes/normalize.py`、`backend/app/graph/nodes/trusted_context.py`、`backend/app/graph/state.py`、`backend/app/planner/payloads.py`、`eval/harness.py`、`eval/runner.py`、`backend/reports/w8/RELAY.md`（本件 `HANDOFF_新窗.md` 由新窗自行决定）
   - 新文件：`backend/tests/unit/test_llm_error_detail.py`、`test_session_history_carrier.py`、`test_tenant_self_reference_strip.py`、`eval/results_a1fix5_r47.json`、`eval/cassettes/w8_r47_a1fix5.jsonl`（57 条批产物 `eval/results_a1fix57_r47.json`＋`eval/cassettes/w8_r47_a1fix57.jsonl` **是否入笔由新窗裁** —— 它们是 P0-A-1 的 57 条 after 证据）
   - ⚠️ 提交前跑机械护栏：`pytest backend/tests/unit/test_migration_dsn_hygiene.py` ＋ `python -X utf8 backend/scripts/scan_secrets.py --working-tree`（本件落笔时 = **0 命中**）
2. **P0-A-2（U-131 活体三面）** —— 见 §2，**未验证**。
3. **P0-A-3 属主二轮 API 端到端**（U-129 第 2 轮不崩＋终态不复用）—— **未验证**。

### 3.2 P0-A-2 复现入口（脚手架已迁出仓库）
- `%TEMP%\w8r47\_w8ot_env.py`：一次性 env 装载（`deploy/.env` 只读不回显）＋ `kuaipao.pro` 进程内 DNS shim（宿主 DNS 超时、IP 可达）＋ 一次性 DSN `PG 127.0.0.1:55433`／`REDIS :56380`。
- `%TEMP%\w8r47\_w8ot_probe.py`：起服务 ＋ 一次真查询自证（`TestClient(app)`）。
- 🔴 **卡点**：**三面断言脚本尚未写**（现有 probe 只覆盖"服务起＋一次真查询跑完"）。
- 🔴 **为什么迁出**：它们原本在 `backend/tests/integration/` 里读 `deploy/.env`，触发守卫 `test_no_env_file_dsn_derivation.py`（集成模块**不得读 `.env`**）⇒ 离线全量曾 **2 failed**；迁出后**复绿**。
- ✅ **更稳的路子**：改用既有 `backend/tests/integration/_env_dsn.py`（U-114 一次性库 DSN 防线）取 DSN，避免再触守卫。
- ⚠️ 集成套件还需 `COMMERCEQL_TEST_SUPER_DSN`／`COMMERCEQL_TEST_RW_DSN` 环境变量（QA §67.3），**不得**把共享 `ecom` 当测试库。

### 3.3 交叉依赖与后续阶段（**不属 P0-A，勿混号**）
- `backend/tests/integration/test_semantic_materialization.py` **两处字面量**逾期（` :115`／`:319` 断言 `2026.09.14.1`，现读语义包版本更高）⇒ 集成套件 **122 passed / 2 red**（QA §67.8）；须同步版本字面量后重跑至 **124 passed**。
- **F-1…F-5**（46 条非 metric 面）＋ 已落 13 metric 的联合修复 ⇒ 独立一轮（QA §67.6：τ **顺延**，不得当 G-2/G-5 前置借口）。
- **对外件刷新**（`OVERVIEW.md §6/§7/§9`）＋ **CI 本地绿／全历史红差异**措辞 ⇒ **专门一轮**（禁夹带、防行位漂移）。
- `budget.py` 价表**未补**：新模型名不在价表 ⇒ 计价一律标 `price_guess`（按 pro 档兜底），**`tokens` 是主报量**。

---

## §4 本机环境坑（本轮新增 / 重申）

- 🔴 **必须用仓库 venv**：`.\.venv\Scripts\python.exe`。PATH 上的 `python` 落到 `D:\anacoda3` **缺 `redis`** ⇒ 全量会出 **72 个 collect ERROR**（`app/api/errors.py:21` import redis 失败），**不是代码红**。
- 🔴 **启用了新上游**：`kuaipao.pro/v1`，fast／strong = `deepseek-v4.1-flash`；宿主 DNS 解析该域名**超时但 IP 可达** ⇒ 需进程内 DNS shim（见 §3.2 `_w8ot_env.py`）。任何出站/花费必须实报（模型＋tokens＋应用计价＋时段）。
- 🔴 **匣带纪律**：`eval/cassette.py` key = `sha256(path + canonical_json(body))`；**miss 时抛 `CassetteMiss`（不降级、不回真实网络）**，评测侧记 `unscored(基础设施)`、不计模型失败率。**改 prompt 文本 ⇒ 指纹变 ⇒ 必须重录**（本轮 P0-A-1 改归一化即触发 `plan` 那一跳 cassette_miss，如实记为基础设施）。
- 🔴 **行尾**：`RELAY.md`／`DELIVERY.md`／`PROMPT.md`（及本件 `HANDOFF_新窗.md`）= **LF**；`docs/07`、`semantic/bundle_*.yaml` = 工作树 **CRLF**（改它们要字节级读写并显式保 CRLF）。
- 🔴 **P0-A-2 守卫**：`backend/tests/integration/**` 里**不得**读 `deploy/.env`（`test_no_env_file_dsn_derivation.py`）。
- 🔴 其余七条环境坑（`PYTHONUTF8` 双设／`-p no:randomly`／`TZ` 在 Git-Bash 返回 UTC／cwd≠`backend/`⇒`asyncio_mode` 失效／集成日志必须 `-v`／Docker Desktop 内嵌 DNS 会抖／演示登录三件）见 PROMPT.md §3 与项目记忆《CommerceQL 本机环境坑》。

---

## §5 复算入口（带时点，禁自指）

- 离线全量（基线绿）：`.\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests --ignore=backend/tests/integration -q` ⇒ 本件落笔 **2524 passed / 0 failed**（第 45 轮 2493 ⇒ ＋31 新单测 = 6＋18＋7）；HEAD `311e9e5`。
- 扫描（机械护栏）：`python -X utf8 backend/scripts/scan_secrets.py --working-tree` ⇒ **0 命中 / 691 件**（⚠️ CI 下界，不含 gitleaks 默认集与全历史）。
- 57 条批读数：`python %TEMP%\w8r47\dump57.py`（读 `eval/results_a1fix57_r47.json`）⇒ `refuse→complete 41 / →refuse 12 / →clarify 4`；`tokens 1,340,546`／应用计价 `4.810022`（`price_guess`）。
- 5 条批读数：`eval/results_a1fix5_r47.json` ⇒ `5/5 complete`／`tokens 135,371`／应用计价 `0.738990`（`price_guess`）。
- 取号现读：`grep -n "^> \*\*下一个可用号" docs/07_*.md` ⇒ `U-143`（`docs/07_技术设计文档_TDD.md:1094`）。

---

## §6 本轮（收口 P0-A）改动文件清单（= 待提交面）

**已改（`git status` = `M`）**：`backend/app/api/runner.py`｜`backend/app/graph/nodes/_shared.py`｜`backend/app/graph/nodes/normalize.py`｜`backend/app/graph/nodes/trusted_context.py`｜`backend/app/graph/state.py`｜`backend/app/planner/payloads.py`｜`eval/harness.py`｜`eval/runner.py`｜`backend/reports/w8/RELAY.md`（新增 `§四六`，`:4550` 起）
**新增（`??`，待入笔）**：`backend/tests/unit/test_llm_error_detail.py`｜`backend/tests/unit/test_session_history_carrier.py`｜`backend/tests/unit/test_tenant_self_reference_strip.py`｜`eval/results_a1fix5_r47.json`｜`eval/results_a1fix57_r47.json`｜`eval/cassettes/w8_r47_a1fix5.jsonl`｜`eval/cassettes/w8_r47_a1fix57.jsonl`｜本件 `backend/reports/w8/HANDOFF_新窗.md`
**未入库的临时件（在 `%TEMP%\w8r47\`，不入库）**：`_w8ot_env.py`／`_w8ot_probe.py`（P0-A-2 脚手架）／`p4_live.py`／`p3_wiring.py`／`dump57.py` 等

⚠️ `?? .workbuddy/` **不是本轮产物**，不 add、不整理。
</content>
