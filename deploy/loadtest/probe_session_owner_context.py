"""U-131 取证（补 W1B 要的那格）：跨属主会话**内容**到底可不可读。

旧件 `probe_session_owner.py` 的顺序有缺陷：它先跑非属主 POST，再让属主问一轮，最后 GET ⇒
读到的"2 个回合"里混着**非属主自己那一轮**，无法判"能不能读到属主内容"。本件按正确顺序做四步：

1. 属主建会话并在其上问一句**带标记词**的 Q1（默认标记 = `2026-06-01` + `退款率`）；
2. **非属主 GET** 该会话 ⇒ 逐轮取 `question` 原文 ⇒ 属主问句出现 = **读侧**内容外泄；
3. 非属主 `POST /query` 提一个**必须依赖上文**的追问 ⇒ 看流里是否出现只可能来自 Q1 的词
   ⇒ 上下文跨属主流入 = **推理侧**外泄；同时看回显的 `session_id` 是不是别人的会话；
4. 属主再 GET ⇒ 回合数是否增加、追问原文是否已进入**别人的**会话 = **写侧**污染。

⚠️ 同一 `thread_id` 的第 2 轮有**两种**形状（W4 `20066a5` 离线复现）：崩（`error(INTERNAL)`、审计 0 行）
与**不崩但静默复用上一轮终态**（HTTP 200 + 多一条同 `outcome` 的审计行 ⇒ 批级不变量在那格差 0、抓不到）。
本件第 4 步因此记两条客户端侧探测器：`terminal_without_any_stage`（本轮没有任何节点报完成却给出终止帧）
与 `terminal_digest_same_as_turn1`（终止帧内容逐字等于第 1 轮）⇒ 两臂（非属主 + `--control` 属主正对照）
必须同交，单臂的 `clarify` 读不出结论。

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


def _sse_names(text: str) -> dict[str, list[str]]:
    """流里出现过哪些 `event:` 名与 `stage` 值 —— **结构**证据，不是内容证据。

    存在的理由：标记词命中（`stream_hits_owner_only_terms`）分不出两种完全不同的事实 —
    "图真的带着别人的上下文跑到了 `gen_sql`" 与 "这一轮在鉴权处就 404 了、流是空的"。
    推理侧那一臂要的正是后者能被**否证**，所以把逐帧的 stage 序列交出去。
    """
    events: set[str] = set()
    stages: set[str] = set()
    for line in text.splitlines():
        if line.startswith("event:"):
            events.add(line[6:].strip())
        elif line.startswith("data:"):
            try:
                body = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict) and isinstance(body.get("stage"), str):
                stages.add(body["stage"])
    return {"events_seen": sorted(events), "stages_seen": sorted(stages)}


#: 终止帧里每轮都会变的键 ⇒ 比对"两轮结论是否同一个"之前先剥掉。
_VOLATILE_FRAME_KEYS = ("task_id", "trace_id", "session_id", "elapsed_ms", "ts", "timestamp", "seq")


def _terminal_frame(text: str) -> dict[str, Any] | None:
    """流里最后一个 `terminal: true` 帧（连同它的 `event:` 名）。"""
    event_name: str | None = None
    found: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            try:
                body = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict) and body.get("terminal") is True:
                found = {**body, "_event": event_name}
    return found


def _frame_digest(frame: dict[str, Any] | None) -> str:
    """终止帧的**内容指纹**（剥掉 `_VOLATILE_FRAME_KEYS`）。

    存在的理由（W4 `20066a5` 的读数）：同一 `thread_id` 的第 2 轮有一种**不崩**的形状 ——
    它把上一轮的终态当本轮结论返回（HTTP 200），并且多落一条 `outcome` 相同的审计行。
    ⇒ 批级不变量在这一格是 `terminal 1 / 审计行 1 = 差 0`（**绿的**），抓不到；
      能抓它的是"这一轮的终止帧内容与上一轮逐字相同、且本轮没有任何节点完成"。
    """
    if not frame:
        return ""
    kept = {k: v for k, v in sorted(frame.items()) if k not in _VOLATILE_FRAME_KEYS}
    return json.dumps(kept, ensure_ascii=False, sort_keys=True, default=str)


def _task_id_of_stream(text: str) -> str | None:
    """流里**任意一帧**的 `task_id`（真服务端只在 `ack` 帧给）。

    ⚠️ 不能用 `_obj(text)` 取：它返回最后一个可解析帧 = 终止帧，而 `clarify`/`complete`
    帧上没有 `task_id` ⇒ 本轮实测两处都读成 `null`，取证件反而交不出唯一的 join 键
    （没有它，W4/W1B 无法把这一轮对上 `app.audit_log` 的行，只能靠时间窗猜）。
    """
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            body = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and isinstance(body.get("task_id"), str) and body["task_id"]:
            return str(body["task_id"])
    return None


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
    ap.add_argument("--control", action="store_true",
                    help="追问改由**属主**提（正对照）：属主带上下文都拿不到 `complete` ⇒ 这句问不出结论，"
                         "非属主那一臂的 `clarify` 只是「无信息」，不能读成「已验证不触发」")
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
            "task_id": _task_id_of_stream(q1["text"]),
            "terminal_frame_seen": '"terminal": true' in q1["text"].replace('"terminal":true', '"terminal": true'),
            "terminal_frame_digest": _frame_digest(_terminal_frame(q1["text"])),
            **_sse_names(q1["text"]),
        }

        g_other = await get_sess(client, other, sid)
        rep["3_nonowner_get"] = {
            "http": g_other["http"],
            "turn_count": len(g_other["questions"]),
            "owner_q1_readable_by_nonowner": any(all(term in q for term in terms) for q in g_other["questions"]),
            "turn_questions_excerpt": [q[:70] for q in g_other["questions"]][:4],
        }

        asker = owner if args.control else other
        q2 = await ask(client, asker, args.followup, sid)
        parsed2 = _obj(q2["text"]) or {}
        rep["4_nonowner_followup"] = {
            "asked_by": "owner(正对照)" if args.control else "nonowner",
            "question": args.followup,
            "http": q2["http"],
            "sse_bytes": q2["sse_bytes"],
            "task_id": _task_id_of_stream(q2["text"]),
            "echoed_session_id_is_owner_session": _dig(parsed2, "session_id") == sid,
            "stream_hits_owner_only_terms": [w for w in terms if w in q2["text"]],
            "codes_seen": sorted(c for c in ("SESSION_NOT_FOUND", "RATE_LIMITED", "INTERNAL") if c in q2["text"]),
            # ↓ 两条是 W4 那格"不崩的复用臂"的客户端侧探测器：批级不变量在它那格是 差 0（绿的），
            #   只有"本轮没有任何节点报完成却给出了终止帧"与"终止帧内容 == 上一轮"能抓到它。
            "terminal_without_any_stage": bool(_terminal_frame(q2["text"]))
                                          and not _sse_names(q2["text"])["stages_seen"],
            "terminal_digest_same_as_turn1": _frame_digest(_terminal_frame(q2["text"]))
                                             == rep["2_owner_q1"]["terminal_frame_digest"],
            **_sse_names(q2["text"]),
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
