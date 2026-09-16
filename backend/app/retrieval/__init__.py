"""四路检索 + 融合；`tokenizer.py` 为分词唯一入口（N-24 / ADR-07）。

层号：L3｜归属窗口：**W2B**（docs/08 §4.1）。

模块清单（07 §3.2 树）：
- `tokenizer.py`  ★ jieba 唯一入口（写入/查询两侧同源，N-24）
- `view.py`       语义包只读视图（检索面的输入结构；不重复 W2A 的 loader）
- `value.py`      值检索（§6.6；纯语义包值表）
- `graph.py`      Join 图扩展（§6.5；BFS ≤2 跳只走认证边）
- `fuse.py`       RRF 融合 + 降级权重重分配 + 截断（§6.7；纯函数）
- `dense.py`      稠密检索（§6.3；Ollama /api/embed + 向量存储）
- `sparse.py`     稀疏词法检索（§6.4；FTS + ts_rank_cd，非 BM25——N-22）
- `search.py`     `RetrievalPort` 实现（四路编排，mode 如实回填——C-11）
- `refine.py`     LLM 精筛（**P0 未实现**：07 无行为定义且 3A 未交付，见文件内登记）

同层 import 允许（.importlinter 注②）；对 L0/L1 的依赖走注入
（连接池唯一装配点在 `app/repo/pools.py`，本包不自建池——N-14）。
"""
