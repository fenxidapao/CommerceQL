/**
 * T2 单测：queryStream（06 §10.1 硬规则逐条对应）
 * 用假 fetch 直接喂字节流，不依赖 MSW node 服务。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __clearIdempotencyKeyCache,
  makeIdempotencyKey,
  openQueryStream,
  parseSSEChunk,
  NO_EVENT_TIMEOUT_MS,
  type StreamHandlers,
} from './queryStream';
import type { SseEvent } from './types';

function encodeStream(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

/** 把文本按指定大小切分成多个 chunk（模拟网络分片） */
function chunkedStream(text: string, chunkSize: number): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(text);
  return new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) {
        controller.enqueue(bytes.slice(i, i + chunkSize));
      }
      controller.close();
    },
  });
}

function makeResponse(body: ReadableStream<Uint8Array>, init?: { status?: number; headers?: Record<string, string> }) {
  return new Response(body, { status: init?.status ?? 200, headers: init?.headers });
}

function makeHandlers(): StreamHandlers & {
  events: SseEvent[];
  terminals: string[];
  errors: string[];
  rateLimits: unknown[];
  conflictRetries: number[];
} {
  const h = {
    events: [] as SseEvent[],
    terminals: [] as string[],
    errors: [] as string[],
    rateLimits: [] as unknown[],
    conflictRetries: [] as number[],
    onEvent(evt: SseEvent) {
      h.events.push(evt);
    },
    onTerminal(reason: string) {
      h.terminals.push(reason);
    },
    onTransportError(err: Error) {
      h.errors.push(err.message);
    },
    onRateLimit(info: unknown) {
      h.rateLimits.push(info);
    },
    onSessionConflictRetry(attempt: number) {
      h.conflictRetries.push(attempt);
    },
  };
  return h as StreamHandlers & {
    events: SseEvent[];
    terminals: string[];
    errors: string[];
    rateLimits: unknown[];
    conflictRetries: number[];
  };
}

const INPUT = { question: '测试问题', sessionId: 'ss_test' };

describe('parseSSEChunk', () => {
  it('解析 event + data', () => {
    const parsed = parseSSEChunk('event: stage\ndata: {"stage":"intent","terminal":false}');
    expect(parsed).toEqual({ event: 'stage', data: { stage: 'intent', terminal: false } });
  });

  it('忽略注释行；无 data 返回 null', () => {
    expect(parseSSEChunk(': comment from proxy')).toBeNull();
  });

  it('单行 JSON 解析失败 → 降级 _raw，不抛异常', () => {
    const parsed = parseSSEChunk('event: meta\ndata: {broken json');
    expect(parsed?.event).toBe('meta');
    expect((parsed?.data as { _raw: string })._raw).toBe('{broken json');
  });
});

