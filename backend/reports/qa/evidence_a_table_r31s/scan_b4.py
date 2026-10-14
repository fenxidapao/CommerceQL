# -*- coding: utf-8 -*-
"""B4 反查：42 条 P0/P0（安全）逐条按功能关键词扫 S2（实现）与 S3（测试）两面。

🟢 关键先验（本窗从清单读出的形状）：**42/42 全部缺 S3**，30/42 缺 S2。
⇒ 本扫描器先回答一个问题：这「缺」是「真没有」还是「有但没写 ID」？
"""
import io, json, os, subprocess, sys

REPO = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
os.chdir(REPO)

# 42 条 → 功能关键词（人工拟定，用于召回；判定仍须回读原文）
ITEMS = {
    "FR-1.2":  ["相对时间", "相对时间表达", "resolve_time", "本周", "上周", "同比", "环比", "monday", "周起点"],
    "FR-1.3":  ["Asia/Shanghai", "财年", "时区", "timezone", "系统当前时间"],
    "FR-1.4":  ["黑话", "别名", "双11", "618", "动销率", "爆款", "长尾"],
    "FR-1.6":  ["意图分类", "classify_intent", "INTENT_MAP", "IntentKind"],
    "FR-2.2":  ["混合检索", "稠密", "dense", "稀疏", "sparse", "RRF", "融合"],
    "FR-2.3":  ["few-shot", "few_shot", "Gold Query", "top_k", "示例检索"],
    "FR-2.5":  ["按租户过滤", "tenant", "跨租户", "scope"],
    "FR-2.6":  ["双语", "别名", "alias", "en_alias", "中文问题"],
    "FR-2.7":  ["隐式外键", "外键", "join_path", "人工确认", "候选"],
    "FR-3.1":  ["查询计划", "结构化查询计划", "Plan", "plan_summary", "query_plan"],
    "FR-3.3":  ["绑定解析顺序", "five_step", "五步", "resolve_detailed", "filters"],
    "FR-3.4":  ["RESOLVED_UNIQUE", "ambiguous", "unresolved", "仅当"],
    "FR-4.3":  ["输出模板", "参数", "param", "sql_params", "防注入"],
    "FR-4.4":  ["字面量", "literal", "parameterize", "值位", "R14"],
    "FR-5.1":  ["sqlglot", "AST", "白名单校验", "ast_gate"],
    "FR-5.4":  ["允许清单", "allowlist", "该角色", "RBAC"],
    "FR-5.5":  ["JOIN", "join_path", "未认证", "R10"],
    "FR-5.7":  ["安全会话变量", "SET LOCAL", "short_term", "角色", "session"],
    "FR-6.1":  ["ANALYTICS_DB_URL", "只读", "default_transaction_read_only", "read_only"],
    "FR-6.2":  ["语句超时", "statement_timeout", "超时"],
    "FR-6.3":  ["最大返回行数", "max_rows", "游标", "cursor", "分批"],
    "FR-6.4":  ["内存上限", "EXEC_RESOURCE_EXCEEDED", "resource_exceeded", "执行期"],
    "FR-6.5":  ["并发队列", "连接池", "pool", "配额", "semaphore"],
    "FR-6.7":  ["truncated", "截断", "显式标记"],
    "FR-7.2":  ["脱敏", "sanitize", "safe_error", "不回灌", "原始报错"],
    "FR-7.4":  ["降级链", "degrade", "template_only", "refuse"],
    "FR-8.1":  ["已执行的 SQL", "sql_text", "生成时间", "present"],
    "FR-8.2":  ["数据新鲜度", "freshness", "Owner", "来源资产"],
    "FR-8.3":  ["chart spec", "chart_type", "后端返回", "受约束"],
    "FR-8.5":  ["单位", "万元", "亿", "unit"],
    "FR-8.6":  ["空结果", "分母为 0", "NaN", "empty"],
    "FR-8.8":  ["role_limited", "空结果", "披露策略", "row-level"],
    "FR-9.2":  ["重新完整走一遍", "复用旧 SQL", "不得复用", "re-run"],
    "FR-9.5":  ["替代问法", "suggestion", "refuse"],
    "FR-10.4": ["tenant_id", "user_id", "session_id", "thread", "隔离"],
    "FR-11.1": ["结果有误", "feedback", "正确 SQL", "标记"],
    "FR-11.2": ["Gold Query", "gold_query", "审核", "修正后"],
    "FR-12.2": ["认证资产", "Owner", "维度层级", "同义词", "时间语义"],
    "FR-12.4": ["版本变更", "失效", "invalidate", "bundle_version"],
    "FR-13.3": ["RLS", "CREATE POLICY", "行级安全", "PG RLS"],
    "FR-13.4": ["CLS", "GRANT SELECT", "列级安全", "deny_columns"],
    "FR-13.5": ["PII", "脱敏", "receiver_phone", "mask", "***"],
}

S2_ROOTS = ["backend/app", "frontend/src"]
S3_ROOTS = ["backend/tests", "frontend/src"]


def g(kw, root, maxc=6):
    r = subprocess.run(["git", "grep", "-n", "-I", f"--max-count={maxc}", "-e", kw, "--", root],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [l for l in (r.stdout or "").split("\n") if l.strip()]


def main():
    out = {}
    for rid, kws in ITEMS.items():
        s2, s3 = [], []
        for kw in kws:
            for root in S2_ROOTS:
                s2 += g(kw, root, 2)[:2]
            for root in S3_ROOTS:
                s3 += g(kw, root, 2)[:2]
        def uniq(xs):
            seen, u = set(), []
            for x in xs:
                p = x.split(":")[0]
                if p in seen:
                    continue
                seen.add(p)
                u.append(x[:190])
            return u[:6]
        out[rid] = {"s2": uniq(s2), "s3": uniq(s3)}
        print(f"===== {rid} | S2 命中文件={len(set(x.split(':')[0] for x in s2))} | S3 命中文件={len(set(x.split(':')[0] for x in s3))}")
        for h in out[rid]["s3"]:
            print("   [S3]", h[:180])
        for h in out[rid]["s2"][:2]:
            print("   [S2]", h[:180])
        print()
    os.makedirs("E:/tmp_qoder/qa_r31s", exist_ok=True)
    io.open("E:/tmp_qoder/qa_r31s/b4_raw.json", "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    # 汇总
    hit_s3 = sum(1 for v in out.values() if v["s3"])
    hit_s2 = sum(1 for v in out.values() if v["s2"])
    print(f"### 汇总：{len(out)} 条 | S3 有命中 {hit_s3} | S2 有命中 {hit_s2}")


main()
