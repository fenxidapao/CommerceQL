"""评测产物的只读装载层（层号 L3｜归属窗口：W8，T-34）。

**这个模块只读，不重跑**（QA 第 8 轮派单的硬约束）：
数据源 = 仓库根 `eval/results_*.json`（评测批次产物）＋ `backend/reports/w6/eval_metrics.json`
（门禁报告产物）。两者**都已入 git** ⇒ 任何一次 checkout 都能复算本页读数。
端点里不得重跑评测、不得出站调模型、不得新增凭据、不得连库。

为什么路径走环境变量而不是 `Settings` 字段：
镜像里只 `COPY backend/app`（`deploy/Dockerfile:32`），产物在容器内位于只读挂载点
（`deploy/docker-compose.yml` 的 api 服务 `volumes`，与语义包 `/semantic:ro` 同一先例）。
这两个路径是**部署面**的，不是应用行为配置 ⇒ 按 `DRAIN_TOKEN` 的先例处理
（compose 文件头注释：非 Settings 字段，故不在 `deploy/.env.example`），
`tests/contract/test_config_failfast.py` 的双向同步断言因此不受影响。

⚠️ `run_id` 只做**标识**，永远不参与路径拼接前的信任链：
传入值先过 `_RUN_ID` 白名单字符集，解析出的绝对路径必须仍在产物目录内（`_inside`），
两者任一不过 ⇒ 视为"不存在"（与 `SessionNotFound` 同形：不区分"没听过"与"不许听"）。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ArtifactNotFound",
    "gate_report",
    "gate_report_path",
    "load_run",
    "paths",
    "read_json",
    "run_ids",
    "runs_dir",
    "valid_run_id",
]


class ArtifactNotFound(Exception):
    """产物不在位，或 `run_id` 解析不到在位的产物文件。

    ⚠️ 这是一个**内部信号**，不是 HTTP 异常：`app.present` 在 L3，
    不许 import `app.api`（`backend/.importlinter` 的层序契约）。
    由 `routers/admin_eval.py` 翻译成 `RUN_NOT_FOUND` / `DATASET_NOT_FOUND`。
    """


_RUN_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$")

#: 深度尺现测：本文件 = `<仓库根>/backend/app/present/artifacts.py`
#: ⇒ `parents[0]=present`、`parents[1]=app`、`parents[2]=backend`、`parents[3]=仓库根`。
#: （本项目在相对深度上翻过三次车，故此处把四级都写出来供对表。）
_REPO_ROOT: Final = Path(__file__).resolve().parents[3]

_DEFAULT_RUNS_DIR: Final = _REPO_ROOT / "eval"
_DEFAULT_GATE_REPORT: Final = _REPO_ROOT / "backend" / "reports" / "w6" / "eval_metrics.json"

_CACHE_MAX: Final = 4
_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_LOCK = threading.Lock()


def runs_dir() -> Path:
    """评测批次产物目录（容器内由只读挂载提供）。"""
    return Path(os.getenv("COMMERCEQL_EVAL_RUNS_DIR") or str(_DEFAULT_RUNS_DIR))


def gate_report_path() -> Path:
    """门禁报告产物路径（`eval/reporter.py` 的输出件）。"""
    return Path(os.getenv("COMMERCEQL_EVAL_GATE_REPORT") or str(_DEFAULT_GATE_REPORT))


def paths() -> dict[str, str]:
    """当前生效的两个路径（**响应里要原样带出去**，否则读数无法自证来源）。"""
    return {"runs_dir": str(runs_dir()), "gate_report": str(gate_report_path())}


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.fullmatch(run_id))


def _inside(candidate: Path, root: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def read_json(path: Path) -> dict[str, Any]:
    """带 (路径, mtime_ns, 字节数) 三元组键的只读缓存。

    缓存不是优化而是**一致性**要求：一次页面加载会打 2~3 个端点，
    同一次加载里 `total` 与 `items` 必须出自同一份字节。
    """
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ArtifactNotFound(f"产物顶层不是对象：{path.name}")
    parsed: dict[str, Any] = raw
    with _LOCK:
        _CACHE[key] = parsed
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
    return parsed


def run_ids() -> list[str]:
    """目录里现有的评测批次产物（按文件名，稳定排序）。"""
    root = runs_dir()
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("results_*.json") if p.is_file())


def load_run(run_id: str) -> dict[str, Any]:
    """按 `run_id`（= 产物文件名去扩展名）读一份批次产物。"""
    if not valid_run_id(run_id):
        raise ArtifactNotFound(f"run_id 形状不合法：{run_id!r}")
    root = runs_dir()
    path = root / f"{run_id}.json"
    if not _inside(path, root) or not path.is_file():
        raise ArtifactNotFound(f"批次产物不在位：{run_id}")
    return read_json(path)


def gate_report() -> dict[str, Any] | None:
    """门禁报告；**不在位返回 `None`**（调用方必须把"没有门禁报告"如实报出去）。"""
    path = gate_report_path()
    if not path.is_file():
        return None
    return read_json(path)
