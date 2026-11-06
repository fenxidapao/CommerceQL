# AGENTS.md —— 新 Agent / 新手的唯一入口

> 本文件是**导航与禁区**，不是项目文档。读完这一页就够开工；细节按 §3 的预算去读，不要整仓乱翻。
> 项目本体全部在本目录（仓库根），**没有嵌套子目录**。人读版说明见 `README.md`，完整导读见 `OVERVIEW.md`。
>
> **现状态先读 [`docs/09_当前状态与交接.md`](docs/09_当前状态与交接.md)**：HEAD／完成度／实测读数／未完成项／验证命令一页给全。
> 当前阶段：**Phase A 验收已补（静态全绿：ruff 0 / mypy 0 / lint-imports 4/0；简历数字 4/4 复算）；Phase B 进行中**（B1/B2/B3/B4/B5 完成；B6 复杂档 + few-shot + 多轮条件继承 + 多轮 runner 已完成（离线），live 二轮未测；B7 完成：100 题、live EX 70.88% ± 1.61%；B8 可选）。执行计划在仓库外 `Text2SQL/计划_合并版.md`。

---

## 1. 这是什么 / 不是什么

基于 **Text2SQL** 的电商数据分析 Agent：一句中文业务问题 → 一条**受控** SQL → 只读库执行 → 图表 + 带口径说明的结论。

**核心命题**：LLM 生成的 SQL 是**不可信输入**。所有设计由此展开——三道闸门（AST / 政策 / 成本）、按租户的 RLS 行级隔离、出站白名单、两段式审计（fail-closed）、语义层口径版本化。

**不是**："让 LLM 写 SQL 然后执行"的 demo。任何"先跑通再说安全"的改动方向都与本项目前提冲突。

技术栈：FastAPI + LangGraph + PostgreSQL(只读业务库) + Redis + React/Vite/TS；LLM 走 DeepSeek（可切 Ollama），评测用 cassette 回放做到零成本。

---

## 2. 30 秒心智模型

**分层（唯一权威 = `backend/.importlinter`，只能依赖严格更低层）**

| 层 | 包 | 含义 |
|---|---|---|
| L5 | `app.api` | 接入层（路由 / SSE / DTO） |
| L4 | `app.graph` | LangGraph 编排（节点 + 纯函数条件边） |
| L3 | `app.planner` `app.retrieval` `app.present` | 决策层，**可调 LLM** |
| L2 | `app.binding` `app.guard` `app.exec` `app.mask` `app.cache` | 确定性服务层，**结构上禁止 import `app.llm`** |
| L1 | `app.semantics` `app.llm` `app.auth` `app.obs` | 能力层（语义包 / LLM / 鉴权 / 审计观测） |
| L0 | `app.repo` `app.core` | 基础设施（存储 / 取值集 / 配置） |

**主链路（`app/graph/nodes/__init__.py` 是节点名唯一真相）**

```
trusted_context → normalize → intent → link → plan → bind → gen_sql
  → gate1_ast → gate2_policy → gate3_cost → execute → mask
  → audit_pre → present → audit_supp → END
        ↘ repair → 回 gate1_ast
终态出口：clarify_out / refuse_out / error_out（三个独立节点，不是一种节点的三种行为）
```

**定位改动（先查表再 grep）**

| 要改什么 | 去哪个包 |
|---|---|
| HTTP 端点 / SSE / 错误码 | `app/api/`（契约权威 `docs/02`） |
| SQL 能否执行、成本上限 | `app/guard/`（`ast_gate` / `policy_gate` / `cost_gate`） |
| 指标口径、同义词、default_predicates | `semantic/bundle_*.yaml` + `app/semantics/` |
| 表列→指标→粒度绑定 | `app/binding/` |
| 执行、结果归一、行数兜底 | `app/exec/` |
| 图表 / 结论 / 披露文案 | `app/present/` |
| 审计落库与只读查询 | `app/obs/audit.py` + `app/repo/audit_{store,read}.py` |
| 图怎么装、checkpoint 策略 | `app/graph/build.py` |

---

## 3. 阅读预算（硬性：只读这 10 个，约 75KB）

