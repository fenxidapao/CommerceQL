"""给压测回执补「构建身份」自证面（`07 §16.5` 三层证据 ｜ T-35 主单硬要求 (b)）。

零额度、只读：只做 `docker exec` + `git show` + 本地哈希，不发任何 LLM 请求。

三层从弱到强（缺任何一层都可能给出假结论）：

| 层 | 证据 | 判得住什么 |
|---|---|---|
| 1 | 单文件容器 md5 == 工作树（原始 / LF 两把都试并具名）＋ `worktree_vs_head_lf` 直读工作树 ⟷ HEAD | 只证**那一个文件**（没被改过的文件无判别力） |
| 2 | 逐文件**行尾归一**后比 md5（raw / LF / CRLF 都试）＋ 全 `app/**.py` 聚合 | 字节级"内容 == 某 revision" |
| 3 | 容器内 `import` 一个**只有新构建才存在**的符号 | 改动在不在这个构建里（不依赖字节） |

🔴 **对外只写两链，不写"三面相等"（T-42 B，尺的语义）**：**链一 = 容器 ⟷ 工作树字节**（这把尺真量到的面，
逐件 `verdict` ＋ 聚合 `two_links.container_vs_worktree`）；**链二 = 工作树 ⟷ HEAD**（逐件
`worktree_vs_head_lf` ＋ 聚合 `two_links.worktree_vs_head`，并由跑前 `worktree_dirty_at_attest = false` 兜住整棵树）。
两链同真才可以说"容器 == HEAD"；只量到链一就写"git 面已比过"是缩口径（第 15/16 轮的旧措辞已就地 🔻 订正）。

用法：

    python deploy/loadtest/attest_build_identity.py --receipt deploy/loadtest/healthy_xxx.json \
        [--container w7load-api] [--files backend/app/graph/state.py,...]
    python deploy/loadtest/attest_build_identity.py --self-test   # 零 docker、零网络，钉住"不 strip"这条语义

写回 = 在回执 JSON 里加/替换 `build_identity` 块（其余字段一字不动）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根
CONTAINER_APP_DIR = "/srv/app"  # Dockerfile: WORKDIR /srv ＋ COPY backend/app ./app

#: 层 3 的探针符号：U-129 修法（`33675b9`）引入的每轮复位集合
LAYER3_MODULE = "app.graph.state"
LAYER3_SYMBOL = "RUN_SCOPED_STATE_FIELDS"

DEFAULT_FILES = (
    "backend/app/graph/state.py",
    "backend/app/graph/edges.py",
    "backend/app/graph/events.py",
    "backend/app/graph/nodes/audit_pre.py",
    "backend/app/graph/nodes/mask.py",
    "backend/app/graph/nodes/repair.py",
    "backend/app/graph/nodes/trusted_context.py",
    "backend/app/api/runner.py",
)


def _run(args: list[str], cwd: str | None = None) -> str:
    p = subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"命令失败 rc={p.returncode}: {' '.join(args)}\n{(p.stderr or p.stdout)[-400:]}")
    return (p.stdout or "").strip()


def _git(*args: str) -> str:
    return _run(["git", *args])


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _container_md5(container: str, path: str) -> str:
    return _run(["docker", "exec", container, "md5sum", path]).split()[0]


def attest_file(container: str, rel: str, head_rev: str) -> dict[str, object]:
    """层 1/2 的**逐件**面：`verdict` 只证「容器 ⟷ 工作树字节」这一链；「工作树 ⟷ HEAD」由 `worktree_vs_head_lf` 直读。

    🔴 `head_blob_lf` 必须走 `_git_bytes` ＋ 只做 `CRLF→LF`、**不 strip**（旧面 `.strip()` 吃掉结尾换行 ⇒
    这把 git 面结构上永远不命中，"三面相等"里那第三面从未参与比较；T-42 A，由 `_self_test` 的负例钉住）。
    """
    work = open(os.path.join(ROOT, rel), "rb").read()
    blob = _git_bytes("show", f"{head_rev}:{rel}")
    in_container = _container_md5(container, f"{CONTAINER_APP_DIR}/{rel.split('backend/app/', 1)[1]}")
    variants = {
        "worktree_raw": _md5(work),
        "worktree_lf": _md5(work.replace(b"\r\n", b"\n")),
        "head_blob_lf": _lf_md5(blob),
    }
    hit = [k for k, v in variants.items() if v == in_container]
    return {
        "path": rel,
        "container_md5": in_container,
        "matched_variant": hit[0] if hit else None,
        "variants": variants,
        "verdict": "SAME" if hit else "DIFF",
        "worktree_vs_head_lf": "SAME" if variants["worktree_lf"] == variants["head_blob_lf"] else "DIFF",
    }


#: 容器侧列内容 = 对 `/srv/app` 下每个 `.py` 取**行尾归一后**的 md5 ＋ 相对路径（正斜杠）。
#: 走 `python -c` 而非 shell 管道：subprocess 以列表传参 ⇒ 不经 shell、没有引号地狱。
_CONTAINER_LIST_SNIPPET = (
    "import hashlib,pathlib;"
    "root=pathlib.Path('/srv/app');"
    "fs=sorted(p for p in root.rglob('*.py'));"
    "lines=[hashlib.md5(p.read_bytes().replace(bytes([13,10]),bytes([10]))).hexdigest()"
    "+'  '+str(p.relative_to(root)).replace(chr(92),'/') for p in fs];"
    "print(chr(10).join(lines))"
)


def _git_bytes(*args: str) -> bytes:
    """原文字节取 blob：**不能**复用 `_git()`（那条走 `text=True` ＋ `strip()` ⇒ 会吃掉行尾与文件末尾换行）。"""
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} rc={p.returncode}: {(p.stderr or b'')[-300:].decode('utf-8', 'replace')}")
    return p.stdout


def _lf_md5(data: bytes) -> str:
    return hashlib.md5(data.replace(b"\r" + b"\n", b"\n")).hexdigest()


def attest_tree(container: str, head_rev: str) -> dict[str, object]:
    """聚合尺（`app/**.py` 全量）：三面各自**行尾归一**后逐文件 md5，再对整段列表取一次 md5。

    🔴 **旧形状那把是坏尺（本窗 10-06 自曝）**：容器侧原本跑 `find . | xargs md5sum | md5sum`，
    行里带 `./` 前缀、而 git 侧拼的是不带前缀的相对路径 ⇒ **三列结构上永远不可能相等** ⇒
    它报的"不等"**不是**漂移证据，只证明自己没被校准过。换代成三面同源之后，
    这一格才第一次能当**全量**证据（任一件内容差一个字节就整列错开）；逐件面仍是独立第二把尺。

    相等与否**按两链报**（`two_links`）：容器 ⟷ 工作树、工作树 ⟷ HEAD。三面由同一算法算出，
    但"三面相等"这句不落下游 ⇒ 引用只认两链（T-42 B）。
    """
    rels = [l for l in _git("ls-files", "backend/app").split("\n") if l.endswith(".py")]
    keyed = sorted(rels, key=lambda r: r.split("backend/app/", 1)[1])
    container_lines = _run(["docker", "exec", container, "python", "-c", _CONTAINER_LIST_SNIPPET])
    c_list = "\n".join(l for l in container_lines.split("\n") if l.strip())
    w_list = "\n".join(f"{_lf_md5(open(os.path.join(ROOT, r), 'rb').read())}  {r.split('backend/app/', 1)[1]}"
                       for r in keyed)
    h_list = "\n".join(f"{_lf_md5(_git_bytes('show', f'{head_rev}:{r}'))}  {r.split('backend/app/', 1)[1]}"
                       for r in keyed)
    c_md5, w_md5, h_md5 = (_md5(x.encode()) for x in (c_list, w_list, h_list))
    return {
        "files_count_git": len(rels),
        "files_count_container": len([l for l in c_list.split("\n") if l.strip()]),
        "aggregate_md5_lf_normalized": {"container": c_md5, "worktree": w_md5, "head_blob": h_md5},
        "two_links": {"container_vs_worktree": c_md5 == w_md5, "worktree_vs_head": w_md5 == h_md5},
        # 旧键名，下游消费者 = backend/reports/w8/t38_assemble.py:195；语义 = 上面两链同时为真
        "three_way_equal": c_md5 == w_md5 == h_md5,
        "ruler": "三面同一算法：LF 归一后逐文件 md5 ＋「md5 + 两个空格 + 相对路径」整段列表再取 md5",
        "note": ("🔻 旧版聚合尺因容器侧带 `./` 前缀而三列永不相等 ⇒ 当时的『不等』不构成证据；"
                 "本字段换代后才有判别力。逐件面 `layer1_2.files` 是独立第二把尺，两把相互印证。"
                 "🔻 T-42 B：相等按 `two_links` 两链引，不写『三面相等』——链一（容器 ⟷ 工作树）是这把尺量到的，"
                 "链二（工作树 ⟷ HEAD）另由 `worktree_vs_head` ＋ 跑前 `worktree_dirty_at_attest` 供给。"),
    }


def attest_layer3(container: str) -> dict[str, object]:
    code = (
        f"import json,{LAYER3_MODULE} as m;"
        f"print(json.dumps({{'present': hasattr(m, '{LAYER3_SYMBOL}'),"
        f"'size': len(getattr(m, '{LAYER3_SYMBOL}', []) or [])}}))"
    )
    out = _run(["docker", "exec", container, "python", "-c", code])
    return {"module": LAYER3_MODULE, "symbol": LAYER3_SYMBOL, **json.loads(out.splitlines()[-1])}


#: 层 2 表里的**钉住真值**（`docs/07 §16.5`，现读该行：`33675b9` 的 blob ⇒ LF、md5 = 下面这串）。
#: `--self-test` 用它证明"git 这面确实参与比较"——固定历史 rev，不随 HEAD 漂移。
ANCHOR_REV = "33675b9"
ANCHOR_PATH = "backend/app/graph/state.py"
ANCHOR_LF_BLOB_MD5 = "0474ef6af7e32345b538456c28735513"


def _blob_md5_via_cat_file(rev: str, rel: str) -> tuple[str, int]:
    """第二条独立取面路径：`rev-parse <rev>:<path>` 拿 blob sha ⇒ `cat-file blob` 拿字节。

    自测用**另一条命令**对拍，才不会和 `_git_bytes("show", …)` 一起坏在同一处（同路自证 = 假绿）。
    """
    sha = _run(["git", "rev-parse", f"{rev}:{rel}"])
    p = subprocess.run(["git", "cat-file", "blob", sha], cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"cat-file 失败 rc={p.returncode}: {p.stderr[-200:].decode('utf-8', 'replace')}")
    return _lf_md5(p.stdout), len(p.stdout)


def self_test() -> int:
    """零额度、零 docker、零网络的尺自检：三条臂全 PASS 才 rc 0（形状照 `backend/tests/contract/` 那几件）。"""
    arms: list[tuple[str, bool, str]] = []

    # 臂 1｜钉住真值：`ANCHOR_REV` 的 blob（LF 归一、不 strip）必须等于 §16.5 表里那串。
    try:
        got, size = _blob_md5_via_cat_file(ANCHOR_REV, ANCHOR_PATH)
        show_face = _lf_md5(_git_bytes("show", f"{ANCHOR_REV}:{ANCHOR_PATH}"))
        arms.append((
            "anchor_blob_md5",
            got == ANCHOR_LF_BLOB_MD5 and show_face == ANCHOR_LF_BLOB_MD5,
            f"cat-file={got} show={show_face} 钉住值={ANCHOR_LF_BLOB_MD5} blob字节={size}",
        ))
    except SystemExit as exc:
        arms.append(("anchor_blob_md5", False, f"锚点不在场：{exc}"))

    # 臂 2｜两条独立 git 取面路径对拍（HEAD 上两件真文件）。
    cross, agree = [], True
    for rel in ("backend/app/api/ratelimit.py", ANCHOR_PATH):
        via_show = _lf_md5(_git_bytes("show", f"HEAD:{rel}"))
        via_cat, _ = _blob_md5_via_cat_file("HEAD", rel)
        agree = agree and via_show == via_cat
        cross.append(f"{rel.split('/')[-1]}: show={via_show} cat-file={via_cat}")
    arms.append(("two_git_paths_agree", agree, " ‖ ".join(cross)))

    # 臂 3｜尺的判别力（负例）：结尾换行被 strip 掉必须改变 md5 ⇒ 若谁把 `.strip()` 加回 blob 那一路，本臂红。
    payload = b"import json\nx = 1\n"
    arms.append((
        "trailing_newline_is_significant",
        _lf_md5(payload) != _md5(payload.strip()),
        f"raw={_lf_md5(payload)} stripped={_md5(payload.strip())}（两者必须不等，否则本自检无判别力）",
    ))

    bad = [name for name, ok, _ in arms if not ok]
    for name, ok, detail in arms:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ｜ {detail}")
    print(f"self-test: {len(arms) - len(bad)}/{len(arms)} PASS" + (f" ｜ 红在 {bad}" if bad else "（零 docker／零出站）"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt")
    ap.add_argument("--container", default="w7load-api")
    ap.add_argument("--files", default=",".join(DEFAULT_FILES))
    ap.add_argument("--self-test", action="store_true", help="只自检尺本身：不碰容器、不发任何出站请求")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.receipt:
        ap.error("非 --self-test 模式必须给 --receipt")

    head_rev = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    image_ref = _run(["docker", "inspect", "--format", "{{.Config.Image}}", args.container])
    created = _run(["docker", "inspect", "--format", "{{json .Created}}", args.container]).strip('"')
    image_id = _run(["docker", "inspect", "--format", "{{.Image}}", args.container])
    tag_id = _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}", "w7load-api"])
    lines = [l for l in tag_id.split("\n") if "w7load-api" in l]

    block = {
        "attested_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "container": args.container,
        "image_ref": image_ref,
        "image_id": image_id,
        "container_created_at": created,
        "image_tags_seen": lines,
        "head_rev": head_rev,
        "head_rev_short": head_rev[:7],
        "worktree_dirty_at_attest": dirty,
        "layer1_2": {
            "files": [attest_file(args.container, f.strip(), head_rev) for f in args.files.split(",") if f.strip()],
            "app_tree_aggregate": attest_tree(args.container, head_rev),
        },
        "layer3_behavior": attest_layer3(args.container),
        "why_this_matters": "落库面没有构建身份列（07 §4.8 的 U-129 行尾上限）⇒ 当期性只能由这一格自证",
        "claim_shape": ("两链并报：链一「容器 ⟷ 工作树字节」= 逐件 verdict ＋ 聚合 two_links.container_vs_worktree；"
                        "链二「工作树 ⟷ HEAD」= 逐件 worktree_vs_head_lf ＋ 聚合 two_links.worktree_vs_head ＋ "
                        "worktree_dirty_at_attest。🚫 本件不产出『三面相等』这句"),
    }

    receipt = json.load(open(args.receipt, encoding="utf-8"))
    receipt["build_identity"] = block
    with open(args.receipt, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    files = block["layer1_2"]["files"]
    same = sum(1 for f in files if f["verdict"] == "SAME")
    w2h = sum(1 for f in files if f["worktree_vs_head_lf"] == "SAME")
    agg = block["layer1_2"]["app_tree_aggregate"]
    links = agg["two_links"]
    print(f"build_identity 写入 {args.receipt}｜逐件 SAME {same}/{len(files)}"
          f"（链二 工作树⟷HEAD {w2h}/{len(files)}）"
          f"｜聚合 链一={links['container_vs_worktree']} 链二={links['worktree_vs_head']}"
          f"（{agg['files_count_container']}/{agg['files_count_git']} 件）"
          f"｜层3 present={block['layer3_behavior']['present']}｜HEAD {head_rev[:7]} dirty={dirty}")
    return 0 if (same == len(files) and links["container_vs_worktree"]
                 and block["layer3_behavior"]["present"]) else 1


if __name__ == "__main__":
    sys.exit(main())
