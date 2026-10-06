# CommerceQL · 交付清单与演示指引（ACCEPTANCE）

> 本文件是压缩包的入口页。验收要求 = 每人一份 PPT ＋ 项目相关文件（代码 / 文档 / 脚本）发李老师邮箱 `312947780@qq.com`。
> 生成时刻：**2026-10-04 14:0x +0800**｜代码 HEAD：`60624ff`（`main`，远端同值）｜包内文件数与哈希见本文件末尾"包身份"。

---

## 1. 包里有什么

| 目录 / 文件 | 是什么 | 对应验收项 |
|---|---|---|
| `OVERVIEW.md` | **一份文本读懂本项目**：目标、架构、技术栈、实测进度（§6）、上线门禁 8 条判定（§7）、已知限制（§9）、数字可信度分级（§11） | PPT 的 a 项目背景 / b 开发目的 直接引它 |
| `docs/01–08` | 契约文档集：PRD、附录 A 接口契约、附录 B 语义层与口径字典、附录 C 评测方案、附录 D 部署清单、UIUX、TDD、实施计划 | c 项目过程 / 步骤 / 流程 的**依据** |
| `backend/` `frontend/` `eval/` `deploy/` `data/` `semantic/` | 项目代码 ＋ 评测执行器 ＋ 部署编排 ＋ 数据生成器 ＋ 语义包 | 代码本体 |
| `backend/reports/wN/{PROMPT,DELIVERY,RELAY}.md` | 每个开发窗口的**过程留痕**：任务书、交付物、实测读数、跨窗转交与裁定（20 个目录） | c 项目过程（最硬的一份证据） |
| `backend/reports/w6/评测报告与门禁判定.md` ＋ `eval_metrics.json` | 机器判定的上线门禁报告（G-1…G-8，含每条为什么不算通过） | 答辩时"你说准了多少"的正面回答 |
| `deliverables/screenshots/*.png` | **真实运行效果截图 7 张**（本机 Docker 栈 ＋ 真 DeepSeek ＋ 真 PG，非 mock） | d 项目运行效果截图 |
| `eval/cassettes/w6_batch.jsonl` | LLM 录制-回放匣带（750 条）⇒ 评测可**零成本复算** | 可复现性 |
| `deploy/runbook/README.md` ＋ `RL-1…RL-6` | 六条运维预案 ＋ 演示登录三步（§5.1） | 演示准备 |

## 2. 怎么跑起来（演示前务必提前起，链路要打真模型）

```bash
cd CommerceQL
cp deploy/.env.example deploy/.env        # 填 DEEPSEEK_API_KEY（包里不含任何真实密钥）
docker compose -f deploy/docker-compose.yml up -d --build
# 就绪探针（注意必须带 /api/v1 前缀，裸 /healthz/ready 是 404）
curl -i http://127.0.0.1:8000/api/v1/healthz/ready     # 期望 200
```

演示登录（登录方式 `D-H` 属架构未决项 ⇒ 生产构建没有登录入口，必须用带调试门的前端产物）：

```bash
cd CommerceQL/backend && ../.venv/Scripts/python.exe scripts/mint_dev_token.py --tenant-id T_A --role analyst --ttl 3600
cd CommerceQL/frontend && VITE_ENABLE_DEBUG_PANEL=true npm run build   # 然后 web 容器无需重启（dist 只读挂载）
# 浏览器 http://localhost/login → 粘贴 token → 进入。⚠️ 令牌只在内存，刷新页面就要重贴。
```

⚠️ 两个已知坑：`--tenant-id` 必须是数据里真存在的 `T_A`/`T_B`/`T_C`（签错**不报错**，只表现为"该条件下没有数据"）；
稠密检索依赖宿主 Ollama `:11434`，缺席时检索降级为 `sparse_only`（属设计内降级，不是故障）。

评测复算（零 LLM 成本）：`python eval/runner.py --mode replay --yes` ＋ `python eval/reporter.py`（rc=1 表示"有门禁没过"，不是崩溃）。
若要跑执行正确率比对，需要沙箱库：`python data/generator/seed_generator.py --out data/ecom_sandbox.db`（确定性生成；
含沙箱库的那份大包已直接放了 421 MB 的成品库，可跳过这步）。

## 3. 演示脚本（按顺序，5 分钟内走完三态 ＋ 一条降级）

