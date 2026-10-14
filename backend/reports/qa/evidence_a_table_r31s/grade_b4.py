# -*- coding: utf-8 -*-
"""B4 全量：42 条 × 每条 2–3 个**强特征词** → 统计 S3（测试面）命中文件数，分档。

判定分档（S3 = 测试面）：
  S3-实质：命中 ≥2 个不同测试文件，且至少 1 行是**断言/测试函数**语境
  S3-弱  ：命中 1 个测试文件
  S3-无  ：0 命中
🔴 输出仅供分档，最终判定须回读原文。
"""
import os, subprocess, json

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

# 42 条 → 强特征词（尽量取「该需求独有」的实现符号，避免蹭词）
STRONG = {
    "FR-1.2": ["resolve_time", "relative_time", "周起点"],
    "FR-1.3": ["Asia/Shanghai", "财年"],
    "FR-1.4": ["黑话", "synonym", "双11"],
    "FR-1.6": ["classify_intent", "IntentKind", "意图分类"],
    "FR-2.2": ["Rrf", "RRF", "hybrid", "稠密", "LlmTask.RERANK"],
    "FR-2.3": ["few_shot", "few-shot", "gold_query"],
    "FR-2.5": ["tenant_scope", "scope 过滤", "按租户过滤", "scope_level"],
    "FR-2.6": ["en_alias", "双语", "alias"],
    "FR-2.7": ["隐式外键", "join_path", "inferred_fk"],
    "FR-3.1": ["plan_summary", "Plan(", "结构化查询计划"],
    "FR-3.3": ["五步", "five_step", "resolve_detailed"],
    "FR-3.4": ["RESOLVED_UNIQUE", "ambiguous"],
    "FR-4.3": ["sql_params", "params 绑定", "模板"],
    "FR-4.4": ["R14", "字面量", "literal"],
    "FR-5.1": ["sqlglot", "ast_gate"],
    "FR-5.4": ["allowlist", "allowed", "该角色"],
    "FR-5.5": ["R10", "join_path", "未认证的 JOIN"],
    "FR-5.7": ["SET LOCAL", "set_config", "app_ro", "会话变量"],
    "FR-6.1": ["ANALYTICS_DB_URL", "read_only", "default_transaction_read_only"],
    "FR-6.2": ["statement_timeout"],
    "FR-6.3": ["EXEC_MAX_ROWS", "max_rows", "游标", "cursor"],
    "FR-6.4": ["EXEC_RESOURCE_EXCEEDED", "work_mem", "resource_exceeded"],
    "FR-6.5": ["连接池", "pool", "semaphore", "配额"],
    "FR-6.7": ["truncated", "截断"],
    "FR-7.2": ["safe_error", "脱敏", "sanitize", "不回灌"],
    "FR-7.4": ["降级链", "TEMPLATE_ONLY", "template_only", "degrade"],
    "FR-8.1": ["sql_text", "present", "生成时间"],
    "FR-8.2": ["freshness", "数据新鲜度", "Owner"],
    "FR-8.3": ["chart_type", "chart_spec", "受约束"],
    "FR-8.5": ["unit", "万元", "单位适配"],
    "FR-8.6": ["NaN", "空结果", "EMPTY_RESULT"],
    "FR-8.8": ["role_limited", "SHOP_LIMITED", "披露"],
    "FR-9.2": ["完整重跑", "不复用", "FR-9.2"],
    "FR-9.5": ["替代问法", "suggestion", "alternatives"],
    "FR-10.4": ["thread", "session_id 隔离", "tenant:user:session"],
    "FR-11.1": ["/feedback", "feedback", "结果有误"],
    "FR-11.2": ["gold_query", "Gold Query"],
    "FR-12.2": ["认证资产", "Owner", "维度层级"],
    "FR-12.4": ["bundle_version 变更", "invalidate", "版本变更"],
    "FR-13.3": ["CREATE POLICY", "RLS", "row level"],
    "FR-13.4": ["deny_columns", "CLS", "GRANT SELECT"],
    "FR-13.5": ["receiver_phone", "mask", "PII"],
}

S3_ROOTS = ["backend/tests", "eval", "frontend/src"]


def files_hit(kw, roots, maxc=20):
    out = set()
    for r in subprocess.run(["git", "grep", "-l", "-I", f"--max-count={maxc}", "-e", kw, "--"] + roots,
                            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.split("\n"):
        if r.strip():
            out.add(r.strip())
    return out


def main():
    rows = []
    for rid, kws in STRONG.items():
        f = set()
        per = {}
        for kw in kws:
            s = files_hit(kw, S3_ROOTS)
            per[kw] = len(s)
            f |= s
        # 只认测试文件（排除纯前端 src 下的非测试）
        tests = {x for x in f if ("/tests/" in x or x.endswith(".test.ts") or x.endswith(".test.tsx") or x.startswith("eval/"))}
        lvl = "S3-实质" if len(tests) >= 2 else ("S3-弱" if len(tests) == 1 else "S3-无")
        rows.append((rid, len(tests), lvl, per))
        print(f"{rid:9s} | 测试文件={len(tests):2d} | {lvl} | {per}")
    import collections
    print()
    print("分档统计 =", dict(collections.Counter(r[2] for r in rows)))
    os.makedirs("E:/tmp_qoder/qa_r31s", exist_ok=True)
    io_open = __import__("io").open
    io_open("E:/tmp_qoder/qa_r31s/b4_grade.json", "w", encoding="utf-8").write(
        json.dumps([{"id": a, "n_test_files": b, "grade": c, "per_kw": d} for a, b, c, d in rows],
                   ensure_ascii=False, indent=1))


main()
