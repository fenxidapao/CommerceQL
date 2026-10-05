"""T-37 A2 的单变量对照：每条变异必须让 `test_admin_audit_contract.py` 翻红。

跑法（venv 在仓库根）：
    cd backend && PYTHONUTF8=1 ../.venv/Scripts/python.exe reports/w8/t37_a2_mutations.py

每条形如：读原字节 → 打一处变异 → 跑契约件 → 还原字节 → 核 md5。
`DAO_SQL` 那族（租户谓词／分页／join／注入形状）之所以能离线判，全靠
`app/repo/audit_read.py::build_queries` 是**纯函数**（见该文件里的理由）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path("E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/backend")
READ = BACKEND / "app/repo/audit_read.py"
VIEW = BACKEND / "app/present/audit_view.py"
ROUTER = BACKEND / "app/api/routers/admin_audit.py"
TEST = "tests/contract/test_admin_audit_contract.py"

MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- 判据③ 第一道：租户谓词 ------------------------------------------------
    ("A1 租户谓词换成恒真", READ, 'clauses.append("a.tenant_id = :scope_tenant")', 'clauses.append("1 = 1")'),
    ("A2 谓词参数给成 None", READ, 'params["scope_tenant"] = tenant_scope', 'params["scope_tenant"] = None'),
    ("A3 租户判断反过来（跨租户恒真）", READ, "if tenant_scope is not None:", "if tenant_scope is None:"),
    # --- 分页与 join ----------------------------------------------------------
    ("A4 count 被分页切过", READ, 'f"SELECT count(*) AS total {_FROM_SQL} {where_sql}"',
     'f"SELECT count(*) AS total {_FROM_SQL} {where_sql} LIMIT :limit"'),
    ("A5 排序去掉 tiebreaker", READ, "'ORDER BY a.\"timestamp\" DESC, a.log_id DESC'",
     "'ORDER BY a.\"timestamp\" DESC'"),
    ("A6 LEFT JOIN 换成 INNER", READ, "LEFT JOIN", "INNER JOIN"),
    # --- 判据② 注入形状 --------------------------------------------------------
    ("A7 is_local 写成 false", READ, "set_config('{key}', :{_GUC_BIND[key]}, true)",
     "set_config('{key}', :{_GUC_BIND[key]}, false)"),
    ("A8 只注入两键（判据② 明令禁止）", READ, 'true)" for key in IDENTITY_GUC_KEYS)',
     'true)" for key in IDENTITY_GUC_KEYS[:2])'),
    # --- 派生谓词 ------------------------------------------------------------
    ("A9 pii_hit 两支同文", READ, '"a.pii_columns_hit <> \'{}\'::text[]"', '"a.pii_columns_hit = \'{}\'::text[]"'),
    ("A10 outcome 绑成枚举成员名", READ, 'params["outcome"] = filters.outcome.value',
     'params["outcome"] = filters.outcome.name'),
    # --- 投影层：不冒充 -------------------------------------------------------
    ("A11 has_more 恒假", VIEW, '"has_more": offset + len(rows) < total,', '"has_more": False,'),
    ("A12 预览不截断（全文下发）", VIEW, "return raw if len(raw) <= QUESTION_PREVIEW_MAX else f\"{raw[:QUESTION_PREVIEW_MAX]}…\"",
     "return raw"),
    ("A13 缺成本补零", VIEW, "    if value is None or isinstance(value, bool):\n        return None",
     "    if isinstance(value, bool):\n        return 0.0\n    if value is None:\n        return 0.0"),
    ("A14 双保证判据放宽成 or", VIEW, '"second_guarantee_in_place": enabled and policies > 0,',
     '"second_guarantee_in_place": enabled or policies > 0,'),
    ("A15 pii_hit 恒假", VIEW, '"pii_hit": bool(pii_columns),', '"pii_hit": False,'),
    ("A16 身份来源写成 query", VIEW, '"source": "jwt",', '"source": "query",'),
    ("A17 注入语句数写成 3", VIEW, '"statement_count": 1,', '"statement_count": 3,'),
    # --- 接入层：门禁／桶／视角 ------------------------------------------------
    ("A18 去掉角色门禁", ROUTER, "        if token.role is not Role.PLATFORM_ADMIN:\n            raise ForbiddenScope(\"该视图仅平台管理员可见\")\n", ""),
    ("A19 吃读取类桶", ROUTER, "RateLimitBucket.ADMIN", "RateLimitBucket.READ"),
    ("A20 跨租户参数不生效", ROUTER, "tenant_scope=None if cross_tenant else ctx.tenant_id", "tenant_scope=ctx.tenant_id"),
    ("A21 跨租户标签不写", ROUTER, "cross_tenant=cross_tenant,", "cross_tenant=False,"),
    ("A22 路由前缀写错", ROUTER, 'router = APIRouter(prefix="/admin", tags=["admin"])',
     'router = APIRouter(prefix="/adm", tags=["admin"])'),
]


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = [line for line in (proc.stdout or "").splitlines() if "passed" in line or "failed" in line]
    return proc.returncode, " | ".join(tail[-2:])


def main() -> int:
    originals = {path: path.read_bytes() for _, path, _, _ in MUTATIONS}
    lines: list[str] = []
    unclosed = 0
    rc, tail = run_pytest()
    lines.append(f"基线 rc={rc} :: {tail}")
    if rc != 0:
        lines.append("!! 基线就红 ⇒ 变异全部作废，先修基线")
        print("\n".join(lines))
        return 2
    for name, path, old, new in MUTATIONS:
        text = originals[path].decode("utf-8")
        hits = text.count(old)
        if hits != 1:
            lines.append(f"{name} :: 靶点命中 {hits} 次 ⇒ 变异未生效，不算闭合")
            unclosed += 1
            continue
        path.write_bytes(text.replace(old, new).encode("utf-8"))
        try:
            code, sub = run_pytest()
        finally:
            path.write_bytes(originals[path])
        unclosed += 0 if code != 0 else 1
        lines.append(f"{name} :: rc={code} {'翻红 ✓' if code else '仍绿 ✗'} :: {sub}")
    restored = all(path.read_bytes() == data for path, data in originals.items())
    lines.append(f"还原后逐文件 md5 与进入前一致 = {restored}")
    for path, data in sorted(originals.items()):
        lines.append(f"  {path.name}: {hashlib.md5(path.read_bytes()).hexdigest()} == {hashlib.md5(data).hexdigest()}")
    lines.append(f"不闭合条数 = {unclosed}")
    out = "\n".join(lines)
    (BACKEND / "reports/w8/t37_a2_mutations_report.txt").write_text(out, encoding="utf-8", newline="\n")
    print(out)
    return 0 if (unclosed == 0 and restored) else 1


if __name__ == "__main__":
    sys.exit(main())
