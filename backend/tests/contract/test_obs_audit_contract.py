"""观测层与审计写入的契约断言（07 §12.4 / §12.4.1 / §15.3 / §18.4.1）。

归属窗口：W0（`app/obs/**` 骨架）。

覆盖两件在本会话**被架构窗口改过规则**的事：

**① U-18 —— 审计写入落 `obs/audit.py` 的代价约束。**
裁定把审计放进观测层，理由是"横切关注点 + 调用方只依赖一个端口"，但附了一条代价：
`obs/` 从此不再是纯无副作用模块（它含一个会**阻断主链路**的写）。约束 =
「`obs/` 内除 `audit.py` 外，任何模块不得引入 DB 依赖」。
本文件用**两道**断言守它：import-linter（`r-dep-3`）管"实际 import"，本文件管"清单完整"
—— 因为新增一个 `obs/xxx.py` 时若忘了同步 `.importlinter` 的 source 列表，
那个新模块就**自动获得 DB 依赖豁免**，而 lint 不会报错（它根本不在 source 里）。

**② U-19 —— τ 未校准"放行但不得隐瞒"的三条硬要求。**
① 启动日志必打 WARN；② 指标 gauge 可查询；③ **不得**塞进 `/healthz`（那是附录 A §A.8.4 的
契约 payload，私增字段违反"唯一规范源"，架构窗口已登记为补充契约 C-13 待回填）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.obs import metrics

pytestmark = pytest.mark.contract

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_OBS_DIR = _BACKEND_ROOT / "app" / "obs"
_IMPORTLINTER = _BACKEND_ROOT / ".importlinter"

#: `obs/` 下**允许**依赖 `repo` 的唯一模块（07 §12.4.1 裁定）。
_AUDIT_MODULE_STEM = "audit"


def _obs_module_stems() -> set[str]:
    return {
        path.stem
        for path in _OBS_DIR.glob("*.py")
        if path.stem != "__init__"
    }


# ---------------------------------------------------------------------------
# 1. U-18：obs 的 DB 依赖面必须**恰好**是 {audit}
# ---------------------------------------------------------------------------

def test_importlinter_declares_the_obs_contract() -> None:
    """`r-dep-3` 必须存在 —— 否则"obs 除 audit 外禁 DB"这条约束只写在文档里。"""
    text = _IMPORTLINTER.read_text(encoding="utf-8")
    assert "[importlinter:contract:r-dep-3-obs-except-audit-no-repo]" in text, (
        "U-18 的代价约束需要一条独立的 forbidden 契约（lint 才拦得住）"
    )


def test_importlinter_obs_source_list_covers_every_obs_module() -> None:
    """★ **本测试兜住 lint 自身的漏网面**。

    `forbidden` 契约只检查**列在 source 里**的模块。新增 `app/obs/xx.py` 却忘了加进
    `.importlinter` → 该模块对 `repo` 的依赖**不会被检查**，而 lint 依然"全绿"。
    所以"目录实际文件 == 契约 source 列表"必须单独钉一次。
    """
    text = _IMPORTLINTER.read_text(encoding="utf-8")
    block = text.split("[importlinter:contract:r-dep-3-obs-except-audit-no-repo]", 1)[1]
    block = block.split("[importlinter:contract:", 1)[0]
    source_section = block.split("source_modules =", 1)[1].split("forbidden_modules =", 1)[0]
    declared = {
        line.strip().split(".")[-1]
        for line in source_section.splitlines()
        if line.strip() and not line.strip().startswith(";")
    }
    expected = _obs_module_stems() - {_AUDIT_MODULE_STEM}
    assert declared == expected, (
        f"`.importlinter` 的 r-dep-3 source 列表与实际 obs 模块不一致："
        f"声明={sorted(declared)} 实际应含={sorted(expected)} —— "
        f"漏加的模块会**静默获得** DB 依赖豁免"
    )


def test_obs_modules_other_than_audit_do_not_import_repo() -> None:
    """静态扫描兜底（lint 之外的第二次检查）。

    刻意用源码扫描而不是 `sys.modules` 检查：后者在"模块没被执行到"时会给出假绿灯。
    """
    offenders: list[str] = []
    for path in sorted(_OBS_DIR.glob("*.py")):
        if path.stem in {"__init__", _AUDIT_MODULE_STEM}:
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(from|import)\s+app\.repo\b", source, flags=re.MULTILINE):
            offenders.append(path.name)
    assert not offenders, (
        f"以下 obs 模块引入了 repo 依赖（U-18 代价约束）：{offenders} —— "
        f"观测层不得在 DB 挂掉时把主链路带崩"
    )


def test_audit_writer_has_no_update_or_delete_statement() -> None:
    """07 §12.4 第 ③ 层：**CI 静态断言 `obs/audit.py` 无 `UPDATE`/`DELETE` 语句**。

    `audit_log` 的 append-only 有四重保证（DB 权限 / 触发器 / 代码 / 集成测试）。
    这一条是"代码层"：模块**只能**插入 —— 一旦这里出现 UPDATE，其余三重就成了摆设
    （因为代码是唯一被允许持有写权限的那一方）。

    ⚠️ 第一版用**全文正则**实现，结果本测试自己红了 —— 因为 `audit.py` 的**文档字符串里
    在讨论**"UPDATE/DELETE 会被拒绝"这件事。那正是这类静态检查最典型的假阳性：
    检查工具把"关于规则的文字"当成了"违反规则的行为"。
    → 改用 `ast`：只看**字符串字面量**（数据），并排除 docstring（说明）。
    注释天然不在 AST 里，故 `# UPDATE` 这类注释不会再造成假阳性。
    """
    source = (_OBS_DIR / f"{_AUDIT_MODULE_STEM}.py").read_text(encoding="utf-8")
    offender_strings = _sql_strings_with(source, r"\b(UPDATE\s+\w|DELETE\s+FROM\b)")
    assert not offender_strings, (
        f"audit.py 在**代码里**（非文档）出现写改删语句 {offender_strings} "
        f"—— append-only 被破坏（N-09/ADR-14）"
    )


def _sql_strings_with(source: str, pattern: str) -> list[str]:
    """返回源码中**非 docstring** 的字符串字面量里命中 `pattern` 的那些。"""
    import ast

    tree = ast.parse(source)
    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found = ast.get_docstring(node, clean=False)
            if found is not None:
                docstrings.add(found)

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        else:
            continue
        if not text or text in docstrings:
            continue
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(text.strip()[:60])
    return hits


def test_audit_writer_is_the_only_importing_module() -> None:
    """反向确认：`audit.py` 存在且**明确**依赖 `repo`/`AuditSinkPort` 语义。

    这条断言防的是"有人把 audit.py 挪走"——挪走后 r-dep-3 的 source 列表就被顺手删空，
    约束随之静默消失。文件不在了，本测试红。
    """
    assert (_OBS_DIR / f"{_AUDIT_MODULE_STEM}.py").is_file()
    source = (_OBS_DIR / f"{_AUDIT_MODULE_STEM}.py").read_text(encoding="utf-8")
    assert "AuditSinkPort" in source, "审计写入器必须实现 core.contracts 的 AuditSinkPort 端口"


# ---------------------------------------------------------------------------
# 2. 指标标签的基数红线（§15.4）
# ---------------------------------------------------------------------------

def test_unbounded_labels_are_never_allowed() -> None:
    """无界标签（`task_id` / `user_id` / …）**绝不可**做指标标签 —— 可用性红线。"""
    overlap = set(metrics.BOUNDED_ALLOWED_LABELS) & set(metrics.UNBOUNDED_FORBIDDEN_LABELS)
    assert not overlap, f"同名字段既在允许表又在禁止表：{sorted(overlap)}"


def test_allowed_labels_have_declared_cardinality_caps() -> None:
    """每个允许的标签都必须声明**基数上界**（没有上界的标签等于无界标签）。"""
    missing = sorted(k for k, cap in metrics.BOUNDED_ALLOWED_LABELS.items() if not isinstance(cap, int) or cap <= 0)
    assert not missing, f"以下标签缺基数上限：{missing}"


def test_rule_id_label_cap_matches_ast_rule_count() -> None:
    """`rule_id` 标签的上限必须等于 AST 规则条数（20）—— U-16 后两者必须同步。"""
    from app.core.enums import AstRule

    assert metrics.BOUNDED_ALLOWED_LABELS["rule_id"] == len(AstRule)


# ---------------------------------------------------------------------------
# 3. U-19：τ 未校准"放行但不隐瞒"的三条硬要求
# ---------------------------------------------------------------------------

def test_startup_warn_is_emitted_when_tau_uncalibrated(capsys: pytest.CaptureFixture[str]) -> None:
    """硬要求 ①：启动日志**必打** WARN，内容可被检索到（不是"暗示"）。

    `structlog` 的 logger_factory 是 PrintLogger（写 stdout），故 capsys 能直接捕获。
    """
    from app.main import create_app

    metrics.set_binding_tau_calibrated(True)  # 先污染成"已校准"，确认启动会覆写
    with TestClient(create_app()):
        pass

    captured = capsys.readouterr().out
    assert "binding_tau_is_calibrated=false" in captured, (
        "U-19 硬要求①：非 prod 且 τ 未校准必须打 WARN 且字段可检索"
    )
    assert "τ 未校准" in captured, "WARN 必须说清后果（L4 精排结果不可用于生产判定）"


def test_gauge_reflects_calibration_state() -> None:
    """硬要求 ②：指标 gauge 0/1 可查询 —— "有多少实例端着未校准的 τ 在跑"必须可答。"""
    metrics.set_binding_tau_calibrated(False)
    assert metrics.get_binding_tau_calibrated() == 0
    metrics.set_binding_tau_calibrated(True)
    assert metrics.get_binding_tau_calibrated() == 1


def test_gauge_is_exposed_in_prometheus_text() -> None:
    """gauge 必须**可被暴露**（W7 接采集端点时直接并入，不得另起一个同名指标）。"""
    metrics.set_binding_tau_calibrated(False)
    text = metrics.render_prometheus_text()
    assert f"# TYPE {metrics.BINDING_TAU_CALIBRATED} gauge" in text
    assert f"{metrics.BINDING_TAU_CALIBRATED} 0" in text
    # 无标签 → 无基数风险（这是它能在阶段 0 破例命名的前提之一）
    assert "{" not in text.split("\n")[-2]


def test_healthz_payload_does_not_carry_config_softening() -> None:
    """硬要求 ③ + 补充契约 C-13：`/healthz` **不得**私增字段承载"配置级软化"。

    `config_warnings[]` 是架构窗口建议的承载位（C-13），但**待回填附录 A**；
    在回填前私增字段 = 违反"唯一规范源"（07 §4.1）。
    本测试是那道"回填前不许先斩后奏"的闸门：C-13 落地时**必须显式改红本测试**，
    而不是被顺手加上去。
    """
    from app.main import create_app

    with TestClient(create_app()) as client:
        for path in ("/api/v1/healthz", "/api/v1/healthz/ready"):
            payload = client.get(path).json()
            body = str(payload)
            assert "config_warnings" not in body, (
                f"{path} 出现了 config_warnings —— C-13 尚未回填附录 A，不得先斩后奏"
            )
            assert "binding_tau" not in body, (
                f"{path} 出现了 binding_tau* 字段 —— U-19 硬要求③：承载方式是启动日志 + 指标"
            )
