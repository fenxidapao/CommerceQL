"""迁移 DSN 的出处纪律（2026-09-16 由 W0 转达的门禁修复，归属窗口：W1B）。

**这件事的来龙去脉**（不写下来的话，下一个人会把默认值加回来）：

`alembic.ini` 与 `app/repo/migrations/env.py` 里原本各有一个兜底 DSN
（形态 = `postgresql+psycopg://` + 属主名 + `:` + 口令 + `@` + 主机）。它不是占位符 ——
它就是本机 compose 栈里 `POSTGRES_USER/POSTGRES_PASSWORD` 的真实取值，**可用**。
两个文件都被 `.gitleaks.toml` 的 `commerceql-dsn-with-password` 规则命中 →
一旦提交，CI 的 DoD④（`gitleaks detect`）必红。

**为什么不是"加进 allowlist 放行"**：那等于把一个可用口令**合法化**，
把"密钥不进仓库"这道门禁从"检查"降级成"装饰"。同一个原则下，
修复只能是"删字面量、只读环境变量"。

**为什么这个测试值得存在**：`.gitleaks.toml` 的 `allowlist` 里已经有两组
DSN 形态的样例值被放行（`app_rw` / `app_ro`）。也就是说，这类"用 allowlist 消红"
的诱惑在本仓库里**已经发生过**。本文件把边界钉在"配置类制品"上：
`alembic.ini` / `env.py` 必须**零命中**，且任何 allowlist 都不得放行属主凭据。

⚠️ 本文件**不**对已应用的迁移文件（`versions/*.py`）做严格断言：
`versions/0001_...py` 里有带默认口令的 DSN，但它是**已执行过的冻结制品**，
改它会让"从零重建的库"与"已建的库"产生不同口令 —— 那是更坏的缺陷。
它目前由 `.gitleaks.toml` 的 allowlist 放行，**如实登记为未决项**，不在这里假装干净。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent
_GITLEAKS_TOML = _REPO_ROOT / ".gitleaks.toml"

#: 配置类制品：这些文件的存在意义就是"被提交"，所以它们必须零命中。
_CONFIG_ARTIFACTS = (
    _BACKEND_ROOT / "alembic.ini",
    _BACKEND_ROOT / "app" / "repo" / "migrations" / "env.py",
)

_DSN_RULE_ID = "commerceql-dsn-with-password"


def _gitleaks_config() -> dict[str, object]:
    assert _GITLEAKS_TOML.exists(), (
        f"{_GITLEAKS_TOML} 不存在 —— 它是 DoD④ 的载体，缺了它本文件验的是空气"
    )
    with _GITLEAKS_TOML.open("rb") as fh:
        return tomllib.load(fh)


def _dsn_rule() -> re.Pattern[str]:
    """从 `.gitleaks.toml` 取出**项目自己的**那条 DSN 规则正则。

    ⚠️ 刻意不在这里重写一份正则：重写的话，两边会各自演化，
    而这个测试就会变成"验我自己写的那条正则"而不是"验 CI 真正会跑的那条"。
    """
    cfg = _gitleaks_config()
    rules = cfg.get("rules")
    assert isinstance(rules, list), ".gitleaks.toml 里 [[rules]] 结构变了，需同步本测试"
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == _DSN_RULE_ID:
            pattern = rule.get("regex")
            assert isinstance(pattern, str), f"{_DSN_RULE_ID} 的 regex 不是字符串"
            assert "(?!" not in pattern and "(?<" not in pattern, (
                f"{_DSN_RULE_ID} 用了 gitleaks 的 RE2 引擎**不支持**的断言 —— "
                f"这不是'少报一条'，而是 gitleaks 直接 panic、DoD④ 整体假阴性"
            )
            return re.compile(pattern)
    raise AssertionError(f".gitleaks.toml 里找不到规则 {_DSN_RULE_ID}")


def _excused_by_allowlist(secret: str) -> bool:
    """模拟 gitleaks 的 allowlist 语义：正则命中或含停用词即放行。"""
    cfg = _gitleaks_config()
    allow = cfg.get("allowlist")
    assert isinstance(allow, dict), ".gitleaks.toml 的 [allowlist] 结构变了，需同步本测试"
    regexes = allow.get("regexes", [])
    stopwords = allow.get("stopwords", [])
    assert isinstance(regexes, list) and isinstance(stopwords, list)
    if any(re.search(str(p), secret) for p in regexes):
        return True
    lowered = secret.lower()
    return any(str(w).lower() in lowered for w in stopwords)


# ---------------------------------------------------------------------------
# ① 配置类制品零命中（本修复的回归护栏）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _CONFIG_ARTIFACTS, ids=lambda p: str(p.name))
def test_config_artifacts_contain_no_dsn_with_password(path: Path) -> None:
    """★ `alembic.ini` / `env.py` 里不得出现任何带口令的 DSN 字面量。

    判定用的是 `.gitleaks.toml` 里那条**真实规则**，且**不套 allowlist** ——
    也就是说本断言比 CI 更严：即便有人把某个值加进 allowlist"消红"，
    这里仍然会红。原因：这两个文件的可读性/可移植性都不依赖任何具体 DSN，
    所以"必须有默认值"从来不是真实需求。
    """
    source = path.read_text(encoding="utf-8")
    hits = _dsn_rule().findall(source)
    assert not hits, (
        f"{path.name} 出现了带口令的 DSN 字面量 {hits} —— "
        f"迁移连接只能来自 MIGRATION_DATABASE_URL 环境变量（见 alembic.ini 顶部注释）"
    )


def test_alembic_ini_stays_pure_ascii() -> None:
    """`alembic.ini` 必须纯 ASCII（GBK 宿主机上非 ASCII 会让 alembic 直接崩）。

    这是本文件自己写明的约束（`configparser.read(..., encoding="locale")`），
    加注释时最容易破坏它 —— 所以钉一条断言，而不是靠"记得"。
    """
    raw = (_BACKEND_ROOT / "alembic.ini").read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not offenders, (
        f"alembic.ini 含 {len(offenders)} 个非 ASCII 字节，首个在 offset {offenders[0][0]} —— "
        f"在 zh-CN Windows 上 alembic 会以 UnicodeDecodeError 起步即崩"
    )


# ---------------------------------------------------------------------------
# ② "不要走 allowlist" 这条原则本身要被钉住
# ---------------------------------------------------------------------------


def test_allowlist_must_not_legalise_an_owner_credential() -> None:
    """★ 属主凭据不得被 allowlist 放行 —— 即"不允许用 allowlist 消红"。

    为什么需要这条：`.gitleaks.toml` 里已经放行了两组 DSN 形态的样例值，
    所以"再加一条"在习惯上毫无摩擦。本断言把 W0 在本轮明确的原则固化成可执行物：
    **放行一个可用口令 = 关掉这道门禁**。

    合成样本用的是"属主凭据"这一**形态**（而不是某个具体密码），
    因此它拦的是"下次有人为了消红再放行一条"这件事本身。
    """
    # ⚠️ 样本**在运行时拼出来**，源码里不留能被规则命中的字面量。
    #    这不是洁癖：本文件的第一版直接把样本写成字面量，全仓重放立刻把它标成
    #    "DoD④ 唯一命中项" —— 即"修完两个文件，又在自己新加的文件里种回同一个问题"。
    scheme = "postgresql+psycopg" + "://"
    sample = f"{scheme}owner_user:s0me_pwd@db.internal:5432/ecom"
    assert _dsn_rule().search(sample), "规则没有命中合成样本 —— 断言前提失效，本测试失效"
    assert not _excused_by_allowlist(sample), (
        "allowlist 放行了一个可用口令形态的 DSN —— 这正是「把可用口令合法化」。\n"
        "正确做法是删掉字面量、改读环境变量；而不是在 .gitleaks.toml 里加例外。"
    )


# ---------------------------------------------------------------------------
# ③ 行为：取不到就失败，且"不需要 DSN 的命令"不受影响
# ---------------------------------------------------------------------------


def _alembic(*args: str, dsn: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "MIGRATION_DATABASE_URL"}
    if dsn is not None:
        env["MIGRATION_DATABASE_URL"] = dsn
    # ⚠️ 编码必须**两侧都钉死**；只钉一侧会比不钉更糟（2026-09-20 四环境实测矩阵）。
    #   · 子进程（alembic）侧：输出编码 = `PYTHONIOENCODING` > UTF-8 模式 > 系统 ACP；
    #   · 本进程侧：`text=True` 的**解码**编码 = `locale.getpreferredencoding(False)`，
    #     它**不受** `PYTHONIOENCODING` 影响（只受 `PYTHONUTF8` 影响）。
    #   两者是两个独立的旋钮 ⇒ 任何"半套 UTF-8 环境"（设了 PYTHONIOENCODING=utf-8、
    #   但系统 ACP 仍是 cp936 —— 中文 Windows runner 的常见形态）都会让两侧不一致：
    #   解码线程抛错 ⇒ `result.stdout` 变 `None` ⇒ 断言以 **TypeError** 红，
    #   长得像测试自己的 bug，极易被顺手删断言（W7 2026-09-19 实测 2 failed）。
    #   ⚠️ 只加 `encoding="utf-8"` 是**把失败搬家**，不是修：实测裸 locale 环境
    #   （子进程发 cp936）会从 7 passed 变 2 failed。所以下面两个 pin 缺一不可。
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def test_alembic_helper_pins_encoding_on_both_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 两侧编码 pin 的守卫 —— 防止有人把 `PYTHONIOENCODING` 那行"简化"掉。

    为什么需要它：这个缺陷在 UTF-8 环境里**完全不可见**（钉一侧、钉两侧都是 7 passed），
    天真的重构会删掉子进程侧那行，然后在中文 Windows runner（ACP=cp936）上炸。
    实测依据：只钉父侧时，裸 locale 环境从 7 passed → 2 failed。

    ⚠️ 断言方式是有意的：**抓传给 `subprocess.run` 的实参**，而不是扫源码文本。
    扫文本会被本文件里别处的 `encoding="utf-8"`（`read_text`）和注释里的同名字样
    轻易骗过 —— 那就是本仓库已经栽过的"断言打错对象"。
    """
    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="0001\n", stderr="")

    # ⚠️ 必须先把环境变量摘掉再抓实参：`_alembic` 的 env 是从 `os.environ` 拷来的，
    #    若调用方环境里本来就设了 `PYTHONIOENCODING`（很多 CI/开发机都有），
    #    那么"删掉 helper 里那行 pin"也照样能通过 —— 本守卫会**假绿**。
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(subprocess, "run", _fake_run)
    _alembic("history")

    env = captured["env"]
    assert isinstance(env, dict)
    assert env.get("PYTHONIOENCODING") == "utf-8", (
        "子进程侧编码 pin 丢失：只钉父侧会让裸 locale 环境（子进程发 cp936）解码失败"
    )
    assert captured.get("encoding") == "utf-8", (
        "父进程侧编码 pin 丢失：`text=True` 会退回 `locale.getpreferredencoding()`"
    )
    assert "MIGRATION_DATABASE_URL" not in env, "helper 没把 DSN 从环境里摘掉"


