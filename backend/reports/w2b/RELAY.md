# W2B RELAY —— 检索层（app/retrieval/**）转述件

- 日期：2026-09-16｜窗口：W2B｜状态：**T0–T6 全部完成**
- 测试：**73 unit/contract passed + 8 integration passed**（真 PG FTS 六用例 + 生产 schema 对齐 + 死端口降级）
- 提交：见 git log（本窗口只 commit 不 push）

---

## 1. 交付物清单（全部在本窗口归属内）

| 文件 | 内容 |
|---|---|
| `app/retrieval/tokenizer.py` | ★jieba 唯一入口：`tokenize()` / `tsvector_source()`（写入侧）/ `tsquery_source()`（查询侧）/ `load_custom_dict()`（词典从 `BundleView.dictionary_terms()` 生成，幂等） |
| `app/retrieval/view.py` | 语义包只读视图 `BundleView`（assets/metrics/aliases/blacklist/joins/value_entries），只读不改语义包 |
| `app/retrieval/value.py` | 值检索：enum 标签/别名/维度值归一化匹配，链 = 精确(1.0)→前缀(0.8)→编辑距离≤1(0.6)，单字 token 禁前缀命中 |
| `app/retrieval/graph.py` | Join 图扩展：`expand_join_graph()`，BFS ≤2 跳、只走 bundle `joins` 认证边、`added_by="join_graph"`，U-28 两跳陷阱有用例覆盖 |
| `app/retrieval/fuse.py` | RRF 融合 k=60：四路权重（config 同源）、`sparse_only` 降级权重重分配（**纯确定性**，同输入同输出有用例）、0.05 截断、资产 Top-5/列 Top-30/指标 Top-5 |
| `app/retrieval/dense.py` | Ollama `/api/embed` 客户端（批量≤32、30s 超时、1 次重试→`EmbeddingUnavailable`）+ `InMemoryVectorStore`（测试替身）+ `PgVectorStore`（SQL 模板对齐 07 §12.2，**UNVERIFIED：列形态待 W2A 冻结后核对**） |
| `app/retrieval/sparse.py` | FTS：`to_tsquery('simple', :terms)` **参数绑定**（禁 plainto_tsquery，N-04）+ `ts_rank_cd(…,32)` + 低分丢弃；表名可注入（集成测试用） |
| `app/retrieval/search.py` | `RetrievalService`：四路编排，实现 `RetrievalPort`，`mode` 如实回填（C-11）；缓存走 `cache/keys.semantic_retrieval()`，**降级轮不写缓存**（防把 sparse_only 结果缓存成 hybrid） |
| `app/retrieval/refine.py` | **P0 占位，未实现**（07 无行为定义，Q5 裁定）；docstring 如实声明，无假实现 |
| `tests/unit/test_retrieval_*.py`（6 个）+ `_retrieval_fixture.py` | 66 个单测，全部离线（N-01，dense 用 fake embedder） |
| `tests/contract/test_retrieval_contract.py` | N-24 静态 half：全仓 `app/**` 扫描，jieba 只准 `retrieval/tokenizer.py` 一处 import；配置权重与 fuse 默认值同源断言 |
| `tests/integration/test_retrieval_fts_pg.py` | 真 PG：N-24 动态 half（写入 `tsvector_source` × 查询同源→必召回）、ts_rank_cd 密度排序、SQL 层租户隔离、`'*'` 哨兵、版本隔离、生产 embed_doc 列对齐、死端口→显式降级 |
| `reports/w2b/recall_report.py` + `recall_report.md` + `recall_results.json` | DoD② 黄金集 recall 报告（见 §4） |

## 2. Q1–Q5 裁定落地记录（2026-09-16 用户采纳）

- **Q1 tokenizer 落位**：按 07 §3.2 落 `retrieval/tokenizer.py`；写入侧（W2A）经组装根注入 `TokenizerPort`，不做 import。矛盾登记待架构分配编号（见 §5）。
- **Q2 CandidateRef 缺口**：端口面按契约返回 `tuple[CandidateRef,…]`；富结果（列 Top-30/指标 Top-5/value_hits/graph 边）经 `RetrievalService.search_full()` 的 `RetrievalResult` 暴露，**W3B/W3C 请从 search_full 取富结果**，端口面缺口待架构裁定。
- **Q3 黄金集**：直接用 `gold_query_seed_v1.json`（119 条），期望集从 gold_sql 解析；脚本落 reports/w2b/，未碰 eval/ 执行器（W6 归属）。
- **Q4 importlinter**：契约文本如下，请 W0 落笔（TODO 1）：
  ```
  [contract] retrieval 禁 LLM（07 §4.8：检索唯一允许 LLM 的是 refine，P0 未实现）
  layers 内 app.retrieval 禁止 import：app.llm、langgraph、langchain、openai、httpx 例外——dense.py 的 Ollama 客户端用 httpx，属 embedding 网关非 LLM 推理，已在该模块 docstring 声明。
  ```
- **Q5 refine**：P0 不实现，`refine.py` 仅占位 + 如实标注。

## 3. 实测发现（重要，含两处已修 bug 与两处待对齐）

1. **`to_tsquery` 空格分隔 = syntax error**（集成测试抓出）。`tokenizer.tsquery_source()` 现产出 `'tok1' & 'tok2'` 显式 AND 形态；07 §6.4 若有「空格串直接传 to_tsquery」表述，请架构窗口顺手更正。同源性不变（两侧同一 `tokenize()`）。
2. **`'*'` 公共哨兵**：W2A 物化的 `app.embed_doc.tenant_id` 实测为 `'*'`（197 行全部如此），非 07 §12.2 所写形态。sparse/dense SQL 已按 `tenant_id IN (:tenant_id, '*')` 适配（公共语义包 doc 无租户数据，不构成跨租户泄露；真租户行仍单租户过滤）。**该哨兵未契约化，待架构/W2A 确认**（§5）。
3. **生产 `app.embed_doc` 197 行 `tsv`/`embedding` 全空**（W2A 建表未填充；宿主 Ollama 无 bge-m3，只有 nomic-embed-text 768d）→ sparse/dense 在线贡献为 0。给 W2A：填充 tsv 时**必须**经 `tokenizer.tsvector_source()`（N-24 静态 half 已有契约测试锁死 jieba 单一 import）。
4. **pgvector 本机已装**（compose 镜像 `pgvector/pgvector:pg16`，`extname` 含 vector）——W1B 时期"未装"的记录已过期。
5. **`app_rw` 无 DDL 权限**：集成测试夹具需要建 schema，走 `RETRIEVAL_TEST_PG_DSN` 环境变量注入（本机用 dev compose 的 `postgres:postgres@127.0.0.1:5432/ecom`）；无 DDL 权限时用例如实 skip，不伪装。
6. **compose 栈在本机已在跑**（commerceql-api-1 目前 **unhealthy**——三探针空实现返回 unhealthy 是预期行为，非故障）。

## 4. DoD 达成状态（08 §3.4）

| DoD | 状态 | 证据 |
|---|---|---|
| ① N-24 分词两侧同源 | ✅ | 静态 half：contract 测试锁 jieba 单一 import；动态 half：集成测试 `test_n24_write_and_query_same_tokenizer_recall`（真 PG 写入×查询同源→必召回） |
| ② 检索黄金集 recall 报告 | ✅（带如实声明） | `reports/w2b/recall_report.md`：asset_recall@5=0.1218 / column_recall@30=0.0508。**这是 value+graph 两路的真实成绩，非四路完整形态**（sparse/dense 因 §3.3 贡献 0，119/119 显式降级）；W2A 填充后必须重跑 |
| ③ 降级路径可触发 | ✅ | 集成测试：死端口→重试耗尽→`sparse_only` + `degraded_reason=embedding_unavailable` + 降级载荷（N-21 不静默）；且降级轮不写缓存 |
| ④ RRF 融合+降级重分配确定性 | ✅ | fuse 单测：同输入同输出断言 + 权重重分配和=1 断言 |

