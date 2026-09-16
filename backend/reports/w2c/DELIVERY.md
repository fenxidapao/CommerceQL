# W2C DELIVERY —— 阶段 2C 三道闸门交付

> 归属：W2C｜日期：2026-09-16｜上游：docs/08 §3.4 / docs/07 §7 全章｜红线自查：本文件所有"已实现"均给出可核对位置。

## 1. 交付物（精确到文件）

| 文件 | 内容 | 对应契约 |
|---|---|---|
| `backend/app/guard/rules.py` | 20 条规则注册表（**规则唯一入口**）：`RuleDef(rule, severity, error_code, user_message, internal_only)` + `FUNCTION_DENYLIST` + 导入期自检（与 `enums.AstRule`/`AST_RULE_SEVERITY` 失同步即 ImportError） | 07 §7.2 规则表、§7.6 文案表 |
| `backend/app/guard/ast_gate.py` | gate1：剥注释（R15，字符串/美元引用感知）→ 多语句（R02）→ 语句类型（R01/R16 消歧）→ **默认谓词 AST 注入** → LIMIT 归一化（R04，§7.3 六情形）→ 全树审计（R03/R05–R14，R09 先于表检查保证 dblink 表函数归因）→ 告警（R17–R20） | 07 §7.2/§7.3、§5.3 节点 8 |
| `backend/app/guard/policy_gate.py` | gate2：版本一致性 → 资产白名单二次复核 → 数据域 ⊆ JWT.scope（越界 = `refuse(out_of_scope)`，C-12）→ deny 列二次复核 → **scope 四分支** + `tenant_scoped ⇔ tenant_id 列` 双向断言（违反抛 `ContractViolationError`） | 07 §7.4、§7.6.1 |
| `backend/app/guard/cost_gate.py` | gate3：EXPLAIN JSON 计划树解析（Plan Rows 递归累加）→ 阈值表三态（Total Cost / 行数 / Nested Loop 外层 / Seq Scan / Sort / 计划深度）；`CostThresholds.from_mapping` 可配置（DoD④）；`SKIPPED`（passed=False）与 `explain_error→warn` 语义 | 07 §7.5、§14.2 D6 |
| `backend/app/guard/__init__.py` | `SqlGuard`（实现 `core.contracts.GuardPort`，`isinstance` 校验通过）+ `run_gate1/2/3` 完整出参导出 | 07 附-1 |
| `backend/tests/unit/guard_fixtures.py` | allowlist 夹具：**从真语义包 YAML 构建**（单一事实来源）；`FakeSemanticBundle`；`make_ctx` | — |
| `backend/tests/unit/test_guard_rules.py` | 注册表完整性 / severity 与 enums 同源 / 错误码族 / **文案零 schema 泄露**（逐条，DoD②） | DoD② |
| `backend/tests/unit/test_guard_gate1.py` | 20 规则逐条 + LIMIT 六情形 + 谓词注入 + 告警级"放行+告警"反向断言（U-16） | §7.8 测试矩阵 |
| `backend/tests/unit/test_guard_gate2.py` | 四分支逐条 + 冗余复核 + 版本钉 + refuse/error 边界 + 双向断言 | §7.4 |
| `backend/tests/unit/test_guard_gate3.py` | 阈值表逐行（含 warn 带）+ 三态出口 + skipped 不报通过 + 可配置（DoD④） | §7.5 |
| `backend/tests/redteam/test_redteam_guard.py` | **红队 66 条全量**（DoD①）+ 不泄露断言 + **负向对照**（审计器失效→阻断类必翻转；gate2 冗余兜底验证） | DoD①、§7.8 |
| `backend/reports/w2c/RELAY.md` | U-62/U-63/U-64 提案、W2A 对齐点、他窗失败观察、未做清单 | docs/08 §4.1 |
| `backend/reports/w2c/W4_PROMPT.md` | 给 W4 的接线提示词（用户约定：完成后写下一阶段提示词） | 用户开工约定 |

## 2. DoD 对照（docs/08 §3.4 阶段 2C 行）

| DoD | 结果 | 证据 |
|---|---|---|
| ① 红队集全绿 = 危险 SQL 放行 0 | ✅（gate 层；1 条冻结集内部矛盾按契约拒绝并登记，见 RELAY §1-U56#6） | `tests/redteam/test_redteam_guard.py`：66/66，137 tests green |
| ② 每条规则的可解释文案不泄露表名 | ✅ | `test_guard_rules.py::TestNoSchemaLeakageInUserMessages`（逐条 20 规则）+ 红队 `TestNoLeakageOnReject`（对全部拒绝路径，用真 bundle 的表/列名做泄露集） |
| ③ `rule_id` 进 `gate_detail` | ✅ | 三个 gate 的 `GateResult.rule_id` 全填（阻断必带；`test_rule_id_always_present_on_block`）；C-02 |
| ④ gate3 阈值表可配置 | ✅ | `CostThresholds.from_mapping` + `TestConfigurableThresholds`（含未知键忽略） |

