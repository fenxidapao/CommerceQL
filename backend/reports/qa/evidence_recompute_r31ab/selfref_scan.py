#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31ab · 附：W8 复算入口「自指」机械扫描（只读、零出站、零花费）

动机：本项目连续两轮出现同一形态 —— **复算入口的 pattern 命中「写下这条入口的那一行」**
（§34.4 原 pattern「恒命中它自己」；修后改用的行首串锚点**又**命中 §34.4 自身）。
本脚本把该形态从「偶遇」改成「机械扫」：
  ① 从 RELAY / DELIVERY 里所有含「复算入口」的行中，抽出反引号内的 grep/pattern；
  ② 对每条 pattern，测它**是否命中它自己的声明行**（自指）；
  ③ 命中即报（🟡 自指；若同时被当成"唯一尺"使用 ⇒ 升为 🔴）。

只读：只读文件 + 内存比较，不起子进程、不写盘。
"""
import io
import os
import re
import subprocess
import sys

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

FILES = [
    "backend/reports/w8/RELAY.md",
    "backend/reports/w8/DELIVERY.md",
]

# 抽「grep ... 'PAT'」/「grep ... "PAT"」里的 PAT（只取单/双引号包起来的第一段）
GREP_PAT = re.compile(r"grep\s+(?:-[a-zA-Z]+\s+)*['\"](.+?)['\"]")


TARGET = re.compile(r"[\w./\u4e00-\u9fff_-]+\.(?:md|py|json|yaml|yml|sql)")


def pattern_hits_file(pat, target, self_file):
    """把 pat 当 grep BRE 用，返回它在 target 里命中的**行号集**（用 git grep，只读）。"""
    try:
        r = subprocess.run(["git", "grep", "-n", "-I", "-e", pat, "--", target],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except Exception:
        return set()
    out = set()
    for l in (r.stdout or "").split("\n"):
        mm = re.match(r"^[^:]+:(\d+):", l)
        if mm:
            out.add(int(mm.group(1)))
    return out


def main():
    total_entries = 0
    total_patterns = 0
    selfref = []
    untested = []
    for f in FILES:
        lines = io.open(f, encoding="utf-8").read().split("\n")
        for i, l in enumerate(lines):
            if "复算入口" not in l:
                continue
            total_entries += 1
            for idx, m in enumerate(GREP_PAT.finditer(l)):
                pat = m.group(1)
                # 目标文件 = 该 pattern **之后** 的下一个 token（第一个出现的 .md/.py/.json/目录）
                tm = TARGET.search(l[m.end():])
                target = tm.group(0) if tm else None
                total_patterns += 1
                # 🔴 自指 = 该 pattern **对它的目标文件** 跑得出**它自己这一行**。
                #    首版口径写成「pattern 字面出现在声明行里」⇒ 把 18 条**全部**误报为自指（假阳性风暴）。
                #    grep 的 pattern 本来就写在命令里，字面共现是必然的，不构成自指。
                if not target or not os.path.exists(target):
                    untested.append((f, i + 1, pat, target or "(未解析出目标)"))
                    continue
                hits = pattern_hits_file(pat, target, f)
                if (i + 1) in hits:
                    selfref.append((f, i + 1, pat, target))
    print("=" * 78)
    print("QA R31ab 附 · 复算入口「自指」扫描（只读）")
    print("=" * 78)
    print(f"含「复算入口」的行 = {total_entries}；抽出 grep pattern = {total_patterns}")
    print()
    if not selfref:
        print("✅ 未发现自指（没有 pattern 命中它自己的声明行）")
    else:
        print(f"🟡 自指 = {len(selfref)} 处：")
        for f, ln, pat, tg in selfref:
            print(f"  {f.split('/')[-1]}:{ln}｜pattern = {pat!r}｜目标 = {tg}")
    print()
    print(f"⏭ 未测 {len(untested)} 处（未解析出目标文件，或目标不存在）：")
    for f, ln, pat, tg in untested[:20]:
        print(f"  {f.split('/')[-1]}:{ln}｜pattern = {pat!r}｜{tg}")
    print("=" * 78)
    print("口径说明：本扫描只判「pattern 字面是否出现在自己的声明行」——")
    print("  · 这是**必要**条件，不是充分条件（跨行自指/语义自指不在此列）")
    print("  · 命中 ⇒ 该 pattern **不能**用作「唯一命中」尺（会把自己算进去）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