## 5. 待架构窗口分配编号（本窗口未占用任何号）

⚠️ **撞号预警（自查发现）**：W2A 的 `reports/w2a/RELAY.md §5` 已建议占用 **U-54/55/56**；本窗口下列 4 条的编号分配**以架构登记表（07 §4.8）为准**，若 W2A 的建议号被采纳，本窗口条目应从 **U-58 起**顺延——我未落码占用，仅为叙述标签。

| 建议顺延号 | 事项 | 来源 |
|---|---|---|
| 待分配（候选 U-58） | tokenizer 落位矛盾（contracts docstring vs 07 §3.2），本实现按 07 §3.2 + 端口注入消解，终裁归架构；**与 W2A 的 U-54 建议同一件事，可合并裁定** | Q1 |
| 待分配（候选 U-59） | `CandidateRef` 装不下列级/富结果，W3C binding 需要的列 Top-30 走 `RetrievalResult` 旁路，端口面是否升级待裁 | Q2 |
| 待分配（候选 U-60） | `app.embed_doc.tenant_id='*'` 公共哨兵未契约化（07 §12.2 应补） | §3.2 |
| 待分配（候选 U-61） | `to_tsquery` 需显式 `&` 连接的语法事实（07 §6.4 举例若有空格形态应更正） | §3.1 |

## 6. 给下一阶段窗口（W3）的提示词草案

> 你是阶段 3 W3C（binding）窗口负责人。前置：W2B 检索层已交付。你的输入不是裸 `RetrievalPort.candidates`——请用 `app/retrieval/search.py::RetrievalService.search_full()` 返回的 `RetrievalResult`（含列级 Top-30、指标 Top-5、`value_hits`（term/asset/column/values/confidence/source）、`graph_hits`）。注意：① `value_hits.confidence` 是 1.0/0.8/0.6 三档，对应精确/前缀/编辑距离，绑定阈值取舍请引用 07 §6.6 并在 RELAY 登记你的选择；② graph 扩展只认 bundle `joins` 认证边，U-28 两跳陷阱已有用例，不要自行放宽；③ 降级语义（`mode`/`degraded_reason`/`action_taken`）必须透传给 planner，不得吞。红线沿用：不伪造实现、决策点先报告现状。开工方式：先出执行计划等确认。

（W3A/W3B 的接续提示词由编排层按 08 §4 计划分发，本窗口只对自己下游 W3C 给出草案。）

## 7. 未尽事项 / 风险

- `refine.py` 未实现（Q5 裁定，P0 范围外）；3A 网关建立后由后续窗口或本窗口 P1 补。
- `PgVectorStore` SQL 模板列形态 **UNVERIFIED**（W2A embed_doc 填充后跑真向量路径核对）。
- 4 个 `--check`（含 importlinter）未挂 CI —— W0 待办，非本窗口。
- recall 报告低数值的**根因是上游数据未填充**，不是检索逻辑缺陷；但 value 路仅覆盖 22/119 题（值类问句占比所限），四路齐备后预计显著改善——此为推断，待重跑验证。

---

## 8. 收口回执（2026-09-17，响应 W2-INT 转达的 4 条）

| # | 事项 | 处置 |
|---|---|---|
| 1 | `dense.py:273` F821（`Mapping` 未定义） | ✅ 已修：文件头补 `from collections.abc import Mapping`（采纳 W0 提示的 typing 行补法之外的规范形态，`collections.abc` 是 ruff UP035 指向的正解） |
| 2 | ruff 域内收口 | ✅ 17 条全清（W0 清单计 13 条，实测当日为 17——含我上轮 `Mapping` import 触发的 I001/UP035）：11 条 `--fix` 自动 + 6 条手动（B007×2→`for key in params`、B905×2→`zip(strict=True)`、SIM102→合并 elif、RUF059→`_`）；`ruff check` 域内 **All checks passed** |
| 3 | CI 红撤回 | ✅ 知悉，未做任何 skip 分支；本机回归 73 unit/contract + 8 integration 全绿（集成用例不受 ruff 修改影响） |
| 4 | 07 v0.9 §4.8 裁决 | ✅ 知悉并留档：**U-54**=(a) 契约留 contracts、装配根注入 tokenizer 两侧同实例（与我实现一致，无需改码）；**U-59**=(a) **升级 RetrievalPort 端口面**、`search_full()` 旁路被否决、contracts.py 由 W0 落笔 → **本窗口 `search.py::RetrievalResult` 富结果在 W0 落笔后按新端口面收敛，阶段 3 排期项**（收敛动作归我，等 W0 交付后由我或阶段 3 窗口执行，见 §6 提示词草案需同步更新）；U-60/U-61 已契约化，sparse/dense 实现无需改 |

---

## 9. `U-112` 落地回执（2026-09-21，响应 W7 的端到端阻塞报障）

> 输入 = W7 转 W2B 的两条：① `dense.py:279` 对 NULL 分数无条件 `float()` ⇒ `INTERNAL`；
> ② `app.embed_doc` 没灌向量/tsv。**①②不可互替**（架构 §16⑥ 已钉）。本轮回执 **① 已落地**，
> **② 具备开跑条件但未执行**（见 §9.6，等用户放行）。

### 9.1 事实复核（独立复跑，非采信转述）

探针 `_w2b_u112_probe.py`（仓库外，不入 git）：

| # | W7 的读数 | 我实测 | 结论 |
|---|---|---|---|
| 1 | `embed_doc` 197 行，`embedding` NULL=197 | `count(*)=197`，`count(embedding)=0` | 一致 |
| 2 | 分 kind：synonym 105 / column 75 / metric 9 / asset 8 | 完全相同（105/75/9/8） | 一致 |
| 3 | `tsv` 非空 = 0 | `count(tsv)=0` 且 `tsv::text<>''` = 0 | 一致 |
| 4 | `tenant_id='*'` / bundle `2026.09.14.1` | 全表同一组合，197 行 | 一致 |
| 5 | `dense` 路返回 NULL 分数 ⇒ `float()` 炸 | 原样跑那条 SQL：返回 5 行、**score 全为 NULL**；`float(None)` ⇒ `TypeError` | **实测成立** |
| 6 | 加 `AND embedding IS NOT NULL` 会怎样（W7 未测，我补的对照） | **0 行** = 静默空 | ⇒ **光过滤不够**，会从"报错"变成"静默"（架构原话的"静默形态"） |
| 7 | 稀疏侧是否同样炸（W7 未断言） | 稀疏侧 `WHERE tsv @@ query` 已把 NULL 行滤掉 ⇒ **返 0 行、不出 NULL 分数** | ⇒ **sparse 无需改**，与 07 §5.3 行 4"稀疏侧同样空 ⇒ 自然 `refuse(no_data_asset)`"一致 |
| 8 | 环境：pgvector 是否可用 | `vector 0.8.6` **已装**；`embedding` 列类型 = `vector` | ⇒ `dense.py` 模块头旧注"本机 pgvector 也未安装 / schema UNVERIFIED"**已过时，本轮回填** |

### 9.2 改了什么（只动 `app/retrieval/dense.py`，W2B 独占域）

| 位置 | 改动 |
|---|---|
| `PgVectorStore._row_to_hit` | 返回 `VectorHit \| None`；**分数为 NULL 时返回 `None`**。**不把 NULL 当 0 分**（那会让空向量列伪造出"全 0 分候选"，比报错更坏） |
| `PgVectorStore.topk` | 丢弃 `None` 行；**作用域内有行却零条可用向量 ⇒ 抛 `EmbeddingUnavailable`** |
| 模块头 + SQL 模板注释 | 记 U-112 两形态、降级出口、以及"两处刻意什么都不加"的理由（见下） |

**出口不新发明**：`EmbeddingUnavailable` 正是 `search.py:146` 既有的 `except` 分支，
一路走到 §5.3 行 4 的 `degraded(embedding_unavailable, sparse_only)` ⇒ `link` 不变、W4 不变。

**两处刻意不加（改动前请先读，它们各有理由）**：