| # | 问句 | 会看到什么 | 截图 |
|---|---|---|---|
| 1 | `T_A 从 2026-06-01 起的 GMV 是多少？` | 单值表 ＋ 口径条（耗时／成本／语义包版本／任务号） | `01_result_table_with_cost_bar.png` |
| 2 | `各渠道的订单量排名` | 多行表（direct/ad/live/search/feed 五档真实计数） | `02_multirow_table_channel_rank.png` |
| 3 | `帮我分析一下为什么销量下滑` | **澄清卡**（"需要确认一下" ＋ 倒计时）——拒答≠错误，这是设计 | `04_clarify_card_analysis.png` |
| 4 | `看看竞品的销量` | 同为澄清出口（问句缺主体与时间） | `03_clarify_card_countdown.png` |
| 5 | `把所有买家的手机号导出来` | **拒答卡**：受保护字段被闸门拦下（`pii_blocked`） | `05_refuse_card_pii_blocked.png` |

🚫 **演示时口径字典那两页仍必 404；「评测」页要分两支看**（🔻 10-05 14:5x +0800 现测订正，`OVERVIEW.md` §9 同源同改）：
`openapi.json` 现读 **15 条 path**（原写 12 条是 10-04 的取证）。评测页**列表支** `GET /api/v1/admin/eval/runs` **已接线** —— 
对 `platform_admin` 给 200（网格 12 格／门禁 8 条），对 **analyst 给 403 `FORBIDDEN_SCOPE`**（角色门禁 fail-closed）；
评测页**发起支** `POST /api/v1/admin/eval/run` 与口径字典的 `/semantic/metrics`／`/semantic/assets` **仍无路由** ⇒ 点了必 404。
📌 演示默认令牌是什么角色，决定观众看到 200 还是 403 ⇒ 别把 403 讲成"坏了"（那是设计）。缺口登记在 `OVERVIEW.md` §9，两张 404 现状截图仍是 `07/08_page_*_HTTP404.png`（页面渲染层本轮未重跑，记 UNVERIFIED）。
🔻 **10-05 第 14 轮 23:3x +0800 现测订正（`OVERVIEW.md` §9 同源同改；上面那段原句保留作历史取证）**：
`openapi.json` 现读 **19 条 path**（原写 15 条是重建前的活体面，本轮 `docker build` ＋ recreate 后两个面才对上；尺 = `curl -s http://127.0.0.1:8000/api/v1/openapi.json` 数 `paths`）。
新增四条：`GET /semantic/metrics`、`GET /semantic/assets`、`POST /admin/eval/run`、`GET /admin/audit`；迁移数 **5 → 6**（新增 `0006_audit_read_grant.py`，活体 `alembic_version` = `0006`）。
⇒ 演示脚本因此**可以**加两步、也**必须**改掉一句话：
① 「口径字典」两页现在**有数据**（活体 `total = 9` 条指标／`8` 行资产），不再是 404 错误卡 ⇒ 上面那句"仍必 404"作废；截图换成 `backend/reports/w8/screens/a5_semantic_*.png`（旧的 `07/08_page_*_HTTP404.png` 只作历史取证）。
② 「评测」页发起支现在 200，但**它是预检不是发起**：面板标题就写着「预检结果 —— 未发起评测（`run_id` 为空，零出站、零花费）」。
🚫 讲法只许是"这批要打 538～620 条调用、非峰 ¥0.337171～¥0.391504、保守口径 ¥0.901214，**还没打**"；
说成"评测已发起／这是本次花的钱"就是把预检讲成执行（三条缺口 `eval_run_registry`／`in_process_runner`／`approved_spend` 逐条写在响应的 `launch_blockers` 里，可直接指着念）。
③ 审计读 `GET /admin/audit` 有端点**没有页面**（`App.tsx:3` 那条分期未落地仍成立）⇒ 演示只能走 `curl`，别在页面上找它。
⚠️ 另两条讲答辩时要一起带着：审计响应的 `rls.second_guarantee_in_place = false` 是**现查**出来的（第二道保证不在位，是已登记的待裁定项，不是"做好了但没显示"）；
`tenant_id`／`user_id` 不是查询参数（带 `?tenant_id=T_C` 仍只回 `T_A` 的行），这一条可以现场演示。

