# -*- coding: utf-8 -*-
"""补全端点冒烟（POST，max_tokens=1，成本≈¥0；只报状态与时延，不打印凭据/正文）。"""
import io, os, time
ROOT = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"
env = {}
for line in io.open(os.path.join(ROOT, "deploy", ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
import httpx
MODELS = [env.get("LLM_MODEL_FAST"), env.get("LLM_MODEL_STRONG")]
# 用项目网关**同样的超时形态**：connect=5.0 / read=None
TO = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)
for m in MODELS:
    for i in (1, 2):
        t0 = time.monotonic()
        try:
            c = httpx.Client(base_url=env["DEEPSEEK_BASE_URL"], timeout=TO, trust_env=False)
            r = c.post("/chat/completions",
                       headers={"Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}"},
                       json={"model": m, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
            dt = time.monotonic() - t0
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            fr = (body.get("choices") or [{}])[0].get("finish_reason")
            usage = body.get("usage") or {}
            print(f"[{m:18s} #{i}] http={r.status_code} t={dt:.2f}s finish={fr} usage={usage}")
            c.close()
        except Exception as e:
            print(f"[{m:18s} #{i}] EXC {type(e).__name__} t={time.monotonic()-t0:.2f}s {str(e)[:90]}")