1. **不加 `AND embedding IS NOT NULL`** —— 加了就再也分不清"作用域内无文档"与"文档在但向量没物化"，
   而这两者的正确处理**相反**：前者如实返空（空 KB 是合法状态），后者必须降级。
   混为一谈会把"没数据"灌进 `retrieval_mode=sparse_only` 的降级率，而 07 把它当**软依赖健康度**信号用。
2. **不写显式 `NULLS LAST`** —— SQL 的 `ORDER BY embedding <=> v` 是 ASC，PG 的 ASC 默认 `NULLS LAST`，
   显式写与默认同义（却多一处与 pgvector HNSW 有序扫描计划交互的语法）。改为**用断言锁**：
   集成用例 `test_dense_null_rows_never_crowd_out_valid_vectors` 故意让 NULL 行数 > `limit`，
   谁把排序方向改成 `DESC` 谁就把它变红。

### 9.3 判据覆盖"两形态"（架构 §16⑥ 的硬要求）

| 形态 | 判据 | 落点 |
|---|---|---|
| **(i) 抛异常**（Ollama 不通） | 既有 `test_embedding_down_yields_explicit_degradation`（未改） | unit/search |
| **(ii) NULL 分数 / 空向量列** | 新增 4 条单测：全 NULL ⇒ 抛；混合 ⇒ 只回有效且不降级；0 行 ⇒ 不降级；**`score=0.0` 不得被当 falsy 丢掉** | unit/dense |
| | 新增 1 条服务级：真 `RetrievalService` + 真 `PgVectorStore`，同夹具同作用域，断言 `mode=sparse_only` / `degraded_reason=embedding_unavailable` / `action_taken=sparse_only` / 候选非空 | unit/search |
| | 新增 3 条集成（**真 pgvector 0.8.6**，临时 schema + 真 `vector(4)` 列；无 pgvector 时具名 skip）：NULL 行不挤掉有效向量 / 全 NULL ⇒ `EmbeddingUnavailable` / 0 行 ⇒ 返空 | integration |

**正向对照（修复前必须红）** —— 因本会话 git 不可用（见 §9.7），改用**进程内 monkeypatch**
把 `_row_to_hit` 换回旧实现，夹具/向量/作用域完全相同（`_w2b_u112_control.py`，仓库外）：

```
A 组（修复前） topk 抛出 TypeError: float() argument must be a string or a real number, not 'NoneType'
               是 EmbeddingUnavailable 吗 : False   ⇒ search.py 的 except 接不住
               服务层：抛出 TypeError —— 连 degraded 都没机会发（这就是 INTERNAL 的形状）
B 组（修复后） topk 抛出 EmbeddingUnavailable（…embedding 全为 NULL ⇒ 向量列未物化…）
               服务层：mode=sparse_only / degraded=True / reason=embedding_unavailable ✅
```

⇒ W7 报的"`TypeError` ⇒ `link` 抛 ⇒ runner 兜底 `error(INTERNAL)`"**按要求复现**，且修复后同一输入
走的是降级出口。**不是`测试写法`造成的假象**。

### 9.4 门禁读数（2026-09-21，均为本机实跑）

| 门 | 命令 | 读数 |
|---|---|---|
| lint | `ruff check app/retrieval tests/...` | **All checks passed** |
| 类型 | `mypy app` | **Success: no issues found in 146 source files** |
| 单测+契约 | `pytest tests/unit tests/contract` | **1772 passed**（含新增 5 条） |
| 集成（本域） | `pytest tests/integration/test_retrieval_fts_pg.py` | **11 passed**（8 → 11） |
| 分层契约 | `lint-imports`（**控制台脚本**，非 `python -m importlinter.cli`） | **4 kept, 0 broken** |

⚠️ `ruff format --check` 会报 10 个文件"would be reformatted"，**其中 5 个我从没碰过**
（`fuse/graph/value/view/sparse`）⇒ 本项目**不以 `ruff format` 为门**（仓库风格是有意不同于
formatter 的：对齐式行尾注释、模块 docstring 后空两行）。**故未 reformat，避免制造无关大 diff**。

### 9.5 顺带修掉一个夹具 bug（此前"看着没事"）

`tests/integration/test_retrieval_fts_pg.py::make_fetcher` 原来做
`sql.replace(f":{key}", f"%({key})s")` —— 这会把 `(:vector)::vector` 里 `::vector` 的
**后半截也吃掉**，产出 `(%(vector)s):%(vector)s` ⇒ `syntax error at or near ":"`。
旧写法之所以没暴露：**本文件此前只有 sparse 用例，而 sparse 的 SQL 里没有任何 `::` 转换**。
本轮加 dense 集成用例时立刻踩到 ⇒ 改成带否定后顾的正则 `(?<![:\w]):name\b`（只换 `params` 里真有的键）。
**这是一条"用例覆盖面盲区"的实证**，不是笔误。

### 9.6 issue②（灌数据）状态：**具备条件，未执行**

已独立核实的前置（`_w2b_u112_materialize.py --dry-run`）：

- Ollama 可达 ✅、`bge-m3:latest` **在册** ✅；语义包加载 ✅、**将写入恰好 197 篇**（与现存行数相符）；
- 写入前计数 197 / embedding 0 / tsv 0（与 §9.1 一致）；
- `materialize()` 对**同一 `bundle_version` 幂等**（`DELETE` 相关行 → `INSERT`，**单事务**；
  佐证 `materialize.py:296-299`）⇒ 可重跑、失败整体回滚。

**未执行的理由（不是能力问题，是边界问题）**：

1. `app/semantics/**` 属 **W2A**，本窗口纪律是"改别人的文件只提需求、不落笔"；
   本脚本只**调用** `materialize()`，不改它一行，但**真跑 = 写共享 dev 库**。
2. 目标是**全窗口共用**的 `ecom` 库（`app_rw`）；本机最近一次同类事故正是 `U-113`（另一窗口清掉了
   `cost_ledger` 的对账基线）。**在拿到明确放行前不写。**
3. 本会话 **git 不可用**（§9.7）⇒ 我**无法在写库前留一个可回退的提交快照**，这削弱了风险对冲。

**默认跑法 = 数据 only**：`--with-policy=False`（只写数据、**不碰 GRANT/POLICY**，权限面爆炸半径为零）；
需要完整 §6.2 六步发布再加 `--with-policy`（ADR-10 纯函数，重派生同一语句集）。**等一句放行即可开跑。**

### 9.7 🔴 环境阻塞：本会话 git 不可用（**请其他窗口注意**）

- **现象**：`git stash push` 在 harness 上被 SIGTERM 中断；此后**同一目录内**所有 git 命令均报
  `fatal: not a git repository`（`-C` / `--git-dir=` / `GIT_DIR` 三种显式写法皆同）。
- **实测到的磁盘状态**（用 Python 直读，绕开 bash 缺 coreutils 的问题）：
  `.git/` 有 11 项 —— `COMMIT_EDITMSG / FETCH_HEAD / HEAD / ORIG_HEAD / config / description / hooks / index / info / logs / objects`，
  **`packed-refs` 与 `refs/` 都不在**；而 **`.git/logs/refs/heads/main` 与 `.git/logs/refs/remotes/` 确实存在**。
- **两个已确认的推论**：
  1. `refs/` 缺失正是 git 判定"非仓库"的原因（仓库识别要求 `HEAD` + `objects/` + `refs/` 三者齐备）。
  2. **`objects/`（含 pack）与 `logs/`（reflog）完好** ⇒ 历史与服务端无关地可恢复。
     最后已知 HEAD 就在 reflog 末行 = **`5d47c0e41f6521d35d14500d33c16d7c20a06a35`**（W6 的 commit）。
- **⚠️ 我不确定的是**"`refs/` 是被真的删了，还是**只被沙箱遮蔽**"：本仓库早有记录
  "沙箱写不进 `.git/refs/remotes/**`"，而**没有任何 git 操作会删 `refs/` 却留着 `logs/refs/`**，
  故遮蔽的可能性存在。**我没有继续试探**（再写 `.git` 可能把状况搞得更糟）。