def test_alembic_history_needs_no_dsn() -> None:
    """正向对照：`alembic history` **不需要** DSN，撤掉默认值后必须照常可用。

    没有这条，"删默认值"就会被当成"把 alembic 弄坏了"而被回滚 ——
    所以要把"哪些命令仍可用"测出来，而不是靠解释。
    """
    result = _alembic("history")
    assert result.returncode == 0, f"alembic history 失败：\n{result.stderr}"
    assert "0001" in result.stdout


def test_upgrade_fails_loudly_when_dsn_missing() -> None:
    """★ 无 DSN 时 `upgrade` 必须**失败**，且失败原因是本模块的显式拒绝。

    两处断言缺一不可：
    · 退出码非 0 —— 否则 CI/脚本会以为迁移成功了；
    · 错误里**没有** psycopg 的连接错误 —— 否则说明它是"先连了再失败"，
      即"安静地连上某个库"那条最坏路径仍然存在（本修复要消灭的正是它）。
    """
    result = _alembic("upgrade", "head")
    assert result.returncode != 0, "无 MIGRATION_DATABASE_URL 时 upgrade 竟然成功了"
    output = result.stdout + result.stderr
    assert "MIGRATION_DATABASE_URL" in output, (
        f"失败信息没有点名缺失的变量，操作者无从下手：\n{output}"
    )
    assert "RuntimeError" in output, f"不是本模块的显式拒绝，而是别的故障：\n{output}"
    for leak in ("OperationalError", "connection failed", "could not connect"):
        assert leak not in output, (
            f"输出里出现了 {leak} —— 说明代码已经**尝试连接**过数据库，"
            f"fail-fast 没有生效：\n{output}"
        )