🔻 **10-06 第 15 轮（T-38）收口订正（`OVERVIEW.md` §6/§7 同源同改；上面几段原句保留作取证）**：
① 🔴 **演示脚本硬红线：不当场点「发起评测」去跑评测**。那一支现在只会给**预检**（`run_id` 恒 `null`、面板自己写着"未发起评测"），点了**不花钱**；但讲成"这就是评测在跑"是假的，而**真发起**要打 **538～620 条调用／¥0.337171～¥0.391504**（保守口径 ¥0.901214）⇒ 那是**另一笔钱、另一轮批准**。可以现场点的只有「口径字典」两页，审计读仍走 `curl`。
② 「评测」页弹窗里那个**「评测集」下拉直到 10-05 才真有数据** —— 之前恒"暂无数据"是前端一处自取消的 `useEffect`（`EvalRunsPage.tsx`：把自己正在 `set` 的 loading 放进了依赖数组 ⇒ cleanup 抢先置 `cancelled` ⇒ `then`/`catch`/`finally` 全跳过，**连 403 都被吞**）。缺陷自 `e01c198`（W5）就在树里、路由接上之后才第一次可见，已修 ＋ 4 臂回归件 `EvalRunsPage.test.tsx` ⇒ 演示前不用手工塞夹具；DOM 尺 = `document.querySelectorAll('.ant-select-item-option').length` 应为 **2**。
③ 🔴 **上面第 62 行那句"本轮 `docker build` ＋ recreate 后两个面才对上"要按现状降调**：第 15 轮**没有重建镜像**。19 条 path 的当期性锚 = 镜像 `sha256:ca34ea791a81…`（`Created = 2026-10-05T15:19:25Z`）＋ 容器 `commerceql-api-1`（`Created = 2026-10-05T15:19:26Z`）＋ **逐件三面 md5 18/18 SAME ＋ 全量 `app/**.py` 158/158 三面聚合相等 ＋ 层 3 `RUN_SCOPED_STATE_FIELDS` present（size = 47）（🔻 **第 18 轮 T-42 B 就地订正**：这句里「三面」二字作废 —— 逐件尺的 git 面当时走了 `.strip()`、从未参与比较（`U-139`，本轮已修）；按两链读 = 链一 容器 ⟷ 工作树字节 ＋ 链二 工作树 ⟷ HEAD。见下面第 18 轮那段）**，复算 = `deploy/loadtest/attest_build_identity.py --container commerceql-api-1 --receipt <回执路径>`。⇒ 当期性**只由 md5／层 3 自证**，"重建过"不作为证据。
④ 上线门禁 **PASS 1/8** 未变（八格 = PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2）⇒ 仍**不得写"门禁通过"**；本轮那把真跑批（`steady c=3 n=30`，准入 **9**、实付 **¥0.066117**／全非峰）**没有改变 `G-6` 判向**（9 < 样本下限 20 ⇒ `g6_p95_le_8s = null`）⇒ 答辩里不许报"端到端 P95 达标"，只可报"样本不足，`G-6` 待一把 ≥20 准入的批"（两条可选形状与其价格见 `OVERVIEW.md` §6 收口段）。

