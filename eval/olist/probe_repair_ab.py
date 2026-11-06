#!/usr/bin/env python
"""repair 两臂 A/B 探针（T-15；live、计费、自带硬停；**评测侧实验**）。

为什么必须是 live：cassette 的键 = `sha256(path + canonical body)`，换 prompt 必 miss
⇒ 离线回放证明不了「带失败 SQL 的自纠能不能改对」。

两条臂**只差一个变量**：
  A `digest_only`     —— 现行生产形态：只有脱敏错误摘要（类别级文案，见
                        `backend/app/exec/errors.py::MESSAGES`）。
  B `with_failed_sql` —— 同一 prompt 再追加失败 SQL 原文 + `pgcode`。
                        ⚠️ 违反 N-17（`backend/app/llm/prompts/repair_v1.txt:5` 明写
                        「你看不到出错的那条 SQL，这是刻意的」）⇒ 本件只在评测侧跑，
                        **不接生产**；要接生产必须先在 `docs/07 §4.8` 取号并重审 N-17。

判据（本件只报可复算的三个桶，不宣称「改对了」）：
  · `parse_ok`   —— 输出能被 sqlglot 按 postgres 解析；
  · `exec_ok`    —— 能在 SQLite 沙箱里跑通（沙箱 = 评测同款只读库）；
  · `rows`       —— 跑通时的行数（仅记录，不作判据）。
  🔻 `equal_gold` **本件不算**：那要 equivalence 全口径（列序/容差/舍入），
     留给单独一件。所以即使 B 臂 `exec_ok` 全绿，也只能说「能跑通」，
     不能说「改对了」——下一窗别把这两个读串。

⚠️ 只读输入、不写证据件：`--out` 只写本探针自己的 JSON。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

OLIST_DIR = Path(__file__).resolve().parent
REPO_ROOT = OLIST_DIR.parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "olist" / "olist_sandbox.db"
DEFAULT_OUT = OLIST_DIR / "probe_repair_ab.json"
DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "deepseek-v4.1-flash"
ARMS = ("digest_only", "with_failed_sql")

#: 与 `app/llm/budget.py` 的 PRICES 同值（USD / 100 万 token）。
#: ⚠️ 键必须与 `--model` 对得上：对不上就是按 v4-pro 兜底（账本虚高约 4.4 倍）。
PRICES: dict[str, dict[str, tuple[float, float, float]]] = {
    "deepseek-v4.1-flash": {
        "off_peak": (0.015, 0.15, 0.60),
        "peak": (0.03, 0.30, 1.20),
    },
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _usd_cny_rate() -> tuple[float, str]:
    """优先取仓库常量（唯一真相），取不到用 7.1 兜底并**标明是兜底**。"""
    try:
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.llm.budget import USD_CNY_RATE

        return float(USD_CNY_RATE), "app.llm.budget.USD_CNY_RATE"
    except Exception:  # noqa: BLE001 - 兜底必须仍能算出一个数，并标明来源
        return 7.1, "fallback 7.1 (未能读取 app.llm.budget.USD_CNY_RATE)"


def is_peak(now: datetime) -> bool:
    """与 `app.llm.budget.classify_tier` 同一条业务规则：北京时间工作日 09–12 / 14–18。"""
    local = now.astimezone(timezone(timedelta(hours=8)))
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return (9 * 60 <= minutes < 12 * 60) or (14 * 60 <= minutes < 18 * 60)


def cost_cny(usage: dict[str, Any], model: str, peak: bool, rate: float) -> float:
    prices = PRICES.get(model)
    if prices is None:
        return float("nan")  # 不去猜未入表模型的价格
    hit_p, miss_p, out_p = prices["peak" if peak else "off_peak"]
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    usd = (
        (cached * hit_p + max(prompt_tokens - cached, 0) * miss_p + output_tokens * out_p)
        / 1_000_000
    )
    return usd * rate


def load_failing_cases(paths: list[Path], *, limit: int | None) -> list[dict[str, Any]]:
    """挑「真走过 repair 且仍失败」的样例（`nodes` 里出现 repair 且终态非 complete）。"""
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else data.get("records") or []
        for record in records:
            if not isinstance(record, dict):
                continue
            case_id = str(record.get("case_id"))
            nodes = record.get("nodes") or []
            if "repair" not in [str(n) for n in nodes]:
                continue
            if str(record.get("terminal_event")) == "complete":
                continue
            if case_id in seen:
                continue
            seen.add(case_id)
            picked.append(
                {
                    "case_id": case_id,
                    "question": str(record.get("question") or ""),
                    "sql_text": str(record.get("sql_text") or ""),
                    "error_class": str(record.get("exec_error_class") or "syntax_error"),
                    "terminal_code": str(record.get("terminal_code")),
                    "gold_sql": str((record.get("gold") or {}).get("gold_sql") or ""),
                }
            )
    picked.sort(key=lambda item: item["case_id"])
    return picked[:limit] if limit else picked


def schema_summary(db_path: Path, limit: int = 40) -> str:
    """沙箱 schema（本探针在 SQLite 沙箱上判 exec_ok，所以 summary 取沙箱自身）。"""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "select name, sql from sqlite_master where type in ('table','view') order by name"
        ).fetchall()
    finally:
        conn.close()
    lines = [f"- {name}: {(ddl or '').split('(')[-1][:400]}" for name, ddl in rows[:limit]]
    return "\n".join(lines)


def build_prompt(case: dict[str, Any], arm: str, digest: str, schema: str) -> tuple[str, str]:
    system = (
        "你是 CommerceQL 的 SQL 生成/纠错组件。可用对象只有下列（其他表名列名一律不得出现）：\n"
        f"{schema}\n\n"
        "输出要求：只输出一条可执行的 SELECT 语句原文，不要 JSON、不要解释、不要代码围栏。"
        "必须显式写 LIMIT；表别名不得用 SQL 保留字（order/group/select/table 等）。"
    )
    user = f"[问题]\n{case['question']}\n\n[脱敏错误摘要]\n{digest}\n"
    if arm == "with_failed_sql":
        user += f"\n[失败的那条 SQL]\n{case['sql_text']}\n\n[pgcode]\n{case.get('pgcode') or '(none)'}\n"
    return system, user


def call_model(
    *, endpoint: str, model: str, api_key: str, system: str, user: str, max_tokens: int
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 探针必须记录失败而不是抛出
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "latency_ms": int((time.monotonic() - started) * 1000)}
    choice = (body.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    return {
        "ok": True,
        "text": text,
        "usage": body.get("usage") or {},
        "finish_reason": choice.get("finish_reason"),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def clean_sql(text: str) -> str:
    """剥代码围栏与前后缀；模型常带 ```sql。"""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip().rstrip(";").strip()


def judge(sql: str, db_path: Path) -> dict[str, Any]:
    """三个可复算桶：parse_ok / exec_ok / rows。不判等价。"""
    verdict: dict[str, Any] = {"parse_ok": False, "exec_ok": False, "rows": None, "note": ""}
    try:
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        import sqlglot

        sqlglot.parse_one(sql, dialect="postgres")
        verdict["parse_ok"] = True
    except Exception as exc:  # noqa: BLE001
        verdict["note"] = f"parse: {type(exc).__name__}"
        return verdict
    if "%(" in sql:
        verdict["note"] = "placeholder: %(...)s 参数占位，SQLite 无法直执行"
        return verdict
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute(sql).fetchmany(10001)
            verdict["exec_ok"] = True
            verdict["rows"] = len(rows)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        verdict["note"] = f"exec: {type(exc).__name__}: {str(exc)[:120]}"
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="repair 两臂 A/B 探针（live，计费）")
    parser.add_argument("--results", type=Path, nargs="+",
                        default=[OLIST_DIR / f"results_v3_r{i}.json" for i in (1, 2, 3)])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cases", type=int, default=1, help="用几条样例（冒烟用 1）")
    parser.add_argument("--reps", type=int, default=1, help="每臂每样例重复次数")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--max-cost-cny", type=float, default=0.2)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        print("REFUSE: DASHSCOPE_API_KEY 未设置（本探针只从进程环境读，不读 .env）", file=sys.stderr)
        return 2
    if not args.db.is_file():
        print(f"REFUSE: 沙箱库不存在 {args.db}", file=sys.stderr)
        return 2
    if args.model not in PRICES:
        print(f"REFUSE: 模型 {args.model} 未入 PRICES ⇒ 成本不可复算（会走 v4-pro 兜底，虚高约 4.4 倍）",
              file=sys.stderr)
        return 2

    cases = load_failing_cases(list(args.results), limit=args.cases)
    if not cases:
        print("REFUSE: 没挑到「真走过 repair 且仍失败」的样例", file=sys.stderr)
        return 2

    rate, rate_src = _usd_cny_rate()
    now = datetime.now(UTC)
    peak = is_peak(now)
    schema = schema_summary(args.db)

    # 脱敏错误摘要：与生产同类级别文案，**不外泄**原始库文本（N-11）
    digest_by_class = {
        "syntax_error": "SQL 语法有误",
        "unknown_function": "使用了不存在的函数",
        "unknown_column": "引用了不存在的列（已隐去名称）",
        "unknown_table": "引用了不存在的资产",
        "type_mismatch": "比较或运算的双方类型不一致",
    }

    runs: list[dict[str, Any]] = []
    calls = 0
    spent = 0.0
    stopped = False

    print(f"cases={[c['case_id'] for c in cases]} arms={list(ARMS)} reps={args.reps} "
          f"model={args.model} peak={peak} cap_cny={args.max_cost_cny} max_calls={args.max_calls}")

    for case in cases:
        digest = digest_by_class.get(case["error_class"], "SQL 无法执行")
        for arm in ARMS:
            for rep in range(args.reps):
                if calls >= args.max_calls or spent >= args.max_cost_cny:
                    stopped = True
                    break
                system, user = build_prompt(case, arm, digest, schema)
                result = call_model(
                    endpoint=args.endpoint, model=args.model, api_key=api_key,
                    system=system, user=user, max_tokens=args.max_tokens,
                )
                calls += 1
                usage = result.get("usage") or {}
                this_cost = cost_cny(usage, args.model, peak, rate) if result.get("ok") else 0.0
                if not math.isnan(this_cost):
                    spent += this_cost
                sql = clean_sql(result.get("text") or "")
                verdict = judge(sql, args.db) if sql else {"parse_ok": False, "exec_ok": False,
                                                          "rows": None, "note": "empty output"}
                runs.append(
                    {
                        "case_id": case["case_id"],
                        "arm": arm,
                        "rep": rep,
                        "call_ok": bool(result.get("ok")),
                        "error": result.get("error"),
                        "finish_reason": result.get("finish_reason"),
                        "latency_ms": result.get("latency_ms"),
                        "usage": usage,
                        "cost_cny": None if math.isnan(this_cost) else round(this_cost, 6),
                        "sql": sql[:1200],
                        **verdict,
                    }
                )
                print(f"  {case['case_id']} {arm} rep{rep}: call_ok={result.get('ok')} "
                      f"parse={verdict['parse_ok']} exec={verdict['exec_ok']} "
                      f"cost=¥{this_cost:.6f} note={verdict.get('note', '')[:60]!r}")
            if stopped:
                break
        if stopped:
            break

    per_arm = {
        arm: {
            "n": sum(1 for r in runs if r["arm"] == arm),
            "parse_ok": sum(1 for r in runs if r["arm"] == arm and r["parse_ok"]),
            "exec_ok": sum(1 for r in runs if r["arm"] == arm and r["exec_ok"]),
            "cost_cny": round(sum(r["cost_cny"] or 0 for r in runs if r["arm"] == arm), 6),
        }
        for arm in ARMS
    }
    result = {
        "schema": "T15_REPAIR_AB_PROBE/v1",
        "note": "本件只判 parse_ok/exec_ok，**不判 equal_gold**；B 臂违反 N-17，仅评测侧实验",
        "generated_at": now.isoformat(timespec="seconds"),
        "model": args.model,
        "endpoint": args.endpoint,
        "peak": peak,
        "usd_cny_rate": rate,
        "usd_cny_rate_source": rate_src,
        "cap": {"max_calls": args.max_calls, "max_cost_cny": args.max_cost_cny,
                "stopped": stopped, "calls": calls, "spent_cny": round(spent, 6)},
        "cases": [c["case_id"] for c in cases],
        "arms": list(ARMS),
        "per_arm": per_arm,
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"TOTAL calls={calls} spent=¥{spent:.6f} stopped={stopped} peak={peak} rate={rate}({rate_src})")
    print(f"per_arm={json.dumps(per_arm, ensure_ascii=False)}")
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
