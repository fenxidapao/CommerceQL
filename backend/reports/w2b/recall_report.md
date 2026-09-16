# W2B 检索黄金集 Recall 报告（DoD②）

- 日期：2026-09-16｜黄金集：eval/gold_query_seed_v1.json（119 条）
- **asset_recall@5（宏平均）= 0.1218**（计入 119 条有资产期望的 seed）
- **column_recall@30（宏平均）= 0.0508**（计入 118 条有列期望的 seed）
- 路由归因：value 命中 22 题｜graph 命中 0 题｜显式降级 119 题

## ⚠️ 如实声明（未解决的风险）

1. 生产 `app.embed_doc` 197 行中 `tsv` 与 `embedding` **全部为空**（W2A 已建表未填充；宿主 Ollama 亦无 bge-m3 模型）→ sparse/dense 两路本轮贡献 0。
2. 本报告数值是 **value+graph 两路的真实召回**，不得对外宣称为四路完整成绩；
   W2A 填充 tsv/embedding 后须重跑本脚本取得完整口径。
3. 未满分 seed 119 条，明细见 recall_results.json 的 misses。

## 复现方式

```
cd backend && ../.venv/Scripts/python.exe reports/w2b/recall_report.py
```