0. `docs/10_未决问题台账.md`（**未决唯一视图：现在到底有几件事没关；只减不增**）
1. `docs/09_当前状态与交接.md`（**现行状态与完成度；先读这一页**）
2. `README.md` §2–§4（快速开始 / 目录 / 五条工程约束）
3. `backend/.importlinter`（8 分钟看懂 16 个包的层次与禁则，性价比最高）
4. `backend/app/main.py`（组装根：lifespan 六步按什么顺序装配）
5. `backend/app/core/enums.py` + `contracts.py`（取值集与端口，全仓引用最多）
6. `backend/app/graph/build.py`（图装配、`GRAPH_VERSION`、条件边挂载）
7. `semantic/bundle_2026.09.14.1.yaml` 的 `meta:` 段（版本真相与刻意解耦说明）
8. `eval/README.md` + `backend/reports/README.md`（评测与证据怎么读）
9. 仓库外 `Text2SQL/计划_合并版.md` §3–§4、§9（Phase A/B 范围与状态清单）

其余一律 **grep 定位后只读 20–40 行**，不要整文件通读。`docs/07`（3,708 行）只在需要契约原文时按 § 检索。

---

## 4. 禁止整读的文件（附替代命令）

| 文件 | 体积 | 为什么不读 | 怎么读 |
|---|---|---|---|
| `backend/reports/qa/TASK_BOARD.md` | 741KB | 只追加的验收流水 | 只读末节：`F=backend/reports/qa/TASK_BOARD.md; N=$(grep -n '^## ' "$F" \| tail -1 \| cut -d: -f1); sed -n "${N},\$p" "$F"` |
| `backend/reports/qa/{RELAY,QA_LEDGER}.md` | 615/322KB | 同上 | 同上换文件名 |
| `backend/reports/w8/RELAY.md` / `DELIVERY.md` | 903/203KB | 窗口交接流水 | 只要对外口径 → `DELIVERY.md` 终版节 |
| `eval/results_*` | 共 9 件 | 历史轮次，已去重 | **只认 `results_w80_*` 一组** |
| `deploy/loadtest/EVIDENCE.md` | 253KB | 压测逐轮流水 | 需要时按轮次 grep |
| `OVERVIEW.md` §6/§7/§9 的历史段 | — | 已切到 `../CommerceQL-archive/reports/OVERVIEW_HISTORY_2026-10-25.md` | 平时不读 |

---

## 5. 五条不可违反的工程约束

1. **三个单一真相文件**：`app/core/enums.py`（取值集/查找表）、`app/core/contracts.py`（跨模块 Protocol 端口）、`app/cache/keys.py`（缓存键）。别处不得再定义第二份；改取值集不同步 `CONTRACT_COUNTS` 会让构建失败。
2. **依赖方向由机器保证**：只用 `lint-imports` 命令本身。⚠️ **禁止** `python -m importlinter.cli lint-imports`——该形态无输出、exit 0、什么都没验的**假绿**（U-41）。
3. **审计 fail-closed**：`audit_log` append-only，代码层只暴露 `insert()`，静态断言禁 `UPDATE/DELETE`。**审计写失败 = 不下发数据**。
4. **新增依赖双录账**：`pyproject.toml` 白名单 + 契约测试两处同改；新增配置项必须同步 `deploy/.env.example`。
5. **冻结集不可动**：`eval/dataset_v1_frozen.json`、`gold_query_seed_v1.json`、`red_team_cases_v1.json`、`eval/olist/dataset_v1_frozen.json`、`eval/olist/dataset_v2_frozen.json` 与门禁阈值/判据措辞，不因调试或"整理"而改。要改先按 §8 取号。

---

## 6. 命令速查

