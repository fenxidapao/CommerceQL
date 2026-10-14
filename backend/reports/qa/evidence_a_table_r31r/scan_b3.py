# -*- coding: utf-8 -*-
"""B3 反查扫描器：对 30 条「四段全 0」需求做**功能关键词反向查找**（不认 ID）。

判据（A_TABLE_VERDICT §一 J-1/J-2/J-3 的延伸，B3 专门用）：
  按**功能描述**（而非 ID）在实现面/测试面找载体。
  · 命中 ⇒ 「有载体、ID 零引用」（追溯链断，非功能缺失）
  · 未命中 ⇒ 「疑似真缺」（须人工复核，不得仅凭 scanner 定罪）

🔴 本扫描器只产「候选载体清单」，**判定权在人**：每条都要落行读原文。
"""
import io, json, os, re, sys, subprocess

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

# 30 条「四段全 0」→ 功能关键词（人工拟定；宁可多给关键词，让命中可复核）
ITEMS = {
    "FR-1.1":  ["中文", "中英", "混输", "normalize", "归一化"],
    "FR-1.5":  ["指代", "代词", "消解", "coreference", "anaphora"],
    "FR-1.7":  ["开放式", "open_analysis", "OPEN_ANALYSIS", "替代问法"],
    "FR-1.8":  ["数值", "单位", "value_parse", "normalize_number", "亿", "万"],
    "FR-2.1":  ["裸表", "认证资产", "allowed", "allowlist", "AssetAllowlist"],
    "FR-2.4":  ["精筛", "压缩上下文", "candidate_limit", "top_k", "rerank"],
    "FR-4.1":  ["gen_sql", "方言", "dialect", "sql_dialect"],
    "FR-4.2":  ["dialect", "postgres", "sqlite", "DialectPort", "方言适配"],
    "FR-4.5":  ["asset_manifest", "置信度", "confidence", "口径说明", "caveat"],
    "FR-5.2":  ["SELECT *", "select_star", "R03", "star"],
    "FR-5.3":  ["LIMIT", "limit_injected", "强制注入"],
    "FR-5.6":  ["语义包版本", "数据角色", "敏感列", "租户范围", "bundle_version"],
    "FR-5.8":  ["EXPLAIN", "扫描行数", "join", "成本估算", "cost_estimate"],
    "FR-5.9":  ["阈值", "拒绝并建议", "转异步", "threshold", "gate3"],
    "FR-6.6":  ["负载", "降级", "degrade", "预计算", "缓存路由"],
    "FR-7.3":  ["超限", "可解释的失败", "budget", "COST_TOO_HIGH", "熔断"],
    "FR-8.4":  ["折线", "饼", "柱状", "直方", "散点", "chart_type"],
    "FR-8.7":  ["反馈", "feedback", "是否有误"],
    "FR-11.4": ["回归测试", "bad_case", "regression", "自动转化"],
    "FR-12.6": ["口径字典", "metric_dictionary", "字典", "browse"],
    "FR-13.1": ["OIDC", "JWT", "tenant_id", "user_id", "role"],
    "FR-13.2": ["三级权限", "RBAC", "租户", "角色"],
    "FR-13.7": ["token 预算", "配额", "quota", "预算"],
    "NFR-3.1": ["危险 SQL 放行", "dangerous", "放行", "leak"],
    "NFR-3.2": ["权限类错误", "permission", "403", "FORBIDDEN"],
    "NFR-3.3": ["跨租户", "cross_tenant", "leak", "泄露"],
    "NFR-3.5": ["PII", "明文外泄", "pii_columns_hit", "mask"],
    "NFR-4.4": ["会话历史", "token 增长", "history", "裁剪"],
    "NFR-5.4": ["覆盖率", "coverage", "CI", "evaluation suite"],
    "NFR-6.5": ["备案", "生成式 AI", "filing", "compliance"],
}

SEARCH_ROOTS = ["backend/app", "frontend/src", "backend/tests", "eval", "deploy"]


def grep(kw: str, root: str, limit: int = 4):
    """按关键词在指定根目录下找命中（只认源码/文档面，排除 .pyc 与 node_modules）。"""
    try:
        r = subprocess.run(
            ["git", "grep", "-n", "-I", "--max-count=" + str(limit), "-e", kw, "--", root],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = [l for l in (r.stdout or "").split("\n") if l.strip()]
        return out
    except Exception:
        return []


def main():
    results = {}
    for rid, kws in ITEMS.items():
        hits = []
        for kw in kws:
            for root in SEARCH_ROOTS:
                for line in grep(kw, root, 3)[:3]:
                    hits.append(line)
        # 去重、截断
        seen, uniq = set(), []
        for h in hits:
            key = h.split(":")[0] + ":" + h.split(":")[1] if h.count(":") >= 2 else h
            if key in seen:
                continue
            seen.add(key)
            uniq.append(h[:220])
        results[rid] = uniq[:8]
        print(f"===== {rid} ({len(uniq)} 命中) =====")
        for h in uniq[:8]:
            print("   ", h[:200])
        print()
    out = "E:/tmp_qoder/qa_r31r/b3_raw.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=1))
    print("RAW →", out)


main()
