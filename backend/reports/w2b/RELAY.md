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

## 5. 待架构窗口分配编号（下一可用号 U-54 起，我未占用任何号）

| # | 事项 | 来源 |
|---|---|---|
| 待 U-54 | tokenizer 落位矛盾（contracts docstring vs 07 §3.2），本实现按 07 §3.2 + 端口注入消解，终裁归架构 | Q1 |
| 待 U-55 | `CandidateRef` 装不下列级/富结果，W3C binding 需要的列 Top-30 走 `RetrievalResult` 旁路，端口面是否升级待裁 | Q2 |
| 待 U-56 | `app.embed_doc.tenant_id='*'` 公共哨兵未契约化（07 §12.2 应补） | §3.2 |
| 待 U-57 | `to_tsquery` 需显式 `&` 连接的语法事实（07 §6.4 举例若有空格形态应更正） | §3.1 |

## 6. 给下一阶段窗口（W3）的提示词草案

> 你是阶段 3 W3C（binding）窗口负责人。前置：W2B 检索层已交付。你的输入不是裸 `RetrievalPort.candidates`——请用 `app/retrieval/search.py::RetrievalService.search_full()` 返回的 `RetrievalResult`（含列级 Top-30、指标 Top-5、`value_hits`（term/asset/column/values/confidence/source）、`graph_hits`）。注意：① `value_hits.confidence` 是 1.0/0.8/0.6 三档，对应精确/前缀/编辑距离，绑定阈值取舍请引用 07 §6.6 并在 RELAY 登记你的选择；② graph 扩展只认 bundle `joins` 认证边，U-28 两跳陷阱已有用例，不要自行放宽；③ 降级语义（`mode`/`degraded_reason`/`action_taken`）必须透传给 planner，不得吞。红线沿用：不伪造实现、决策点先报告现状。开工方式：先出执行计划等确认。

（W3A/W3B 的接续提示词由编排层按 08 §4 计划分发，本窗口只对自己下游 W3C 给出草案。）

## 7. 未尽事项 / 风险

- `refine.py` 未实现（Q5 裁定，P0 范围外）；3A 网关建立后由后续窗口或本窗口 P1 补。
- `PgVectorStore` SQL 模板列形态 **UNVERIFIED**（W2A embed_doc 填充后跑真向量路径核对）。
- 4 个 `--check`（含 importlinter）未挂 CI —— W0 待办，非本窗口。
- recall 报告低数值的**根因是上游数据未填充**，不是检索逻辑缺陷；但 value 路仅覆盖 22/119 题（值类问句占比所限），四路齐备后预计显著改善——此为推断，待重跑验证。