- **恢复方式（待用户在有正常 shell 的机器上确认后再动）**：若 `refs/` 真丢，
  `mkdir .git/refs/heads` 后把上述 SHA 写回 `.git/refs/heads/main`（或 `git update-ref`）即可；
  **不要**在恢复前跑任何 `stash`/`gc`/`prune`。
- **后果**：本轮回执**未提交任何 commit**（不是"忘了"，是 git 不可用）；已落盘的改动都在工作区，
  内容完好（用 Read/Grep 复核过）。

### 9.8 未做 / 留给下一轮

- **issue② 真跑**（等放行）；跑完 W7 才可能拿到 ≥1 条 `outcome=ok`（他的放行判据）。
- **`U-59`=(a) 端口面收敛**（`RetrievalResult` 富结果并进 `RetrievalPort`）仍等 W0 落 `contracts.py`。
- **`U-111` 的启动断言**在 W1B / `ASSERTION_NAMES` 4→5 的耦合在 W7 —— 本窗口不越界，仅登记。
- **本轮回执的代码未提交**（§9.7 所限）。**→ 已于 §10.1 补交。**

---

## 10. `U-112` issue② 执行回执（2026-09-21）+ 🔴 新缺陷：集成夹具会清空物化向量

### 10.1 总控要求①：提交（已完成）

- commit **`1255065`** = `fix(w2b)+test(w2b): U-112 落地 —— 向量列未物化时降级而非 INTERNAL`；
  5 文件 **439 insertions / 10 deletions**；`git log` = `1255065` ← `42c4250`。
- **未推**：提交前 `origin/main == 42c4250`（= 提交前的 HEAD）⇒ 本地现领先 1 个 commit。
  按纪律"上传严格听指令"，**我不自行推**；总控说一句即可。
- 门禁复跑（提交前，皆为实跑）：`ruff check .` **All checks passed**；`lint-imports`
  **4 kept / 0 broken**；`tests/unit + tests/contract + tests/graph_snapshot` = **1785 passed**；
  `tests/integration` = **100 passed**（带 `RETRIEVAL_TEST_PG_DSN`）。

### 10.2 总控要求②：物化（已跑，三个痕齐）

| 时点 | 行数 | embedding 非空 | tsv 非空 |
|---|---|---|---|
| **跑前**（原样 SQL，独立于 runner 自报） | 197 | **0** | **0** |
| **跑后** | 197 | **197** | **197** |

完整命令（逐字）：

```bash
export PATH="/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:/c/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.2.0/cmd:$PATH"
cd "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent"
"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/.venv/Scripts/python.exe" _w2b_u112_materialize.py
```

- runner 位置 = **工作区根**（`E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\`，**在 git 之外**）。
- 实际调用 = `materialize(loaded, dsn=<deploy/.env 的 DATABASE_URL 换 host 为 127.0.0.1>,
  tokenizer=app.retrieval.tokenizer.tokenize, embedder=OllamaEmbedder(bge-m3, dim=1024) 的同步适配器,
  with_policy=False)`。
- 报告：`doc_count=197 / embedding_status=embedded / tsv_status=tokenized /
  grant_policy_executed=False` + 1 条 warning（GRANT/POLICY 未执行，`with_policy=False`，**故意**）。
- 前置全绿：Docker 在、`commerceql-pg-1` healthy、Ollama 可达、`bge-m3:latest` 在册。

### 10.3 计数 ≠ 可读：另做了一次真实读路径自证

`_w2b_u112_verify_read.py`（工作区根）用**生产实现**真打两条路，不是看计数：

- **稠密** `PgVectorStore.topk`（真调 Ollama 生成查询向量，dim=1024）：命中 5 条 ——
  `0.707283 [synonym] 销售额`、`0.618468 [column] product.on_sale`、`0.592584 [metric] sell_through_rate`、
  `0.590137 [column] order_paid.channel`、`0.587569 [synonym] 成交额`；分数全非 NULL、降序已断言。
- **稀疏** `SparseSearch.search`（归一化标志 32 / `score_min` 0.05，取 `deps.py:468-469` 的生产值）：
  命中 1 条 —— `0.090909 [synonym] 销售额`。

### 10.4 🔴 新缺陷：`tests/integration/test_semantic_materialization.py` 会清空共享库的物化向量

**这条直击判据④，而且会反复发生。**

- **干净的正向对照**：物化后 `(197, 197, 197)` → 只跑该文件（**7 passed**）→ `(197, 0, 0)`。
  测试全绿，**静默毁数据**。
- **根因（读原文，非推断）**：`test_semantic_materialization.py:114`
  `materialize(loaded, dsn=_RW, with_policy=False)`；`_RW` 默认 =
  `postgresql://app_rw:app_rw_pwd@localhost:5432/ecom` —— **就是共享 dev 库**；
  且**不传 `tokenizer=` / `embedder=`** ⇒ `_insert_rows`（`materialize.py:296-299`）对同一
  `bundle_version` **先 DELETE 9 张表再 INSERT** ⇒ `embed_doc` 197 行回来时 embedding/tsv 全 NULL。
- **不止一处**：该文件共 5 处会重写（L114 / L131-132 / L149 / L168 / L181 / L196）。
  反过来 `test_retrieval_fts_pg.py` **是安全的**（走临时 schema）：实测跑完仍是 `(197, 197, 197)`。
- **与 `U-113` 的关系**：U-113 的首诊（"夹具无'目标库必须隔离'门禁"）**在此得到机制实证**，
  且这是**第二张受害者表**。⇒ **不是新根因，是新证据 + 新受害者（而这个直击 G-6）。**
- **影响口径**：任何窗口本地跑一次集成测试，物化向量归零 ⇒ 判据④ 的读数**依赖跑测顺序**，
  "我灌了 / 你跑完就没了"会变成互指。**修好之前，判据④ 的读数不可信。**
- **我方边界**：该文件属语义域（W2A），**我不落笔**。请 架构/总控 归号并派单 ——
  `07:1050` 记 **下一个可用 = `U-114`**；**我不自行占号**（避免与并发窗口撞号），
  建议归号后由 架构 回填 §4.8。
- **立刻可用的三个临时措施（都不必改别人的文件）**：
  1. 判据④ 每次采样前先 `_w2b_u112_materialize.py --verify-only` 复核计数，为 0 就先重物化；
  2. 要跑集成测试的窗口把 `COMMERCEQL_TEST_RW_DSN` 指向一次性库；
  3. **不要在"物化 → 预检"之间跑 `tests/integration`**。

### 10.5 顺手回答总控附带的问题：`embedding_status="pending_embedder"` 有读端消费者吗

**没有 —— 生产侧零读者，`U-111` 的判断成立。** 全仓 grep（`backend/**/*.py`）只有三类命中：

1. 生产代码里的**定义处**（`materialize.py:262 / 450 / 500`），以及一处**承认零读者的注释**
   （`obs/metrics.py:163` 原文："materialize 的 `embedding_status` 生产侧零读者"）；
2. 探针脚本 `reports/w2-int/e2e_stage2_check.py:110`（**不属生产链路**）；
3. 测试 `tests/integration/test_semantic_materialization.py:124-125`（断言 pending 值）。

另：`app/retrieval/dense.py:351` 的命中只是本次新增的**异常消息文本**，不是读者。
**并且**：`MaterializeReport` 是 `frozen dataclass`，`embedding_status` **不落库**
（落库的 `app.semantic_bundle.status='staged'` 是版本生命周期状态，是另一回事）
⇒ 该字段目前**连"写 — 读"闭环都不存在，只有壳**。

### 10.6 待总控裁（新增两条）

- **runner 要不要收进仓库**：`_w2b_u112_materialize.py` 与 probe / control / verify 四个脚本
  现在**只活在工作区根、不在 git 内** = 与 U-112 五文件**同款孤本风险**，而 W7 复现判据④ 正靠它。
  建议收进 `deploy/`（如 `deploy/materialize_bundle.py`）。**归谁落笔请裁。**
