# CommerceQL

基于 **Text2SQL** 的电商数据分析 Agent：把一句中文业务问题，变成一条**受控**的 SQL，
再变成带口径说明的图表与结论。

> 这不是"让 LLM 写 SQL 然后执行"的 demo。整个设计围绕一个事实展开：
> **LLM 生成的 SQL 是不可信输入**。因此系统里有三道闸门、按租户的行级隔离（RLS）、
> 出站内容白名单、两段式审计（fail-closed），以及一套"先登记决策、再写代码"的契约机制。

---

## 1. 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| **0** | 脚手架 + 契约固化（目录 / 依赖白名单 / 三个单一真相文件 / 契约 CI / 三探针） | ✅ 完成 |
| 1A | 地基（语义包 / 合成数据 / 冻结评测集 / 红队用例集） | ⏳ 未开始 |
| 1B | 骨架（认证 / 审计 / 图装配 / checkpointer / 三池） | ⏳ 未开始 |
| 2–7 | 确定性核心 → LLM 链路 → 编排收口 → 前端 → 评测 → 观测部署 | ⏳ 未开始 |

**阶段 0 的四项完成定义（全部实测通过）：**

| # | 要求 | 结论 | 证据 |
|---|---|---|---|
| ① | `docker compose up` 后 `/healthz/live`=**200**、`/healthz/ready`=**503** | ✅ | 真实容器实测（`ready`=503 是**正确**行为：硬依赖尚未接线） |
| ② | 故意写一个违规 import → CI 必须失败 | ✅ | 双重证据：本地 `scripts/assert_importlinter.py`（3 条契约逐条「注入 → 断言红 → 还原 → 复绿」）**＋ 真实 CI 端到端红**（临时分支注入 `app.guard → app.llm`，CI 的「依赖方向契约」job 失败，失败步骤精确落在「基线 lint」，其余三个 job 保持绿 → 单点归因，无连带误报。探针分支已删除） |
| ③ | 契约断言集必须能跑通 | ✅ | `pytest` **166** 条断言全绿（本地与 CI 双环境）；另有 `python -m app.core.enums` 自检入口 |
| ④ | gitleaks 无命中 | ✅ | 本地 `gitleaks dir .` → `no leaks found`（做过正向对照：注入假密钥会命中）；CI 的「密钥扫描」job 以 `fetch-depth: 0` 扫**全史** |

附加：`ruff check .` 全通过、`mypy app` 无问题（35 个文件）、`lint-imports` **3 contracts kept, 0 broken**。
`main` 分支最近三次 CI 全绿。

> 关于 DoD① 与路径写法：`/healthz/*` 实际挂在版本前缀下，全路径是 **`/api/v1/healthz/live`**、
> `/api/v1/healthz/ready`、`/api/v1/healthz`（PRD §11.7 接口表即为此写法）。
> 编程实施计划的 DoD 行写的是简写 `/healthz/live`，二者不冲突，但**验证时要用全路径**。

---

## 2. 快速开始

```bash
# 1) 准备环境变量（仓库内不放任何真实密钥）
cp deploy/.env.example deploy/.env
#    按需填写 DEEPSEEK_API_KEY 等；DSN / 端口已按 compose 服务名预置

# 2) 起基础设施 + API
docker compose -f deploy/docker-compose.yml up -d --build pg redis api

# 3) 验三探针
curl -i http://127.0.0.1:8000/api/v1/healthz/live     # 期望 200
curl -i http://127.0.0.1:8000/api/v1/healthz/ready    # 阶段 0 期望 503（硬依赖未接）
curl -i http://127.0.0.1:8000/api/v1/healthz          # 期望 503 + degraded_dependencies
```

本机开发（不经容器）：

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/pip install -e ".[dev]"   # Windows
pytest
```

---

## 3. 目录结构

```
backend/
├── app/
│   ├── core/        enums.py ★  contracts.py ★  config.py  errors.py  clock.py
│   ├── cache/       keys.py ★
│   ├── obs/         logging / trace / metrics / audit / schema
│   ├── api/         errors.py（错误码唯一映射）· sse.py（帧唯一编码）· routers/health.py
│   ├── repo/        dsn.py（两套 DSN + 身份注入）
│   ├── main.py      ASGI 组装根
│   └── {semantics,retrieval,binding,planner,guard,exec,mask,llm,graph,auth}/   仅 __init__.py
├── tests/contract/  契约断言（158 条）
├── scripts/         assert_importlinter.py（DoD② 的注入实验）
├── .importlinter    依赖方向契约（R-DEP-1/2/3）
└── pyproject.toml   依赖白名单 + pytest / ruff / mypy 配置
deploy/              docker-compose.yml · Dockerfile · nginx.conf · .env.example
.github/workflows/   ci.yml（契约断言 / import-linter / gitleaks）
.gitignore           密钥/虚拟环境/评测产物 不进仓库（清单外新增，理由见 §5）
.gitattributes       行尾归一化 LF（清单外新增，理由见 §5）
```

**两个清单外新增文件的理由**（都不在上游阶段的交付清单里，但阶段 0 的目标依赖它们）：
`.gitignore` —— 没有它，一次 `git add -A` 就会把 `deploy/.env` 提交上去，DoD④ 与密钥纪律同时失效；
`.gitattributes` —— 开发在 Windows、CI 与容器在 Linux，不做行尾归一化会出现"容器内读到 `\r\n`"
以及"PR diff 整文件全红全绿、真实改动被淹没"两类问题。二者均已在此处显式登记，不属静默增项。

---

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

---

## 5. 已知限制（不隐瞒）

- **阶段 0 的 `/healthz/ready` 恒为 503** —— 四个硬依赖（元数据库 / checkpointer / Redis /
  语义包）的探针实现归后续阶段，这不是缺陷，而是阶段划分的必然状态。
- **决策点 τ（绑定层精排阈值）尚未校准** —— 非 `prod` 环境允许启动，但**必须可见**：
  启动日志会打 WARN，指标 `binding_tau_calibrated` 暴露 0/1。此窗口产出的任何准确率 / 澄清率
  结论**不得**作为评测证据。`APP_ENV=prod` 时该检查为 fail-closed（拒绝启动）。
- **结果缓存（查询级）在 P0 阶段关闭** —— `cache/keys.py` 刻意不提供该键。
- 需要真实外部依赖的 4 条启动断言（分析库只读角色、embedding 维度、审计表权限、
  语义包五步校验）**留给了后续阶段** —— 纯配置层校验不出来，必须连上依赖才能判定。

---

## 6. 文档位置

需求规格（PRD）、附录 A–D、UI/UX 设计、技术设计（TDD）、编程实施计划（阶段划分与窗口归属）
**不随本仓库分发**，它们由独立文档窗口维护。本仓库内的代码注释会引用其章节号
（例如 `07 §11.2`、`附录 A §A.11`），那是契约溯源，不是失效链接。

`README.md` 的上游归属见编程实施计划的文件归属权表 —— 本文件当前只保证"能跑起来 + 约束在哪"，
产品级说明待上游窗口补全。
