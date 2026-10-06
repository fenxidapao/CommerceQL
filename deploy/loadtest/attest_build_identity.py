"""给压测回执补「构建身份」自证面（`07 §16.5` 三层证据 ｜ T-35 主单硬要求 (b)）。

零额度、只读：只做 `docker exec` + `git show` + 本地哈希，不发任何 LLM 请求。

三层从弱到强（缺任何一层都可能给出假结论）：

| 层 | 证据 | 判得住什么 |
|---|---|---|
| 1 | 单文件容器 md5 == 工作树 == HEAD blob | 只证**那一个文件**（没被改过的文件无判别力） |
| 2 | 逐文件**行尾归一**后比 md5（raw / LF / CRLF 都试）＋ 全 `app/**.py` 聚合 | 字节级"内容 == 某 revision" |
| 3 | 容器内 `import` 一个**只有新构建才存在**的符号 | 改动在不在这个构建里（不依赖字节） |

用法：

    python deploy/loadtest/attest_build_identity.py --receipt deploy/loadtest/healthy_xxx.json \
        [--container w7load-api] [--files backend/app/graph/state.py,...]

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
    work = open(os.path.join(ROOT, rel), "rb").read()
    blob = (_git("show", f"{head_rev}:{rel}")).replace("\r\n", "\n").encode()
    in_container = _container_md5(container, f"{CONTAINER_APP_DIR}/{rel.split('backend/app/', 1)[1]}")
    variants = {
        "worktree_raw": _md5(work),
        "worktree_lf": _md5(work.replace(b"\r\n", b"\n")),
        "head_blob_lf": _md5(blob),
    }
    hit = [k for k, v in variants.items() if v == in_container]
    return {
        "path": rel,
        "container_md5": in_container,
        "matched_variant": hit[0] if hit else None,
        "variants": variants,
        "verdict": "SAME" if hit else "DIFF",
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
        "three_way_equal": c_md5 == w_md5 == h_md5,
        "ruler": "三面同一算法：LF 归一后逐文件 md5 ＋「md5 + 两个空格 + 相对路径」整段列表再取 md5",
        "note": ("🔻 旧版聚合尺因容器侧带 `./` 前缀而三列永不相等 ⇒ 当时的『不等』不构成证据；"
                 "本字段换代后才有判别力。逐件面 `layer1_2.files` 是独立第二把尺，两把相互印证。"),
    }


def attest_layer3(container: str) -> dict[str, object]:
    code = (
        f"import json,{LAYER3_MODULE} as m;"
        f"print(json.dumps({{'present': hasattr(m, '{LAYER3_SYMBOL}'),"
        f"'size': len(getattr(m, '{LAYER3_SYMBOL}', []) or [])}}))"
    )
    out = _run(["docker", "exec", container, "python", "-c", code])
    return {"module": LAYER3_MODULE, "symbol": LAYER3_SYMBOL, **json.loads(out.splitlines()[-1])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--container", default="w7load-api")
    ap.add_argument("--files", default=",".join(DEFAULT_FILES))
    args = ap.parse_args(argv)

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
    }

    receipt = json.load(open(args.receipt, encoding="utf-8"))
    receipt["build_identity"] = block
    with open(args.receipt, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    same = sum(1 for f in block["layer1_2"]["files"] if f["verdict"] == "SAME")
    agg = block["layer1_2"]["app_tree_aggregate"]
    print(f"build_identity 写入 {args.receipt}｜逐件 SAME {same}/{len(block['layer1_2']['files'])}"
          f"｜聚合三面 equal={agg['three_way_equal']}"
          f"（{agg['files_count_container']}/{agg['files_count_git']} 件）"
          f"｜层3 present={block['layer3_behavior']['present']}｜HEAD {head_rev[:7]} dirty={dirty}")
    return 0 if (same == len(block["layer1_2"]["files"]) and agg["three_way_equal"]
                 and block["layer3_behavior"]["present"]) else 1


if __name__ == "__main__":
    sys.exit(main())