🔻 **10-06 15:2x +0800 第 16 轮（T-39）收口订正（判据措辞一字未改；`OVERVIEW.md` §6 同源同改；上面几段原句保留作取证）**：
① 🔴 **新增一句必须能当场说清的区分：「未认证 ≠ 越权」**。`AST-R10`（连接路径未在口径字典认证）与 `AST-R11`（关联条件可能产生笛卡尔积）的出口文案已从越权句拆成两句独立话术 —— `backend/app/guard/rules.py:102`／`:107` 现读：R10 = **「这个查询的表连接路径系统未认证，请换一种问法」**，R11 = **「这个查询的关联条件可能产生笛卡尔积，请指明用哪个字段关联」**；而 `R05`／`R13` 的越权句「查询涉及的数据范围超出你的权限」与 `R06`／`R07` 的「查询包含受保护字段」**一字未动**（契约件 `backend/tests/contract/test_r10_cte_join_contract.py` 把这两半都钉住了：R10/R11 文案里不许再出现「权限」，同时断言 R05/R13 原句不变）。讲法只许是：**拒绝来自"数据范围"判定（R05 表不在 allowlist／R13 UNION 越范围）时才能说"越权"；R10/R11 说的是这条 JOIN 的走法系统不认，两侧资产常常都在 allowlist 内** —— 把后者讲成权限拦截，就是拿量具形状冒充安全结论。依据：`docs/07 §7.2` AST-R10 行 v1.7.23 定义补句 ＋ `docs/07 §7.6` 分组（`AST-R05 / R10 / R11 / R13` 已由一行拆成三行）。
② 🔴 **演示那句「上个月复购率最高的 10 个店铺是哪些？」落地后仍不出数 ⇒ 别把它放进"会出表"那一栏**。零出站实测（SQL 只读自 `app.audit_log.final_executed_sql`，闸门是纯静态件）：T-38 那批 3 条 `GATE_AST_REJECTED` 来自 **2 个题面**（复购率 1 条／客单价 2 条 —— 🔻 本窗初版把它写成"同一题的三条变体"是错的，已按现读改正并保留订正痕迹），本轮改动**只改判其中 1 条**，而那条**恰好就是演示那句**：R10 → **R06**（`passed` 仍 False，用户文案变成"查询包含受保护字段"）；另 1 条仍 R10（**真该拒**：其资产对不在认证边集内，只是起的文案不再是越权句）；1 条前后同为 R06、与本号无关。**三条没有一条翻成放行**（after tally = `R06|passed=False: 2`／`R10|passed=False: 1`）。⇒ 现场该讲的是"**归因换了一句、出口仍然是拒绝**"，🚫 不许讲成"U-137 落地后这句话能出数了"。复算 = `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t39_u137_before_after.py`（产物 `backend/reports/w8/evidence/t39/u137_before_after.json`）。顺带订正第 15 轮那句过度归因：`RELAY §16.3`／`OVERVIEW` 里"三条 GATE_AST_REJECTED 明确归 U-137 面"⇒ 实测只有 **1/3** 落在 U-137 面。
③ ⚠️ **本轮没有重建镜像**（🚫 不许写"本轮 `docker build` ＋ recreate"）⇒ 上面两句新文案**在活体页面上还看不到**，页面仍是旧越权句。当期性锚仍是第 15 轮那一串：镜像 `sha256:ca34ea791a81…`／`Created = 2026-10-05T15:19:25Z` ＋ 逐件三面 md5 **18/18 SAME** ＋ 全量 `app/**.py` 158/158 三面聚合相等。⇒ 要在演示里说新文案（🔻 **第 18 轮就地订正同上**：「三面」二字作废、按两链读），只许对着 `rules.py` 与契约件说；要让页面也说，得先单独申请一次重建。
④ 对外措辞全部保持现状：门禁 **PASS 1/8**（`backend/reports/w6/eval_metrics.json` 本轮干净树重发：PASS 1／FAIL 3／PARTIAL 2／UNVERIFIED 2）⇒ 不得写"门禁通过"；`G-6` **仍不可引用**（9 < 样本下限 20）；🚫 **不当场点「发起评测」**（预检 ≠ 执行，真发起 = 538～620 条／¥0.337171～¥0.391504，那是另一笔钱另一轮批准）；「评测集」下拉 DOM 尺 `document.querySelectorAll('.ant-select-item-option').length` = **2**；「口径字典」两页有数据（活体 `total = 9` 指标／`8` 行资产）；审计读 `GET /admin/audit` 有端点没页面，只走 `curl`。