```bash
# 起服务（compose 已按服务名预置 DSN/端口；密钥只在 deploy/.env，不入库）
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up -d --build pg redis api
curl -i http://127.0.0.1:8000/api/v1/healthz/live    # 200
curl -i http://127.0.0.1:8000/api/v1/healthz/ready   # 200（依赖就绪时）
curl -i http://127.0.0.1:8000/api/v1/healthz         # 503 + degraded_dependencies 是设计
#   ⚠️ 必须带 /api/v1 前缀；裸 /healthz/* 是 404

# 本机跑测试（仓库内不含 .venv；venv 在 ../CommerceQL-archive/local/.venv，用 python -m 调用）
cd backend && python -m pytest -q tests/unit tests/contract
# tests/eval 必须让 eval 可导入（Windows 分隔符为 ;）
PYTHONPATH="<repo>;<repo>/eval" python -m pytest -q tests/eval

cd ../frontend && npm run test && npm run typecheck && npm run build

# 静态检查（在 backend/ 下）
ruff check . && mypy app && lint-imports
# lint-imports 的合法 Python 形态（⚠️ 禁用 python -m importlinter.cli lint-imports，见 §5）：
PYTHONUTF8=1 python -c "from importlinter.cli import lint_imports_command; lint_imports_command()"

# 评测（参数以 --help 为权威；离线回放零 LLM 零出站）
python eval/runner.py --help
python eval/reporter.py --help
```

🚫 **不要跑 live 跑批**：`--live` 会真花钱（G-6 压测按 ¥40+ 估），无预算批准一律不跑。

---

## 7. 五个已知陷阱

1. **`app/xxx/engine.py` 与 `app/graph/nodes/xxx.py` 是"引擎 / 节点薄包装"成对结构**（`guard`、`mask`、`planner` 都是），全仓统一模式，**不是重复代码**。合并它们会破坏分层。
2. **`backend/reports/w6/**` 是事实上的测试夹具，不可删**：6 个文件是生产默认路径（`app/present/artifacts.py` 读 `eval_metrics.json`）或测试直接执行的探针；`tests/eval/test_pg_contact_surface.py` 还有 `assert len(scanned) >= 4` 的目录 glob 断言。
3. **semantic 文件名与版本号刻意解耦**：文件叫 `bundle_2026.09.14.1.yaml`，版本真相是 YAML 内 `meta.version`（现 `2026.10.16.2`；Olist v1/v2 分别是 `2026.10.27.1` / `2026.10.31.1`）。二者不等是设计（约 40 处硬编码文件名），不是漂移。
4. **沙箱库不在仓库里**：`data/` 只有生成器。跑 eval 前先 `python data/generator/seed_generator.py`（约 440MB，`.gitignore` 排除）。
5. **禁止读取** `.env`、`deploy/.env`、`deploy/secrets/*.pem`：含真实 API key 与带密码 DSN。需要新增配置 → 改 `deploy/.env.example`。

---

## 8. 改动纪律

- **现状只认一处**：`docs/09_当前状态与交接.md`；`README §1`、`OVERVIEW.md` 的旧快照是历史叙述，引用前现读。
- **取号**：新问题先在 `docs/07 §4.8` 登记 `U-xx` 再动代码；一个号只对应一件事。
- **未决不许消失**：任何未完成项必须在 `docs/10_未决问题台账.md` 有一行。关闭 = 状态改 `CLOSED` + 盘上证据 + 可复算命令；跳过 = `WAIVED` + 复审触发条件，且 `docs/09` 同框写「豁免」。收口必跑 `python tools/open_issues.py --check`（有违规非零退出）。台账**只减不增**，WIP（OPEN/BLOCKED-BY-DATA/EVIDENCE-MISSING）> 12 条时先关后开。
- **证据不改手**：`eval/results_*`、`backend/reports/**` 是证据，要修正读数就新生成一件并记 rev / 时刻 / 命令。
- **两个门禁数必须同框**：官方快照 `PASS 1/8`（`backend/reports/w6/eval_metrics.json`）与当期复算 `6 PASS / 2 UNVERIFIED`（`eval/results_w80_gate_recompute.json`）是两件事——**6/8 ≠ 门禁通过**，G-6 与 G-8 仍是 `UNVERIFIED`。
- **未跑过的写 `UNVERIFIED`**，不得写"门禁通过"；数字必须带源件 + 复算命令 + 日期。
- **提交粒度**：一个逻辑改动一个 commit；`add` 与 `commit` 同条命令，禁 `git add -A`。
