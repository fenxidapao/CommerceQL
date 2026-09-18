# W4 续窗交接（PROMPT_RESUME）—— 从本文件开始你就是 W4

> 写给：接手 W4 的下一个窗口（2026-09-18 深夜交接）。
> 上一窗（W4）已完成 T1–T8 全部 + T9 批次①，**中断点 = T9 批次②（决策表 B–G 组）**。
> 本文件自包含；读完再动手。冲突时优先级：07/08 规范 > `reports/w1b/PROMPT_TO_W4.md` > 本文件。

---

## 〇、你是谁：W4 的归属权（`08 §4.1`，动手前逐行核对）

- **你的写入白名单**：`app/graph/**`、`app/api/{errors,sse,deps,ratelimit}.py`、`app/api/routers/**`（**health.py 除外**）、`app/api/{dto,exceptions}.py`、`app/main.py`（**只追加**，不得另立第二装配根）、`tests/{contract,graph_snapshot,redteam}/**`、`reports/w4/**`。
- **别人的一律不碰**（改别人的文件只提需求写进 RELAY）：上游 docs/01–08 只读；`deploy/**`/`scripts/**`/`app/auth`/`app/repo+migrations` = W0/W1B；`app/semantics` = W2A；`app/retrieval` = W2B；`app/guard` = W2C；`app/exec`/`app/mask` = W2D；`app/llm` = W3A；`app/planner` = W3B；`app/binding` = W3C；`frontend` = W5；`eval` 执行器 = W6。
- 动手前 `git status --porcelain`：出现**你不认识的改动 = 别的窗口在制品**，只 stage 自己的文件。
- **同文件多处修改必须串行 Edit**（并行丢编辑在本项目发生过两次，已实锤）。

## 一、当前状态（截至交接，远端 `main` = `d60aab8`）

### 已完成（不要重做）

| 任务 | 状态 | 证据 |
|---|---|---|
| T1–T4 图骨架（19 节点 + 14 条件边 + 事件层） | ✅ | `app/graph/**`，`tests/graph_snapshot/test_graph_wiring.py` |
| T5.1–T5.3 端点（query/session/clarify/feedback） | ✅ | `app/api/routers/**`；feedback 实证 = `reports/w4/RELAY.md §六`（真 PG 探针三要件 PASS） |
| T6 GraphRuntime 装配（解 `/query` 500） | ✅ | `deps.build_graph_runtime` + `main.py` lifespan §4.5；`SINGLE_SAVER_SHARED_POOL` |
| T7 每请求上下文 + query_plan 落库 | ✅ | `bind.py` `set_binding_scope` + `runner._drive` `set_call_context`；**W3C DoD① 已闭合（待 W3C 复核）** |
| T8 韧性 | ✅ | 每节点超时（`build.py::NODE_TIMEOUT_S` + asyncio.timeout）、§16.2 占位先推（runner 1.6s，NFR-1.2 唯一执行点）、会话版本固定写侧（`touch_session` 旧值优先）、两段审计复核。详 = RELAY §七 |
| T9 批次① | ✅ | §14.3 八条逐条（`test_spec143_sequence_contract.py` 12 例）+ 决策表 **A 组 6 行**（`test_decision_table_contract.py`，真图转录级）+ **顺手修复 `events.py` AUDIT_PRE fail-closed 仍发 data 帧的真缺口**。详 = RELAY §八 |

- **门禁现状**：ruff 全过 / mypy app 143 files / lint-imports 4 kept / **全量 pytest 1734 passed / 6 skipped / 0 failed / 0 error**。
- **远端 `main` = `d60aab8`**（`git ls-remote` 验证过；本地 `origin/main` 引用在沙箱里不落盘，**判断推送与否一律用 `git ls-remote`**）。

### 剩余（你的全部待办）

1. **T9 批次②：决策表 B–G 组逐行（约 34 行）** —— 07 §14.2 L2647–2732。这是硬骨头：
   - B 组（检索绑定 6 行）需要脚本化 `deps.retrieval.search_full`（返回形态看 `app/graph/nodes/link.py` 的消费：`.candidates/.value_hits/.graph_hits/.columns/.mode/.degraded_reason/.action_taken`）；
   - C/D/E 组（计划/闸门/执行）需要 **plan → gen_sql → gate1/2/3 → execute → mask → audit_pre 全链脚本**——当前图测试只走早退路径，`GraphDeps` 的 `executor/mask/binding` 都是"未预期调用当场炸"的 `object()` 占位。建议自建 `_FullChainDeps`（真图 astream 到 complete）；
   - F 组 6 行（LLM/呈现）：F1 可脚本 planner 抛异常降级；F4 已由 T8 的 present 超时同形覆盖一半（`_with_node_timeout`）；F5 转异步**不可达**（`GateResult` 无预估延迟载体，已有测试钉住——别接它，登记等待载体）；F6 无事件行断言转录无异常即可。
   - G 组 4 行：G1 fail-closed（audit 写库失败）已在 T9① 部分覆盖（emissions 层）——补节点级；G2 段 2 写失败不阻断；G3 kill switch（找 `settings` 的禁用开关）；G4 recursion_limit。
   - **H 组不用做**：W0 的 `tests/contract/test_contract_counts.py`（41 项）已钉死全部映射。
   - 行级断言形态照抄 A 组：事件 / code|reason / terminal / `task_status_of` 投影 / 审计段位。**"无事件"行**（C3/D5/D6/E1/F6/B6）断言转录无对应事件 + detail 落位（`gate_detail`/审计）。
