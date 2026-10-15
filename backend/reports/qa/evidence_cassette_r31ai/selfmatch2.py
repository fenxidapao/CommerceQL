# -*- coding: utf-8 -*-
"""自匹配实测 v2（修正循环测试：改动前的行从 git 取）。

纪律记录：v1 拿**改动后**的行去测**改动前**的 pattern ⇒ 那段字面量已被删 ⇒ 循环测试。
"""
import io
import re
import subprocess

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
WS = r"[^ \t\r\n\f\v]"
OLD = "postgres://" + WS + "*:" + WS + "+@\\)"
NEW = "postgres://"

def read_line(ref):
    t = subprocess.run(["git", "show", ref + ":backend/reports/w8/RELAY.md"],
                       capture_output=True, text=True, encoding="utf-8", cwd=REPO).stdout
    for ln, l in enumerate(t.split("\n"), 1):
        if "scan_rc" in l and "grep -lInE" in l:
            return ln, l
    return None, None

pre_n, pre = read_line("bdcd111^")
post_n, post = read_line("HEAD")
print(f"改动前 :{pre_n} = {pre[-70:]!r}")
print(f"改动后 :{post_n} = {post[-70:]!r}")

print("\n--- 尺自检 ---")
print("  OLD 命中 GOOD =", bool(re.search(OLD, "x postgres://u:p@) y")), "(应 True)")
print("  OLD 命中 BAD  =", bool(re.search(OLD, "x postgres://u:p@h) y")), "(应 False)")
assert re.search(OLD, "x postgres://u:p@) y")
print("  ✅ 通过")

print("\n--- 自匹配矩阵（行 × pattern）---")
hdr = f"{'':10s} | {'改动前(OLD)':>12s} | {'改动后(NEW)':>12s}"
print(hdr); print("-" * len(hdr))
for nm, line in (("改动前的行", pre), ("改动后的行", post)):
    a = bool(re.search(OLD, line)); b = bool(re.search(NEW, line))
    print(f"{nm:10s} | {str(a):>12s} | {str(b):>12s}")

print("\n--- 被测集合里是否有该文件 ---")
r = subprocess.run(["git", "diff", "--name-only", "983214c..HEAD"],
                   capture_output=True, text=True, cwd=REPO)
md = [f for f in r.stdout.split("\n") if f.strip() and re.search(r"\.(json|py|md)$", f)]
print("  集合 =", len(md), "| 含 w8/RELAY.md =", any(f.endswith("reports/w8/RELAY.md") for f in md))
