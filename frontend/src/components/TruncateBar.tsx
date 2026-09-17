/**
 * C8 TruncateBar 截断提示条（06 §4.8）
 * - 红线 R-4：data.truncated === true 必须渲染；只由 truncated 驱动
 * - 位置：结果块顶部（由页面组装保证）
 * - 截断 + 饼图 → 额外 degraded 提示「占比不可信」
 */
import { Button } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { ChartType } from '../api/types';

export interface TruncateBarProps {
  truncated: boolean;
  rowCount: number;
  /** 本次请求的 options.max_rows */
  maxRows: number;
  chartType?: ChartType;
  /** 「收窄范围重问」：把提示语填回 AskBox（不自动提交） */
  onNarrow?: () => void;
}

export function TruncateBar({ truncated, rowCount, maxRows, chartType, onNarrow }: TruncateBarProps) {
  if (!truncated) return null;

  return (
    <div data-testid="c8-truncate-bar">
      <div
        role="status"
        style={{
          borderRadius: tokens.radius.md,
          background: tokens.color.info.bg,
          border: `1px solid ${tokens.color.info.border}`,
          color: tokens.color.info.text,
          padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
          fontSize: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span className="sr-only">结果被截断</span>
        <InfoCircleOutlined aria-hidden />
        <span>
          本次仅返回前 <strong>{rowCount}</strong> 行（上限 {maxRows}）。结果不是全量，请勿据此判断总量。
          {rowCount >= maxRows && ' 如需完整数据，请收窄时间范围或增加筛选条件。'}
        </span>
        {onNarrow && (
          <Button size="small" type="link" onClick={onNarrow} style={{ fontSize: 12, padding: 0 }}>
            收窄范围重问
          </Button>
        )}
      </div>
      {chartType === 'pie' && (
        <div
          role="status"
          style={{
            marginTop: 4,
            borderRadius: tokens.radius.md,
            background: tokens.color.degraded.bg,
            border: `1px solid ${tokens.color.degraded.border}`,
            color: tokens.color.degraded.text,
            padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
            fontSize: 12,
          }}
        >
          占比图基于被截断的部分数据，占比不可信。
        </div>
      )}
    </div>
  );
}