🔻 **10-06 18:4x +0800 第 17 轮（T-41）收口订正（判据措辞一字未改；`OVERVIEW.md §6/§7` 同源同改；上面几段原句保留作取证）**：
① 🔴 **那句演示的"真实拦点"现在可以当场指给评委看：不是权限、也不是 JOIN 路径，是 R06 列面**。零出站现读（SQL 只读自 `app.audit_log`，闸门是纯静态件；尺 = `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t41_r06_block_cell.py`，产物 `backend/reports/w8/evidence/t41/r06_block_cell.json`）：`tk_ca342fa6…` 在 HEAD 闸门上 = `passed=False`／`rule_id=R06`／`reason = 查询包含受保护字段`。⇒ 讲法只许是：**第 16 轮把"未认证"与"越权"分开成两句之后，这句才露出真正的卡点（列面／语义包）**；要让它出数得动**语义包／列权限面 = 另一件主单**，🚫 不许说"`U-137` 修完这句就能演示"。⚠️ 指的时候还要补一句：这类按 `rule_id` 的归因来自**离线器件**（生产回执只有 `GATE_AST_REJECTED` 一个码，分不出 R06/R10 —— `U-125`）。
② 🟢 **两个号现在有状态可念**（裁定来自 **QA 第 20 轮**，不是本窗自裁）：`U-129` = **转绿**、`U-137` = **已结案**，落在 `docs/07 §4.8` 那两行的状态格（v1.7.24）。🔴 **但"转绿"的三条限定语必须一起念，缺一就按未证处理**：**(a)** 当期性只认**构建身份**（逐件 md5 ＋ 全量聚合 ＋ 层 3），🚫 不认 `audit_log` 日期窗；**(b)** 转绿**作废三批历史读数** —— W7 侧的 `ok` 率／H（当时引用 `6.18s`）／轮次分布都要**重测后才可引用**，并按规矩「新镜像首格作废 ＋ 跑前预热一格」；**(c)** 镜像 `Created = 2026-10-05T15:19:26Z`、第 15／16 轮**都没重建** ⇒ 🚫 不得说"活体面已带本轮改动"。另外 `U-129` 的结案**不依赖活体臂**（v1.7.13 句 A）⇒ 别把它跟 `G-6` 那笔钱讲成同一件事。
③ ⚠️ **本轮又现测了一次构建身份，给 (a)/(c) 添一句硬话**：今天再跑那把尺 ⇒ 逐件 **SAME 1/3**、全量聚合 **不相等**（第 16 轮改了 `app/guard/**` 两件，镜像里仍是落地前那份）⇒ 上一轮文档里"158/158 三面相等"那句**只能引用为 `4f08698` 之前构建的读数**，🚫 现在起照抄就是假话（转绿本身不受影响，因为它的引用面是第 15 轮那把批当时取到的三面）。
④ 🔴 **对外的两个计数现在必须带面名**：**2,454 = 三目录面**（`tests/unit`＋`tests/contract`＋`tests/eval`）、**2,485 = 五目录面**（再加 `tests/redteam` 11 ＋ `tests/graph_snapshot` 13）⇒ **不许相减、不许再叫"同尺"**（逐目录 `--collect-only -q` 在两棵树上各验过：三目录 2,454→2,461、五目录 2,478→2,485）；另 **G-1 的判定输入是未跟踪的 `.log`**（`.gitignore:47`）⇒ **"把仓库拷过来就能重跑 G-1"不成立**（异地只带入库件时 G-1 读作 `NOT_AVAILABLE`、PASS 0/8）。门禁总数不变 = **PASS 1/8**，🚫 不得写"门禁通过"；第 16 轮那三句红线维持（不当场点「发起评测」／DOM 尺 = **2**／页面上还看不到新文案）。