- **推不推**：见 §10.1 —— 本提交尚未上远端。

---

## 11. 认领 W7 的四问 / 两条不一致（2026-09-21，W7 → 架构 / W4 / W2B）

### 11.1 "出路表 vs stage 帧" —— **没有偏移，是拿两把尺子量同一件事**

`build.py:610-622` 那张表是**超时出路表**：节点撞 `NODE_TIMEOUT_S` 时的兜底动作
（逐节点复用 §5.3「失败转移」列）。它把 `no_data_asset` 记在
normalize/plan/gen_sql/repair、intent、link、bind 名下，说的是
**"这些节点超时之后怎么出去"**，**不是**"运行期这次终止是谁造成的"。

⇒ 与 stage 帧的读数**不在同一论域**，不构成"出路表与实现有偏移"。
⇒ 反过来说更该警惕：该表 9 行里**有 4 行都产出 `refuse(no_data_asset)`**
⇒ **"看到 no_data_asset"这件事本身不携带任何归因信息**。

### 11.2 后半句猜对了：**确实是"那个节点不发 stage 帧"**，且可精确到节点

- `Stage` 只有 6 值（`core/enums.py:80-83`：intent / schema_linking / plan_ready /
  sql_ready / gate_passed / executing）；**发帧的节点只有 5 个**
  （`events.py:174 / 179 / 188 / 206 / 208`：INTENT / LINK / PLAN / GEN_SQL / GATE3_COST）。
- 图序（`build.py:767-800`）：
  `START → trusted_context → normalize → INTENT → LINK → PLAN → BIND → GEN_SQL
   → gate1_ast → gate2_policy → gate3_cost → execute → …`
- ⇒ **`BIND` 正好落在 `plan_ready`（PLAN 发）与 `sql_ready`（GEN_SQL 发）之间，而它一个帧都不发。**
  `trusted_context` / `normalize` 同样无帧。
- ⇒ W7 的"`plan_ready` 与 `execute` 之间有一道从未被通过的关卡"，在**指标面上结构性不可归因**。
  这正是 **`U-115`**（`metrics.py:72` 已登记节点级钩子缺位）。**别在 W2B 这里找那个钩子，它归 U-115。**

### 11.3 静默窗口里有**两个**候选人，而当前读数区分不了

| 候选 | 触发条件 | 出口与指纹 |
|---|---|---|
| **PLAN 自己拒** | 模型返回非空 `blocking_issues`（`plan.py:90-107`） | 设终态 `refuse(no_data_asset)`；**同时**写 `intent_detail.reason_code="plan_blocked"` + `blocking_issues[...]`；`plan` 不写回 `None`；**刻意不发 degraded**（模块 docstring：产品结论 ≠ 故障） |
| **BIND 拒** | `binding_status ∈ {unresolved, 未登记取值}`（`edges.py:264-269`） | → `REFUSE_OUT`；`refuse_out.py:14 / 17` **兜底**取 `no_data_asset`（无 `intent_detail` 可依） |

两者的指标签名**逐字相同**：`plan_ready` 有帧、`no_data_asset` +1、`sql_ready` 无帧。
⇒ **W7 现在的读数与两个候选人同时相容。**

### 11.4 用 W7 手里已有的数据就能判（**零新增调用**）

1. **最强指纹**：该 run 的 `intent_detail`（审计 / 终态里）。出现
   `reason_code="plan_blocked"` 或非空 `blocking_issues` ⇒ **PLAN 路径**
   —— 那是模型的**产品结论**（"这问题要的数据不在语义层"），**不是缺陷**；
   没有该字段 ⇒ **BIND 路径**，那才是要查的缺陷。
2. **次强**：`stage=plan_ready` 帧的 `plan_summary`。非空 ⇒ PLAN 产出了计划 ⇒ 拒绝发生在 BIND；
   `null` ⇒ PLAN 自己拒的。
3. **已被 W7 自己的数据否掉的一条**：`schema_linking=7 == plan_ready=7` ⇒ **没有任何 run 从 LINK 出口终止**
   ⇒ 那 3 条 `clarify` 只能来自 `route_after_intent`，**不是** `route_after_link` 的歧义。
   （这同时**作废**了我此前"终止可能发生在 link"的暗示 —— 与 W7 作废其两个成因同理。）

### 11.5 先质疑前提：**"没通过"不等于"有 bug"**

若指纹是 `plan_blocked`，那 G-6 卡住的**不是编排缺陷，而是语义层覆盖**：当前 bundle 只有 8 个 asset，
模型在这些题上判"数据不在语义层"是**正确行为**。
⇒ 那么"让 `stage=executing` 从 0 变 ≥1"这个目标本身就是错的 —— 正确动作是**换能答的题**或**补语义层**，
而不是让 BIND 放行。**把"没通过"默认读成"有 bug"，会推着所有人去拆一道不该拆的门。**
⇒ 反之若指纹指向 BIND，才是真缺陷；第一手证据 = `binding_status` 具体取值
与 `link` 给出的 `candidates` 在哪一格对不上（那一段才是 W2B/W4 的活）。

### 11.6 归档：**请保留**，但其中有一个真问题我修了

- **逐字节复核**：4 个文件 sha256 与工作区根**全部一致** ✅（W7 确为逐字节复制，未改一字符）。
- **但归档原先不自足**：`_w2b_u112_verify_read.py` 用 `sys.path.insert(0, ROOT)` 去**工作区根**
  取 `_w2b_u112_materialize`。实测从 `deploy/` 跑时，`import` 到的**仍是工作区根那份**
  （`'w2b_materialize' in __file__ == False`）⇒ 原件一旦被删或换机，归档就断。
- **已修**（2 行 + 注释）：把脚本**自身目录最后**插入 `sys.path`（后插者优先）⇒ 同级优先、两处均可独立跑。
  实测归档副本现在 `import` 到同级（`True`），两条读路径照常通过；
  **工作区根版与 `deploy/` 版 sha256 仍一致**（`7b25e89d5dd3ca2f`）。
- **顺带替 W7 核了两条 CI 风险（都干净）**：
  ① DoD④ —— 这 6 个文件对「DSN 形态」（`postgresql+psycopg://` + 用户名 + `:` + 口令 + `@` + 主机）
  与 API key 形态（`sk-` 起头）**零命中**，即 `ci.yml:120` 警告的那类。
  ⚠️ **本行原文整段复述了门禁规则的模式串 ⇒ 自己成了违规**（被 DoD④ 抓下，见 §12.9）；
  正确写法 = **只描述形态、不复述字面量**（这条纪律 W1B/W2A 早已立，我漏了）；
  ② ruff —— CI 的 `ruff check .` 在 `backend/` 下跑，**不扫 `deploy/`** ⇒ 归档不会把 CI 弄红。
- **权威口径**接受 W7 README 的写法。**唯一附加要求**：以后我若再改原件，我会**同时**刷新
  `deploy/` 副本并报新 sha256 —— 否则"以 W2B 为准"这句没有消费者。

---

## 12. G-6 根因回执（2026-09-21，响应 W7 §二十四）+ 回一处待核项（09-21 第七轮）

### 12.1 结论一句话

W7 那句"**题集与语义资产不对齐**被证伪"是对的，但他们由此推出的**反面**（"语义层覆盖没问题，所以先别动语义层"）不成立。
真正卡死链路的是一件更上游的事：**指标口径目录从来没有进过 plan 的出站 prompt**。`gmv` 在语义包里定义得好好的，但**模型看不到它**。

### 12.2 判定链（三段，全部可复现，**零 LLM 成本**）

