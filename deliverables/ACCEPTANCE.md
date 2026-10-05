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
| 三道闸门 ＋ RLS ＋ 两段式审计 fail-closed 都有实现与反证测试；离线 2,340 ＋ 集成 107 条用例全绿 | ❌"结果算对了"（执行正确率 **EX = 6/124 = 4.8%**） |
| 评测体系可复算：166 题冻结集带 `content_hash` 验真 ＋ LLM 匣带录制回放（零成本重跑） | ❌"跨用户隔离已达成"（`U-131` 同租户内跨属主会话可读可写，**未修**） |
| 语义层是版本化 YAML（8 资产 / 9 指标 / 105 同义词），口径可追溯 | ❌"自动出图"（P0 的图表呈现是空壳，每轮都带一条降级标注，属如实降级） |

被问到"为什么准确率这么低"时的诚实答案：主阻塞不在模型也不在闸门，在**语义包的指标面 ≠ 冻结集的期望**——
124 条 execute 用例里 63 条要的指标（各类 `COUNT` 与未声明的列级聚合）在语义包里根本不存在，
计划层按契约拒答是**正确行为**，是考卷把它们标成了"该答"。这条已作为判据侧缺口上呈，未擅自改考卷或改判据。

## 6. 包身份

两个版本：可邮件的**轻包**（代码＋文档＋截图＋git 历史）与含 421 MB 评测沙箱库的**重包**。
两者的条目数／大小／SHA-256 与打包命令记在 `backend/reports/w8/RELAY.md` §六.21（包无法自含自己的哈希，所以不写在本文件里）。
不含任何真实密钥：`deploy/.env` 与 `deploy/secrets/*.pem` 一律排除，收件人按 §2 自建。
⚠️ 两个包都含 `.git/` 全量历史（388 笔）——那是"项目过程"最硬的证据，但历史里存在早期提交写进报告的 DSN 字面量（`U-134` 同源，仓库侧已被 gitleaks allowlist 放行）；若你希望交付包不带历史，说一声即可重打一份。