2. **T10 收口**：08 §3.6 四条 DoD 逐条自验（§八）；六道门禁原样进 `reports/w4/DELIVERY.md`（新写）；`RELAY.md` 终稿（§给 W5 联调清单已在 HANDOFF §四）；`feat(w4)` 提交 + push。
3. **T9 附带**：`tests/redteam/` 与 W2C 共建（`test_redteam_guard.py` 骨架已在，看它缺什么）。

## 二、已登记的缺口与口径差异（别当 bug 修，也别谎报已解决）

| 项 | 现状 |
|---|---|
| 会话级版本固定**图内读侧** | 写侧已固定（`sess:meta`），但 pinned 版本注回 `RunContext.bundle_version` 缺 `RepositoryPort` 通道（`trusted_context.py` §三登记）——需要装配层把 `RepositoryPort` 收进 `GraphDeps`，属跨层新增，先 RELAY 登记 |
| F5 转异步不可达 | `route_after_gate3._should_go_async` 缺"预估延迟"载体（`GateResult` 无该字段），恒 False 且有测试钉住 |
| A2 reason 差异 | 07 字面 `reason=ambiguity`，实现走 `time_ambiguous`（`clarify_out` reason 无枚举）——断言按实现事实写，差异已登记 |
| `GET /query/{id}` 的 data/audit_ref/progress 恒 null | 诚实边界（`runner.py` 模块 docstring §四）：CachePort 无实现 / AuditSinkPort 不回 id / progress 无映射规则 |
| 容器内端到端 | 🔴 红线：**不得宣称"容器内端到端已验证"**——本地 `commerceql-api-1` 跑的是旧镜像；探针是进程内 TestClient |
| 待裁挂账 | 转架构：§11.7/§12.3 表列补齐、`gold_query.source` 取值集、`app/cache/` CachePort 归属等（见 MEMORY §5 尾） |

## 三、环境与纪律（每一条都踩过坑）

- **Bash 工具必须加 PATH 前缀**（否则 git/工具找不到）：
  `export PATH="/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/bin:$PATH"`
  （stderr 两行 `dirname not found` 噪音无害；别用 PowerShell，零回显。）
- 仓库根 = `CommerceQL/`（**不是** `CommerceQL/backend`）；`git status` 路径带 `backend/` 前缀；工作目录常被重置，命令开头先 `cd`。
- 一律 `backend` 目录下跑 `../.venv/Scripts/python.exe`；**pytest 必须 `--basetemp=.w4tmp`**（否则摘要行被 harness safe-delete 守卫杀掉、exit=1），跑完 `rm -rf .w4tmp`。
- **不写 `async def test_`**：同步用例内 `asyncio.run(...)`（pytest-asyncio 1.4 + Windows ProactorEventLoop 会撞 psycopg）。
- 集成测试（PG）需 Docker Desktop 先起；`commerceql-pg-1` healthy 即可。3 DSN 无默认值；探针进程内自给 `DATABASE_URL`(app_rw) + `ANALYTICS_DB_URL`(**必须 app_ro**，N-02 禁同值)。
- 门禁四件套：`ruff check app tests` / `mypy app` / `lint-imports`（入口是 `.venv/Scripts/lint-imports.exe`，不是 `-m importlinter`）/ 全量 pytest。
- 提交规范：`feat(w4)` 前缀、只 stage 白名单文件、**push 前看用户当轮是否授权**（本项目惯例 = 明确授权才推；`git ls-remote` 验证）。
- 编号纪律：07 §4.8 唯一权威；下一可用编号 = **U-88**。
- 红线：不编数据、不谎报、Mock 不冒充集成、决策点先报告再动手、"必须 X 没给值"时登记而非发明。
- 完成实质工作后：更新 `reports/w4/RELAY.md`（续 §九）+ `.workbuddy/memory/2026-09-18.md`（或当日新文件）+ `MEMORY.md` 的 W4 段（**先读后写、只写自己窗口段、写完 grep 复核**——本项目写丢过两次）。

## 四、必读文件索引（按顺序）

1. `backend/reports/w4/PROMPT.md`（T1–T10 任务定义 + §五必读清单 + §六接线硬约束）
2. `backend/reports/w4/HANDOFF.md`（**§五"已裁口径，直接用不要再问"**——TaskStatus/cancel/每节点超时/占位/X-RateLimit 四头）
3. `backend/reports/w4/RELAY.md`（§一~§五 = 跨窗口需求；§六 feedback 实证；§七 T8；§八 T9① 进度与 B–G 缺口登记）
4. `docs/07`：§5.3（节点契约表）· §5.3.1（两段审计）· §14.2（A–H 决策表，L2625–2732）· §14.3（八条约束，L2734+）· §14.4（retryable 三级）· §16.2（占位）
5. `tests/contract/test_decision_table_contract.py` + `test_spec143_sequence_contract.py`（你的行级断言模板）
6. `app/api/runner.py` 模块 docstring（SSE 层全部诚实边界）
7. 项目记忆 `MEMORY.md`（跨窗口约定/归属权/坑清单）

## 五、开工第一句话建议

```
继续 W4：T9 批次②（决策表 B–G 组逐行），交接文档 = backend/reports/w4/PROMPT_RESUME.md
```