| # | 事实 | 出处（逐字） |
| --- | --- | --- |
| 1 | **prompt 向模型承诺"指标口径在这里"** | `app/llm/prompts/plan_v1.txt:6` "可用的语义资产与指标口径（**只能使用这里出现过的资产**）：" + L27 硬性规则 2 "口径必须**显式引用**语义包中的指标名" |
| 2 | **`semantic_summary` 是资产信息到模型的唯一通道** | `app/planner/engine.py:711` "计划的资产信息**只经 `semantic_summary`** 到达模型"；`plan_v1.txt:8` 是唯一 `$semantic_summary` 插值点 |
| 3 | **该通道里没有指标段，且明说没有** | 探针实跑（见 12.7）：3293 字摘要，段落只有 `## 认证资产` / `## 维度与层级` / `## 唯一字段绑定`；**无 `## 指标`**；9 个 metric 名只命中 `order_cnt`、`uv`（且是 `traffic_daily` 的**列名**，不是指标条目）；缺口声明原文 "（本次未提供**指标口径目录**与**同义词表**：语义层运行时尚未暴露枚举器，已登记需求。因此：指标名请只使用上文资产段落里出现过的名字，**不要自行发明口径**，找不到就把问题写进 `blocking_issues`。）" |

**合成**：prompt 要指标名 ⇒ 唯一通道里没有指标名、还明确指示"**找不到就写进 `blocking_issues`**"
⇒ **模型把 `GMV` 写进 `blocking_issues`，是在正确遵循指令**，不是语义层覆盖不足，也不是题集错。

**因果闭环（对齐 W7 的帧序列）**：`blocking_issues` 非空 → `nodes/plan.py:89-106` 阻塞路径 → `plan_summary=null`（W7 的次强指纹，**成立**）
→ `refuse(no_data_asset)` → 到不了 BIND/GEN_SQL ⇒ `sql_ready=0` / `gate_passed=0` / `executing=0`
**是结构性为 0，不是偶发、不是超时、不是 embedding 那茬**。这同时解释了 §二十四 ③ 的六档全表。

### 12.3 根因定位（**唯一一处，在 W2A 目录内**）

`SemanticBundleRuntime` **缺 `metrics()` 枚举器**（探针逐项探测 10 个端口名：`active_version`/`asset_allowlist`/`policy`/`resolve_alias`/`dimensions`/`field_bindings`/`metric`/`time_semantics` ✅，`metrics` / `aliases` **❌ 不存在**）
⇒ `build_semantic_summary()` 没有可枚举来源 ⇒ 渲染不出指标段 ⇒ 只剩那条缺口声明。

⚠️ **这不是"没人知道"**：生产代码自己登记了（`payloads.py:204 summary_gaps()`，且 `_METRIC_GAP_NOTE` 注释写明"已登记需求"）。
**没人量过的是它的后果**——后果就是 G-6 这一格。**属 W2A**（语义层运行时），不是 W2B 的绑定域、也不是 W4 的图。

### 12.4 回 W7 §③ 的待核项：**"减法无效"我接受，但原因不是重入 intent**

W7 写"探针 A 在一条 run 内发了两次 `stage=intent` ⇒ **有 run 重入了 `intent`**"。**这条诊断错了**，真因是 **§16.2 首字节占位帧**：

- `api/runner.py:374-382`：占位条件 = `not self._placeholder_sent` ∧ `not drive.done()` ∧ **`not recorder.has_stage_emission()`** ∧ `now - started >= 1.6`；
  占位帧的 stage **写死** `Stage.INTENT`（`events.py:491-497`，`Emission(SseEvent.STAGE, {"elapsed_ms": …}, stage=Stage.INTENT)`）——**与 intent 节点是否执行无关**。
- 对上读数：探针 A 首帧 `intent 1609ms` = 占位（真实 intent 在 12628ms，远超 1.6s）；探针 B 真实 intent 1237ms < 1.6s ⇒ **只一帧、无占位**。
- ⇒ `intent=11` = **10 条 run 的真实帧 + 1 帧占位**（探针 A 那条）。**没有任何 run 重入 intent**。
  （唯一的回边 `route_after_normalize → INTENT`（`edges.py:193`）每 run 只走一次，不构成重入。）

**"相等有效"我给证明**（这是我自己的推理前提，不能只当公理用）：

1. `LINK` 的**唯一入边** = `route_after_intent`（`edges.py:196-211`）的返回值；`PLAN` 的**唯一入边** = `route_after_link`（`edges.py:214-230`）的返回值。全 `app/graph/` 内**无第二处**返回 `LINK` / `PLAN`。
2. `repair` 环**不进这两个节点**：`route_after_repair → GATE1_AST`（`edges.py:378`）。
3. 两者的 stage 帧**无条件发射**（`events.py:179-195`：只按节点名派生，不看载荷、不看 `update` 内容）。
⇒ 每 run 对 `LINK` / `PLAN` **至多执行一次、执行即发一帧** ⇒ 恒有 `schema_linking ≥ plan_ready`，**取等 ⟺ 无任何 run 在 LINK 出口终止**。
⇒ `7 == 7` ⇒ **"没有 run 从 LINK 出口终止"成立**。（旁证：帧里 `candidates_count=5` 非空，本也走不到 `route_after_link` 的 `refuse_out` 分支。）

⚠️ 但这**不救 `intent` 那一档**：intent 有**两个发射点**（真实帧 + 占位帧）⇒ `intent − schema_linking = 1` **不能**读成"1 条 run 终止在 intent"。**减法无效、相等有效**——W7 引用得对，我把它从"经验规则"升级为"带证明的规则"。

### 12.5 `U-115` 已落地（我复核了，但它**只能看、不能治**）

- `9c65a42`（W4）在 `api/runner.py:530-543` 的 `REFUSE_OUT` 分支上：读 `trace.state["intent_detail"]`，`reason_code == "plan_blocked"` 且有 `blocking_issues` 时挂到 refuse 帧；契约测试 `test_c_plan_blocked_refuses_with_blocking_issues_in_frame` 断言落在**帧载荷**上（正是 W7 要的"外部证据"）。
- ⚠️ **拿到理由 ≠ 修好链路**：带出来的内容会是"`GMV` 找不到口径"一类话术 ⇒ 它证明的是 12.2，**不改变** 12.3 那一处。断言口子仍在 `executing`。
- ❌ 我**没有**做端到端验证（那要一次真实调用，口子在 W7）；我只做了代码 + 契约测试复核。

### 12.6 处置建议（按 ROI 排，我**不越界动手**）

1. **W2A 补 `metrics()`（顺手 `aliases()`）枚举器 ⇒ `build_semantic_summary` 加 `## 指标口径` 段。** 这是**唯一**能让 `executing` 从 0 变 ≥1 的改动。改动面小（运行时一个方法 + payloads 一段 + 两处测试）。
2. **在此之前，"换题集"和"补语义层资产"都是白做**：换任何题只要问指标，同样被拒（8/9 个指标名都不在摘要里）。
3. **更早的断言**：`stage_duration_seconds_count{stage="sql_ready"}` 应从 0 变 ≥1 —— 它在 `executing` **之前**，能提前一格暴露"指标段有没有真的生效"。

### 12.7 本轮实测 / 未实测

- ✅ 实测（**零 LLM**）：`build_semantic_summary()` 真跑并留存 3293 字原文；10 项端口枚举器逐项探测；9 个指标名逐字比对；`plan_v1.txt` 全文；`events.py` / `edges.py` / `runner.py` 三处发射点与入边逐行读。
- ✅ 花费：**0 次 LLM 调用 / ¥0.000000**（探针只读 YAML 与纯函数，不碰服务、不碰 DB）。
- ✅ 归档：探针 `_w2b_plan_prompt_probe.py` 已逐字节复制进 `backend/reports/w2b/`（sha256 见 12.8）。
- ❌ 未跑：活体 SSE / 指标（我不碰服务）；`tests/integration`（会把 `embed_doc` 清回 NULL，见 §10）。
- ❌ 未改代码：12.3 那一处在 W2A 目录内，本窗口只交证据。

### 12.8 复现命令（任何窗口可零成本重跑）

```
cd E:\01_实训\项目\基于Text2SQL的电商数据分析Agent
CommerceQL\.venv\Scripts\python.exe _w2b_plan_prompt_probe.py
```

