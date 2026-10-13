# -*- coding: utf-8 -*-
import json
import re

P = r"C:\Users\林琪荣\.workbuddy\projects\e-01_实训-项目-基于Text2SQL的电商数据分析Agent-CommerceQL\07afc410-c693-42b7-a157-28970f46c90a.jsonl"

SR = re.compile(r"<system-reminder[^>]*>.*?</system-reminder>", re.S)


def human_text(o):
    if o.get("type") != "message" or o.get("role") != "user":
        return None
    c = o.get("content")
    parts = []
    if isinstance(c, str):
        parts = [c]
    elif isinstance(c, list):
        for it in c:
            if isinstance(it, dict) and it.get("type") == "input_text":
                parts.append(it.get("text") or "")
    txt = "\n".join(parts).strip()
    if not txt:
        return None
    # 剥掉全部 system-reminder 包装块
    txt = SR.sub("", txt).strip()
    if not txt:
        return None
    return txt


msgs = []
with open(P, encoding="utf-8") as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = human_text(o)
        if t:
            msgs.append((i, o.get("timestamp") or "", t))

print(f"TOTAL_HUMAN={len(msgs)}")
for i, ts, t in msgs:
    print("=" * 78)
    # ts 可能是毫秒纪元
    print(f"[line {i}] {ts}")
    print(t[:2200])