describe('openQueryStream', () => {
  beforeEach(() => {
    __clearIdempotencyKeyCache();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('跨 chunk 半行缓冲：事件被拆到任意字节边界仍正确解析', async () => {
    const text =
      'event: ack\ndata: {"task_id":"tk_1","session_id":"ss_test","terminal":false}\n\n' +
      'event: complete\ndata: {"terminal":true}\n\n';
    // 每 3 字节一个 chunk，必然切碎事件边界
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(makeResponse(chunkedStream(text, 3))),
    );
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.errors).toEqual([]);
    expect(h.events.map((e) => e.event)).toEqual(['ack', 'complete']);
    expect(h.terminals).toEqual(['complete']);
  });

  it('终止唯一判据 data.terminal===true：degraded 不终止，流继续到 complete', async () => {
    const text =
      'event: ack\ndata: {"task_id":"tk_1","session_id":"ss_test","terminal":false}\n\n' +
      'event: degraded\ndata: {"reason":"cost_too_high","action_taken":"reduced_candidates","terminal":false}\n\n' +
      'event: data\ndata: {"columns":[],"rows":[],"row_count":0,"truncated":false,"terminal":false}\n\n' +
      'event: complete\ndata: {"terminal":true}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(encodeStream(text))));
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.events.map((e) => e.event)).toEqual(['ack', 'degraded', 'data', 'complete']);
    expect(h.terminals).toEqual(['complete']);
  });

  it('heartbeat 只保活：不进入 onEvent、不触发终止', async () => {
    const text =
      'event: ack\ndata: {"task_id":"tk_1","session_id":"ss_test","terminal":false}\n\n' +
      'event: heartbeat\ndata: {"terminal":false}\n\n' +
      'event: complete\ndata: {"terminal":true}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(encodeStream(text))));
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.events.map((e) => e.event)).toEqual(['ack', 'complete']);
    expect(h.terminals).toEqual(['complete']);
  });

  it('terminal 缺失视为 false 并告警，不提前终止', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const text =
      'event: ack\ndata: {"task_id":"tk_1","session_id":"ss_test"}\n\n' + // 无 terminal
      'event: complete\ndata: {"terminal":true}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(encodeStream(text))));
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.events.map((e) => e.event)).toEqual(['ack', 'complete']);
    expect(warn).toHaveBeenCalledWith('[contract] missing_terminal', 'ack');
    expect(h.terminals).toEqual(['complete']);
  });

  it('流自然结束但无 terminal:true → 报 stream_closed_without_terminal', async () => {
    const text = 'event: ack\ndata: {"task_id":"tk_1","session_id":"ss_test","terminal":false}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(encodeStream(text))));
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.errors).toContain('stream_closed_without_terminal');
  });

  it('90s 无事件超时：主动中止并调 cancel（不得收紧为其他值）', async () => {
    expect(NO_EVENT_TIMEOUT_MS).toBe(90_000);
    vi.useFakeTimers();
    const cancelCalls: string[] = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/cancel')) {
        cancelCalls.push(String(url));
        return Promise.resolve(new Response('{}', { status: 200 }));
      }
      // 主请求：先给 ack，之后永不推送（连接挂着）；abort 时按真实 fetch 行为报错
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              'event: ack\ndata: {"task_id":"tk_timeout","session_id":"ss_test","terminal":false}\n\n',
            ),
          );
          init?.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('The operation was aborted.', 'AbortError'));
          });
        },
      });
      return Promise.resolve(makeResponse(stream));
    });
    vi.stubGlobal('fetch', fetchMock);
    const h = makeHandlers();
    const p = openQueryStream(INPUT, h, new AbortController().signal);
    // 推进 90s 触发看门狗
    await vi.advanceTimersByTimeAsync(NO_EVENT_TIMEOUT_MS + 10);
    await p;
    expect(h.errors).toContain('no_event_timeout');
    expect(cancelCalls.some((u) => u.includes('/query/tk_timeout/cancel'))).toBe(true);
  });

  it('Idempotency-Key：同会话同问题复用同 key；改问题换新 key', () => {
    const k1 = makeIdempotencyKey('ss_a', '问题一');
    const k2 = makeIdempotencyKey('ss_a', '问题一');
    const k3 = makeIdempotencyKey('ss_a', '问题二');
    expect(k1).toBe(k2);
    expect(k1).not.toBe(k3);
    expect(k1).toMatch(/^q_ss_a_\d+_[0-9a-f-]{36}$/);
  });

  it('409 SESSION_CONFLICT：自动重试 1 次并复用同一幂等键，不进限流态', async () => {
    const keys: (string | null)[] = [];
    let call = 0;
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      call++;
      keys.push((init?.headers as Record<string, string>)['Idempotency-Key'] ?? null);
      if (call === 1) {
        return Promise.resolve(
          new Response(JSON.stringify({ code: 'SESSION_CONFLICT' }), {
            status: 409,
            headers: { 'Retry-After': '0' },
          }),
        );
      }
      return Promise.resolve(
        makeResponse(encodeStream('event: complete\ndata: {"terminal":true}\n\n')),
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.conflictRetries).toEqual([1]); // 恰好重试 1 次
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(keys[0]).toBe(keys[1]); // 复用同一幂等键
    expect(keys[0]).toBeTruthy();
    expect(h.rateLimits).toEqual([]); // 409 不喂 QuotaIndicator
    expect(h.terminals).toEqual(['complete']);
  });

  it('409 重试后仍失败 → 报 session_conflict_after_retry（总共 2 次请求）', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ code: 'SESSION_CONFLICT' }), {
          status: 409,
          headers: { 'Retry-After': '0' },
        }),
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(h.errors).toContain('session_conflict_after_retry');
  });

  it('限流头只认 query 桶：read 桶不回调 onRateLimit', async () => {
    const text = 'event: complete\ndata: {"terminal":true}\n\n';
    const fetchMock = vi.fn().mockResolvedValue(
      makeResponse(encodeStream(text), {
        headers: {
          'X-RateLimit-Bucket': 'read',
          'X-RateLimit-Limit': '120',
          'X-RateLimit-Remaining': '118',
          'X-RateLimit-Reset': '1789374400',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.rateLimits).toEqual([]);
  });

  it('query 桶限流头正常回调 onRateLimit', async () => {
    const text = 'event: complete\ndata: {"terminal":true}\n\n';
    const fetchMock = vi.fn().mockResolvedValue(
      makeResponse(encodeStream(text), {
        headers: {
          'X-RateLimit-Bucket': 'query',
          'X-RateLimit-Limit': '10',
          'X-RateLimit-Remaining': '7',
          'X-RateLimit-Reset': '1789374400',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.rateLimits).toEqual([{ bucket: 'query', limit: 10, remaining: 7, reset: 1789374400 }]);
  });

  it('单事件 JSON 解析失败不终止流：后续事件照常分发', async () => {
    const text =
      'event: meta\ndata: {broken\n\n' +
      'event: complete\ndata: {"terminal":true}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makeResponse(encodeStream(text))));
    const h = makeHandlers();
    await openQueryStream(INPUT, h, new AbortController().signal);
    expect(h.events.map((e) => e.event)).toEqual(['meta', 'complete']);
    expect((h.events[0].data as { _raw: string })._raw).toBe('{broken');
    expect(h.terminals).toEqual(['complete']);
  });
});
