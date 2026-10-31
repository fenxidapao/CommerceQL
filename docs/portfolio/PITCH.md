# PITCH —— 3 分钟口述稿 + 10 问

> 用法：面试/答辩时按四段讲；每段标注建议时长。所有数字都能追到源件（文件:行）。
> 口径：**72.73%（v2，当前）仍未达** 85%；41.47%（v1）作历史保留；G-6/G-8 仍 `UNVERIFIED`；`6/8 ≠ 门禁通过`。

---

## 一、3 分钟口述稿

### 0:00–0:30 ｜问题：LLM 写的 SQL 是不可信输入

"这个项目做的是：一句中文业务问题，变成一条受控 SQL，再出图和结论。它不是一个
'让大模型写 SQL 然后 execute' 的 demo。整个设计围绕一个前提：**模型生成的 SQL 是不可信输入**。
所以我在 SQL 进数据库之前放了三道闸门，在数据库里放了租户级行级隔离，在结果出站之前
放了内容白名单和两段式审计。目标不是让模型'更敢写'，而是让它在越界时**被挡住**。"

### 0:30–1:20 ｜设计：固定图 + 三闸门 + RLS + fail-closed 审计

"主链路是一张固定的 19 节点图：从 trusted_context、normalize、intent、link、plan、bind、
gen_sql，到 gate1_ast、gate2_policy、gate3_cost，再到 execute、mask、audit_pre、present、
audit_supp。三个终态出口 clarify / refuse / error 是三个独立节点。
三道闸门分别管三件事：AST 管语法、DDL、表列和危险函数；政策管角色和列级 allowlist；
成本管 EXPLAIN 的预估行数和成本。repair 只能回到 gate1_ast，不能绕过政策/成本。
数据库侧，业务 SQL 只走 `v_o_*` 认证视图，`FORCE RLS` 对属主也生效，策略由语义包物化。
审计是两段式：present 之前和之后各一段；**审计写失败就不下发数据**。
依赖方向不是靠纪律，是靠 `importlinter` 的 R-DEP-1..4：L2 确定性层结构上不能 import LLM。"

### 1:20–2:20 ｜证据：60 题、3 批、72.73%、448,152 行、5 条 demo

"证据分两块。评测：Olist 真实数据 60 题冻结集，55 道 execute、5 道交互；3 个独立批次，
同一温度 0.0、同一 DSN；`EX_official = 72.73% ± 1.82%`（n=3；三批 41/55、39/55、40/55）。
上一轮是 41.47%，差的 31.26 个百分点**不是模型变强**：我把三类与模型无关的缺陷逐类归因修掉了 ——
表别名写成保留字 `AS order`（7 条语法错）、gold 做了 `ROUND` 而模型不做（13~15 条判不等）、
`delivery_late_rate` 表达式漏乘 100（5 条比率恒 0）；修完三类桶三批全归零，
**剩下 12 条是 postgres↔SQLite 的方言缺口，没修，单列、不算模型错**。
交互正确这一轮**有退化**（c01、r02），不进 EX 但我不藏。
这里要诚实：72.73% 也没到 85%，G-6 的 8 秒和 G-8 的澄清率还是 UNVERIFIED。
数据侧：迁移 0007 + Olist 五表 448,152 行；materialize 一致性 5/5；T_B 金丝雀每表 1 行、
删后 0；app_ro 不带租户 GUC 时五表全 0。演示：生产栈浏览器 5/5，4 张图 + 1 条危险请求拒答，
单次跑完 ¥0.02384。"

### 2:20–3:00 ｜反思：如果重做，先补哪三件

"如果重做，我先补三件。第一，R14 的月度时序：闸门一的字面量白名单不认
`to_char`/`date_trunc` 的格式串，W2 同族 12/55 被拒，演示里因此没有折线图。
第二，生成侧的 `AS order` 保留字，7/55 直接 SQL 语法错，这是生成缺陷，不是方言。
第三，`delivery_late_rate` 的 bundle expression 没乘 100，PG 整数除法还会截断。
这三件都不是'调参'，是口径或判据层面的修正，所以我按 v2 走，不在 v1 偷改冻结集。
这个项目给我最大的训练不是写 SQL，而是**把'安全'做成架构的一部分，并让每个数字可复算**。"

---

## 二、10 问（每问给指针）

### Q1. 为什么是单管道，而不是多 Agent？

主链路是固定的 19 节点图（16 主节点 + 3 终态出口），每个节点、每条条件边、每个终态出口
都在图上有确定位置；审计和闸门也在固定位置。多 Agent 的开放式协作会把"谁在什么时候
调用了什么"变成运行时才确定的事，审计闭合和 RLS 身份传递都会更难。
指针：`backend/app/graph/nodes/__init__.py:1`、`:95-127`（16 主节点 + 3 出口的唯一真相）；
`backend/.importlinter`（R-DEP-1..4）。

### Q2. 为什么需要三道闸门？一道不够吗？

三道闸门管三种不同的失败：AST 管"这条 SQL 的形状"（DDL、SELECT *、危险函数、未授权表列）；
政策管"这个角色能不能看这些列"（RBAC + allowlist）；成本管"这条 SQL 会不会把库拖垮"
（EXPLAIN 预估行数/成本）。把三者合并成一道，要么漏掉一类，要么在同一个判据里混入
不可归因的拒绝。repair 只能回 gate1_ast，不能跳过政策/成本。
指针：`backend/app/guard/ast_gate.py`、`backend/app/guard/policy_gate.py`、
`backend/app/guard/cost_gate.py`。