🔻 **10-06 19:2x +0800（= 11:2xZ）第 18 轮（T-42 B／C）收口订正（判据措辞一字未改；`OVERVIEW.md §6/§7` ＋ `docs/07 §16.5` 层 1 行 ＋ `U-129` 行限定语 (a) 同源同改；上面几段原句保留作取证）**：
① 🔴 **上面第 15／16 轮那两句「逐件三面 md5 18/18 SAME ＋ 全量 `app/**.py` 158/158 三面聚合相等」里的「三面」二字作废**，改成两链并报。🔴 **构建身份对外只写两链**：**链一「容器 ⟷ 工作树字节」**= `attest_build_identity.py` 逐件 `verdict` ＋ 聚合 `two_links.container_vs_worktree`（这把尺**真量到的**那一面）；**链二「工作树 ⟷ HEAD」**= 逐件 `worktree_vs_head_lf` ＋ 聚合 `two_links.worktree_vs_head` ＋ 跑前 `worktree_dirty_at_attest = false`。两链都通才可以说「容器 == HEAD」；🚫 不再写「三面相等／git 面已比过」。 ⚠️ **答辩讲法（不许讲成抓到自己造假）**：第 15 轮那句**不是假结论**（本轮修尺后回算，`ratelimit.py` 三把确实全等、`state.py` 的 git 面确实等于 `0474ef6a…`），**高估的是证据强度** —— 那把逐件尺的 git 面走了 `.strip()` ⇒ 从未参与比较（已立案 `U-139`、本轮修好并补 `--self-test`）。**链二没断、`U-129` 转绿不受影响**（它引用的是第 15 轮当时取到的两链），而限定语 (c)「本轮没重建 ⇒ 页面看不到新文案」现在**更硬**：修后现测 `ast_gate.py` **链二 SAME ／ 链一 DIFF** = 改动在树里、不在构建里。
② 🔴 **本轮修尺的三条结案读数（零额度、只读；产物 `backend/reports/w8/evidence/t42/attest_closure.json`）**：本轮（第 18 轮，HEAD `28c580b`／462 笔，容器 = `commerceql-api-1`）修后现测：① `backend/app/api/ratelimit.py` 三把变体（`worktree_raw`／`worktree_lf`／`head_blob_lf`）**全相等** = `7d2cdc4d387ae9339e6d03792e196a2a` 且与容器面同值；② `backend/app/graph/state.py` 的 `head_blob_lf` = **`0474ef6af7e32345b538456c28735513`**，与 `git show HEAD:… | md5sum` **逐字符同值**（= `docs/07 §16.5` 层 2 表钉住的那串真值）；③ `backend/app/guard/ast_gate.py` 报**无命中**（容器 `cf698983…` ⟂ 工作树 `f0c9e616…`（LF 归一 `a9443bff…`）⟷ HEAD `a9443bff…` ⇒ 链二 SAME ／ 链一 DIFF）；聚合 158 件对 158 件、**链一 False ／ 链二 True**；`--self-test` **3/3 PASS**（零 docker、零出站）。产物 `backend/reports/w8/evidence/t42/attest_{pre,post}_fix_probe.json` ＋ `attest_closure.json`。 复算入口 = `PYTHONUTF8=1 .venv/Scripts/python.exe deploy/loadtest/attest_build_identity.py --self-test`（3/3 PASS）＋ `… --receipt <仓库外副本> --container commerceql-api-1 --files backend/app/api/ratelimit.py,backend/app/graph/state.py,backend/app/guard/ast_gate.py`。
③ ⚠️ **给演示加一条前置检查**：被测容器 `w7load-api` 本轮开工前已不在场（镜像 `w7load-api:latest` digest `4adbcfc2e8f6` 仍在）⇒ 本轮容器面取自共享栈 `commerceql-api-1`，而 `docs/07 §16.5` **禁令 ②** 说共享栈**不是被测构建** ⇒ 演示与下一把批都要先点名「哪一面」，🚫 不许把共享栈的读数写成被测构建的；顺带订正旧标签：那句「镜像 `Created = 2026-10-05T15:19:26Z`」量的是**容器**创建时间，镜像 `Created` = `2026-10-05T15:19:25Z`。门禁措辞不变 = **PASS 1/8**，第 16／17 轮那三句红线（不当场点「发起评测」／新文案在活体页面看不到／`G-6` 样本不足）全部维持。

## 4. PPT 素材映射（a–e）

- **a 项目背景**：`OVERVIEW.md` §1（三十秒电梯版）＋ §2 主张 1（同一批模型 Spider 1.0 86.6% vs Spider 2.0 10.1%）。
- **b 开发目的**：`OVERVIEW.md` §1（替代"提需求给数据团队排期"）＋ `docs/01` PRD §3.1 的 7 类角色。
- **c 项目过程 / 步骤 / 流程**：`docs/08` 的阶段划分与窗口归属 ＋ `backend/reports/wN/` 的逐窗留痕 ＋ git 提交历史（388 笔）。
- **d 运行效果截图**：本包 `deliverables/screenshots/` 7 张（真机真模型，非设计稿）。
- **e 项目心得**：**必须本人写**——AI 可以整理事实，但心得是你的判断与感受，且验收通知里明写"PPT 的 AI 痕迹请自行去除"。
  可引用的真实素材（供你自己组织语言）：`OVERVIEW.md` §7 那段"最诚实的部分"、`backend/reports/w8/RELAY.md` §六.16
  （一条"口径条 ¥0.003288 vs 落库面 ¥0.004670"的对撞怎么揪出计量缺陷）、§六.11 的三条自曝。

## 5. 答辩前必须知道的真实状态（别把话说满）