期望判据输出（本次实测逐字）：

```
gap 声明进入了摘要（'指标口径目录' 出现） : True
9 个指标名出现在摘要里的                 : ['order_cnt', 'uv']
摘要里有 '## 指标' 段落吗                 : False
```

### 12.9 🔴 门禁自伤：我复述了要防的规则，于是我自己成了违规（同日尾轮）

**由 W7 报障**（他的原话："你在写'DoD④ 零命中'时把规则的模式串原样引用了 ⇒ 门禁扫全仓，引用即命中"）。**实测核实：他报得准确，无一处误报。**

- **门禁是什么**：`backend/tests/unit/test_migration_dsn_hygiene.py::test_repo_wide_replay_of_the_dod4_rule_is_green` —— 从 `_REPO_ROOT` **全仓 `rglob`**（只跳过 `.venv`/`node_modules`/`__pycache__` 等构建产物目录，**含未跟踪文件**），逐行重放 `.gitleaks.toml` 的 `commerceql-dsn-with-password` 规则。
- **我的违规**：`§11.6` 那句"这 6 个文件对〈DSN 字面量〉与 `sk-` 形态**零命中**"——为了**证明**零命中，**把规则要抓的模式串整段抄进了文档**。
- **修复前实测（正向对照，必红）**：
  ```
  backend/reports/w2b/RELAY.md:391                        〈DSN 字面量〉
  backend/reports/w2b/RELAY.md.bak-20260921-1631:391      〈DSN 字面量〉
  ```
- **修复后实测**：该文件 **8 passed**（全绿），全仓重放零未放行命中。
- **同时删掉 `RELAY.md.bak-20260921-1631`**：门禁**扫未跟踪文件** ⇒ 我按"写盘前留 `.bak`"纪律留下的备份，反而成了第二个命中项。内容已由 `a7e31b6` 的 git 历史完整保留 ⇒ **删它零损失**（不是"为了绿灯牺牲审计痕迹"）。
- **正确写法 = W1B/W2A 早已立的项目惯例，本窗口漏了**：描述形态一律写
  「`postgresql+psycopg://` + 用户名 + `:` + 口令 + `@` + 主机」，**绝不复述字面量**。

**两条可复用推论**：

1. **"证明某形态零命中"这个动作本身会制造命中** ⇒ 写门禁报告要用**分段形态描述**，不能用"引用规则原文"。
2. **该门禁的作用域 = 工作区 ⊃ git 追踪** ⇒ **`*.bak-*` 留在仓内会被扫到**（W6 那批没命中，只是因为它们的内容里恰好没有该形态，不是因为被豁免）。⇒ 备份要么放仓外（本项目的工作区根就是"仓外"），要么用完即删。

---

## 13. `app.embed_doc` 重灌回执（2026-09-22，响应 W7 的恢复请求）

**触发**：W7 只读取证 —— 共享库 `app.embed_doc` 于 09-22 从 `197|197|197`（09-21 21:05 读数）掉回 `197|0|0`；PG 今晨 09:19:52 重启后该表 `ins=1970 / del=1970 / upd=0`（= **10 次全表重载、末次留 NULL**）。机制 = `tests/integration/test_migration_0003_views.py` 的 `materialize(loaded, dsn=_RW_SP, with_policy=True)`（L201/L228）**不带 `embedder`/`tokenizer`** ⇒ 按 `materialize.py:20-21` 契约写 NULL。**我复核了该文件的 DSN 默认值（L44-56）**：`_SUPER`（postgres 超管）与 `_RW`（app_rw）两套默认值**都直指共享库 `ecom`** —— 与 `test_semantic_materialization.py` 同款（U-114 的处置范围）。

### 13.1 三痕齐全（跑前 / 命令 / 跑后）

- **跑前**（`--dry-run` 独立取证，非转述）：`197 | 0 | 0`（未就绪）；Ollama 可达 ✅、`bge-m3:latest` 在册 ✅、语义包将写 197 篇。
- **命令**：`CommerceQL\.venv\Scripts\python.exe _w2b_u112_materialize.py`（工作区根 = `deploy/loadtest/w2b_materialize/` 归档件的原件；`with_policy=False`，只写数据、不碰 GRANT/POLICY）。
- **跑后**（`MaterializeReport`）：`version=2026.09.14.1 | doc_count=197 | embedding_status=embedded | tsv_status=tokenized | grant_policy_executed=False`（warning 一条：§6.2 步骤②未执行 —— 与 09-21 首灌一致）。

### 13.2 恢复判据（用 W7 的**原句 SQL** 复核，不换口径）

- `select count(*), count(embedding), count(tsv) from app.embed_doc`（**不过滤版本**）= **`(197, 197, 197)`** ✅
- 按 `bundle_version`：**唯一版本** `2026.09.14.1` 197/197/197，无其他版本残留行；`tenant_id` 全部 `'*'`。
- `kind` 分布 = synonym 105 + column 75 + metric 9 + asset 8 = 197，**与 09-21 首灌逐字一致**。

### 13.3 超出判据的自证（计数 ≠ 可读）+ 权限面复核（新增）

- **生产读路径真打**（`_w2b_u112_verify_read.py`，与 09-21 同一份脚本）：稠密（真 Ollama 查询向量 → `PgVectorStore.topk`）5 命中，top-1 = **`0.707283 [synonym] 销售额`** —— **与 09-21 首灌同值** ⇒ 重灌后检索面稳定；稀疏（`SparseSearch.search`）1 命中 `0.090909 [synonym] 销售额`。
- **权限面复核（对 W7 机制读数的延伸）**：那 10 次重载走的是 `with_policy=True` ⇒ **GRANT/POLICY 被重放了 10 次**。我按 §6.2 的口径复核：`assert_grant_policy_consistency` = **True / mismatches=0**，`app` schema 现存 POLICY 6 条 ⇒ **权限面完好**（ADR-10"派生同语句集"的幂等性这次是被实打验证了）。**但这不改变结论**：一个集成测试默认能以 app_rw（且测试文件里还有一套超管默认 DSN）反复重放共享库的权限面，这正是 U-114 要关的门。

### 13.4 第三次实锤：重灌是止血，U-114 才是伤口

- 本窗口 09-21 已重灌一次（`51543e1`），09-22 又被清 ⇒ **只要 `COMMERCEQL_TEST_*_DSN` 缺省仍指向共享库，谁跑 `tests/integration` 谁就再清一次**（本次的清空者 = `test_migration_0003_views.py`，连"带 `with_policy=True`"这条都超出了我 09-21 报的 `test_semantic_materialization.py` 那一档）。
- **本窗口处置照旧**：不跑 `tests/integration`；预检前复核 `(197,197,197)`；**在 U-114 落地前，此恢复动作可能还要再来**。

### 13.5 归属更正（W7 指出，2026-09-22）

`0f3f125` 除本文件的 §13 外，**还含 W4 的三处未署名改动**（`backend/reports/w4/RELAY.md`、`backend/tests/contract/test_decision_table_d_e.py`、`backend/tests/contract/test_exec_port_face_contract.py`）——成因 = **多窗口共享同一工作区**，我 `git add` 只点了本文件，但它们已在暂存区被一并卷入。**归属 = W4**（其 RELAY §十七 已作归因凭据，不回改历史）；本窗口只是提交载体。⚠️ **下一窗口勿据 commit author 判归属**。

### 13.6 第三次重灌（09-22 16:11，两道防线落地后）

- **前置核**：`5e47558`（U-123 缺派生器禁破坏性清空 + 防线① 夹具 DSN 去字面默认）与 `36c782a`（防线② CI 静态断言）**均已在远端 main** ⇒ W7 的"先等防线落地再灌"条件满足，且经我 `git show` 复核：U-123 把 `embed_doc` 从 DELETE 循环里剔除、缺派生器时**连 DELETE 都不做**（rows=0 + 具名 PENDING），正是"重灌还会被清"的根因关闭点。
- **跑前**（原句）`(197,0,0)` → **跑后**（原句）**`(197,197,197)`**；命令同 §13.1，退出码 **0**；唯一版本 `2026.09.14.1`。
- **"跑前+跑后各测一次原句 SQL"已列为固定动作**（W7 要求，两次都以 `select count(*),count(embedding),count(tsv) from app.embed_doc` 不换口径执行）。
- 证据：`_w2b_repour_20260922b.log`（工作区根，**仓外**）。

