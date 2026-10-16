"""`scripts/scan_secrets.py` 的离线契约测试（W8 第 45 轮，QA §63.4／§64.1 四）。

**为什么需要它**：该脚本的产出被当作"凭据扫描 0 命中"的**证据**引用，而
`--since` 口径**看不见未跟踪的新件** —— 第 44 轮实测就吃过这个：报"0 命中／78 件"时，
当时新建的脚本／匣带／结果三件**根本没进被测集合**。
⇒ 本文件钉两层：
· **正例**：含带口令 DSN 的行**必须被扫出来**（否则"0 命中"是空气）；
· **反例**：干净件、`.gitleaks.toml` allowlist 放行的形态、`***` 占位 —— **都不得**报命中
  （否则扫描器会逼人"加例外消红"，那正是 `test_migration_dsn_hygiene.py` 明文反对的事）。

⚠️ **样本字面量在运行时拼出**（`scheme = "postgres" + "://"`），与本仓库既有做法一致：
把可直接命中的字面量写进源码 = "修完 A 又在自己新加的文件里种回 B"
（`test_migration_dsn_hygiene.py` 第一版就这么栽过）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND.parent
_SCRIPT = _BACKEND / "scripts" / "scan_secrets.py"

#: 运行时拼装，源码里不留可命中的连续字面量。
_SCHEME = "postgres" + "://"  # noqa: ISC001  (拼装只为躲开扫描器，不是风格问题)
_OWNER_DSN = _SCHEME + "owner_user:s0me_pwd@db.internal:5432/ecom"
_ALLOWLISTED_DSN = _SCHEME + "app_rw:app_rw_pwd@127.0.0.1:5432/ecom"
_PLACEHOLDER_DSN = _SCHEME + "owner_user:***@db.internal:5432/ecom"


def _module():
    """按路径加载脚本（`scripts/` 不是包，无法 import）。"""
    spec = importlib.util.spec_from_file_location("scan_secrets_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_root(tmp_path: Path, name: str, text: str) -> Path:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")
    return root


def _scan_one(mod, root: Path, name: str) -> list[str]:
    rules = mod._rules(mod._load_gitleaks_config())
    excused, stopwords, allow_paths = mod._allowlist(mod._load_gitleaks_config())
    return mod._scan(root, [name], rules, excused, stopwords, allow_paths)


# ---------------------------------------------------------------------------
# 正例：必须扫得出来
# ---------------------------------------------------------------------------


def test_positive_owner_credential_is_hit(tmp_path: Path) -> None:
    """★ 正例：属主口令形态的 DSN **必须**命中（否则"0 命中"这条证据是空气）。"""
    mod = _module()
    root = _fixture_root(tmp_path, "leak.md", f"示例：{_OWNER_DSN}\n")
    hits = _scan_one(mod, root, "leak.md")
    assert len(hits) == 1, f"含属主口令的 DSN 没被扫出来 —— 扫描器失效：{hits}"
    assert "leak.md:1" in hits[0]
    assert "s0me_pwd" not in hits[0], "命中行不得回显口令原文（只留掩码）"
    assert "commerceql-dsn-with-password" in hits[0], "命中应点名规则 id，便于对表"


def test_positive_hit_within_working_tree_walk(tmp_path: Path) -> None:
    """★ 正例（工作树口径）：`_worktree_files` 必须**看见未跟踪的新件** —— 这正是第 44 轮漏掉的一面。"""
    mod = _module()
    root = _fixture_root(tmp_path, "brand_new.py", f"URL = '{_OWNER_DSN}'\n")
    files = mod._worktree_files(root)
    assert "brand_new.py" in files, f"工作树遍历没看见新件：{files}"
    rules = mod._rules(mod._load_gitleaks_config())
    excused, stopwords, allow_paths = mod._allowlist(mod._load_gitleaks_config())
    assert mod._scan(root, files, rules, excused, stopwords, allow_paths), "工作树口径漏掉了同一处命中"


# ---------------------------------------------------------------------------
# 反例：不得误报
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text", "why"),
    [
        ("clean.md", "普通文档：SELECT COUNT(*) FROM v_shop；指标 shop_cnt。", "干净件必须 0 命中"),
        ("allowlisted.md", f"示例：{_ALLOWLISTED_DSN}", "`.gitleaks.toml` 的 regexes 放行的 dev 弱口令形态"),
        ("placeholder.md", f"文档占位：{_PLACEHOLDER_DSN}", "`***` 占位由 allowlist 放行，不得逼人加例外"),
        ("mention_only.md", "本仓库禁止把 " + _SCHEME + " 形态的串写进文档。", "只提 scheme、不带口令 ⇒ 不得命中（第 43 轮的过宽形态）"),
    ],
)
def test_negative_no_false_positive(tmp_path: Path, name: str, text: str, why: str) -> None:
    mod = _module()
    root = _fixture_root(tmp_path, name, text + "\n")
    hits = _scan_one(mod, root, name)
    assert not hits, f"{why} —— 但扫出了 {hits}"


def test_negative_repo_itself_is_clean() -> None:
    """反例（真实面）：**当前仓库工作树**跑一遍必须 0 命中。"""
    mod = _module()
    rules = mod._rules(mod._load_gitleaks_config())
    excused, stopwords, allow_paths = mod._allowlist(mod._load_gitleaks_config())
    hits = mod._scan(_REPO_ROOT, mod._worktree_files(_REPO_ROOT), rules, excused, stopwords, allow_paths)
    assert not hits, "工作树出现未放行命中（CI 的 gitleaks 会红）：\n  " + "\n  ".join(hits)


def test_script_source_does_not_self_match() -> None:
    """★ 反例（本文件自身）：脚本源码**不得**被自己的规则命中 —— 第 43 轮"自匹配"的根因就在这。"""
    mod = _module()
    rules = mod._rules(mod._load_gitleaks_config())
    text = _SCRIPT.read_text(encoding="utf-8")
    for rule_id, pattern in rules:
        assert not pattern.findall(text), f"{rule_id} 命中了扫描器自己的源码（自匹配）"