### Q3. EX 到底怎么测？分母、批次、温度、DSN、rev 各是什么？

60 题 = 55 execute + 5 interaction（3 clarify + 2 refuse）。3 个独立批次，各自进程、
各自 `--batch-id`（`w2_r1..r3`），批次日期 2026-10-28；温度全 0.0；DSN
`postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ecom`；三批运行时刻
`git_rev=aeb53eb`、`git_dirty=true`（W2 窗未提交的中间态），最终入库代码 `b780125`。
分母不是常量：r1 有 1 条 `GraphRecursionError`（o19）记 unscored，所以 54；r2/r3 是 55。
`scored_total` 现算，不抄常量。
指针：`eval/olist/report.md:15`、`:21-25`、`:75`；`backend/app/llm/router.py:202-260`；
`deploy/demo/README.md:60`。

### Q4. 最难的 bug 是什么？

最险的不是某个业务 bug，而是**依赖升级悄悄改变闸门判据**：`sqlglot` 升到 30.25 会让
闸门一的 R04 从 rewrite 变 reject，红掉 2 条既有测试；所以项目把 `sqlglot` 钉在 30.18.0，
并写进开窗约束。另一个教训是前端：后端 kpi 是对的，但 `CHART_TYPES_ALL` 缺 `'kpi'`，
渲染时被当成未知类型降级成表格；浏览器验收抓到，补一行后重拍截图。
指针：`AGENTS.md`（sqlglot 钉版本）；`backend/reports/w3_demo/browser_acceptance.json`
（kpi 修复前后与截图）。

### Q5. 为什么不做多 Agent？

同上：这个任务的正确性边界在**闸门、RLS、审计**，不在"再找一个 Agent 来复核"。
多 Agent 会增加出站面、身份传递面和不可复算的分支；而本项目的卖点是"每个数字都能
用一条命令追到源件"。固定图 + 纯函数条件边 + 两段式审计，已经能把"哪条路径设了终态"
钉死（N-08）。
指针：`backend/app/graph/nodes/__init__.py:36-40`（三个终态出口是独立节点）；
`backend/app/graph/build.py`（图装配与版本号）。

### Q6. 结果级校验为什么不做库级对账？

因为 `presenter` 是**无 IO 的纯函数**，拿不到库级总量；再发一条"总量 SQL"会超出结果级
契约，也增加成本/延迟。所以四条判据是保守的：空结果、全 NULL、单行 KPI 异常、守恒式；
守恒式只在结果自带合计行且 `plan.limit` 为空、`truncated=False` 时校验——没有基准就
**跳过而不是猜**。
指针：`backend/app/present/checks.py:1-6`、`backend/app/graph/nodes/present.py:144`。

### Q7. R14 的月度时序缺口怎么解释？

闸门一的 AST 白名单不认 `to_char(..., 'YYYY-MM')` / `date_trunc('month', ...)` 里的格式串；
W2 的 `results_v1_r1.json` 里 12 条"每月"题同族被拒。演示因此把"2017 年每个月的订单量"
换成"各商品类目的商品件数前五"，折线形态只在单测里覆盖。修它要改 `app/guard/**`，
等于改判据，所以本窗只登记、不改。
指针：`backend/reports/w3_demo/r14_line_gap.json`、`deploy/demo/README.md §2.5`、
`eval/olist/report.md:69`。

### Q8. 72% 算高吗？

还是没到：任务书目标是 85%，v2 是 72.73%，v1 是 41.47%。但口径是严格的：结果等价、
`REL_TOL=1e-6`、方言缺口 12/55 单列；`EX_exec=41/55` 只是 coverage，不是官方数。
**涨的那 31 个点我不算成"模型变强"** —— 它来自三类非模型缺陷的归因修复，逐类可复算
（`report_v2.md` §6 的分桶表）；而且 v2 走百炼、v1 走官方端点，端点差异我写在报告里。
所以我对外只说"72.73%，未达 85%"，并把分母、批次、冻结件、三类修复和剩余 12 条缺口一起报。
指针：`eval/olist/report_v2.md`（固定五行 + v1→v2 对比）、`eval/olist/report.md`（v1 历史）、
本目录 `README.md §4/§7`。

### Q9. 如果重做，会改什么？

三件优先：R14 的字面量白名单/格式串；`AS order` 的生成约束；`delivery_late_rate` 的
×100 与整数除法。然后补 B0 消融，扩数据时间范围（Olist 止于 2018-08），再考虑折线图。
改题/改 bundle 必须升 v2，不回头改 v1 冻结集。
指针：`eval/olist/report.md:66-76`、`deploy/demo/README.md §2.6`、本目录 `README.md §7`。

### Q10. 数据合规怎么做？

Olist 数据集是 **CC BY-NC-SA 4.0**（2026-10-29 实查 Kaggle 元数据：`licenseName`、
`ownerName=Olist`、`creatorName=Francisco Magioli`）；义务是署名、非商业、相同方式共享。
仓库**不分发**原始数据/沙箱库（`*.db` 被 `.gitignore:54` 忽略），只提交 loader、schema、
语义包、说明与归属；`gold60_results` 等派生聚合结果也按同许可证说明。
仓库当前没有代码 LICENSE（由项目所有者决定）；公开前跑 `scan_secrets.py --working-tree`
（本窗 0 命中）和 `git ls-files` 三条检查。
指针：`docs/portfolio/LICENSES.md`、`backend/reports/w4_acceptance/kaggle_olist_metadata.json`。
