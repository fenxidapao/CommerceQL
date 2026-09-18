# W4 交付 —— 阶段 4 · 编排收口（T9 批次② + T10 收口）

> 窗口：W4｜日期：2026-09-18｜分支 `main`｜提交：`feat(w4)` + `docs(w4)`（见 §5）
> 依据：`reports/w4/PROMPT_RESUME.md`（T9② 决策表 B–G 组 + T10 收口）｜规格：07 §14.2/§14.3、08 §3.6
> 前序（T1–T8 + T9 批次①）见 `RELAY.md §六–§八`；本文件只记**本批**增量。

---

## 1. 交付范围（本批）

| 产出 | 说明 |
|---|---|
| `tests/contract/_fullchain_deps.py` | 全链脚本 deps 夹具库（plan→gen_sql→gate1/2/3→execute→repair→mask→audit_pre→present→audit_supp 深链假件，接口逐字对齐节点调用面） |
| `tests/contract/test_decision_table_b_c.py` | B 组（6 行）/ C 组（3 行）逐行图级测试 |
| `tests/contract/test_decision_table_d_e.py` | D 组（7 行）/ E 组（8 行）逐行图级测试 |
| `tests/contract/test_decision_table_f_g.py` | F 组（6 行）/ G 组（4 行）逐行图级测试（不可达/缺载体行如实登记，见 §4） |
| 生产代码 5 处修复 | `execute.py` / `errors.py` / `runner.py` / `refuse_out.py` / `error_out.py` / `events.py` / `audit_supp.py`（详见 RELAY §九，含 3 个真缺口修复） |

**未落笔**（属他人范围）：`app/core/**`（W0）、`app/{llm,planner,binding,guard,exec,mask,semantics,retrieval}`（W2A/B/C/D、W3A/B/C）、`frontend/**`（W5）、H 组映射（W0 `test_contract_counts.py` 已钉死 41 项）。

---

## 2. DoD 逐条自验（08 §3.6 ①–④）

| # | 要求 | 实现落点 | 断言（可核对的测试名） |
|---|---|---|---|
| ① | SSE 转录测试覆盖**全部出口路径**，并断言"恰有 1 个 `terminal:true`"（N-08） | `run_chain` → `asyncio.run(_collect())` 收字节帧 → `_parse` → `terminal_frames` 过滤 `terminal is True`；`clarify/refuse/error/complete` 四出口各铺行 | `test_spec143_sequence_contract.py`（终态唯一转录级）＋ `test_decision_table_{contract,b_c,d_e,f_g}.py` 每例 `assert len(terminals) == 1` |
| ② | 07 §14.3 的 **8 条事件序列约束全绿** | `test_spec143_sequence_contract.py`（12 例）：① 终态唯一 ② 三者互斥 ③ 终态最后 ④ degraded 前置 ⑤ refuse 无 data / error 前可有 data ⑥ DATA 发射点唯一 + fail-closed ⑦ meta 必含 scope/retrieval_mode ⑧ stage 恰 6 值 | `test_spec143_sequence_contract.py` 全 12 例（contract 目录 380 passed 之内） |
| ③ | `stage` 取值只有 6 个（枚举校验） | `core.enums.Stage` 6 值；`events.py` 发射取值全部来自 `core.enums`（确定性模块纪律）；契约自检脚本钉基数 | `python -m app.core.enums` → `stage: 6` |
| ④ | 07 §14.2 的 **A–H 八组决策表逐行有对应测试** | A：`test_decision_table_contract.py`；B/C：`test_decision_table_b_c.py`；D/E：`test_decision_table_d_e.py`；F/G：`test_decision_table_f_g.py`；H：W0 `test_contract_counts.py` | 见 §2.1 逐行覆盖表 |

### 2.1 决策表 A–H 逐行覆盖表