| 可以正面说 | 不可以说 |
|---|---|
| 端到端链路真跑通：中文问句 → 受控 SQL → 只读库执行 → 表格 ＋ 带口径说明的结论，三档出口（澄清／拒答／错误）在 UI 上可区分 | ❌"门禁通过"（**8 条只过 1 条**，只有 G-1 全量测试绿） |
| 三道闸门 ＋ RLS ＋ 两段式审计 fail-closed 都有实现与反证测试；离线 2,340 ＋ 集成 107 条用例全绿（🔻 10-06 第 16 轮现读 = **离线 2,485 ＋ 集成 124**，两把 rc 0，取证件自报 `f7bf106`／干净树 ⇒ 左边那对是 10-04 的历史读数，别当现状念；尺见 `OVERVIEW.md` §7 第 16 轮指针段。🔻 **第 17 轮点清"面"**：**2,485 是五目录面**（`tests/unit`＋`contract`＋`eval`＋`redteam` 11＋`graph_snapshot` 13），而**第 15 轮登记的 2,454 是三目录面**（前三者）⇒ **两个数不可相减、不许叫"同尺"**；逐目录 `--collect-only -q` 两棵树实测 = 三目录 2,454→2,461、五目录 2,478→2,485） | ❌"结果算对了"（执行正确率 **EX = 6/124 = 4.8%**） |
| 🔴 **`U-129` 与 `U-137` 已由 QA 第 20 轮裁定**（10-06，v1.7.24 落在 `docs/07 §4.8` 两行状态格）：前者**转绿** = 结案引用四件当期位置齐（三格并报／直读式 = 0／`ok` 率与三把窗的 H／零额度夹具），后者**已结案** = 夹具五条 ＋ 红队三臂不退步 ＋ 文案与抄本三处同轮改 | ❌把这两句说成"门禁通过"（**总数仍 PASS 1/8**）或"那道演示题修好了"（`U-137` 结案**不覆盖**这句：现读拦点 = **R06 受保护字段**，属列面）。⚠️ 念"转绿"必须同框三条限定语：**(a)** 当期性只认构建身份不认日期窗、**(b)** **转绿作废三批历史读数**（W7 的 `ok` 率／H（曾引 `6.18s`）／轮次分布 ⇒ 须重测）、**(c)** 镜像未重建 ⇒ 别说"活体已带本轮改动"；且 `U-129` 结案**不依赖活体臂**，与 `G-6` 那笔钱是两件事 |
| 评测体系可复算：166 题冻结集带 `content_hash` 验真 ＋ LLM 匣带录制回放（零成本重跑） | ❌"跨用户隔离已达成"（`U-131` 同租户内跨属主会话可读可写，**未修**） |
| 语义层是版本化 YAML（8 资产 / 9 指标 / 105 同义词），口径可追溯 | ❌"自动出图"（P0 的图表呈现是空壳，每轮都带一条降级标注，属如实降级） |
| 🔻 10-06 第 16 轮起：闸门把两类拒绝的**话术分开了** —— `AST-R05/R13` 讲"数据范围超出你的权限"（越权类），`AST-R10` 讲"表连接路径系统未认证"、`AST-R11` 讲"关联条件可能产生笛卡尔积"（未认证类，两侧资产常常都在 allowlist 内）；文案在 `backend/app/guard/rules.py:102`／`:107`，契约件钉住"R10/R11 里不许出现「权限」"（`backend/tests/contract/test_r10_cte_join_contract.py`） | ❌把"未认证的 JOIN 路径"讲成"被权限拦下了"（`U-137` 修的正是这个混淆；🔴 **未认证 ≠ 越权**）。⚠️ 新文案**在活体页面上还看不到**（本轮未重建镜像，§3 第 16 轮 ③） |

被问到"为什么准确率这么低"时的诚实答案：主阻塞不在模型也不在闸门，在**语义包的指标面 ≠ 冻结集的期望**——
124 条 execute 用例里 63 条要的指标（各类 `COUNT` 与未声明的列级聚合）在语义包里根本不存在，
计划层按契约拒答是**正确行为**，是考卷把它们标成了"该答"。这条已作为判据侧缺口上呈，未擅自改考卷或改判据。

## 6. 包身份

两个版本：可邮件的**轻包**（代码＋文档＋截图＋git 历史）与含 421 MB 评测沙箱库的**重包**。
两者的条目数／大小／SHA-256 与打包命令记在 `backend/reports/w8/RELAY.md` §六.21（包无法自含自己的哈希，所以不写在本文件里）。
不含任何真实密钥：`deploy/.env` 与 `deploy/secrets/*.pem` 一律排除，收件人按 §2 自建。
⚠️ 两个包都含 `.git/` 全量历史（388 笔）——那是"项目过程"最硬的证据，但历史里存在早期提交写进报告的 DSN 字面量（`U-134` 同源，仓库侧已被 gitleaks allowlist 放行）；若你希望交付包不带历史，说一声即可重打一份。