## 3. 验证记录（report-before-run）

- 环境：`CommerceQL/.venv`（托管 Python 3.13），Windows 宿主。
- guard 测试域：`pytest tests/unit/test_guard_* tests/redteam/test_redteam_guard.py` → **137 passed**（0.75s，离线，N-01）。
- import-linter：`python scripts/assert_importlinter.py` → 3 contracts kept；guard 未引入 llm/repo 依赖（R-DEP-1/2/3 探针全过）。
- 全量：`pytest -q` → **758 passed / 3 failed / 8 skipped**；3 个失败均在 W2B/W2D 在制品（逐条记录于 RELAY §4），与本阶段无关。
- **负向对照**（防护栏摆设，含"看清红的确实是目标断言"）：
  - monkeypatch `_Auditor.run` 恒不阻断 → 全部审计级阻断用例翻转（R01/R02/前置检查类除外，已在测试内注明）；
  - 还原后同用例必红恢复；
  - gate1 失明时 gate2 二次复核仍兜底（`G2-DENY`）。

## 4. 实现中做出的口径决策（均有测试锚定，异议走 U-xx）

1. **R17 告警的可达性**：R17（类型失配）只能对"列-常量比较"生效 → R14 的拒绝位收窄为"字面量-字面量恒真 + 无列上下文自由字面量"（红队 RT-R14-* 三条正好全部落在该口径内）。见 `ast_gate.py::_check_literals` docstring。
2. **R03 只查根 scope 投影**：内层 SELECT * 不直接暴露列，且 RT-R19-001 的嵌套 SELECT * 必须 warn 放行。
3. **R19 深度口径**：Select 总层数（含顶层）> 5，与 RT-R19-001（6 层）一致。
4. **LIMIT/OFFSET 字面量并入 R14 白名单**（三类来源之①的延伸：保留的合法 LIMIT 与既有 OFFSET 同属行界参数）。
5. **JOIN 归因**：无条件连接/`ON 1=1`/无认证边 → R10；认证边上条件列错配 → R11（红队冻结口径，与 §7.2 文字映射有出入，RELAY §1-U56#4）。
6. **R13 显式化**：集合查询分支违规统一归因 R13（分支独立过 R05/R06/R07 的"归因落点"），全局检查对其余形态不变。
7. **gate2 版本一致性**：请求锚定版本经 allowlist 的 `bundle_version` 进入（端口签名无独立参数）；与 `bundle.active_version()` 不一致 → `G2-VERSION`。
8. **R14 第③类**：语义包无声明区 → `allowed_constants=[]`，键已预留，W1A 增补零改动。

## 5. 未解决的风险（诚实清单）

- **U-64 的 6 条口径冲突未裁定**：W2C 按冻结红队集执行；若架构窗口裁定相反方向，改动集中在 `ast_gate.py`（LIMIT ALL、SET 消歧、join 归因、R14 口径）+ 对应测试，其余模块不受影响。
- **RT-LIM-003**：deny_columns（tenant_id）与"execute 返回 0 行"期望互斥 —— 这是**安全方向偏保守**的选择（拒绝 > 放行），若裁定放行需 W2D/W6 联动。
- **gate2 二次复核的列解析**与 gate1 共用 `_Auditor._resolve_column`：若 W2A 的 allowlist 形状变更，两处同变（单点实现，无复制）。
- **gate3 性能契约**（1.0s 超时预算）未压测：纯函数部分估算 <10ms，EXPLAIN 的连接成本归 W4 节点层。
- 敏感字段二次审批（P1）未实现（接口预留，07 §13.6 一致）。

## 6. 交接状态

- 代码可独立合入（不依赖 W2A/W2B/W2D 产物；测试夹具自足）。
- 下一阶段提示词：`reports/w2c/W4_PROMPT.md`（阶段 4 启动时交给 W4）。
- 编号提案待架构窗口落 07 §4.8：U-62（GuardPort 出参通道）/ U-63（EXPLAIN 执行归属）/ U-64（口径冲突 6 条；原提案号 U-54/55/56 与 W2A 撞号、U-59/60/61 与 W2B 候选撞号，两次让号，见 RELAY §1）。
