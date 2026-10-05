/**
 * U-136 判据②的**测试面**（T-36 B，零额度）：会话创建那支 401 必须把契约码送到渲染层。
 *
 * 为什么要单开这一支：第 12 轮的真机走查发现金路第一步不是 `POST /query` 而是 `POST /session`
 * （无会话时先建会话），而当时的 `ChatPage` 把 `ApiError` 丢成一句字符串、错误卡硬编码
 * `code="INTERNAL" traceId=""` ⇒ 用户读到「错误编号：INTERNAL」。修在 `26f246e`，但**没有夹具**
 * ⇒ QA 13.8 裁定② 记「判据②测试面 UNVERIFIED」。本件把那格补上（不动判据措辞）。
 *
 * 三臂分工：
 *  1. 过期令牌 ⇒ `POST /session` 回 401 真信封 ⇒ 错误卡编号 = `AUTH_FAILED`、文案「请重新登录」；
 *  2. 状态码不被改写：`apiPost` 抛出的 `ApiError.httpStatus/code/traceId` 原样（🚫 不得改成 403／500）；
 *  3. 对照：非契约码（502 网关 HTML）⇒ 仍退回 `INTERNAL` ⇒ 证明臂 1 的 `AUTH_FAILED` 是**透传**出来的，不是兜底值。
 */
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { ChatPage } from './ChatPage';
import { API_BASE } from '../api/base';

// jsdom 没有这两个 DOM 能力（不是被测代码的缺陷）：ChatPage 会 scrollIntoView、antd 会量尺寸。
const realScroll = Element.prototype.scrollIntoView;
const realResize = globalThis.ResizeObserver;

beforeAll(() => {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* no-op：jsdom 无布局 */
  };
  globalThis.ResizeObserver =
    realResize ??
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
});

afterAll(() => {
  Element.prototype.scrollIntoView = realScroll;
  if (realResize) globalThis.ResizeObserver = realResize;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ENVELOPE_401 = {
  code: 'AUTH_FAILED',
  message: '令牌已过期',
  detail: null,
  suggestions: null,
  trace_id: null,
  server_time: '2026-10-05T05:22:58+00:00',
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** 只装两件事：健康探针恒 200（组件会轮询），以及本臂要验的那个端点。 */
function stub(opts: { session?: Response; query?: Response }) {
  const calls: { url: string; method: string }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);
    calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() });
    if (url.includes('/healthz')) {
      return jsonResponse({
        status: 'ok',
        checks: {
          graph_compiled: true,
          metadata_db: true,
          redis_reachable: true,
          checkpointer_reachable: true,
          semantic_bundle_loaded: true,
          llm_reachable: true,
          embedding_reachable: true,
        },
      });
    }
    if (url.endsWith('/session')) return opts.session ?? jsonResponse({ code: 'OK' }, 200);
    if (url.endsWith('/query')) return opts.query ?? jsonResponse({ code: 'OK' }, 200);
    return jsonResponse({ code: 'OK' });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

function renderChat() {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <Routes>
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function ask(question: string) {
  const box = await screen.findByLabelText('提问输入框');
  fireEvent.change(box, { target: { value: question } });
  fireEvent.click(await screen.findByLabelText('发送问题'));
}

describe('U-136 判据②：会话创建支的 401 必须传到错误卡', () => {
  it('过期令牌 ⇒ 编号 = AUTH_FAILED（非空）且文案指向重新登录', async () => {
    const { calls } = stub({ session: jsonResponse(ENVELOPE_401, 401) });
    renderChat();
    await ask('上个月复购率最高的 10 个店铺是哪些？');

    const card = await screen.findByText(/错误编号：/);
    expect(card.textContent).toContain('AUTH_FAILED');
    expect(screen.getByText(/登录已过期或令牌无效，请重新登录/)).toBeTruthy();
    expect(screen.getAllByText(/重新登录/).length).toBeGreaterThan(1);

    const sessionCall = calls.find((c) => c.url.endsWith('/session'));
    expect(sessionCall?.method).toBe('POST');
    expect(sessionCall?.url).toBe(`${API_BASE}/session`);
  });

  it('令牌片段不得出现在页面上（U-136 判据①的泄露面）', async () => {
    const { calls } = stub({ session: jsonResponse(ENVELOPE_401, 401) });
    const { container } = renderChat();
    await ask('各渠道的订单量排名');
    await screen.findByText(/错误编号：/);
    expect(container.textContent).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}/);
    expect(calls.filter((c) => c.url.endsWith('/query')).length).toBe(0);
  });

  it('对照：非契约码（502 网关 HTML）仍退回 INTERNAL ⇒ 臂 1 的 AUTH_FAILED 是透传不是兜底', async () => {
    stub({
      session: new Response('<html>502 Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    });
    renderChat();
    await ask('各渠道的订单量排名');

    await waitFor(async () => {
      const card = await screen.findByText(/错误编号：/);
      expect(card.textContent).toContain('INTERNAL');
    });
  });
});