---

## 14. RL-2 接线回执：`observe_retrieval_mode()` 落地（2026-09-23，响应 W7 第⑤条派单②）

**一句话**：接线已落，口径按"分母 = **真的尝试过 embedding 的轮次**"钉死，并附**正向对照**（注入必红 / 还原必绿）与**导出面自证**（`/metrics` 文本真出现该序列）⇒ `retrieval_mode_total` 从"本体在、**无调用点**"进入**可引用**状态。

### 14.1 改动（三处）

| 文件 | 改什么 |
|---|---|
| `app/retrieval/search.py` | **唯一一行接线**：`search_full` 末尾 `observe_retrieval_mode(effective_mode)`（`search()` 只是它的薄封装 ⇒ 不重复计）；模块 docstring 增"检索模式埋点"职责条；两条早退路径各加"不计"注释（含理由） |
| `tests/unit/test_retrieval_search.py` | **10 → 17 条**：计数 / **实际档 vs 请求档** / 降级率可算 / 两条早退不计 / 契约面只计一次 / **导出面自证** / 口径边界登记；另加 autouse 指标复位夹具（用仓内公共助手 `metrics.reset_for_tests()`，不碰私有 `_reset`） |
| `app/obs/metrics.py` | **只改一行文档**：§"未接线项"表里检索模式那一行 → 改为**已接线** + 口径 + 遗留边界。⚠️ 这是 W7 域文件，若判"不该动"，**回退这一行即可，不影响功能**（代码零改动） |

### 14.2 口径（引用前必读；已写进 `metrics.py` 那一行）

- **分母 = 真的尝试过 embedding 的轮次**。两条早退**刻意不计**：
  - **空问题轮**：没发生检索 ⇒ 计进去会把降级率**稀释**成"含空问的比率"；
  - **缓存命中轮**：没调 embedding，且**降级轮从不写缓存** ⇒ 记成 `hybrid` 会**系统性低估**降级率（分子分母双失真）。
    - 副作用（**有意**，已登记）：本指标**看不见"被缓存兜住的降级轮"**。这是对的 —— 那种轮次在用户侧**无影响**，不该污染依赖健康度读数。
- **标签 = 实际执行档**（`effective_mode`），**不是**请求档（C-11）。记请求档 ⇒ 降级率**永远是 0**，正好把 RL-2 要发现的病抹掉。

### 14.3 判据与正向对照（arch 要求"注入必红"）

- **正向对照（本轮实测）**：把那一行注释掉 ⇒ `pytest tests/unit/test_retrieval_search.py` = **7 failed / 10 passed**，红的**恰好是 7 条新用例**、10 条旧用例**全绿**（归因干净）；还原 ⇒ **17 passed**，且 `POSITIVE-CONTROL-TEMP` 标记已核为 0 处。
- **导出面自证**：跑完一轮后断言 `'retrieval_mode_total{retrieval_mode="hybrid"} 1' in render_prometheus_text()`。**与计数断言刻意分开** —— 本项目被"计数 ≠ 可读"咬过一次（物化 197 行、向量却全 NULL）。
- **可计算性**：健康 1 轮 + 降级 1 轮 ⇒ `{sparse_only} / 全体 = 1/2`（不再是 0/0）。

### 14.4 ⚠️ 遗留口径边界（我主动登记，不靠"没人会这么调"糊过去）

**请求** SPARSE_ONLY 与**降级**出的 SPARSE_ONLY **同标签、不可区分**。
当前成立的理由（**已核，非假设**）：生产唯一调用点 `app/graph/nodes/link.py:61` 的 `_REQUESTED_MODE` **写死 `RetrievalMode.HYBRID`** ⇒ 线上 `sparse_only` 序列**只可能**来自降级。
风险：若将来 eval / A-B / fast-mode 拿**真** `RetrievalService` 请求 SPARSE_ONLY，该序列立刻变成"请求 + 降级"混合 = **假分子**（本项目已两次栽在假分子/假分母上）。⇒ 届时二选一：加区分标签（需架构裁定）或把这类调用导到不注册指标的替身。（`eval/harness.py` 现为自带替身，不调真服务 ⇒ 暂无污染。）

### 14.5 门禁读数（本窗口实测）

- `ruff check .` = All checks passed；`mypy app` = **147 files / 0 issues**；`lint-imports` = **4 kept / 0 broken**。
- `pytest tests/unit tests/contract` = **1824 passed / 0 failed**（该文件 10 → 17）。
- `tests/integration` **未跑**（U-114 面 + W7 正在跑批 ⇒ 本窗口全程**零 DB**，不重灌）。
- ⚠️ 顺带一条**假红**陷阱（这次差点误判）：pytest 收尾清理 `%TEMP%\pytest-of-*` 垃圾目录时会被本机 safe-delete 钩子拦（该次 86 个文件 > 阈值 50），表现为 **exit=1 + 满屏点阵 + 无 summary 行** —— 只看退出码会读成"测试失败"。规避 = `--basetemp=<工作区路径>`。**同一批用例换 basetemp 即 `exit 0 / 1824 passed`**，归因可复现。
- `ruff format --check` 仍未纳入门禁；我这两个文件**在 HEAD 就已不合**（已用 `git show HEAD:` 的副本对照确认：`search.py` 同 4 处、测试文件同 5 处），**本次只新增 2 处同风格**（未顺手全局重排，避免把 W2B 文件的大 diff 混进本轮）。

### 14.6 未做 / 需要配合

- **不重灌**：遵你第⑤条③，跑批期间暂停任何重灌；本窗口本轮未碰库。
- "52 次"那一格我不再复算（你已按"带时刻两读差分"结案：`15:17→19:43 = 21`、`19:43→次日 15:57 = 0`）。
- 复现命令（零成本，零 DB）：`cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit/test_retrieval_search.py -q`

### 14.7 顺带订正一条**过期读数**：arch RELAY 记的"三族零调用点"现只剩一族

arch RELAY（`REFERENCE.md:203` 转记的那条）写的是 `binding_state_total` / `binding_layer_total` / `retrieval_mode_total` **三族零调用点**。本窗口 2026-09-23 17:1x 现读：

| 指标 | 调用点 | 现状 |
|---|---|---|
| `binding_state_total` | `app/api/deps.py:563` | **已有**（不是零） |
| `binding_layer_total` | `app/api/deps.py:564` | **已有**（不是零） |
| `retrieval_mode_total` | `app/retrieval/search.py:242` | **本轮补上** |

⇒ **此后这条读数按"三族皆已接线"记**（W7 若要引用"零调用点"结论，请改用带时刻的现读）。`app/binding/__init__.py:52` 也把这两条写进了契约说明 —— 与该现读一致。

---

## 15. 一条**重踩**提醒：`python -m importlinter.cli lint-imports` = 静默假绿（**不是新发现**，U-41 在案）

- 现象：exit **0**、**零输出**。我第一遍就是这么"验绿"的，差点把"无输出"读成"契约通过"。机制 = `importlinter/cli.py` **无 `if __name__ == "__main__"` 块** ⇒ `-m` 只 import、不执行。
- 正解：`./.venv/Scripts/lint-imports.exe`（读 `.importlinter`）⇒ 输出 `Contracts: 4 kept, 0 broken.`。CI 另有 `grep -q "Contracts: "` 守卫（`ci.yml:269-278`）。
- **这不新**：`U-41` 在案、README 已注明、CI 已设守卫 —— 我记它的唯一价值 = **"没输出"不等于"绿"**（这次我是在**已经知道**这条规则的情况下又踩了一次）。




