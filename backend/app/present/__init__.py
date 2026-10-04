"""L3 呈现聚合包（归属窗口：W8，T-34，2026-10-04 起不再是空壳）。

**本包今天落的是哪一面，没落的是哪一面**（这两句必须分开写，否则"present/ 已实现"
会被读成"图表呈现已实现"）：

- ✅ 已落：管理端评测报告页的三个投影 —— 评测集清单（§A.9.2）、批次清单（§A.9.3）、
  单批次结果含 4×3 网格与归因分布与门禁判定（§A.9.4）。数据源 = 已入库的评测产物，
  只读、不重跑（`app/present/artifacts.py` ＋ `app/present/eval_report.py`）。
- ❌ 未落：**图内**的 `chart_spec`／`insight` 生成器（原 W3B 归属）。
  `GraphDeps.presenter` 仍恒为 `None`（`app/api/deps.py:823-827`），
  `app/graph/nodes/present.py` 的「P0 = 如实降级（`present_failed`／`table_only`）」
  与「presenter 被装配进来就 fail-fast」（同文件 `:26-29`）**两条都照旧生效**。
  ⇒ 本包**没有**给 `presenter` 发明接口；那条接口仍不存在，谁需要它谁先补契约。
"""

from __future__ import annotations

from app.present.eval_report import dataset_ids, datasets, run_detail, runs

__all__ = ["dataset_ids", "datasets", "run_detail", "runs"]
