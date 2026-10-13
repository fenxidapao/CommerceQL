# -*- coding: utf-8 -*-
"""R31e: A 表 117 条需求四段对表 —— 第一轮机械证据扫描（零额度、纯读）。

只读仓库；唯一写面 = 本 scratch 目录（E:/tmp_qoder/qa_r31e/）。
输出：
  req_inventory.json  全量数据（需求清单 + 每条的四段引用）
  req_scan.md         人读摘要（分布 + 逐条表）
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(r"E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL")
OUT = Path(r"E:\tmp_qoder\qa_r31e")
OUT.mkdir(parents=True, exist_ok=True)

DOC01 = REPO / "docs" / "01_需求规格说明书_PRD.md"

ID_RE = re.compile(r"(?<![A-Za-z])((?:FR|NFR)-\d+\.\d+)(?![0-9])")
CELL_ID_RE = re.compile(r"^\*{0,2}((?:FR|NFR)-\d+\.\d+)\*{0,2}$")


def split_row(line: str):
    """按 GFM 切表行；先保护转义竖线。返回 cell list 或 None。"""
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s.strip("|")
    protected = s.replace("\\|", "\x00")
    cells = [c.strip().replace("\x00", "|") for c in protected.split("|")]
    return cells


def parse_requirements():
    """尺与 COMPLETENESS.md:14 同：表首列为 FR/NFR-x.y 的行 + 闸门表第二列 FR-5.x。"""
    text = DOC01.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    reqs = {}
    dup = []
    for i, line in enumerate(lines, 1):
        cells = split_row(line)
        if not cells or len(cells) < 2:
            continue
        m = CELL_ID_RE.match(cells[0])
        rid = None
        src = "table"
        if m:
            rid = m.group(1)
        else:
            # 闸门表：第二列为 FR-5.x（首列是"第 N 道：…"）
            m2 = CELL_ID_RE.match(cells[1])
            if m2 and m2.group(1).startswith("FR-5."):
                rid = m2.group(1)
                src = "gate"
        if not rid:
            continue
        prio = ""
        for c in reversed(cells):
            c2 = c.strip().strip("*").strip()  # 粗体包裹的优先级格：**P0（安全）**
            if re.match(r"^P[01]", c2):
                prio = c2
                break
        if rid in reqs:
            dup.append((rid, reqs[rid]["line"], i))
            continue
        kind = "FR" if rid.startswith("FR-") else "NFR"
        reqs[rid] = {
            "id": rid,
            "kind": kind,
            "prio": prio,
            "src": src,
            "line": i,
            "text": (cells[1] if src == "table" else cells[2])[:160],
        }
    return reqs, dup


def area_of(rel: str) -> str:
    if rel.startswith("docs/07"):
        return "docs07"
    if rel.startswith("docs/"):
        return "docs"
    if rel.startswith("backend/app/"):
        return "app"
    if rel.startswith("backend/tests/"):
        return "tests"
    if rel.startswith("frontend/"):
        base = rel.rsplit("/", 1)[-1]
        if ".test." in base or ".spec." in base or "/tests/" in rel:
            return "fe_tests"
        return "frontend"
    if rel.startswith("eval/"):
        return "eval"
    if rel.startswith("deploy/"):
        return "deploy"
    if rel.startswith("backend/reports/"):
        return "reports"
    if rel.startswith(".github/"):
        return "ci"
    if rel in ("OVERVIEW.md", "deliverables/ACCEPTANCE.md"):
        return "external"
    if rel.startswith("semantic/"):
        return "semantic"
    if rel.startswith("data/"):
        return "data"
    if rel.startswith("_refs/"):
        return "refs"
    return "other"


def scan(reqs):
    # 🔴 core.quotePath=false：默认 true 会把非 ASCII 路径转义成八进制（"docs/01_\351..."），
    # 既匹配不了前缀也在盘上解析失败 ⇒ 上一版静默跳过 14 个文件（含全部 docs/）。
    r = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=str(REPO), capture_output=True,
    )
    if r.returncode != 0:
        print("git ls-files FAILED", r.stderr[:500])
        sys.exit(2)
    files = [f for f in r.stdout.decode("utf-8", errors="replace").splitlines() if f.strip()]
    hits = defaultdict(lambda: defaultdict(list))  # id -> area -> [(file, line)]
    area_files = defaultdict(set)
    n_files = 0
    skipped = []
    for rel in files:
        p = REPO / rel
        try:
            if p.stat().st_size > 3_000_000:
                skipped.append((rel, "too_big", p.stat().st_size))
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError) as e:
            skipped.append((rel, type(e).__name__, 0))
            continue
        n_files += 1
        area = area_of(rel)
        area_files[area].add(rel)
        for ln, line in enumerate(raw.splitlines(), 1):
            for m in ID_RE.finditer(line):
                rid = m.group(1)
                if rid in reqs:
                    hits[rid][area].append((rel, ln))
    return hits, area_files, n_files, len(files), skipped


def main():
    reqs, dup = parse_requirements()
    fr = [r for r in reqs.values() if r["kind"] == "FR"]
    nfr = [r for r in reqs.values() if r["kind"] == "NFR"]
    print(f"REQS total={len(reqs)} FR={len(fr)} NFR={len(nfr)} dup={dup}")
    print("FR prio dist:", defaultdict(int, {p: sum(1 for r in fr if r['prio'] == p) for p in sorted({r['prio'] for r in fr})}))
    print("NFR prio dist:", defaultdict(int, {p: sum(1 for r in nfr if r['prio'] == p) for p in sorted({r['prio'] for r in nfr})}))
    print("FR src dist:", defaultdict(int, {s: sum(1 for r in fr if r['src'] == s) for s in sorted({r['src'] for r in fr})}))

    hits, area_files, n_read, n_tracked, skipped = scan(reqs)
    print(f"files tracked={n_tracked} read={n_read} skipped={n_tracked - n_read}")
    for s in skipped:
        print("  SKIPPED:", s)
    for a in sorted(area_files):
        print(f"  area {a}: {len(area_files[a])} files")

    # 每条汇总（细粒度区域 + 四段口径）
    # 四段口径（与 COMPLETENESS.md 对表定义同）：
    #   S1 设计节 = docs/07（TDD）；S2 实现 = app + frontend；
    #   S3 测试 = tests + fe_tests + eval；S4 文档 = docs 全家（含 07）
    rows = []
    for rid in sorted(reqs, key=lambda x: (x.split("-")[0], [int(t) for t in x.split("-")[1].split(".")])):
        h = hits.get(rid, {})
        seg = {
            "docs07": len(h.get("docs07", [])),
            "docs": len(h.get("docs", [])) + len(h.get("docs07", [])),
            "app": len(h.get("app", [])),
            "frontend": len(h.get("frontend", [])),
            "tests": len(h.get("tests", [])) + len(h.get("fe_tests", [])),
            "eval": len(h.get("eval", [])),
            "deploy": len(h.get("deploy", [])),
            "reports": len(h.get("reports", [])),
            "ci": len(h.get("ci", [])),
            "external": len(h.get("external", [])),
            "semantic": len(h.get("semantic", [])),
            "data": len(h.get("data", [])),
            "refs": len(h.get("refs", [])),
            "other": len(h.get("other", [])),
        }
        s1 = seg["docs07"]
        s2 = seg["app"] + seg["frontend"]
        s3 = seg["tests"] + seg["eval"]
        s4 = seg["docs"] - 1  # 剔除 docs/01 定义行自身（dup=[] ⇒ 每条恰有一条定义行）
        roll = {"S1_设计节": s1, "S2_实现": s2, "S3_测试": s3, "S4_文档": s4}
        ex = {a: v[:3] for a, v in h.items()}
        rows.append({"id": rid, "prio": reqs[rid]["prio"], "src": reqs[rid]["src"],
                     "line": reqs[rid]["line"], "text": reqs[rid]["text"],
                     "seg": seg, "roll": roll, "ex": ex})

    (OUT / "req_inventory.json").write_text(
        json.dumps({"reqs": rows, "dup": dup}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # 分布（四段口径）
    def cnt(pred):
        return sum(1 for r in rows if pred(r))
    zero = [r for r in rows if all(v == 0 for v in r["seg"].values())]
    miss_s1 = [r["id"] for r in rows if r["roll"]["S1_设计节"] == 0]
    miss_s2 = [r["id"] for r in rows if r["roll"]["S2_实现"] == 0]
    miss_s3 = [r["id"] for r in rows if r["roll"]["S3_测试"] == 0]
    miss_s4 = [r["id"] for r in rows if r["roll"]["S4_文档"] == 0]
    print(f"ZERO-HIT ids (全仓零引用): {len(zero)} -> {[r['id'] for r in zero]}")
    print(f"缺 S1 设计节(docs/07 零引用): {len(miss_s1)}")
    print(f"缺 S2 实现(app+frontend 零引用): {len(miss_s2)}")
    print(f"缺 S3 测试(tests+eval 零引用): {len(miss_s3)}")
    print(f"缺 S4 文档(docs 全家零引用): {len(miss_s4)}")
    full4 = cnt(lambda r: all(v > 0 for v in r["roll"].values()))
    print(f"四段皆有引用: {full4}")

    with open(OUT / "req_scan.md", "w", encoding="utf-8") as f:
        f.write("# A 表四段对表·第一轮机械证据扫描（R31e，零额度纯读）\n\n")
        f.write(f"- 需求总数 {len(rows)}（FR {len(fr)} / NFR {len(nfr)}）；重复登记行：{dup}\n")
        f.write(f"- 跟踪文件 {n_tracked}，实读 {n_read}\n")
        f.write(f"- 全仓零引用 {len(zero)} 条；四段皆有引用 {full4} 条\n")
        f.write("- 四段口径：S1 设计节 = `docs/07` 引用；S2 实现 = `backend/app`＋`frontend`；"
                "S3 测试 = `backend/tests`＋前端测试＋`eval`；S4 文档 = `docs/**`\n\n")
        f.write("| ID | P | S1 | S2 | S3 | S4 | docs07 | app | frontend | tests | eval | reports | external |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            s, ro = r["seg"], r["roll"]
            f.write(f"| {r['id']} | {r['prio'] or '—'} | {ro['S1_设计节']} | {ro['S2_实现']} | {ro['S3_测试']} | {ro['S4_文档']} "
                    f"| {s['docs07']} | {s['app']} | {s['frontend']} | {s['tests']} | {s['eval']} | {s['reports']} | {s['external']} |\n")
    print("WROTE", OUT / "req_inventory.json", "and req_scan.md")


if __name__ == "__main__":
    main()