| 组 | 行 | 测试文件 | 状态 |
|---|---|---|---|
| A | A1–A6 | `test_decision_table_contract.py` | ✅ 6 行全绿（T9 批次①） |
| B | B1–B6 | `test_decision_table_b_c.py` | ✅ 6 行（检索绑定） |
| C | C1–C3 | `test_decision_table_b_c.py` | ✅ 3 行（计划/异常；C1+C2 合并，见 U-89） |
| D | D1–D7 | `test_decision_table_d_e.py` | ✅ 7 行（闸门/成本/执行） |
| E | E1–E8 | `test_decision_table_d_e.py` | ✅ 6 行实测 + E7/E8 引用既有测试（见 U-99） |
| F | F1–F6 | `test_decision_table_f_g.py` | ✅ F1–F4 实测；F5/F6 无图级可观测面（见 U-93/U-94） |
| G | G1–G4 | `test_decision_table_f_g.py` | ✅ G1/G2 实测；G3/G4 缺载体（见 U-95/U-96） |
| H | 映射全集 | `test_contract_counts.py`（W0） | ✅ 41 项已钉死，W4 不重复建 |

---

## 3. 门禁实测输出（2026-09-18，本机，`.venv`，`cd backend`）

```
$ ../.venv/Scripts/python.exe -m pytest --basetemp=.w4tmp -q --tb=short
1674 passed, 87 skipped, 1 failed, 6 errors in 192.60s
# 1 failed + 6 errors 全部 = tests/integration/test_retrieval_fts_pg.py::psycopg ConnectionTimeout
#   （PG compose 栈未起）；87 skip = 其余 integration 用例的"集成环境不可用"如实 skip。
#   与本窗口变更无关（tests/contract 380 passed 全绿，见下）。

$ ../.venv/Scripts/python.exe -m ruff check app tests
All checks passed!

$ ../.venv/Scripts/python.exe -m mypy app
Success: no issues found in 143 source files

$ ../.venv/Scripts/lint-imports.exe          # 控制台脚本，非 -m importlinter（U-41）
Analyzed 185 files, 999 dependencies.
R-DEP-1/2/3/4 均 KEPT
Contracts: 4 kept, 0 broken.

$ ../.venv/Scripts/python.exe -m app.core.enums
enums.py 契约自检通过；取值集基数 = {stage: 6, error_code: 28, ..., task_status: 8, ...}

$ ../.venv/Scripts/python.exe scripts/assert_importlinter.py   # CI 同款 DoD② 注入实验
[baseline] 干净状态 lint 通过（Contracts: 4 kept, 0 broken.）
[probe] ✅ r-dep-1/2/3/4 四条契约
[restored] 还原后 lint 重新通过（Contracts: 4 kept, 0 broken.）
DoD② 通过 —— 4 条契约均已证明「脏了必红」

# 本批范围另核对：
$ ../.venv/Scripts/python.exe -m pytest tests/contract -q --tb=short
380 passed, 1 warning in 41.27s
```

---

## 4. 差异登记（完整见 RELAY §九，U-88 起）

本批新增 14 条差异/修复登记（U-88–U-101），涵盖：B2+B3 reason 取值、C1+C2 合并、D3 error≠refuse、D4 message 空、F1 无弱模型档、F5/F6/G3/G4 不可达或缺载体、TaskStatus.DEGRADED 不可达、B6 disclosure 仅审计可见、E7/E8 引用既有测试，以及 3 处生产真缺口修复（出口帧 reason/code 侧信道、C3 `exec_error` 残留、B6 supp 降级累积器）。

---

## 5. 诚实边界（收口结论，不谎报）

1. **端到端"可用"未宣称**：本批测试全部是**进程内真图转录级**（`SseRunner.stream` + `asyncio.run`），未经 uvicorn/compose 容器层，也不含与 W5 前端的真实联调。W5 的 17 条 BLOCKED QA 仍待联调环境。
2. **U-68 合并档未落**：plan+gen_sql 仍两 task 接线，W3B DoD① 的部分达成与本窗口无关，维持"未完成"口径。
3. **全量 pytest 唯一红 = 环境不可达**：`test_retrieval_fts_pg.py` 的 1F+6E 是 PG compose 栈未起导致的 `ConnectionTimeout`，非回归；如需真库绿需先 `docker compose up` 起 `commerceql-pg-1`。