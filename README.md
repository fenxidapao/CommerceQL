# CommerceQL

> **新 Agent / 新接手请先读 [`AGENTS.md`](AGENTS.md)**（导航、阅读预算、禁区、五个陷阱）。本文是工程约束说明。
> **现状态（2026-11-04）→ [`docs/09_当前状态与交接.md`](docs/09_当前状态与交接.md)**：HEAD、完成度、实测读数、未完成项与验证命令一页给全；本文 §1 只是快照。

> **Showcase**：受控 Text2SQL 电商分析 Agent —— 三道闸门 + 租户 RLS + 两段式审计。
> **EX_official = 72.73% ± 1.82%**（Olist 60 题，3 批，n=3，v2 / 百炼 `deepseek-v4.1-flash`）｜ **448,152 行** Olist 五表入库 + RLS 金丝雀｜ **5/5** 生产栈 demo（4 图 + 1 拒答）。
> 历史读数：**41.47% ± 1.33%**（v1 / 官方 `deepseek-flash`，同一 60 题题面、同一判分器；v2 的冻结集与 bundle 按 U-151/U-152 升版，v1 原件未改，**保留可复算**）。
> 图：[bar](backend/reports/w3_demo/demo_1_bar.png) ｜ [KPI](backend/reports/w3_demo/demo_5_kpi.png) ｜ [拒答](backend/reports/w3_demo/demo_4_refuse.png)
> 详情 / 复算附录 → [docs/portfolio/README.md](docs/portfolio/README.md)
> ⚠️ 72.73% 仍未达 85%；`6/8 ≠ 门禁通过`（G-6/G-8 `UNVERIFIED`）。v2 修的是 **3 类非模型缺陷**
> （`AS order` 保留字 / gold `ROUND` 舍入 / `delivery_late_rate` 未 ×100），**剩余 12 条 R14 方言缺口未修**。
> `+31.26pp` 是**净观测差**，不全部归因于修复：端点也换了（百炼 vs 官方），交互 `c01`/`r02` 有退化；
> 可复算的修复面 = 桶内 **51 条次**转等价（逐批 18/16/17），另有 2 条非桶转等价、**2 条回归**、
> 7 条次旧桶案例仍不等价（含 `o38` 的时间基准差）。源：`eval/olist/report_v2.md` §5–§6.1。

基于 **Text2SQL** 的电商数据分析 Agent：把一句中文业务问题，变成一条**受控**的 SQL，
再变成带口径说明的图表与结论。

> 这不是"让 LLM 写 SQL 然后执行"的 demo。整个设计围绕一个事实展开：
> **LLM 生成的 SQL 是不可信输入**。因此系统里有三道闸门、按租户的行级隔离（RLS）、
> 出站内容白名单、两段式审计（fail-closed），以及一套"先登记决策、再写代码"的契约机制。

---

## 1. 当前状态（2026-11-04 快照 · 必然过期）

> **完整完成度与未完成项见 [`docs/09_当前状态与交接.md`](docs/09_当前状态与交接.md)**；本节只是速览。
> 引用前先实跑 `git rev-parse --short HEAD; git rev-list --count HEAD; git status -sb` 并读源件，不要抄本节。

