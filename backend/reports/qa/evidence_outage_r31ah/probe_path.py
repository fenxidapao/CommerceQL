# -*- coding: utf-8 -*-
"""出网路径诊断（只打 /models，零花费；不打印任何凭据）。

目的：W8 的门用 host Python + httpx；QA 上一轮用 curl（走沙箱代理）。
两者可能是**不同的出网路径** => QA 的 6/6 200 未必能推翻 W8 的 2/2 失败。
"""
import io, os, re, sys, time

ROOT = r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL"

def load_env():
    p = os.path.join(ROOT, "deploy", ".env")
    out = {}
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

env = load_env()
key = env["DEEPSEEK_API_KEY"]
base = env["DEEPSEEK_BASE_URL"]
print(f"base_url = {base}")
print(f"key      = <{len(key)} chars, 不打印>")
print(f"host env 代理变量 = " + ", ".join(
    f"{k}={'set' if os.environ.get(k) else 'unset'}"
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")))
print()

import httpx
print("httpx", httpx.__version__)
print()

def try_path(label, *, trust_env, proxy=None):
    kw = {"trust_env": trust_env}
    if proxy is not None:
        kw["proxy"] = proxy
    t0 = time.monotonic()
    try:
        c = httpx.Client(base_url=base, timeout=httpx.Timeout(connect=8.0, read=15.0, write=8.0, pool=8.0), **kw)
        r = c.get("/models", headers={"Authorization": f"Bearer {key}"})
        dt = time.monotonic() - t0
        ids = []
        try:
            ids = [m.get("id") for m in r.json().get("data", [])]
        except Exception:
            pass
        print(f"[{label:24s}] http={r.status_code} t={dt:.2f}s models={ids}")
        c.close()
        return r.status_code
    except Exception as e:
        dt = time.monotonic() - t0
        print(f"[{label:24s}] EXC {type(e).__name__} t={dt:.2f}s detail={str(e)[:110]}")
        return None

# ① 直连（不读环境代理）—— 这是 W8 若没代理时的路径
try_path("direct(trust_env=False)", trust_env=False)
# ② 读环境代理（沙箱注入的那个）
try_path("env-proxy(trust_env=True)", trust_env=True)
# ③ 显式指定环境里的代理
p = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
if p:
    try_path("explicit-env-proxy", trust_env=False, proxy=p)
