# -*- coding: utf-8 -*-
"""B5 全量：33 条（defonly 10 ＋ 余下 23）逐条强特征词反查 → 测试文件级分档。

⚠️ 本批特点：主体是 NFR（性能/可用性/持久化/合规）＋ P1。
NFR 的载体形态与 FR 不同：常落在**配置常量／守卫机制／契约测试**，而非单一功能点。
⇒ 关键词要取「该 NFR 的机制符号」，不能取 NFR 名（如「可用性」）。
"""
import os, subprocess, json, collections

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

# 33 条 → 机制符号词（每条 2–4 个）
ITEMS = {
    # —— defonly 10 条 ——
    "FR-7.1":  ["repair", "max_repair", "修复轮", "RETRY"],
    "FR-7.5":  ["TEMPLATE_ONLY", "template_only", "模板", "LLM_UNAVAILABLE"],
    "FR-9.3":  ["近似答案", "NEAR_MISS", "refuse"],
    "FR-9.4":  ["两个错类", "误拒", "false_reject", "should_have_refused"],
    "FR-10.2": ["追 modify", "修改计划", "modify_plan", "re-plan"],
    "FR-10.3": ["条件继承", "inherit", "carry_over"],
    "FR-11.4": ["bad_case", "回归", "regression"],
    "FR-11.3": ["归因", "attribution", "schema linking"],
    "FR-12.1": ["YAML", "bundle_2026", "语义包以 YAML", "git 版本"],
    "FR-13.6": ["二次审批", "approval", "审批令牌"],
    "NFR-6.2": ["egress", "出站", "脱敏中间件", "egress_guard"],
    # —— b5_rest 23 条 ——
    "FR-2.8":  ["列召回", "column_recall", "recall"],
    "FR-11.5": ["待补清单", "unmapped", "未识别词"],
    "FR-12.5": ["schema 变更", "drift", "重新发布"],
    "NFR-1.1": ["P95", "p95", "latency_ms", "WINDOW_S"],
    "NFR-1.3": ["P99", "p99"],
    "NFR-1.4": ["db_latency", "查询延迟", "latency_ms"],
    "NFR-1.5": ["cache_hit", "缓存命中"],
    "NFR-2.1": ["可用性", "healthz", "availability"],
    "NFR-2.2": ["降级", "degrade", "LLM_UNAVAILABLE"],
    "NFR-2.3": ["persist", "持久化", "checkpoint", "state_store"],
    "NFR-2.4": ["recursion_limit", "死循环", "loop"],
    "NFR-2.5": ["幂等", "idempot", "Idempotency-Key"],
    "NFR-2.6": ["fail-closed", "审计故障", "audit_db_failure"],
    "NFR-2.7": ["Ollama", "embedder", "EMBEDDING"],
    "NFR-4.1": ["cost_cny", "单次查询成本", "budget"],
    "NFR-5.1": ["prompt_version"],
    "NFR-5.2": ["图结构版本", "graph_version", "灰度", "rollback"],
    "NFR-5.3": ["确定性代码", "deterministic", "不得依赖 LLM"],
    "NFR-6.1": ["境内", "跨境", "DeepSeek"],
    "NFR-6.3": ["不外传", "schema/注释", "egress_guard"],
    "NFR-6.4": ["留存", "90 天", "retention"],
    "NFR-7.2": ["一次成功率", "clarify_success", "G-8"],
    "NFR-7.3": ["该澄清未澄清", "should_clarify", "G-8"],
}

ROOTS = {"S2": ["backend/app", "frontend/src"], "S3": ["backend/tests", "eval", "frontend/src"]}


def files(kw, roots, maxc=30):
    r = subprocess.run(["git", "grep", "-l", "-I", f"--max-count={maxc}", "-e", kw, "--"] + roots,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {x for x in (r.stdout or "").split("\n") if x.strip()}


rows = []
for rid, kws in ITEMS.items():
    s2, s3, per = set(), set(), {}
    for kw in kws:
        f2 = files(kw, ROOTS["S2"]); f3 = files(kw, ROOTS["S3"])
        s2 |= f2; s3 |= f3
        per[kw] = (len(f2), len(f3))
    tests = {x for x in s3 if ("/tests/" in x or x.startswith("eval/") or x.endswith(".test.ts") or x.endswith(".test.tsx"))}
    lvl = "S3-实质" if len(tests) >= 2 else ("S3-弱" if len(tests) == 1 else "S3-无")
    rows.append({"id": rid, "n_s2": len(s2), "n_test_files": len(tests), "grade": lvl, "per_kw": per})
    print(f"{rid:9s} | S2文件={len(s2):3d} | 测试文件={len(tests):2d} | {lvl}")
    print(f"            {per}")

print()
print("分档统计 =", dict(collections.Counter(r["grade"] for r in rows)))
os.makedirs("E:/tmp_qoder/qa_r31t", exist_ok=True)
io_open = __import__("io").open
io_open("E:/tmp_qoder/qa_r31t/b5_grade.json", "w", encoding="utf-8").write(
    json.dumps(rows, ensure_ascii=False, indent=1))