| 项 | 读数 | 源 |
|---|---|---|
| 代码 HEAD | 最后代码提交 `19190dd` / 798 笔（本节文档提交后 799）；`origin/main` 落后 **87 笔（未推送；文档提交后 88）** | `git log -1`；`git rev-list --count HEAD`；`git status -sb` |
| 后端回归 | B2 **133 passed**；B6 few-shot **75 passed**；B6 多轮/图接线 **33 passed**；全量 unit+contract **2506 passed / 3 failed（既有）**；`tests/eval` 505 passed / 2 failed（既有） | 2026-11-04 现跑；命令见 docs/09 §5.3 |
| 前端 | `40 passed`（7 files）；`tsc --noEmit` 与 `npm run build` 通过 | 2026-11-04 复跑（新增导出 7 条） |
| 静态检查 | `ruff 213`（113 可自动修）；`mypy 0 / 179 files`；`lint-imports 4 kept / 0 broken` | 2026-11-04 复跑 |
| Phase B | B1/B2/B3/B4/B5 **完成**（B2 真栈 + 浏览器导出已验）；**B6 复杂档 + few-shot + 多轮条件继承完成（离线），live 二轮未测**；B7 未做；B8 可选 | `docs/09` §4.2；提交见 git log |
| 官方快照 | `88f3500` / **PASS 1/8**（PASS 1 / FAIL 3 / PARTIAL 2 / UNVERIFIED 2），生成 `2026-10-07T05:27:34Z`，最后改动该文件的提交 `24d4477` | `backend/reports/w6/eval_metrics.json`；`backend/reports/w8/OFFICIAL_SNAPSHOT_DECISION.md` |
| 当期复算 | **6 PASS / 0 PARTIAL / 2 UNVERIFIED / 0 FAIL**，复算件 rev `26421ae`（2026-10-24） | `eval/results_w80_gate_recompute.json`；`backend/reports/w8/DELIVERY.md` 终版节 |
| 契约文档 | `07 v1.7.42`（3,708 行）；`08 v1.4.3` | `docs/07_技术设计文档_TDD.md` 头部版本字段 |

**两个门禁数必须同框**：官方快照是入库件、不是当期读数；当期复算是审计复算、不是官方快照。
**6/8 不等于门禁通过**：G-6（P95 延迟）与 G-8（澄清率）仍是 `UNVERIFIED`，属外部输入阻塞（见 §6）。

## 2. 快速开始

```bash
# 1) 准备环境变量（仓库内不放任何真实密钥）
cp deploy/.env.example deploy/.env
#    按需填写 DEEPSEEK_API_KEY 等；DSN / 端口已按 compose 服务名预置

# 2) 起基础设施 + API
docker compose -f deploy/docker-compose.yml up -d --build pg redis api

# 3) 验三探针（必须带 /api/v1 前缀；裸 /healthz/ready 是 404）
curl -i http://127.0.0.1:8000/api/v1/healthz/live     # 期望 200
curl -i http://127.0.0.1:8000/api/v1/healthz/ready    # 当前栈实测 200
curl -i http://127.0.0.1:8000/api/v1/healthz          # 期望 503 + degraded_dependencies
```

本机开发（不经容器）：

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/pip install -e ".[dev]"   # Windows
pytest

cd ../frontend
npm ci && npm run dev        # Vite 开发服务器
npm run test                 # vitest
```

## 3. 目录结构

```
backend/
├── app/            16 个业务包：api auth binding cache core exec graph guard
│                   llm mask obs planner present repo retrieval semantics
├── tests/          6 个目录：unit · contract · eval · integration · redteam · graph_snapshot
├── reports/        当前证据：w6（评测输出）/ w8 / qa → 读 backend/reports/README.md
├── scripts/        探针、门禁与 secrets 扫描脚本
└── pyproject.toml  依赖白名单 + pytest / ruff / mypy 配置
eval/               评测执行器 + 冻结集 + 当期 W77–W80 结果 + 2 个 cassette
                    → 读 eval/README.md
