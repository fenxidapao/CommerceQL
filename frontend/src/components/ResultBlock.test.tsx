/**
 * B2：ResultBlock 只负责触发下载（06 §6.8）。
 *
 * 三臂：
 *  1. 有 taskId ⇒ 按钮可见；点击调用 `exportResult(taskId)` 并触发一次 anchor 下载；
 *  2. 无 taskId ⇒ 不渲染按钮（导出必须带服务端 task_id 做归属校验）；
 *  3. 导出失败 ⇒ 错误就地可见，不静默。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ResultBlock } from './ResultBlock';
import { exportResult } from '../api/client';
import type { DataEvent } from '../api/types';

vi.mock('../api/client', () => ({ exportResult: vi.fn() }));

const mockedExport = vi.mocked(exportResult);

const DATA: DataEvent = {
  columns: [{ name: 'amount', type: 'number' }],
  rows: [[1]],
  row_count: 1,
  truncated: false,
};

const realCreate = URL.createObjectURL;
const realRevoke = URL.revokeObjectURL;
const realMatchMedia = window.matchMedia;
const realResize = globalThis.ResizeObserver;

beforeEach(() => {
  globalThis.ResizeObserver =
    realResize ??
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  // jsdom 没有 matchMedia，antd Grid/useBreakpoint 一挂载就订阅它（不是被测代码的缺陷）。
  window.matchMedia =
    realMatchMedia ??
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList);
  Object.defineProperty(URL, 'createObjectURL', {
    value: vi.fn(() => 'blob:test'),
    configurable: true,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: vi.fn(),
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  Object.defineProperty(URL, 'createObjectURL', { value: realCreate, configurable: true });
  Object.defineProperty(URL, 'revokeObjectURL', { value: realRevoke, configurable: true });
  if (realResize) globalThis.ResizeObserver = realResize;
  if (realMatchMedia) window.matchMedia = realMatchMedia;
});

describe('ResultBlock 导出入口', () => {
  it('有 taskId 时点击导出，调用 exportResult 并触发下载', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    mockedExport.mockResolvedValue({ blob: new Blob(['amount\r\n1\r\n']), filename: 'tk_1.csv' });

    render(<ResultBlock data={DATA} chart={null} taskId="tk_1" />);
    fireEvent.click(screen.getByTestId('c5-export-csv'));

    await waitFor(() => expect(mockedExport).toHaveBeenCalledWith('tk_1'));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });

  it('无 taskId 时不渲染导出按钮', () => {
    render(<ResultBlock data={DATA} chart={null} />);
    expect(screen.queryByTestId('c5-export-csv')).toBeNull();
  });

  it('空结果仍可导出（后端回表头行）', () => {
    render(
      <ResultBlock
        data={{ ...DATA, rows: [], row_count: 0 }}
        chart={null}
        taskId="tk_empty"
      />,
    );
    expect(screen.getByTestId('c5-export-csv')).toBeTruthy();
  });

  it('导出失败时就地显示错误', async () => {
    mockedExport.mockRejectedValue(new Error('审计写入失败'));
    render(<ResultBlock data={DATA} chart={null} taskId="tk_1" />);
    fireEvent.click(screen.getByTestId('c5-export-csv'));

    await waitFor(() => expect(screen.getByTestId('c5-export-error')).toBeTruthy());
    expect(screen.getByTestId('c5-export-error').textContent).toContain('审计写入失败');
  });
});
