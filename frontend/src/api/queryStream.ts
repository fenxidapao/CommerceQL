/**
 * SSE 查询客户端（契约：附录A §A.1.2/A.1.4/A.13/A.14 + 06 §10.1–10.7）
 *
 * 硬规则（06 §10.1）：
 * - 禁止原生 EventSource（不支持 POST/自定义头/读响应头）
 * - 跨 chunk 半行缓冲到 \n\n 才解析
 * - 终止唯一判据：data.terminal === true（禁止事件白名单）
 * - degraded 恒不终止；terminal 缺失视为 false 并告警
 * - 90s 无事件（含心跳）→ 主动中止 + cancel（不得收紧）
 * - 409 SESSION_CONFLICT 自动重试 1 次（复用同一幂等键），不进限流禁用态
 * - 限流头只认 X-RateLimit-Bucket === 'query' 才喂 QuotaIndicator
 */
import type { QueryOptions, QueryRequest, RateLimitInfo, SseEvent } from './types';

const API_BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`;

/** 90s 无事件超时（A.1.4 契约值，禁止收紧） */
export const NO_EVENT_TIMEOUT_MS = 90_000;
/** 409 SESSION_CONFLICT 自动重试次数（06 §10.4：唯一允许自动重试的错误码） */
export const SESSION_CONFLICT_MAX_RETRY = 1;
const SESSION_CONFLICT_DEFAULT_RETRY_AFTER_MS = 3_000;

// ---------------------------------------------------------------------------
// Token（登录页为 stub，D-H 待裁决；token 只放内存，不落 localStorage）
// ---------------------------------------------------------------------------

let authToken: string | null = null;

export function setToken(token: string | null): void {
  authToken = token;
}

export function getToken(): string | null {
  return authToken;
}

// ---------------------------------------------------------------------------
// 幂等键（06 §10.2：同一次提交的重试必须复用；改问题后必须换新）
// ---------------------------------------------------------------------------

const keyCache = new Map<string, string>();

export function makeIdempotencyKey(sessionId: string, question: string): string {
  const cacheKey = `${sessionId}::${question}`;
  if (!keyCache.has(cacheKey)) {
    keyCache.set(cacheKey, `q_${sessionId}_${Date.now()}_${crypto.randomUUID()}`);
  }
  return keyCache.get(cacheKey)!;
}

/** 仅测试用：清空幂等键缓存 */
export function __clearIdempotencyKeyCache(): void {
  keyCache.clear();
}

// ---------------------------------------------------------------------------
// SSE 解析（06 §10.2：单事件 JSON 解析失败不终止流，降级为 _raw）
// ---------------------------------------------------------------------------

export interface ParsedChunk {
  event: string;
  data: unknown;
}

export function parseSSEChunk(raw: string): ParsedChunk | null {
  const lines = raw.split('\n');
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    // ':' 开头是注释行（部分代理会插入），忽略
  }
  if (!dataLines.length) return null;
  const text = dataLines.join('\n');
  try {
    return { event, data: JSON.parse(text) };
  } catch {
    // ⚠️ 刻意不抛：单个事件解析失败不得终止整个流，由 UI 层决定忽略
    return { event, data: { _raw: text } };
  }
}

// ---------------------------------------------------------------------------
// 限流头（只认 query 桶喂 QuotaIndicator，06 §4.14 / §10.6）
// ---------------------------------------------------------------------------

function readRateLimit(headers: Headers): RateLimitInfo | null {
  const bucket = headers.get('X-RateLimit-Bucket');
  if (bucket !== 'query') return null;
  const limit = Number(headers.get('X-RateLimit-Limit'));
  const remaining = Number(headers.get('X-RateLimit-Remaining'));
  const reset = Number(headers.get('X-RateLimit-Reset'));
  if ([limit, remaining, reset].some((n) => Number.isNaN(n))) return null;
  return { bucket, limit, remaining, reset };
}

// ---------------------------------------------------------------------------
// 流客户端
// ---------------------------------------------------------------------------

/** 仅用于埋点分类（onTerminal 参数），不参与终止判定（06 §10.2 警告） */
export type TerminalEvent = 'complete' | 'refuse' | 'clarify' | 'error';

export interface StreamHandlers {
  onEvent: (evt: SseEvent) => void;
  onTerminal: (reason: TerminalEvent) => void;
  onTransportError: (err: Error) => void;
  /** 仅 bucket==='query' 时回调 */
  onRateLimit?: (info: RateLimitInfo) => void;
  /** 409 SESSION_CONFLICT 自动重试回调（attempt 恒为 1） */
  onSessionConflictRetry?: (attempt: number, retryAfterMs: number) => void;
}

export interface QueryStreamInput {
  question: string;
  sessionId?: string | null;
  options?: QueryOptions;
}

export interface QueryStreamResult {
  taskId?: string;
}

let activeController: AbortController | null = null;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function openQueryStream(
  input: QueryStreamInput,
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<QueryStreamResult> {
  const sessionId = input.sessionId ?? '';
  const idempotencyKey = makeIdempotencyKey(sessionId, input.question);

  const body: QueryRequest = {
    question: input.question,
    session_id: input.sessionId ?? null,
    options: {
      explain: input.options?.explain ?? true,
      chart_preference: input.options?.chart_preference ?? 'auto',
      max_rows: Math.min(input.options?.max_rows ?? 5000, 5000), // 前端硬上限 5000
      allow_clarify: true, // 恒 true，不暴露
      timezone: 'Asia/Shanghai', // 恒定
      // max_candidates 不传：由后端决定（成本旋钮，非体验旋钮）
      // async_if_slow / async_threshold_ms 不传：用默认 true / 8000
    },
  };

  // 409 SESSION_CONFLICT：自动重试 1 次，复用同一 Idempotency-Key（A.12）
  for (let attempt = 0; attempt <= SESSION_CONFLICT_MAX_RETRY; attempt++) {
    const result = await doFetch(body, idempotencyKey, handlers, signal);
    if (result.retryAsSessionConflict) {
      handlers.onSessionConflictRetry?.(attempt + 1, result.retryAfterMs);
      await sleep(result.retryAfterMs);
      continue;
    }
    return result.result;
  }
  // 重试后仍 409 → 解除加锁并提示手动重试（由 UI 层处理）
  handlers.onTransportError(new Error('session_conflict_after_retry'));
  return {};
}

/**
 * 澄清应答（A.4 POST /clarify）—— 同样是 SSE 流，且是一条**新流**（原 clarify 事件 terminal:true）
 * 澄清后必然重新完整走一遍权限/绑定/校验/执行（FR-9.2），因此阶段条从第 2 段重新开始。
 */
export async function openClarifyStream(
  clarifyId: string,
  answer: { selected_value?: string; free_text?: string },
  handlers: StreamHandlers,
  signal: AbortSignal,
  sessionId?: string | null,
): Promise<QueryStreamResult> {
  const body = {
    clarify_id: clarifyId,
    selected_value: answer.selected_value ?? null,
    free_text: answer.free_text ?? null,
  };
  const idempotencyKey = makeIdempotencyKey(sessionId ?? '', `clarify:${clarifyId}`);
  const outcome = await doFetch(body, idempotencyKey, handlers, signal, '/clarify');
  return outcome.result;
}

interface FetchOutcome {
  result: QueryStreamResult;
  retryAsSessionConflict?: boolean;
  retryAfterMs: number;
}

async function doFetch(
  body: unknown,
  idempotencyKey: string,
  handlers: StreamHandlers,
  signal: AbortSignal,
  path = '/query',
): Promise<FetchOutcome> {
  const none: FetchOutcome = { result: {}, retryAfterMs: 0 };
  const controller = new AbortController();
  activeController = controller;
  const onExternalAbort = () => controller.abort();
  signal.addEventListener('abort', onExternalAbort, { once: true });

  // 90s 无事件看门狗：任何事件（含 heartbeat）都会重置
  let taskId: string | undefined;
  let timedOut = false;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const markAlive = () => {
    if (watchdog) clearTimeout(watchdog);
    watchdog = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, NO_EVENT_TIMEOUT_MS);
  };
  markAlive();

  const cleanup = () => {
    if (watchdog) clearTimeout(watchdog);
    signal.removeEventListener('abort', onExternalAbort);
    if (activeController === controller) activeController = null;
  };

  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        'X-Trace-Id': crypto.randomUUID(),
        'Idempotency-Key': idempotencyKey,
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    cleanup();
    if (timedOut) {
      // A.1.4 超时兜底：90s 无事件 → 主动中止 + cancel 释放服务端资源
      if (taskId) await cancelQuery(taskId);
      handlers.onTransportError(new Error('no_event_timeout'));
      return none;
    }
    if (signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
      // 用户中止：由 stopCurrentQuery 统一处理 cancel，此处静默
      return none;
    }
    handlers.onTransportError(err instanceof Error ? err : new Error(String(err)));
    return none;
  }

  // 限流信息只能在响应头读到（原生 EventSource 拿不到）
  const rateLimit = readRateLimit(resp.headers);
  if (rateLimit) handlers.onRateLimit?.(rateLimit);

  if (resp.status === 409) {
    // SESSION_CONFLICT：保持加锁 + 自动重试 1 次；不得进限流禁用态（06 §10.4）
    cleanup();
    const ra = Number(resp.headers.get('Retry-After'));
    const retryAfterMs = Number.isNaN(ra) ? SESSION_CONFLICT_DEFAULT_RETRY_AFTER_MS : ra * 1000;
    return { result: {}, retryAsSessionConflict: true, retryAfterMs };
  }

  if (!resp.ok || !resp.body) {
    cleanup();
    handlers.onTransportError(new Error(`HTTP ${resp.status}`));
    return none;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = ''; // ⚠️ 跨 chunk 半行缓冲
  let terminalSeen = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // ⚠️ 只在遇到事件分隔符时才切分；最后一段留在 buffer 里等下一个 chunk
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() ?? '';

      for (const chunk of chunks) {
        const parsed = parseSSEChunk(chunk);
        if (!parsed) continue;

        const data = (parsed.data ?? {}) as Record<string, unknown>;
        markAlive();

        // 心跳：只用于保活，不驱动任何 UI（A.14 第 3 条）
        if (parsed.event === 'heartbeat') continue;

        if (parsed.event === 'ack') taskId = data.task_id as string;

        handlers.onEvent(parsed as SseEvent);

        // ⚠️ 终止判定唯一规则：data.terminal === true（A.1.4）
        if (data.terminal === undefined) {
          // 契约要求每个事件的 data 都带 terminal；缺失视为 false 并告警
          console.warn('[contract] missing_terminal', parsed.event);
        }
        if (data.terminal === true) {
          terminalSeen = true;
          handlers.onTerminal(parsed.event as TerminalEvent);
          cleanup();
          return { result: { taskId }, retryAfterMs: 0 };
        }
        // degraded 的 terminal 恒为 false → 流继续（A.1.2 / A.1.3）
      }
    }
  } catch (err) {
    cleanup();
    if (timedOut) {
      if (taskId) await cancelQuery(taskId);
      handlers.onTransportError(new Error('no_event_timeout'));
      return none;
    }
    if (signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
      return none; // 用户中止，静默
    }
    handlers.onTransportError(err instanceof Error ? err : new Error(String(err)));
    return none;
  }

  cleanup();
  // 流自然结束但没收到 terminal:true → 传输异常，不是正常完成
  if (!terminalSeen) {
    handlers.onTransportError(new Error('stream_closed_without_terminal'));
  }
  return { result: { taskId }, retryAfterMs: 0 };
}

// ---------------------------------------------------------------------------
// 取消（A.3 / 06 §10.3）
// ---------------------------------------------------------------------------

export async function cancelQuery(taskId: string): Promise<void> {
  await fetch(`${API_BASE}/query/${taskId}/cancel`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: '{}',
  }).catch(() => {
    /* 静默：用户已选择停止，取消失败不该再打扰用户（06 §10.3） */
  });
}

/** 用户中止：断前端连接 + 调 cancel（否则服务端继续烧 token） */
export async function stopCurrentQuery(taskId?: string): Promise<void> {
  activeController?.abort();
  if (taskId) {
    // TASK_NOT_FOUND / TASK_NOT_CANCELLABLE 均静默（06 §10.3 边界表）
    await cancelQuery(taskId);
  }
}
