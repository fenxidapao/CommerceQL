# W2-INT → 全窗口转述件（粘贴版 · 2026-09-16 23:5x 第三版）

> 来源：W2-INT 收口窗口（commit `f351ada` + `167295b` + `3fc1790` + `b697667`，不含第三方提交）
> 用法：每个【】块就是一条完整消息，直接复制给对应窗口，互相无依赖，可一次性全发。
> 证据细节在 `backend/reports/w2-int/DELIVERY.md`（§4 门禁 / §5 端到端 / §6 U-55 授权改动 / §7 CI 分派）与 `backend/reports/w0/RELAY.md`（§6 ruff 清单），收件窗口可自行查。

---

## 【给 W0 · 回复】ruff 33 条已按域分派 + (a) 撤回确认

> 1. **收到 (b) 已落码（c7bb534）**：契约断言 job 挂 PG service 后集成测试真跑全绿——**此前给 W2A/W2B 的分派 (a)"补 skip 分支"撤回**，两窗口无需改动；他们的 CI 红属 (b) 覆盖范围，已改发"知悉 (b) 落地、无需 skip 分支"的通知。你此前表述的 (a)(b) 兼容性判断正确，但既然 (b) 已落地就不再让窗口做无谓改动。
> 2. **ruff 33 条已按你 RELAY §6 清单分派**，两处归属更正请复核修正：
>    - guard 域 10 条 → **归 W2C**（app/guard/** 是 W2C 归属，非 W1B 域）；
>    - `tests/redteam/test_redteam_guard.py:23 F401` 1 条 → **归 W1A**（tests/redteam/** 按 07 归属表为 W1A 内容资产、与 W2C 共建；该文件是红队用例库侧）。
>    - W2-INT 域 1 条（`reports/w2-int/e2e_stage2_check.py:1` UP009）**已由我修复**，`ruff check` 复核 All checks passed。
> 3. `dense.py:273 F821` 按你的⚠️指示，已在给 W2B 的消息里明确"先手动修、--fix 修不了"。
> 4. 上轮 3 条部署面缺口（迁移链无机器保证 / api 容器缺语义包挂载 / .env 行内注释）仍待你收口，清单位置不变（见 DELIVERY §7 转述件存档或 `reports/w2-int/RELAY.md`）。

---

## 【给 W2A】U-55(a) 已代改 + CI 红已由 W0 (b) 方案解决，请复核

> 1. **CI 红（test_semantic_materialization.py ×2）无需你改**：W0 已落 (b) 方案（c7bb534，pytest job 挂 PG service），集成测试在 CI 真跑全绿——原分派的"补 skip 分支"撤回。
> 2. **架构已裁 U-55 = (a)：RLS 落基表、视图透传。** 因该项在你归属（`app/semantics/materialize.py`）但按流程由收口窗口代改，请你**复核以下改动**（记录 = `backend/reports/w2-int/DELIVERY.md §6`，commit `b697667`）：
>    - `derive_policy_statements` 的 RLS/POLICY 段改为基表目标：`ALTER TABLE {基表} ENABLE/FORCE ROW LEVEL SECURITY`、`CREATE POLICY p_{基表}_tenant ON {基表}`；CLS GRANT 仍在视图；
>    - `assert_grant_policy_consistency` 的 pg_policies 查询改查基表名；
>    - 你的 `tests/unit/test_materialize_derivation.py` 有 4 条断言随之更新（基表名），并新增"目标是基表不是视图"的锁定断言；已做注入对照（还原旧行为 → 4 条必红 → 还原 → 必绿）。
> 3. U-56 裁决 = W1B alembic 迁移建 v_* 视图+基表；U-54 = (a)（契约留 contracts、装配根注入两侧同实例）→ 你的 tokenizer 注入点（`materialize(..., tokenizer=...)`）可按此接线，阶段 3 排期。
> 4. 上轮接线确认（启动断言注入 PASS / readiness 探针 200 / materialize 197 docs 复现 / 指针切换回滚 PASS）不变，无新动作。

---

## 【给 W2B】dense.py:273 F821 先手动修 + ruff 12 条 + 端口面收敛预告

> 1. **⚠️ 优先手动修 `app/retrieval/dense.py:273` F821（Undefined name `Mapping`）**——W0 特别提示：这是运行时 NameError（`from __future__ import annotations` 只护注解不护该处使用），`ruff check . --fix` 修不了；修法 = 文件头 `from typing import` 行补 `Mapping`（当前第 32 行只有 `Any, Final, Protocol, Sequence`）。
> 2. **ruff 33 条中你域内 13 条**（清单 = `backend/reports/w0/RELAY.md §6`）：上述 1 条手动 + 其余 12 条可用 `ruff check . --fix` 收口（含 retrieval 6 条与 reports/w2b/recall_report.py 等）。收口窗口按纪律不代改你归属文件。
> 3. **CI 红（test_retrieval_fts_pg.py ×6）无需你改**：W0 已落 (b) 方案（c7bb534，PG service 进 CI），原分派的"补 skip 分支"撤回。
> 4. **裁决结果知悉**（07 v0.9 §4.8）：U-54 = (a) 契约在 contracts、装配根注入 tokenizer 两侧同实例；U-59 = (a) **升级 RetrievalPort 端口面**（列级富结果进契约，**`search_full()` 旁路被否决**，contracts.py 由 W0 落笔）→ 你的旁路调用后续按新端口面收敛，阶段 3 排期留意；U-60（`tenant_id='*'` 哨兵）与 U-61（`to_tsquery` 显式 `&`）已契约化进 07。

---

## 【给 W2C】ruff 10 条 + mypy 19 条 + U-62/63/64 裁决结果

> 1. **ruff 33 条中你域内 10 条**（app/guard/，UP035×4 / RUF034×2 / UP037 / RUF100 等，清单 = `backend/reports/w0/RELAY.md §6`），多数可 `ruff check . --fix` 收口；行为未动，纯 lint 级。
> 2. **mypy 22 条中 19 条在 guard**（ast_gate 15 / cost_gate 4，清单 = `backend/reports/w2-int/DELIVERY.md §4`），非阻断但会挂 CI 类型检查，建议一并收。
> 3. **裁决结果知悉**（07 v0.9 §4.8）：U-62（GuardPort 改写类出参通道）、U-63（gate3 EXPLAIN 归 W4 的 gate3_cost 节点）、U-64（红队冻结集口径）均已登记。U-64 若终局与你的实现有出入，改动集中在 ast_gate.py，请对照 §4.8 复核一次。

---

## 【给 W2D】提交提醒（仍 untracked）+ U-63 契约知悉

> 1. **你的代码当前仍未提交（untracked）**——收口窗口基于工作区实测的结论（91 条测试通过、0 条 ruff/mypy 归你）仍有效，但请尽快提交并通知收口窗口重跑门禁复核一次。
> 2. U-63 已裁决：gate3 的 EXPLAIN 执行 = W4 的 `gate3_cost` 节点跑 EXPLAIN 并传计划 JSON，此为正式契约——你 exec 侧如有对 gate3 执行位置的假设，请对照 07 v0.9 §4.8 核对。

---

## 【给 W1A】1 条 ruff + 红队集口径已被 U-64 裁决

> 1. **ruff 33 条中 1 条在你域**：`tests/redteam/test_redteam_guard.py:23` F401（未使用 import），`--fix` 可收（清单 = `backend/reports/w0/RELAY.md §6`）。
> 2. U-64 已裁决并登记 07 v0.9 §4.8（红队冻结集 vs 07 §7.2/§7.3 六处口径冲突，含 LIMIT ALL / SET 消歧 / CROSS JOIN 归因 / R14 vs R17 / RT-LIM-003）——W2C 按冻结集执行的口径已获确认；如裁决要求 07 侧文档让步，无需你改用例。你此前的遗留（L1 变体 patch、L5 零分母 SKU、4 个 `--check` 挂 CI）状态不变。

---

## 【给 W1B】U-56 迁移请求（当前关键路径）

> 架构已裁 **U-56：v_* 业务视图（8 个）+ 对应基表的 PG 侧 DDL 由你以 alembic 迁移落**（迁移链 0001/0002 已存在，新增 0003 起）。这是 DoD③ 端到端当前**唯一硬阻塞**：收口窗口实测六步发布在 step② `materialize(with_policy=True)` 报 `UndefinedTable: relation "v_order_paid" does not exist`（单事务回滚无半态）。迁移落地后语义包即可从 candidate 转正式发布。配套知悉：U-55(a) 已实施（RLS 落基表、策略名 `p_{基表}_tenant`、视图透传，GRANT 仍挂视图），迁移脚本建表/建视图时请与此口径一致；实测细节 = `backend/reports/w2-int/DELIVERY.md §5/§6`。另：你名下 U-53（pool.close() 2s）仍未做，可随本次一并收。

---

## 【给架构窗口 · FYI】裁决已收到并核实，无新请求

> 9 条裁决（07 v0.9 §4.8）已收悉并逐条核对：U-55(a) 已由收口窗口在授权范围内实施（`derive_policy_statements` 基表化 + 注入对照 + 全量门禁复核，commit `b697667`，已请 W2A 复核）；其余各窗口分派已发出。**下一可用编号 = U-65**（W1A/W1B/W2A/W2B 区间已用尽，无新增请求）。唯一关键路径 = U-56 迁移（已派 W1B）。编号登记烦请确认 U-62/63/64 归属段无撞号（W2C 曾两次让号）。
