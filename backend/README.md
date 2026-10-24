# backend —— 代码主目录（入口说明）

> 本文件只解决一个问题：**171 个 `app/` 文件 + 166 个测试 + 204 个 `reports/` 文件，从哪读起、什么别读。**
> 项目级定位、命令速查、改动纪律见仓库根 [`AGENTS.md`](../AGENTS.md)。

---

## 1. 分层（唯一权威 = `.importlinter`，只能依赖严格更低层）

| 层 | 包 | 含义 |
|---|---|---|
| L5 | `app.api` | 接入层（routers / dto / sse / errors） |
| L4 | `app.graph` | LangGraph 编排（`build.py` 装配、`nodes/` 节点、`edges.py` 纯函数路由、`state.py`） |
| L3 | `app.planner` `app.retrieval` `app.present` | 决策层，**可调 LLM** |
| L2 | `app.binding` `app.guard` `app.exec` `app.mask` `app.cache` | 确定性服务层，**结构上禁止 import `app.llm`** |
| L1 | `app.semantics` `app.llm` `app.auth` `app.obs` | 能力层（语义包 / LLM 网关 / 鉴权 / 审计观测） |
| L0 | `app.repo` `app.core` | 基础设施（存储与迁移 / 取值集·配置·端口） |

两条正交契约：**R-DEP-1** 只能依赖严格更低层；**R-DEP-2** L2 及以下 + `binding` 禁 import `app.llm`（`R-DEP-3` 限 `obs/` 内除 `audit.py` 外禁依赖 `repo`）。
跑 `lint-imports` 验证；⚠️ **禁止** `python -m importlinter.cli lint-imports`（无输出、exit 0 的假绿，U-41）。

## 2. 主链路（17 个具名节点 ＋ 3 个终态出口）

```
trusted_context → normalize → intent → link → plan → bind → gen_sql
  → gate1_ast → gate2_policy → gate3_cost → execute → mask
  → audit_pre → present → audit_supp → END
        ↘ repair → 回 gate1_ast
终态出口：clarify_out / refuse_out / error_out
```

`app/graph/nodes/__init__.py` 是**节点名的唯一来源**（图注册 / 条件边返回值 / 事件映射 / 契约测试四处都 import 它的常量）。

## 3. 建议阅读顺序（12 步）

| # | 文件 | 为什么 |
|---|---|---|
| 1 | `.importlinter` | 最便宜：8 分钟看懂 16 个包的层次与禁则 |
| 2 | `pyproject.toml` | 依赖白名单 + pytest markers（`contract`/`redteam`/`integration`）+ ruff/mypy |
| 3 | `app/main.py` | 组装根；lifespan 装配顺序；"不在 import 期做 I/O"的原因 |
| 4 | `app/core/enums.py` | 取值集与查找表（全仓引用最多） |
| 5 | `app/core/contracts.py` | 跨模块 Protocol 端口（同层调用必须走它） |
| 6 | `app/core/config.py` | `Settings`：运行时要哪些 env |
| 7 | `app/api/deps.py` | `AppRuntime` / `GraphRuntime`：进程级对象在这里拼起来 |
| 8 | `app/graph/build.py` | 图装配、`GRAPH_VERSION`、checkpoint 策略、条件边挂载 |
| 9 | `app/graph/nodes/__init__.py` | 节点名唯一真相 + 与 `docs/07 §5.3` 的对账表 |
| 10 | `app/graph/edges.py` | 路由全是**纯函数**，可直接单测 |
| 11 | `app/graph/state.py` | `GraphState` 字段，串起全链路数据流 |
| 12 | `tests/contract/test_edges_contract.py` ＋ `test_api_endpoints_contract.py` | 把测试当可执行规格读 |

按需深入：`semantics/{loader,models,runtime,materialize}.py` → `llm/{client,router,budget,egress_guard}.py` + `llm/prompts/*_v1.txt` → `guard/{ast_gate,policy_gate,cost_gate}.py` → `exec/{executor,normalize,fingerprint}.py` → `repo/{pools,migrations}`。

## 4. 别整读的东西

| 目录 / 文件 | 为什么不读 |
|---|---|
| `reports/**`（除 `reports/README.md`） | 判据历史与窗口叙事，与系统行为无关。`reports/qa/` 下三份各 300–740KB，只读末节：`F=backend/reports/qa/TASK_BOARD.md; N=$(grep -n '^## ' "$F" \| tail -1 \| cut -d: -f1); sed -n "${N},\$p" "$F"` |
| `tests/eval/**` 的取证断言 | 判据历史（数字怎么测出来的），不是系统行为 |
| `reports/w6/*.log` | pytest 输出转储；只有 `_full_pytest_w6.log` / `_integration_pytest.log` 是 G-1 的输入 |

## 5. 两个反直觉的事实（不知道会误判）

1. **`app/xxx/engine.py` 与 `app/graph/nodes/xxx.py` 是"引擎 / 节点薄包装"成对结构**（`guard`、`mask`、`planner` 都是）。这是全仓统一模式，**不是重复代码**；合并会破坏分层。
2. **`reports/w6/**` 是事实上的测试夹具**：`eval_metrics.json` 是 `app/present/artifacts.py` 的生产默认路径；`probe_audit_invariant.{py,json}`、`probe_pg_boundary.py`、`redteam_results.json` 被测试直接加载/执行；`tests/eval/test_pg_contact_surface.py` 还有 `assert len(scanned) >= 4` 的整目录 glob 断言。**一个都不能删。**

## 6. 本地跑

```bash
cd backend
python -m pytest -q --ignore=tests/integration   # 集成层需要真实 PG/Redis/Ollama
ruff check . && mypy app && lint-imports
```

仓库内**不含** `.venv`；容器内跑法见 `deploy/`，服务级启动见 `../README.md` §2。
