# -*- coding: utf-8 -*-
"""离线复现 DoD 门失败的真因（零网络 / 零花费 / 不跑 W8 脚本）。

真因链（三处缺陷，逐步实证）：
  ① `eval/cassette.py:161-176`（record 分支）把上游**全部响应头**原样带上
     （含 `content-encoding: gzip` 与**压缩版** `content-length`），
     而 `content=` 用的是 `await response.aread()` 之后的**已解压明文**；
  ② ⟹ httpx 按 `content-encoding` 再解一次 ⇒ **`httpx.DecodingError`**（确定性，非间歇）；
  ③ `backend/app/llm/client.py:346-350` `except httpx.HTTPError` 把它包成
     `LlmUpstreamError("上游连接失败", detail={"model":…, "kind":"DecodingError"})`
     ⇒ 🔴 **把「解码失败」说成「上游连接失败」**（消息误导了三轮归因）；
  ④ `backend/app/graph/nodes/_shared.py:178-205` `llm_error_update` **只取 `default_code`、丢弃 `exc.detail`**
     ⇒ 终态只剩 `LLM_UPSTREAM_ERROR` ⇒ 根因在产物里**不可见**。

本脚本只做 **①②** 的复现（那是真因所在）；③④ 由**读码**证成（行号已具名）。
"""
import asyncio
import gzip
import pathlib
import sys
import httpx

print("httpx", httpx.__version__)
plain = b'{"choices":[{"message":{"content":"ok"}}]}'

print("\n=== ① 最小单元：带 `content-encoding: gzip` 头的 Response ＋ 明文 body ===")
try:
    r = httpx.Response(status_code=200,
                       headers={"content-type": "application/json",
                                "content-encoding": "gzip",
                                "content-length": str(len(plain) + 40)},
                       content=plain)
    print("   ⇒ 未报错（与假设不符）：", r.content[:24])
except Exception as e:
    print("   🔴 抛：", type(e).__name__, "|", str(e)[:80])
    print("      MRO            =", [c.__name__ for c in type(e).__mro__][:5])
    print("      是 httpx.HTTPError 子类 =", isinstance(e, httpx.HTTPError))
    print("      ⇒ 会被 client.py:346 `except httpx.HTTPError` 捕获")

print("\n=== ② 端到端：经 `CassetteTransport(mode='record')`（上游返回真 gzip）===")


class FakeUpstream(httpx.AsyncBaseTransport):
    """模拟真上游：返回 gzip 压缩的响应（真实 API 就是这么回的）。"""

    async def handle_async_request(self, request):
        body = gzip.compress(plain)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json",
                     "content-encoding": "gzip",
                     "content-length": str(len(body))},
            content=body,
        )


sys.path.insert(0, r"E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL")
from eval.cassette import CassetteTransport  # noqa: E402


async def main():
    ct = CassetteTransport(path=pathlib.Path("fake_cassette.jsonl"),
                           mode="record", upstream=FakeUpstream())
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions",
                        json={"model": "deepseek-flash"})
    try:
        resp = await ct.handle_async_request(req)
        print("   ⇒ transport 返回了响应（未报错）")
        print("      头 =", {k: v for k, v in resp.headers.items()
                            if k in ("content-encoding", "content-length", "content-type")})
        _ = resp.content
        print("      resp.content 可读 ⇒ 与假设不符")
    except Exception as e:
        print("   🔴 抛：", type(e).__name__, "|", str(e)[:90])
        print("      是 httpx.HTTPError 子类 =", isinstance(e, httpx.HTTPError))
        print("      ⇒ `detail['kind']` 恰 = type(exc).__name__ = 'DecodingError'")
        print("      ⇒ 与 W8 第 43 轮 spy 捕到的 {\"model\":\"deepseek-flash\","
              "\"kind\":\"DecodingError\"} **逐字吻合**")
    finally:
        await ct.aclose()


asyncio.run(main())

print("\n=== ③ 对照：replay 分支为何**不会**出这个错 ===")
print("   `eval/cassette.py:197-202` 的 `_to_response` ********显式覆盖******** headers"
      " 为 `{\"content-type\": \"application/json\"}`（**不含 content-encoding**）")
print("   ⇒ **同一路线，只有 record 模式会炸** ⇒ 与 W8「带匣带必失败、去掉匣带 success」完全一致")
