# -*- coding: utf-8 -*-
"""B4 抽样严验：8 条，逐条输出命中行全文供人工判「实质 / 名义 / 无」。

🔴 与 scan_b4.py 的差别：不按关键词聚合，而是**先按需求锁定一个「决定性功能词」**，
   再把该词的全部命中行打出来 —— 让判定者能看见上下文，能判「蹭词」还是「真载体」。
"""
import os, subprocess, sys

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

# 抽样 8 条：5 条「缺 S2,S3」+ 2 条「缺 S3」+ 1 条「缺 S1,S3」
SAMPLES = [
    # (id, 决定性功能词, 该词应出现在哪一面, 期望)
    ("FR-5.1",  "sqlglot",              "S2+S3", "白名单 AST 校验"),
    ("FR-6.2",  "statement_timeout",    "S2+S3", "语句超时"),
    ("FR-12.4", "失效",                 "S2+S3", "语义包版本变更→缓存/few-shot/结果缓存失效"),
    ("FR-13.3", "CREATE POLICY",        "S2+S3", "RLS 在 DB 层强制"),
    ("FR-2.5",  "scope",                "S2+S3", "检索按租户过滤"),
    ("FR-3.3",  "五步",                 "S2",    "绑定解析顺序（缺 S3 组）"),
    ("FR-9.2",  "复用",                 "S2+S3", "澄清后重走全链（缺 S3 组）"),
    ("FR-10.4", "session_id",           "S2+S3", "thread 隔离（缺 S3 组）"),
]


def g(kw, root, maxc=10):
    r = subprocess.run(["git", "grep", "-n", "-I", f"--max-count={maxc}", "-e", kw, "--", root],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [l for l in (r.stdout or "").split("\n") if l.strip()]


for rid, kw, face, desc in SAMPLES:
    print(f"########## {rid} ｜ 决定性词 = `{kw}` ｜ {desc} ##########")
    for root, tag in [("backend/app", "S2"), ("frontend/src", "S2"), ("backend/tests", "S3"), ("eval", "S3")]:
        hits = g(kw, root, 8)
        if not hits:
            continue
        print(f"  --- {tag} / {root}（{len(hits)}）---")
        for h in hits[:8]:
            print("     ", h[:210])
    print()
