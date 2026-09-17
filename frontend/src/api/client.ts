/**
 * REST 客户端（除 SSE 之外的只读/写入端点）
 * - 唯一契约源：docs/02_附录A_接口契约详解.md v1.5；不调用契约之外的端点
 * - 统一解包 ApiEnvelope（A.0.4），失败抛 ApiError（含 code / trace_id / detail）
 * - 读取类限流（429）保留 Retry-After，供页面就地提示（不弹全局错误）
 */
import type { ApiEnvelope, ErrorCode } from './types';
import { getToken } from './queryStream';

const API_BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  code: ErrorCode | string;
  traceId: string;
  httpStatus: number;
  detail?: Record<string, unknown>;
  retryAfterSec?: number;

  constructor(init: {
    code: ErrorCode | string;
    message: string;
    traceId?: string;
    httpStatus: number;
    detail?: Record<string, unknown>;
    retryAfterSec?: number;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.code = init.code;
    this.traceId = init.traceId ?? '';
    this.httpStatus = init.httpStatus;
    this.detail = init.detail;
    this.retryAfterSec = init.retryAfterSec;
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

export function buildQuery(params?: Query): string {
  if (!params) return '';
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

async function request<T>(method: 'GET' | 'POST' | 'DELETE', path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        'X-Trace-Id': crypto.randomUUID(),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    throw new ApiError({
      code: 'INTERNAL',
      message: err instanceof Error ? err.message : '网络请求失败',
      httpStatus: 0,
    });
  }

  const ra = Number(resp.headers.get('Retry-After'));
  const retryAfterSec = Number.isFinite(ra) && ra > 0 ? ra : undefined;

  let payload: unknown = null;
  try {
    payload = await resp.json();
  } catch {
    payload = null; // 204 或空体
  }
  const env = payload as ApiEnvelope<T> | null;

  if (!resp.ok) {
    throw new ApiError({
      code: env?.code ?? 'INTERNAL',
      message: env?.message ?? `HTTP ${resp.status}`,
      traceId: env?.trace_id,
      httpStatus: resp.status,
      retryAfterSec,
    });
  }
  if (env && env.code && env.code !== 'OK') {
    // 2xx 但业务码非 OK：按错误处理（防御后端"200 包错误码"）
    throw new ApiError({
      code: env.code,
      message: env.message,
      traceId: env.trace_id,
      httpStatus: resp.status,
      retryAfterSec,
    });
  }
  return env ? env.data : (payload as T);
}

export const apiGet = <T>(path: string, params?: Query) => request<T>('GET', `${path}${buildQuery(params)}`);
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {});
export const apiDelete = <T>(path: string) => request<T>('DELETE', path);