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


def attest_tree(container: str, head_rev: str) -> dict[str, object]:
    """聚合尺：对 `app/**.py` 排序后逐文件 md5 再取一次 md5（行尾按容器里的原字节）。

    ⚠️ 已知失真面（`07 §16.5` 层 2 那条）：镜像里的行尾 = **构建那一秒工作副本的字节**，
    与 git 存的 LF 无关 ⇒ 聚合值只用于"两边同形不同批次"的粗筛，逐件仍以 `attest_file` 为准。
    """
    rels = [l for l in _git("ls-files", "backend/app").split("\n") if l.endswith(".py")]
    container_line = _run(
        ["docker", "exec", container, "sh", "-c",
         f"cd {CONTAINER_APP_DIR} && find . -name '*.py' | sort | xargs md5sum | md5sum"]
    ).split()[0]
    work_lines = "\n".join(f"{_md5(open(os.path.join(ROOT, r), 'rb').read())}  {r.split('backend/app/', 1)[1]}"
                           for r in sorted(rels, key=lambda x: x.split("backend/app/", 1)[1]))
    head_lines = "\n".join(
        f"{_md5((_git('show', f'{head_rev}:{r}')).replace(chr(13) + chr(10), chr(10)).encode())}  {r.split('backend/app/', 1)[1]}"
        for r in sorted(rels, key=lambda x: x.split("backend/app/", 1)[1])
    )
    return {
        "files_count_git": len(rels),
        "container_aggregate_md5": container_line,
        "worktree_raw_aggregate_md5": _md5(work_lines.encode()),
        "head_blob_lf_aggregate_md5": _md5(head_lines.encode()),
        "note": "容器侧是 raw 字节、git 侧是 LF blob ⇒ 聚合值不保证相等；逐件面见 layer1_2.files",
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
    print(f"build_identity 写入 {args.receipt}｜逐件 SAME {same}/{len(block['layer1_2']['files'])}"
          f"｜层3 present={block['layer3_behavior']['present']}｜HEAD {head_rev[:7]} dirty={dirty}")
    return 0 if same == len(block["layer1_2"]["files"]) and block["layer3_behavior"]["present"] else 1


if __name__ == "__main__":
    sys.exit(main())