semantic/           语义包 bundle + 口径字典 + 校验器
data/               合成数据生成器 + schema.sql（沙箱库在仓库外 archive）
deploy/             compose · Dockerfile · nginx · 压测驱动 · runbook · 观测面板
frontend/           Vite + React + TS（SSE 流式对话与评测页）
docs/01–08          契约文档集（2026-10-04 起已入库跟踪）
docs/09_当前状态与交接.md  现行状态与完成度（新窗口先读）
.github/            CI：契约断言 / 迁移闸门 / 依赖方向 / lint / secret-scan
```

> 历史窗口报告、旧评测结果与其余匣带、`deliverables/`、`_refs/`、`W1A_HANDOVER.md`、`.w8r59-*.json` 已移至仓库外 `../CommerceQL-archive/`（2026-10-24 整理）；恢复方式见该目录 README。

文件数 / 行数会随提交变化，不要抄树里的数字；需要时现算，例如：

```bash
git ls-files backend/app | grep '\.py$' | wc -l
git ls-files backend/app | grep '\.py$' | xargs wc -l | tail -1
```

## 4. 五条工程约束（改代码前请先读）

**① 三个单一真相文件 —— 任何地方不得再定义第二份取值集。**
`app/core/enums.py`（取值集与查找表）、`app/core/contracts.py`（跨模块 Protocol 端口）、
`app/cache/keys.py`（缓存键唯一构造入口）。三者都有"自检函数 / 契约测试"兜底：
改了取值集却不同步 `CONTRACT_COUNTS`，构建即失败。

**② 依赖方向由机器而非纪律保证。**
`.importlinter` 定义分层 R-DEP-1（只能依赖严格更低层）、R-DEP-2（确定性模块禁 import `app.llm`）、
R-DEP-3（`obs/` 内除 `audit.py` 外禁依赖 `repo`）。跑 `lint-imports` 即知有没有越界。

⚠️ **禁止以 `python -m importlinter.cli lint-imports` 形态调用**（U-41）：
该形态是无输出、exit 0、**什么都没验**的假绿（包的 `cli.py` 无 `__main__` 守卫）。
唯一合法入口是 `lint-imports` 命令本身；CI 已加"输出必须含 `Contracts: N kept`"的
存在性断言，改错调用形态会红而不是静默绿。

**③ 审计写入是 fail-closed 的安全边界。**
`audit_log` append-only，代码层只暴露 `insert()`，并有静态断言禁止 `UPDATE`/`DELETE`。
**审计写入失败 = 不下发数据**，不是"记不下来就算了"。

**④ 新增依赖必须登记。**
`pyproject.toml` 的依赖白名单与契约测试是"双录账"：加依赖要同时改两处，否则测试红。
同理，新增配置项必须同步 `deploy/.env.example`（双向同步断言钉住）。

**⑤ `Retry-After` 是承诺，不是建议。**
只有"原样重发会有不同结果"的错误才允许带它；"必须先改请求"的错误**不得**带倒计时，
而是给可执行的改法（`suggestions[]`）。

## 5. 文档地图

### 5.1 当前真相的读取顺序

1. **`docs/09_当前状态与交接.md`** —— 现行状态、完成度、未完成项与验证命令的唯一入口；
2. **`backend/reports/w8/DELIVERY.md` 终版节** —— 对外最终口径（6 PASS＋2 UNVERIFIED 的逐格说明）；
3. **`backend/reports/w8/OFFICIAL_SNAPSHOT_DECISION.md`** —— 官方快照 `88f3500` 为何不刷新、何时才允许刷新；
4. **`backend/reports/qa/TASK_BOARD.md` 末节** —— 最新一轮验收结论。该件只追加，当期永远在最后一节：

> `OVERVIEW.md` 是 2026-10-03/10-24 的叙事与取证，**不是当期读数**；只查历史取证时读，引用前现跑命令。

```bash
F=backend/reports/qa/TASK_BOARD.md; N=$(grep -n '^## ' "$F" | tail -1 | cut -d: -f1); sed -n "${N},\$p" "$F"
F=backend/reports/qa/RELAY.md;      N=$(grep -n '^## ' "$F" | tail -1 | cut -d: -f1); sed -n "${N},\$p" "$F"
```

### 5.2 契约文档集（权威顺序：02 > 01 > 06 > 07 > 08）

| 文件 | 用途 |
|---|---|
| [01 需求规格说明书 PRD](docs/01_需求规格说明书_PRD.md) | 角色、目标、NFR、功能需求、假设登记 |
| [02 附录 A 接口契约详解](docs/02_附录A_接口契约详解.md) | 全端点契约、SSE、图表 spec、错误码（最高权威） |
| [03 附录 B 语义层与指标口径字典](docs/03_附录B_语义层与指标口径字典.md) | 指标定义与口径 |
| [04 附录 C 评测方案与合成数据集设计](docs/04_附录C_评测方案与合成数据集设计.md) | 冻结集、红队集、判定方法 |
| [05 附录 D 环境依赖与部署清单](docs/05_附录D_环境依赖与部署清单.md) | 部署矩阵与依赖清单 |
| [06 UIUX 设计文档](docs/06_UIUX设计文档.md) | 页面、交互、视觉与可访问性 |
| [07 技术设计文档 TDD](docs/07_技术设计文档_TDD.md) | 架构、判据、问题编号登记（§4.8 唯一权威）、门禁表 §17.3 |
| [08 编程实施计划](docs/08_编程实施计划_阶段划分与窗口归属.md) | 阶段划分、窗口归属、纪律 |

各文档版本以文件头部版本字段为准，本表不抄版本号。
`deliverables/`（含 `ACCEPTANCE.md` 与截图）已移至仓库外 `CommerceQL-archive/deliverables/`；
它不是当期状态，当前状态看 §1 与 OVERVIEW。

## 6. 已知限制（不隐瞒）

- **探针**：`/api/v1/healthz/ready` 当前栈已实测 200；旧文档里"阶段 0 恒 503"是历史读数。
- **决策点 τ 未校准**：L4 决策份额 0/166；G-2 / G-5 / G-7 的 PASS 标 `tau_applicability=not_exercised`
  （条件性非适用，不是校准证据）。`APP_ENV=prod` 时该检查 fail-closed。
- **结果集缓存已落地（2026-11-04）**：`app/cache/redis_cache.py::RedisCache` 是 `CachePort` 首个实现，
  mask 写侧与轮询 `GET /query/{task_id}` 已接线，`data` 不再恒 `null`；B2 导出读同一份已脱敏行。
  这不是 ADR-12 禁掉的"按问题缓存答案"，评测链路仍显式 `result_cache=None`。
- **4 条启动断言**（分析库只读角色、embedding 维度、审计表权限、语义包五步校验）必须连真实依赖才能判定。
- **G-6（P95 ≤ 8s）仍 `UNVERIFIED`**：需要 live LLM 预算（约 ¥40+）、容量决策（U-126：flash 槽位现 8，
  50 并发/8s 按推导需约 38–48）与满档 50 并发 × 10 分钟的全请求分母（429 单列）。
- **G-8（澄清率 ≤ 15% 且澄清后一次成功率 ≥ 80%）仍 `UNVERIFIED`**：缺 17/18 条 expected=clarify 的
  补答来源、U-141 绑定型澄清路径、二轮真跑；当前 `attempted=0`。
- **图表**：W3 已接线 `ChartPresenter`（commit `223ffdc`），生产栈 demo 5 条中 4 条出图
  （bar/bar/bar/kpi），源 `backend/reports/w3_demo/demo_5.json` 与 `browser_acceptance.json`。
  旧文档里"`GraphDeps.presenter` 恒 `None`、每轮降级"是 10-03 的历史读数，不是现状。
  图片导出仍未支持（B2 只做 CSV；见 `docs/09` §4.2）。
- **红队不是全绿**：G-3 的 PASS 只表示"危险 SQL 放行 = 0"（覆盖 50/50），成本闸门 `NOT_CHECKED`；
  另有 21 条非 G-3 红队断言失败已逐条归类，见 `eval/results_w80_redteam_tail.json`。

## 7. 维护约定

- 每轮收口只更新**当期状态块**（同一组位置）：`docs/09`、本文 §1、`OVERVIEW.md` 顶部指针、QA 末节指针；
  历史段落保留并标日期，不删原文、不把历史数当现状。
- 所有数字必须带**源件 + 复算命令 + 快照日期**；官方快照与当期复算永远同框。
- 未跑过的写 `UNVERIFIED`；不得写"门禁通过"（当前官方快照不是全 PASS）。
- 证据与源码分离：过程证据在 `backend/reports/`，评测产物在 `eval/`，两者都有索引；
  源码、冻结集、阈值与判据措辞不因整理文档而改动。
- 仓库不写入真实密钥：`.env`、`deploy/secrets/`、`.workbuddy/` 均被忽略。
