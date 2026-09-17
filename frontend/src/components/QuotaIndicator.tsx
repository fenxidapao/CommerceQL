/**
 * C14 QuotaIndicator 配额与限流指示（06 §4.14）
 * - 只认 X-RateLimit-Bucket === 'query' 的信息（上游 queryStream 已过滤，这里再防一次）
 * - 无数据不渲染；>30% 灰字；≤30% 琥珀；=0 红 + 由页面驱动 AskBox 限流禁用态
 * - SESSION_CONFLICT（409）永远不得喂到本组件（A.11 补充约定）
 */
import { Popover } from 'antd';
import dayjs from 'dayjs';
import { tokens } from '../theme/tokens';
import type { RateLimitInfo } from '../api/types';

export interface QuotaIndicatorProps {
  rateLimit: RateLimitInfo | null;
}

export function QuotaIndicator({ rateLimit }: QuotaIndicatorProps) {
  // 无响应头 → 不渲染（不显示 0 或 --，避免制造焦虑）
  if (!rateLimit || rateLimit.bucket !== 'query') return null;

  const { limit, remaining, reset } = rateLimit;
  const low = remaining > 0 && remaining <= limit * 0.3;
  const empty = remaining <= 0;
  const color = empty
    ? tokens.color.error.border
    : low
      ? tokens.color.degraded.border
      : tokens.color.text.tertiary;

  return (
    <Popover
      content={
        <div style={{ fontSize: 12 }}>
          <div>查询类额度：本分钟 {remaining} / {limit} 次</div>
          <div>重置时刻：{dayjs.unix(reset).format('HH:mm:ss')}</div>
        </div>
      }
      trigger="click"
    >
      <button
        type="button"
        data-testid="c14-quota-indicator"
        role="status"
        aria-label={`本分钟剩余 ${remaining} 次查询`}
        style={{
          border: 'none',
          background: 'transparent',
          cursor: 'pointer',
          fontSize: 12,
          color,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 8px',
        }}
      >
        {(low || empty) && <span aria-hidden>●</span>}
        本分钟剩余 {remaining} 次
      </button>
    </Popover>
  );
}
