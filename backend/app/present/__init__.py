"""L3 呈现聚合包（归属窗口：W8 起，W3 补图内呈现）。

两面各是什么（必须分开写，否则"present/ 已实现"会被读成"图表呈现已实现"）：

- ✅ 管理端评测报告页的三个投影（§A.9.2 评测集清单 / §A.9.3 批次清单 /
  §A.9.4 单批次结果）：`app/present/artifacts.py` ＋ `app/present/eval_report.py`。
- ✅ **图内** `chart_spec`／`insight` 生成：`app/present/presenter.py::ChartPresenter`
  （`PresenterPort` 实现，纯函数）+ `app/present/checks.py` 的结果级校验。
  生产装配见 `app/api/deps.py`；`eval/harness.py` 仍显式传 `presenter=None`
  （**评测不出图是既定形态**，不是缺口）。
"""

from __future__ import annotations

from app.present.checks import CheckViolation, run_result_checks
from app.present.eval_report import dataset_ids, datasets, run_detail, runs
from app.present.presenter import ALLOWED_OPTION_KEYS, ChartPresenter

__all__ = [
    "ALLOWED_OPTION_KEYS",
    "ChartPresenter",
    "CheckViolation",
    "dataset_ids",
    "datasets",
    "run_detail",
    "runs",
    "run_result_checks",
]
