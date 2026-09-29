"""U-131 取证（补 W1B 要的那格）：跨属主会话**内容**到底可不可读。

旧件 `probe_session_owner.py` 的顺序有缺陷：它先跑非属主 POST，再让属主问一轮，最后 GET ⇒
读到的"2 个回合"里混着**非属主自己那一轮**，无法判"能不能读到属主内容"。本件按正确顺序做四步：

1. 属主建会话并在其上问一句**带标记词**的 Q1（默认标记 = `2026-06-01` + `退款率`）；
2. **非属主 GET** 该会话 ⇒ 逐轮取 `question` 原文 ⇒ 属主问句出现 = **读侧**内容外泄；
3. 非属主 `POST /query` 提一个**必须依赖上文**的追问 ⇒ 看流里是否出现只可能来自 Q1 的词
   ⇒ 上下文跨属主流入 = **推理侧**外泄；同时看回显的 `session_id` 是不是别人的会话；
4. 属主再 GET ⇒ 回合数是否增加、追问原文是否已进入**别人的**会话 = **写侧**污染。

⚠️ 成本 = 2 次模型请求（≈¥0.01–0.02）。
⚠️ 产物不落令牌：只记问题原文、长度、布尔标记与 `task_id`。
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

Q1_DEFAULT = "T_A 从 2026-06-01 起的退款率是多少？"
FOLLOWUP = "上面那个指标按渠道拆开分别是多少？"
OWNER_ONLY_TERMS = ("2026-06-01", "退款", "refund")


def _dig(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            got = _dig(v, key)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _dig(v, key)
            if got is not None:
                return got
    return None


def _last_data(text: str) -> Any:
    """SSE 是多帧文本，整体 `json.loads` 必失败 ⇒ 取最后一个可解析的 `data:` 帧。"""
    last = None
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                last = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    return last


def _obj(text: str) -> Any:
    """两种响应形态都要能读：`/session` 系是**普通 JSON**，`/query` 系是 **SSE 多帧**。

    ⚠️ 只用 `_last_data` 会把 JSON 响应解析成 `None` ⇒ 明明 HTTP 200 却判"建会话失败"（本件第一版就踩了）。
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return _last_data(text)


def _turns(obj: Any) -> list[Any]:
    t = _dig(obj, "turns")
    return t if isinstance(t, list) else []


def _question_of(turn: Any) -> str:
    for k in ("question", "user_question", "input", "query"):
        v = _dig(turn, k)
        if isinstance(v, str) and v:
            return v
    return json.dumps(turn, ensure_ascii=False)[:80]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="http://127.0.0.1:18000/api/v1")
    ap.add_argument("--tokens", required=True, help="两行：第 1 行属主，第 2 行非属主")
    ap.add_argument("--q1", default=Q1_DEFAULT)
    ap.add_argument("--followup", default=FOLLOWUP)
    ap.add_argument("--terms", default=",".join(OWNER_ONLY_TERMS),
                    help="只可能来自 Q1 的标记词（逗号分隔）；追问流里出现 = 上下文跨属主流入")
    ap.add_argument("--out", default="E:/tmp_w7/probe_owner_context.json")
    args = ap.parse_args()

    toks = [t.strip() for t in Path(args.tokens).read_text(encoding="utf-8").splitlines() if t.strip()]
    if len(toks) < 2:
        raise SystemExit("[中止] 需要 2 条令牌（属主 / 非属主）")
    owner, other = toks[0], toks[1]
    terms = [w.strip() for w in args.terms.split(",") if w.strip()]
    base = args.target.rstrip("/")
    rep: dict[str, Any] = {"expected": "非属主 ⇒ 404 SESSION_NOT_FOUND（附录 A §A.11 / 07 §14 H7 / PRD FR-10.4）"}

    async def ask(client: httpx.AsyncClient, token: str, question: str, sid: str) -> dict[str, Any]:
        r = await client.post(
            f"{base}/query",
            json={"question": question, "session_id": sid, "options": {"async_if_slow": False}},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        return {"http": r.status_code, "sse_bytes": len(r.content), "text": r.text}

    async def get_sess(client: httpx.AsyncClient, token: str, sid: str) -> dict[str, Any]:
        r = await client.get(f"{base}/session/{sid}", headers={"Authorization": f"Bearer {token}"})
        turns = _turns(_obj(r.text) or {})
        return {"http": r.status_code, "text": r.text, "questions": [_question_of(t) for t in turns]}

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{base}/session", json={}, headers={"Authorization": f"Bearer {owner}"})
        sid = _dig(_obj(r.text) or {}, "session_id") if r.status_code == 200 else None
        rep["1_owner_create_session"] = {"http": r.status_code, "session_id_present": bool(sid)}
        if not sid:
            raise SystemExit(f"[中止] 建会话失败 HTTP {r.status_code} {r.text[:120]}")

        q1 = await ask(client, owner, args.q1, sid)
        rep["2_owner_q1"] = {
            "question": args.q1,
            "http": q1["http"],
            "sse_bytes": q1["sse_bytes"],
            "task_id": _dig(_obj(q1["text"]) or {}, "task_id"),
            "terminal_frame_seen": '"terminal": true' in q1["text"].replace('"terminal":true', '"terminal": true'),
        }

        g_other = await get_sess(client, other, sid)
        rep["3_nonowner_get"] = {
            "http": g_other["http"],
            "turn_count": len(g_other["questions"]),
            "owner_q1_readable_by_nonowner": any(all(term in q for term in terms) for q in g_other["questions"]),
            "turn_questions_excerpt": [q[:70] for q in g_other["questions"]][:4],
        }

        q2 = await ask(client, other, args.followup, sid)
        parsed2 = _obj(q2["text"]) or {}
        rep["4_nonowner_followup"] = {
            "question": args.followup,
            "http": q2["http"],
            "sse_bytes": q2["sse_bytes"],
            "task_id": _dig(parsed2, "task_id"),
            "echoed_session_id_is_owner_session": _dig(parsed2, "session_id") == sid,
            "stream_hits_owner_only_terms": [w for w in terms if w in q2["text"]],
            "codes_seen": sorted(c for c in ("SESSION_NOT_FOUND", "RATE_LIMITED", "INTERNAL") if c in q2["text"]),
        }

        g_owner = await get_sess(client, owner, sid)
        rep["5_owner_get"] = {
            "http": g_owner["http"],
            "turn_count": len(g_owner["questions"]),
            "turn_count_grew_vs_nonowner_view": len(g_owner["questions"]) > rep["3_nonowner_get"]["turn_count"],
            "nonowner_followup_written_into_owner_session": any(args.followup[:10] in q for q in g_owner["questions"]),
        }

    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "text"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
