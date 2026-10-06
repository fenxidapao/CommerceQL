r"""文档表格排版尺（只读）：格数只数**未转义**竖线；期望取自**该表块自己的分隔行**。

用法：python audit_layout.py <文件> [段标题前缀]     （不给段标题 = 全文件）
异常必须分类「被检节之前（既有史料）」vs「之内（本轮新增）」，否则下一轮会把别人的残行算成我的漏改。
"""
import re
import sys
from pathlib import Path

target = Path(sys.argv[1])
mark = sys.argv[2] if len(sys.argv) > 2 else None
raw = target.read_bytes()
lines = raw.decode("utf-8").split("\n")
PIPE = re.compile(r"(?<!\\)\|")
SEP = re.compile(r"^\|[\s:|-]+\|$")


def cells(row: str) -> int:
    return len(PIPE.findall(row.strip())) - 1


start = next((i for i, ln in enumerate(lines, 1) if mark and ln.startswith(mark)), None)
if mark:
    print(f"段标题命中数（必须 1）= {sum(1 for ln in lines if ln.startswith(mark))} ｜ 起始行 = {start}")
print(f"bytes = {len(raw)} ｜ CRLF = {raw.count(bytes([13, 10]))} ｜ lines = {len(lines)}")

problems, tables, i = [], 0, 0
while i < len(lines):
    if lines[i].strip().startswith("|"):
        j = i
        while j < len(lines) and lines[j].strip().startswith("|"):
            j += 1
        tables += 1
        if j - i < 2:
            problems.append((i + 1, f"孤立表行（块只有 1 行）｜ {lines[i].strip()[:60]}"))
        elif not SEP.match(lines[i + 1].strip()):
            problems.append((i + 1, f"第 2 行不是分隔行 ｜ {lines[i + 1].strip()[:60]}"))
        else:
            want = cells(lines[i + 1])
            for n in range(i, j):
                if cells(lines[n]) != want:
                    problems.append((n + 1, f"格数 {cells(lines[n])} ≠ 分隔行 {want} ｜ {lines[n].strip()[:50]}"))
        i = j
    else:
        i += 1

in_scope = [(n, m) for n, m in problems if not start or n >= start]
out_scope = [(n, m) for n, m in problems if start and n < start]
print(f"表块 = {tables} ｜ 问题合计 = {len(problems)} ｜ 被检节之内(新增) = {len(in_scope)} ｜ 之前(既有) = {len(out_scope)}")
for n, m in in_scope[:12]:
    print(f"  ✗ {n}: {m}")
blank, triples = 0, []
for n, ln in enumerate(lines, 1):
    if ln.strip() == "":
        blank += 1
    else:
        if blank >= 3:
            triples.append(n - 1)
        blank = 0
print(f"三连空行 = {len(triples)}" + ("".join(f" ｜ line {t}（{'本节内' if start and t >= start else '本节前既有'}）" for t in triples[:6])))
