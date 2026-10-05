/**
 * U-136 判据②（渲染侧，零额度）：错误卡的「错误编号」**不得为空**，且 401 走「重新登录」文案。
 *
 * 事故形状（2026-10-04 浏览器走查实测）：令牌过期后 `POST /api/v1/query` 回 401，
 * 统一响应信封里 `code = AUTH_FAILED` 明明在（04:32:05Z 现测），但错误卡渲染成
 * 「查询过程中发生错误 ／ 错误编号：（空）」⇒ 用户与答辩都读不出"该重新登录"。
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ErrorCard } from './ErrorCard';

// vitest 配置里 `globals: false` ⇒ RTL 的自动 cleanup 不会挂上，得自己清（否则上一臂的 DOM 留在页面里）
afterEach(() => {
  cleanup();
});

function numberLine(container: HTMLElement): string {
  const node = [...container.querySelectorAll('span')].find((s) => (s.textContent ?? '').startsWith('错误编号：'));
  return (node?.textContent ?? '').replace('错误编号：', '').trim();
}

describe('U-136 错误卡编号与 401 文案', () => {
  it('trace_id 缺失（请求级 401 的真实形状）⇒ 编号退回 code，不留空', () => {
    const { container } = render(
      <MemoryRouter>
        <ErrorCard code="AUTH_FAILED" message="令牌已过期" traceId="" retryable={false} />
      </MemoryRouter>,
    );
    expect(numberLine(container)).toBe('AUTH_FAILED');
  });

  it('401 的主文案指向「重新登录」，动作按钮在位（🚫 不改状态码语义）', () => {
    render(
      <MemoryRouter>
        <ErrorCard code="AUTH_FAILED" message="令牌已过期" traceId="" retryable={false} />
      </MemoryRouter>,
    );
    // 文本节点被父级 div 一并命中 ⇒ getAllByText（不是"渲染了两遍"）
    expect(screen.getAllByText('登录已过期或令牌无效，请重新登录').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '重新登录' })).toBeTruthy();
    expect(screen.queryByText('查询过程中发生错误')).toBeNull();
  });

  it('有 trace_id 时仍以 trace_id 为编号（防"一律换成 code"这种过度修复）', () => {
    const { container } = render(
      <MemoryRouter>
        <ErrorCard code="INTERNAL" message="x" traceId="tr_0f3a91" retryable={false} />
      </MemoryRouter>,
    );
    expect(numberLine(container)).toBe('tr_0f3a91');
  });
});
