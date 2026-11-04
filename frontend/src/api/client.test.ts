/**
 * B2：`exportResult` 的传输形状。
 *
 * 与 `request()` 的差别只有一处：成功响应是 `text/csv`，不能走 `resp.json()`。
 * 失败仍必须解析统一错误封套，让 404/429/500 能带着 code 到达 UI。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, exportResult } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('exportResult', () => {
  it('成功时返回 CSV blob 与后端文件名', async () => {
    stubFetch(
      new Response('amount\r\n1\r\n', {
        status: 200,
        headers: {
          'content-type': 'text/csv; charset=utf-8',
          'content-disposition': 'attachment; filename="tk_1.csv"',
        },
      }),
    );

    const file = await exportResult('tk_1');
    expect(file.filename).toBe('tk_1.csv');
    // jsdom 的 Blob 没有 .text()，用 FileReader 读同一份字节，避免只断言 size。
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file.blob);
    });
    expect(text).toBe('amount\r\n1\r\n');
  });

  it('失败时解析统一错误封套为 ApiError', async () => {
    stubFetch(
      new Response(
        JSON.stringify({
          code: 'TASK_NOT_FOUND',
          message: '任务不存在或已过期',
          trace_id: 'tr_1',
          detail: null,
        }),
        { status: 404, headers: { 'content-type': 'application/json' } },
      ),
    );

    await expect(exportResult('tk_missing')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'TASK_NOT_FOUND',
      traceId: 'tr_1',
      httpStatus: 404,
    } satisfies Partial<ApiError>);
  });

  it('2xx 但不是 CSV 时按错误处理，避免下载 JSON', async () => {
    stubFetch(
      new Response(JSON.stringify({ code: 'OK', message: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    await expect(exportResult('tk_1')).rejects.toMatchObject({
      code: 'INTERNAL',
      httpStatus: 200,
    });
  });
});
