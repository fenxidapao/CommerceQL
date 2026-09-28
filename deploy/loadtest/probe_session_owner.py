"""会话属主的**负向**探针（W7；一条请求、零并发）。

为什么存在：`driver.py` 的 `single_session` 已按 W1B/W0 09-28 裁定改成"全线固定创建者令牌"
（锁键 §9.3 与 thread_id FR-10.4 都含 user ⇒ 换令牌等于换会话，场景③ 就测不到锁）。
**但"改完不留下断言"= 缩 scope 消红的同族** ⇒ 这条探针把另一面钉住：非属主令牌带**别人的**
`session_id` 打 `POST /query`，契约上应当 **404 `SESSION_NOT_FOUND`**（附录 A §A.11：
"session_id 不存在**或不属于当前用户**"；07 §14 H7；PRD FR-10.4 P0 安全）。

它**不是**门禁件：退出码恒 0，判定写在输出里（`契约期望` vs `实测`），因为
"缺陷"是否成立要架构裁 `会话所有权 = (tenant,user) 还是 (tenant)`（W0 已上报同一问）。

⚠️ 一条请求 ≈ ¥0.0087（若被判 200 才会走到模型；404 则零花费）。

用法：
    python probe_session_owner.py --target http://127.0.0.1:18000/api/v1 \
        --tokens E:/tmp_w7/tokD.txt --question "T_A 2026-08 的 GMV 是多少？"
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

EXPECT = "404 SESSION_NOT_FOUND（附录 A §A.11 / 07 §14 H7 / PRD FR-10.4）"


def _dig(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            got = _dig(v, key)
            if got is not None:
                return got
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            got = _dig(v, key)
            if got is not None:
                return got
    return None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="http://127.0.0.1:18000/api/v1")
    ap.add_argument("--tokens", required=True, help="令牌文件（≥2 条：第 1 条当创建者，第 2 条当非属主）")
    ap.add_argument("--question", default="T_A 2026-08 的 GMV 是多少？")
    ap.add_argument("--out", default="E:/tmp_w7/probe_session_owner.json")
    ap.add_argument("--owner-ask", action="store_true",
                        help="先让属主在该会话问一轮（1 条请求 ≈¥0.009），再测非属主能否读到内容")
    args = ap.parse_args()

    toks = [t.strip() for t in Path(args.tokens).read_text(encoding="utf-8").split() if t.strip()]
    if len(toks) < 2:
        raise SystemExit("[中止] 需要 ≥2 条令牌（创建者 / 非属主）")
    owner, other = toks[0], toks[1]
    base = args.target.rstrip("/")
    report: dict[str, Any] = {"expected": EXPECT}

    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(f"{base}/session", json={}, headers={"Authorization": f"Bearer {owner}"})
        sid = _dig(r.json(), "session_id") if r.status_code == 200 else None
        report["create_session"] = {"http": r.status_code, "session_id_present": bool(sid)}
        if not sid:
            raise SystemExit(f"[中止] 建会话失败 HTTP {r.status_code} {r.text[:120]}")

        # ① 非属主令牌带别人的 session_id 打 /query
        q = await client.post(
            f"{base}/query",
            json={"question": args.question, "session_id": sid, "options": {"async_if_slow": False}},
            headers={"Authorization": f"Bearer {other}", "Accept": "text/event-stream"},
        )
        body = q.text[:400]
        report["nonowner_post_query"] = {
            "http": q.status_code,
            "codes_seen": sorted({c for c in ("SESSION_NOT_FOUND", "RATE_LIMITED", "INTERNAL") if c in body}),
            "sse_bytes": len(q.content),
            "body_head": body[:180],
        }

        # ①′ 可选：先让**属主**在该会话上产生一轮（`--owner-ask`），才能判"非属主能不能读到属主内容"
        if args.owner_ask:
            await client.post(
                f"{base}/query",
                json={"question": args.question, "session_id": sid, "options": {"async_if_slow": False}},
                headers={"Authorization": f"Bearer {owner}", "Accept": "text/event-stream"},
            )
            report["owner_ask_done"] = True

        # ② 非属主 GET 对方的会话（sess:meta 键不含 user ⇒ W0 报的那条缺口）
        g = await client.get(f"{base}/session/{sid}", headers={"Authorization": f"Bearer {other}"})
        report["nonowner_get_session"] = {
            "http": g.status_code,
            "returned_a_title": bool(_dig(g.json(), "title")) if g.status_code == 200 else False,
            "turns_readable_by_nonowner": len(_dig(g.json(), "turns") or []) if g.status_code == 200 else 0,
            "body_head": g.text[:180],
        }

    verdict = report["nonowner_post_query"]["http"]
    print("[契约期望]", EXPECT)
    print("[实测 ①/POST]", verdict, report["nonowner_post_query"]["codes_seen"] or "-")
    print("[实测 ②/GET ]", report["nonowner_get_session"]["http"],
          "是否回对方标题:", report["nonowner_get_session"]["returned_a_title"])
    print("[判定]", "符合契约（非属主被拒）" if verdict == 404
          else f"⚠️ 与契约不符：HTTP {verdict} 被受理 ⇒ 会话属主校验在 /query 路径缺失或粒度只到 tenant")
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[产物]", args.out)


if __name__ == "__main__":
    asyncio.run(main())