# ---------------------------------------------------------------------------
# ④ 本机版 DoD④：全仓重放同一条规则
# ---------------------------------------------------------------------------

#: 与 `.gitleaks.toml` 的 `allowlist.paths` 对齐的"不可扫描"目录。
#: ⚠️ 沿用该文件的**理由**（不是随便挑的）：它们是 gitignore 的构建/依赖产物，
#: 里面塞满了第三方自带的假密钥样本（`.venv` 一扫就是 176MB 噪声），
#: 会把真实命中淹掉。
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".import_linter_cache",
        ".lintprobe",
        "htmlcov",
    }
)


def _iter_text_files() -> Iterator[tuple[Path, str]]:
    for path in sorted(_REPO_ROOT.rglob("*")):
        if not path.is_file() or _SKIP_DIRS & set(path.parts):
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # 二进制或读不动的一律跳过（`.db` / 图片 / 证书）。
            continue


def test_repo_wide_replay_of_the_dod4_rule_is_green() -> None:
    """★ 本机可跑的 DoD④ 替身：全仓重放**同一条**规则，必须零未放行命中。

    为什么需要它（实测，不是推测）：
      · 本机 `gitleaks` **未安装**（`gitleaks version` → command not found），
        所以 DoD④ 目前**只在 CI 上**存在 —— 本机提交前没有任何反馈；
      · 这一步在 2026-09-16 实际抓到了"修好两个文件、却在自己新加的文件里
        把同一个问题种回去"（见本文件 `test_allowlist_must_not_legalise_...` 内注释）。
        **没有全仓视角，这类"修 A 造 B"根本看不见。**

    与 CI 的差别（写清楚，不假装等价）：
      · CI 用 `gitleaks detect`（只扫 **git 追踪**的文件、含全部历史）；
        本测试扫**工作区**（含未跟踪文件）→ 对"还没 commit 的新文件"更严格，
        但**不看历史**（历史里的泄漏要靠 CI 的 `fetch-depth: 0`）。
    """
    rule = _dsn_rule()
    violations: list[str] = []
    for path, text in _iter_text_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        path_allowlisted = any(re.search(str(p), rel) for p in _path_allowlist_patterns())
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in rule.finditer(line):
                secret = match.group(0)
                if path_allowlisted or _excused_by_allowlist(secret):
                    continue
                violations.append(f"{rel}:{lineno}  {secret}")
    assert not violations, (
        "以下位置触发了 DoD④ 的 DSN 规则且未被放行 —— CI 的 gitleaks 会红：\n  "
        + "\n  ".join(violations)
        + "\n\n修法：删掉字面量、改读环境变量；**不要**加进 .gitleaks.toml 的 allowlist。"
    )


def _path_allowlist_patterns() -> list[str]:
    cfg = _gitleaks_config()
    allow = cfg.get("allowlist")
    assert isinstance(allow, dict)
    paths = allow.get("paths", [])
    assert isinstance(paths, list)
    return [str(p) for p in paths]
