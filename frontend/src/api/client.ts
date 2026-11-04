/**
 * REST 客户端（除 SSE 之外的只读/写入端点）
 * - 唯一契约源：docs/02_附录A_接口契约详解.md v1.5；不调用契约之外的端点
 * - 统一解包 ApiEnvelope（A.0.4），失败抛 ApiError（含 code / trace_id / detail）
 * - 读取类限流（429）保留 Retry-After，供页面就地提示（不弹全局错误）
 */
import { API_BASE } from './base';
import type {
  ApiEnvelope,
  AssetDetail,
  CloseSessionResult,
  ErrorCode,
  LoginResult,
  Paged,
  SessionListItem,
} from './types';
import { getToken } from './queryStream';

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

// ---------------------------------------------------------------------------
// Phase B 端点（B3/B4/B5）—— 形状见 api/types.ts；token 由 request() 统一带
// ---------------------------------------------------------------------------

/** B3：本地账号登录。token 只写内存（`setToken` 由调用方负责）。 */
export const login = (username: string, password: string) =>
  apiPost<LoginResult>('/auth/login', { username, password });

/** B3：注册（服务端 `AUTH_ALLOW_REGISTRATION=false` 时返回 403）。 */
export const register = (username: string, password: string) =>
  apiPost<{ user_id: string; username: string; created_at: string }>('/auth/register', {
    username,
    password,
  });

/** B4：会话列表（只回元数据）。 */
export const listSessions = (params?: {
  limit?: number;
  offset?: number;
  q?: string;
  sort?: 'last_turn_at' | 'created_at';
  order?: 'asc' | 'desc';
}) => apiGet<Paged<SessionListItem>>('/sessions', params);

/** B4：软关闭会话。 */
export const closeSession = (sessionId: string) =>
  apiDelete<CloseSessionResult>(`/session/${sessionId}`);

/** B5：资产详情（已被拒列由后端整列剔除，前端不判断）。 */
export const getAssetDetail = (logicalName: string) =>
  apiGet<AssetDetail>(`/semantic/assets/${encodeURIComponent(logicalName)}`);

export interface ExportFile {
  blob: Blob;
  filename: string;
}

function filenameFrom(header: string | null, taskId: string): string {
  const match = /filename="?([^";]+)"?/i.exec(header ?? '');
  if (!match) return `${taskId}.csv`;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/**
 * B2：导出查询结果。
 *
 * ⚠️ 不能复用 `request()`：那个统一 `resp.json()`，而本端点成功时回的是 `text/csv`。
 * 失败仍走统一错误封套（`{code,message,trace_id}`），故错误分支单独解析。
 * ⚠️ 前端只**触发下载**：不把已到浏览器的数据重新拼 CSV（会绕过 `audit_export_log`）。
 */
export async function exportResult(taskId: string): Promise<ExportFile> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/export`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        'X-Trace-Id': crypto.randomUUID(),
      },
      body: JSON.stringify({ task_id: taskId }),
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

  if (!resp.ok) {
    let payload: unknown = null;
    try {
      payload = await resp.json();
    } catch {
      payload = null;
    }
    const env = payload as ApiEnvelope<unknown> | null;
    throw new ApiError({
      code: env?.code ?? 'INTERNAL',
      message: env?.message ?? `HTTP ${resp.status}`,
      traceId: env?.trace_id,
      httpStatus: resp.status,
      retryAfterSec,
    });
  }

  const contentType = resp.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('text/csv')) {
    // 契约不该走到这里；走到了说明后端回了非 CSV 的 2xx，按错误处理，避免下载一份 JSON。
    throw new ApiError({
      code: 'INTERNAL',
      message: '导出响应不是 CSV',
      httpStatus: resp.status,
    });
  }

  return {
    blob: await resp.blob(),
    filename: filenameFrom(resp.headers.get('Content-Disposition'), taskId),
  };
}