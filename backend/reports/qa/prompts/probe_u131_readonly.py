"""U-131 非属主两臂的 QA 独立复算（零额度：两条都应在进图前返回 404）。

只印 状态码 / 布尔 / 计数 —— 不印令牌、不印题面、不印结果行（N-11 同源）。
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api/v1"
MINT = ["../.venv/Scripts/python.exe", "scripts/mint_dev_token.py", "--tenant-id", "T_A"]


def token_for(user_id: str) -> str:
    r = subprocess.run(
        MINT + ["--user-id", user_id],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, r.stderr[-200:]
    return r.stdout.strip()


def call(method: str, path: str, tok: str, body: dict | None = None, idem: str | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + tok,
            "Content-Type": "application/json",
            **({"Idempotency-Key": idem} if idem else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()[:800]
            return resp.status, raw[:1].decode("utf-8", "replace"), len(raw), None, raw
    except urllib.error.HTTPError as e:
        raw = e.read()[:600]
        code = None
        try:
            code = json.loads(raw.decode("utf-8", "replace")).get("code")
        except Exception:
            code = "UNPARSED"
        return e.code, raw[:1].decode("utf-8", "replace"), len(raw), code, b""


owner = token_for("u_qa_own_r5")
nonowner = token_for("u_qa_non_r5")

st, first, n, _, raw = call("POST", "/session", owner, body={})
sid = None
if st in (200, 201):
    try:
        body = json.loads(raw.decode("utf-8"))
        sid = body.get("session_id") or body.get("data", {}).get("session_id")
    except Exception as exc:
        print("create_session_parse_fail:", type(exc).__name__)
print("A_create_session_http =", st, "| sid_in_hand =", bool(sid))

if sid:
    got_owner = call("GET", "/session/" + sid, owner)
    got_non = call("GET", "/session/" + sid, nonowner)
    print("B_owner_GET =", got_owner[0])
    print("C_nonowner_GET =", got_non[0], "| body_code =", got_non[3])
    post_non = call("POST", "/query", nonowner, body={"question": "probe", "session_id": sid}, idem="qa-r5-nonowner")
    print("D_nonowner_POST_query =", post_non[0], "| body_code =", post_non[3], "| sse_first_byte =", post_non[1])
    post_owner = call("POST", "/query", owner, body={"question": " ", "session_id": sid}, idem="qa-r5-owner-blank")
    print("E_owner_POST_blank_question =", post_owner[0], "| （422 才是期望：空题面被 DTO 拦住，不进图）")
else:
    print("SKIPPED: 没拿到 session_id（建会话那步就失败），活体两臂未复算")
