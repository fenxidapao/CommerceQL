#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QA R31ab · W8「复算入口」机械审计（只读、零出站、零花费）

目的：把「尺坏了」这一类缺陷从**逐轮偶遇**改成**机械扫**。
背景：连续三轮各撞一次同族缺陷 ——
  ① 第 37 轮 §34.4「自指死尺」（pattern 恒命中它自己）
  ② 第 38 轮 §34.4「括号内两条条件照字面核不上」
  ③ 第 38 轮 §38.4「入口预期值『各 2』实跑 = 3」
本脚本只跑**只读**入口（grep / git log / python 读文件），逐条对比「写着的预期」与「实跑值」。

禁止：任何写入、任何 psql 非 begin-rollback、任何脚本执行（如 t51_collect.py —— 那条**真打**，约 ¥0.023，绝不在本审计内跑）。
"""
import io
import os
import subprocess
import sys

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)


BASH = r"C:/Users/林琪荣/.workbuddy/binaries/PortableGit/versions/1.3.0/bin/bash.exe"


def run(cmd):
    """跑一条只读命令，返回 (rc, stdout 摘要)。

    🔴 必须显式走 bash：Windows 上 subprocess(shell=True) 默认用 cmd.exe，
       单引号 / 双引号 / 反斜杠转义语义全不同 ⇒ 会造出**假 FAIL**。
       （本脚本首版就踩了：E-13/E-15/E-16..E-19/E-21 全是尺的锅，不是被审对象的锅。）
    """
    r = subprocess.run([BASH, "-lc", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    # 🔴 返回**完整**输出：首版在这里先截断到 300 字符再判定 ⇒ 长行被切掉换行符，
    #    "命中行数" 恒算成 1 ⇒ 又造出 4 个假 FAIL（E-16..E-19）。截断只许用于**打印**。
    return r.returncode, (r.stdout or "").strip()


def brief(out, n=300):
    return out[:n] + " …" if len(out) > n else out


def selftest():
    """🔴 尺自检：先证明本尺能看见**已知存在**的目标，否则一切判定无效。"""
    checks = [
        ("grep -c 'open 集 = 十一枚' OVERVIEW.md", "1"),
        ("git rev-parse --short HEAD", None),
    ]
    ok = True
    print("--- 尺自检（先证明能看见目标）---")
    for cmd, want in checks:
        rc, out = run(cmd)
        good = (rc == 0) and (want is None or out.strip() == want)
        print(f"  [{'OK ' if good else 'BAD'}] {cmd} → rc={rc} out={out[:60]!r}")
        ok = ok and good
    print(f"  尺自检 = {'通过' if ok else '**不通过 ⇒ 下面判定全部作废**'}")
    print()
    return ok


def read(p):
    return io.open(p, encoding="utf-8").read()


CASES = [
    # (编号, 出处, 写的预期, 命令, 判定器)
    ("E-01", "§26.5 :3199",
     "grep '候选不超过 4' PRD 应有命中",
     r'''grep -n '候选不超过 4' docs/01_需求规格说明书_PRD.md''',
     lambda rc, o: (rc == 0 and '候选不超过 4' in o, "有命中" if rc == 0 else "零命中")),

    ("E-02", "§26.5 :3199",
     "semantic 包里 candidates 数 ≥2 者 = 1",
     r'''grep -n 'candidates' semantic/bundle_2026.09.14.1.yaml''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-03", "§26.5 :3199",
     "spend_cny 两件都能 grep 到",
     r'''grep -n spend_cny backend/reports/w8/t51_stage1_city_only*.json''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-04", "§27.2 :3226",
     "grep 'Decimal(str' t51_collect.py 有命中（订正后那句）",
     r'''grep -n "Decimal(str" backend/reports/w8/t51_collect.py''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-05", "§28.6 :3289",
     "grep 'query_plan_writer=None' eval/harness.py 有命中",
     r'''grep -n 'query_plan_writer=None' eval/harness.py''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-06", "§28.6 :3290",
     "grep 'score_l4' bind.py 有命中",
     r'''grep -n 'score_l4' backend/app/graph/nodes/bind.py''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-07", "§29.4 :3346",
     "指针行应 = U-142（**该轮时点**）",
     r'''grep -n "^> \*\*下一个可用号" docs/07_技术设计文档_TDD.md''',
     None),

    ("E-08", "§29.4 :3346",
     "grep -c '^| **U-141** |' 应 = 1",
     r'''grep -c "^| \*\*U-141\*\* |" docs/07_技术设计文档_TDD.md''',
     lambda rc, o: (o.strip() == "1", "= " + o.strip())),

    ("E-09", "§30.3 :3392",
     "grep '只读末节' PROMPT.md 有命中",
     r'''grep -n '只读末节' backend/reports/w8/PROMPT.md''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-10", "§30.3 :3392",
     "grep '第 32 轮计数粒度订正' docs/07 有命中",
     r'''grep -n '第 32 轮计数粒度订正' docs/07_技术设计文档_TDD.md''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-11", "§31.4 :3459",
     "指针行应 = U-143",
     r'''grep -n "^> \*\*下一个可用号" docs/07_技术设计文档_TDD.md''',
     lambda rc, o: ("U-143" in o, "含 U-143" if "U-143" in o else "不含 U-143")),

    ("E-12", "§31.4 :3459",
     "grep -c '^| **U-142** |' 应 = 1",
     r'''grep -c "^| \*\*U-142\*\* |" docs/07_技术设计文档_TDD.md''',
     lambda rc, o: (o.strip() == "1", "= " + o.strip())),

    ("E-13", "§32.5 :3519",
     "43eb8b0 的父 = 6bd9d20",
     r'''git log -1 --format='%h %p' 43eb8b0''',
     lambda rc, o: ("6bd9d20" in o, o[:40])),

    ("E-14", "§32.5 :3519",
     "grep '第 34 轮日期订正' docs/07 有命中",
     r'''grep -n '第 34 轮日期订正' docs/07_技术设计文档_TDD.md''',
     lambda rc, o: (rc == 0, "有命中" if rc == 0 else "零命中")),

    ("E-15", "§33.4 :3568",
     "count('2026-10-13') 应 = 9",
     r'''./.venv/Scripts/python.exe -c "import pathlib;print(pathlib.Path('docs/07_技术设计文档_TDD.md').read_text(encoding='utf-8').count('2026-10-13'))"''',
     lambda rc, o: (o.strip() == "9", "= " + o.strip())),

    ("E-16", "§34.4 :3619",
     "grep -n 'open 集 = 十一枚' 两件**各 1 处**",
     r'''grep -n 'open 集 = 十一枚' OVERVIEW.md deliverables/ACCEPTANCE.md''',
     lambda rc, o: (o.count("\n") + 1 == 2, f"命中行数 = {o.count(chr(10)) + 1}")),

    ("E-17", "§35.5 :3676",
     "grep 'docs/07:1190' 两件**各 1**",
     r'''grep -n 'docs/07:1190' OVERVIEW.md deliverables/ACCEPTANCE.md''',
     lambda rc, o: (o.count("\n") + 1 == 2, f"命中行数 = {o.count(chr(10)) + 1}")),

    ("E-18", "§35.5 :3676",
     "grep 'docs/07:1191' 两件**各 1**",
     r'''grep -n 'docs/07:1191' OVERVIEW.md deliverables/ACCEPTANCE.md''',
     lambda rc, o: (o.count("\n") + 1 == 2, f"命中行数 = {o.count(chr(10)) + 1}")),

    ("E-19", "§35.5 :3676",
     "grep '缺载体（功能缺口）' 两件**各 1**",
     r'''grep -n '缺载体（功能缺口）' OVERVIEW.md deliverables/ACCEPTANCE.md''',
     lambda rc, o: (o.count("\n") + 1 == 2, f"命中行数 = {o.count(chr(10)) + 1}")),

    ("E-20", "§38.4 :3726",
     "grep -c '**④**' 两件**各 2**",
     r'''grep -c '\*\*④\*\*' OVERVIEW.md deliverables/ACCEPTANCE.md''',
     lambda rc, o: (all(x.strip() == "2" for x in o.split("\n") if x.strip()),
                    o.replace("\n", " | "))),

    ("E-21", "§38.4 :3726",
     "len(open 集行) 应 = 836",
     r'''./.venv/Scripts/python.exe -c "import pathlib;print(len([l for l in pathlib.Path('OVERVIEW.md').read_text(encoding='utf-8').split(chr(10)) if l.startswith('- **open 集 = 十一枚**')][0]))"''',
     lambda rc, o: (o.strip() == "836", "= " + o.strip())),
    ("E-22", "§22.x :2981",
     "件内自报 meta.git.rev 应 = 88f3500（入库笔天然差一笔）",
     r'''./.venv/Scripts/python.exe -c "import json;d=json.load(open('backend/reports/w6/eval_metrics.json',encoding='utf-8'));print(d['meta']['git']['rev'])"''',
     lambda rc, o: (o.strip() == "88f3500", "= " + o.strip())),
]

# 🔴 未审清单（诚实登记：以下入口**本轮未跑**，逐条给理由）
UNTESTED = [
    ("§19.8 :2697", "跑 deploy/loadtest/attest_build_identity.py ＋ 对运行容器 docker exec ⇒ 越本窗边界（不动容器/不跑 deploy 脚本）"),
    ("§20.9 :2811", "t43_readings.py **会写盘**（产物 backend/reports/w8/evidence/t43/*.json）⇒ 属 W8 写面，本窗不写"),
    ("§21.10 :2936", "t38_assemble.py ＋ docker exec psql -f SQL 文件 ⇒ 跑脚本 ＋ 动容器"),
    ("§22.7 :3013", "eval/reporter.py 执行 ⇒ 跑 W8 脚本（输出虽在仓库外，仍属执行）"),
    ("§23.x :3066", "执行 backend/reports/w8/_audit_layout.py ⇒ 跑 W8 脚本"),
    ("§24.3 :3101", "t50_reason_probe.py ＋ pytest ⇒ 跑 W8 脚本/测试"),
    ("§25.5 :3148", "🔴 **t51_collect.py 真打 15 次 ≈ ¥0.023** ⇒ **零额度，绝对不跑**"),
]


def main():
    print("=" * 78)
    print("QA R31ab · W8 复算入口机械审计（只读 / 零出站 / 零花费）")
    print(f"HEAD = {subprocess.run(['git','rev-parse','--short','HEAD'],capture_output=True,text=True).stdout.strip()}")
    print("=" * 78)
    if not selftest():
        print("🔴 尺自检未过，审计中止（不得据坏尺下判断）")
        return 2
    bad = []
    for cid, src, expect, cmd, judge in CASES:
        rc, out = run(cmd)
        if judge is None:
            ok, note = None, (out.split("\n")[0][:60] if out else "(空)")
        else:
            ok, note = judge(rc, out)
        flag = "—" if ok is None else ("PASS" if ok else "**FAIL**")
        print(f"[{cid}] {src}")
        print(f"     写的预期 : {expect}")
        print(f"     实跑     : rc={rc} | {brief(str(note))}")
        print(f"     判定     : {flag}")
        print()
        if ok is False:
            bad.append((cid, src, expect, note))
    print("=" * 78)
    print(f"合计 {len(CASES)} 条；**不成立 = {len(bad)}**")
    print()
    print(f"--- 未审 {len(UNTESTED)} 条（诚实登记，逐条理由）---")
    for src, why in UNTESTED:
        print(f"  ⏭ {src}｜{why}")
    for cid, src, expect, note in bad:
        print(f"  🔴 {cid} {src}｜写的预期 = {expect}｜实跑 = {note}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
