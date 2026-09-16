#!/usr/bin/env python
"""阶段 0 DoD② 自动化：**故意注入违规 import，断言 lint 必须失败**。

归属窗口：W0（docs/08 §3.1）。清单外新增，理由见交付说明 **Q-5**。

为什么需要这个脚本（而不是"人工验一次"）：
  DoD② 的原文是"故意写一个违规 import（让 `guard` import `llm`）→ CI 必须失败"。
  如果只人工验一次，那么**下一次**有人把 `.importlinter` 里的
  `forbidden_modules` 改坏（或把 `source_modules` 漏掉一个包），
  契约就变成了一纸空文，而 CI 依然全绿 —— 这类"护栏自己坏了没人知道"的故障
  是最贵的一种。本脚本把 DoD② 变成每次 CI 都跑的**正向实验**：
  先证明"干净时通过"，再证明"脏了必须红"，最后证明"还原后重新变绿"。

探测三个正交维度（与 `.importlinter` 的 forbidden/layers 契约一一对应）：
  - 探针 A → `r-dep-2-no-llm-in-deterministic`：`app.guard` import `app.llm`
    （★ 注意：这一条在 `layers` 契约里**是合法的**，因为 guard 在 L2、llm 在 L1，
      上层依赖下层本来就允许。这正是必须单独写 forbidden 契约的原因。）
  - 探针 B → `r-dep-1-layers`：`app.core` import `app.api`
    （L0 反向依赖 L5，纯方向违规，只有 layers 契约能抓。）
  - 探针 C → `r-dep-3-obs-except-audit-no-repo`（追加型）：`app.obs.metrics` import `app.repo`
  - 探针 D → `r-dep-4-retrieval-no-llm-except-refine`（追加型）：`app.retrieval.dense` import `openai`
    （★ 注入**第三方**包，顺带验证 `include_external_packages=True` 配置不被静默关掉。）

用法::

    cd backend
    python scripts/assert_importlinter.py          # 退出码 0 = DoD② 通过
    python scripts/assert_importlinter.py -v        # 打印每步的 lint 原文
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG = BACKEND_ROOT / ".importlinter"

#: import-linter 的退出码约定（`importlinter.cli`）。
_EXIT_SUCCESS = 0


@dataclass(frozen=True)
class Probe:
    """一次"注入 → 断言失败 → 还原"的实验。"""

    contract_id: str
    layer_note: str
    target: Path                     # 注入点（新建的临时文件）
    source: str                      # 注入内容
    expect_fragments: tuple[str, ...]  # lint 输出里必须**全部**出现的片段

    #: ⚠️ 为什么用「输出片段」而不是「退出码非 0」作为判据：
    #:   退出码非 0 也可能来自**解析错误**（探针 import 了不存在的模块、
    #:   配置写错导致 import-linter 自身报错）。那种「假红」会让 DoD② 失去意义 ——
    #:   它证明不了契约有效，只证明了命令会失败。
    #:   因此要求输出里同时出现：
    #:     ① 契约的**显示名**（证明是这条契约红的，不是别的）；
    #:     ② 违规链路原文 `app.guard._probe_violation -> app.llm`
    #:        （证明红的**正是我们注入的那一行**）。
    #:   ★ 注意 import-linter 打印的是 `name =` 的**显示名**，不是 `[importlinter:contract:<id>]`
    #:     里的 id —— 早期版本这里误用了 id 导致误判，已修正。


PROBES: tuple[Probe, ...] = (
    Probe(
        contract_id="r-dep-2-no-llm-in-deterministic",
        layer_note="app.guard (L2) → app.llm (L1)：方向合法，但被 R-DEP-2 显式禁止",
        target=BACKEND_ROOT / "app" / "guard" / "_probe_violation.py",
        source=(
            '"""临时探针 —— 由 scripts/assert_importlinter.py 自动创建并删除，切勿提交。"""\n'
            "\n"
            "import app.llm  # noqa: F401  # R-DEP-2 违规：guard 属确定性层，禁止 import llm\n"
        ),
        expect_fragments=(
            "确定性模块与 binding 禁止 import app.llm",
            "app.guard._probe_violation -> app.llm",
        ),
    ),
    Probe(
        contract_id="r-dep-1-layers",
        layer_note="app.core (L0) → app.api (L5)：依赖方向倒挂",
        target=BACKEND_ROOT / "app" / "core" / "_probe_violation.py",
        source=(
            '"""临时探针 —— 由 scripts/assert_importlinter.py 自动创建并删除，切勿提交。"""\n'
            "\n"
            "import app.api  # noqa: F401  # R-DEP-1 违规：core 在 L0，不得反向依赖 L5\n"
        ),
        expect_fragments=(
            "R-DEP-1 分层依赖",
            "app.core._probe_violation -> app.api",
        ),
    ),
    Probe(
        contract_id="r-dep-3-obs-except-audit-no-repo",
        layer_note="app.obs.metrics → app.repo：方向合法（L1→L0），但被 U-18 的代价约束显式禁止",
        #: ★ 追加模式（`@@APPEND@@` 前缀）：目标文件**必须已存在**，且**必须在契约的
        #: `source_modules` 列表里**。原因见 `_run_probe` 的文档字符串。
        target=BACKEND_ROOT / "app" / "obs" / "metrics.py",
        source=(
            "@@APPEND@@\n"
            "import app.repo  # noqa: F401  # R-DEP-3 违规：obs 除 audit 外不得依赖 repo\n"
        ),
        expect_fragments=(
            "obs 内除 audit 外禁止依赖 repo",
            "app.obs.metrics -> app.repo",
        ),
    ),
    Probe(
        contract_id="r-dep-4-retrieval-no-llm-except-refine",
        layer_note="app.retrieval.dense → openai：检索链路（refine 除外）禁 LLM（W2B 提案，2026-09-16）",
        #: ★ 追加型：dense.py 在契约 source_modules 里。注入**第三方**包而不是 app.llm ——
        #:   该契约的 forbidden 同时覆盖 app.llm 与 langgraph/langchain/openai，
        #:   探针走第三方那条，正好把 include_external_packages=True 这条配置也一并验掉
        #:   （它若被关掉，整个契约加载会失败——基线就红，不会静默）。
        target=BACKEND_ROOT / "app" / "retrieval" / "dense.py",
        source=(
            "@@APPEND@@\n"
            "import openai  # noqa: F401  # R-DEP-4 违规：retrieval 除 refine 外禁 LLM\n"
        ),
        expect_fragments=(
            "retrieval 禁 LLM",
            "app.retrieval.dense -> openai",
        ),
    ),
)


def _lint(*, verbose: bool) -> tuple[int, str]:
    """跑一次 lint-imports，返回 (退出码, 输出文本)。

    ★ `no_cache=True` 是**必须**的：import-linter 的缓存以文件为单位，
      注入探针后若命中旧缓存，违规会被"缓存掉的干净图"掩盖，实验直接失效。
    """
    from importlinter.cli import lint_imports

    buffer = io.StringIO()
    previous_cwd = Path.cwd()
    try:
        os.chdir(BACKEND_ROOT)  # root_packages=app 的相对解析基准
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            status = lint_imports(
                config_filename=str(CONFIG),
                no_cache=True,
                no_logo=True,
                verbose=verbose,
            )
    finally:
        os.chdir(previous_cwd)
    return status, buffer.getvalue()


def _run_probe(probe: Probe, *, verbose: bool) -> tuple[bool, str, str]:
    """注入 → 断言红 → 还原。返回 (是否通过, 说明, lint 输出)。

    **两种注入方式，按 `probe.target` 是否存在自动选择**（U-18 的探针就是这么发现要加的）：

    · **新建文件**（target 不存在）：适用于 layers / 层间 forbidden 契约 ——
      import-linter 按路径匹配，新建一个 "位于某层" 的文件即可制造违规。
    · **追加到已有文件**（target 已存在）：★ **这是 `r-dep-3` 唯一可行的方式**，
      因为该契约的 `source_modules` 是**逐个列出的具体模块**（forbidden 契约不支持目录通配），
      新建的文件根本不在 source 列表里 → lint 不会检查它 → 探针会"注入成功但 lint 依然通过"。

      ⚠️ 这其实是**更真实**的探针形态：`obs` 模块违规的真实发生方式就是
      "某天有人在 `metrics.py` 里顺手查一次库"，而不是凭空新建一个文件。
      第一版探针用了新建文件的方式，结果就是这个契约"看起来有护栏、实际没被验证"。
    """
    if probe.target.exists() and probe.source.startswith("@@APPEND@@"):
        return _run_append_probe(probe, verbose=verbose)

    if probe.target.exists():
        return False, (
            f"注入点已存在，拒绝覆盖：{probe.target}\n"
            f"  → 疑似上次运行异常中断；请人工确认后删除（它不应存在于仓库中）"
        ), ""

    try:
        probe.target.write_text(probe.source, encoding="utf-8")
        status, output = _lint(verbose=verbose)
    finally:
        probe.target.unlink(missing_ok=True)
        # 清理探针编译产物，避免 __pycache__ 里留下痕迹影响后续静态扫描
        for cached in probe.target.parent.glob("__pycache__/_probe_violation.*"):
            cached.unlink(missing_ok=True)

    return _judge(probe, status, output)


def _run_append_probe(probe: Probe, *, verbose: bool) -> tuple[bool, str, str]:
    """把违规行**追加**到已存在的模块末尾，跑完**逐字节还原**。

    ⚠️ 还原必须写回**原始内容**（而不是"删掉最后一行"）：
      后者在探针中途失败或文件末尾无换行时会把文件剪坏 ——
      一个"修复性脚本"把源码改坏，比它要防的问题更严重。
    """
    original = probe.target.read_text(encoding="utf-8")
    injected_line = probe.source.removeprefix("@@APPEND@@").strip("\n")
    try:
        probe.target.write_text(
            original + ("\n" if not original.endswith("\n") else "") + injected_line + "\n",
            encoding="utf-8",
        )
        status, output = _lint(verbose=verbose)
    finally:
        probe.target.write_text(original, encoding="utf-8")

    ok, message, _ = _judge(probe, status, output, injected_line=injected_line)
    restored = probe.target.read_text(encoding="utf-8") == original
    if not restored:
        return False, f"{message}\n❌ 且**还原失败**：{probe.target} 与原始内容不一致，请用 git 恢复！", output
    return ok, message, output


def _judge(
    probe: Probe, status: int, output: str, *, injected_line: str | None = None
) -> tuple[bool, str, str]:
    """公共判定：lint 必须**失败**，且失败原因必须是**我们注入的那一行**。"""
    shown = injected_line or probe.source.strip().splitlines()[-1]

    if status == _EXIT_SUCCESS:
        return False, (
            f"❌ 注入 `{probe.contract_id}` 违规后 lint **依然通过** —— 契约已失效！\n"
            f"   注入点：{probe.target}\n"
            f"   注入内容：{shown}\n"
            f"   → 检查 `.importlinter` 里该契约的 source_modules / forbidden_modules 是否被改坏；\n"
            f"     若注入点不在 source_modules 的**具体模块列表**里，lint 根本不会检查它\n"
            f"     （forbidden 契约不支持目录通配 —— 这是 r-dep-3 第一版探针失效的原因）\n"
            f"   lint 输出：\n{_indent(output)}"
        ), output

    missing = [frag for frag in probe.expect_fragments if frag not in output]
    if missing:
        return False, (
            f"⚠️ lint 失败了，但输出里找不到预期片段 {missing}。\n"
            f"   预期「契约显示名」与「违规链路原文」必须**同时**出现 ——\n"
            f"   只看到失败、看不到是哪条契约因哪一行而失败，属于「假红」：\n"
            f"   它证明不了契约有效，只证明了这条命令会失败（例如探针自己写错导致解析报错）。\n"
            f"   lint 输出：\n{_indent(output)}"
        ), output

    return True, f"✅ {probe.contract_id} —— {probe.layer_note}", output


def _indent(text: str, prefix: str = "      | ") -> str:
    return "\n".join(prefix + line for line in text.rstrip().splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DoD②：故意注入违规 import，断言 lint 必须失败")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每次 lint 的完整输出")
    args = parser.parse_args(argv)

    for required in (CONFIG, BACKEND_ROOT / "app"):
        if not required.exists():
            print(f"FATAL: 缺少 {required}", file=sys.stderr)
            return 2

    failures: list[str] = []

    # ---------- 第 0 步：基线必须干净 ----------
    status, output = _lint(verbose=args.verbose)
    if status != _EXIT_SUCCESS:
        print("FATAL: 注入任何探针之前，lint 就已经失败 —— 先修好基线再谈 DoD②", file=sys.stderr)
        print(_indent(output), file=sys.stderr)
        return 2
    kept = _parse_kept(output)
    print(f"[baseline] 干净状态 lint 通过（{kept}）")

    # ---------- 第 1 步：逐个探针 ----------
    for probe in PROBES:
        if args.verbose:
            print(f"[probe] 注入 {probe.contract_id} → {probe.target.name}")
        ok, message, probe_output = _run_probe(probe, verbose=args.verbose)
        print(f"[probe] {message}")
        if not ok:
            failures.append(probe.contract_id)
        elif args.verbose:
            print(_indent(probe_output))

    # ---------- 第 2 步：还原后必须重新变绿 ----------
    status, output = _lint(verbose=args.verbose)
    if status != _EXIT_SUCCESS:
        print("FATAL: 探针已全部还原，但 lint 仍失败 —— 说明脚本留下了残留", file=sys.stderr)
        print(_indent(output), file=sys.stderr)
        return 2
    # ⚠️ 只检查**新建文件**型探针是否被清理：追加型探针的目标是**本来就存在的模块**
    #    （`app/obs/metrics.py`），它存在是正确的，不是残留。第一版这里没区分，
    #    导致脚本在做完所有正确的事之后自己 FATAL 退出。
    leftovers = [
        p.target
        for p in PROBES
        if p.target.exists() and not p.source.startswith("@@APPEND@@")
    ]
    if leftovers:
        print(f"FATAL: 探针文件未被清理：{leftovers}", file=sys.stderr)
        return 2
    # 追加型探针的"还原"由 `_run_append_probe` 自己逐字节校验（它拿到过原始内容），
    # 不在这里重复 —— 重复校验需要一个额外的"期望原文"副本，那本身就是第二份真相。
    print(f"[restored] 还原后 lint 重新通过（{_parse_kept(output)}）")

    if failures:
        print(f"\nDoD② **未通过** —— 以下契约在注入违规后未报警：{failures}", file=sys.stderr)
        return 1

    print(f"\nDoD② 通过 —— {len(PROBES)} 条契约均已证明「脏了必红」（注入 → 失败 → 还原 → 通过）")
    return 0


def _parse_kept(output: str) -> str:
    for line in output.splitlines():
        if "kept" in line and "broken" in line:
            return line.strip()
    return "contracts kept (未解析到汇总行)"


if __name__ == "__main__":
    raise SystemExit(main())
