/**
 * C11 DegradeBar 降级提示条（06 §4.11，异常态 3/4）
 * - v1.2 关键修正：degraded 不是终止事件；两种形态由「流是否继续」决定（不是时间窗口启发式）
 *   · Inline 条：degraded 后流继续（仍收到 data/chart/insight）——主路径
 *   · 后台执行中卡片：degraded 后又收到 terminal:true（典型 switched_to_async）
 * - 未知 reason 必须兜底显示，不允许不显示
 * - 预计时间不得编造 → 无字段时只显示「完成后会通知你」
 */
import { useState } from 'react';
import { Button } from 'antd';
import { ClockCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { ActionTaken, DegradedReason } from '../api/types';

export interface DegradeBarProps {
  reason: DegradedReason | string;
  actionTaken: ActionTaken | string;
  partialResult?: unknown;
  pollUrl?: string;
  taskId?: string;
  /** 形态由页面按「流是否继续」判定传入（默认 inline） */
  mode?: 'inline' | 'async_card';
  /** async_card：轮询到终态前展示；页面驱动 */
  asyncHint?: string;
}

/** reason / action → 用户文案（06 §4.11 文案映射表；未知 reason 有兜底） */
function degradeText(reason: string, action: string): string {
  if (action === 'switched_to_async' || reason === 'latency_exceeded') {
    return '查询较慢，已转入后台执行，你可以继续做别的事';
  }
  if (reason === 'llm_unavailable' || action === 'template_only') {
    return '智能解析暂不可用，本次按固定模板查询，结果范围可能受限';
  }
  if (reason === 'cost_too_high') {
    return '本次查询成本较高，已自动缩减范围。建议收窄时间范围或增加筛选条件';
  }
  if (action === 'reduced_candidates' || reason === 'cache_fallback') {
    return '本次返回了部分结果，部分数据未能获取';
  }
  if (reason === 'llm_concurrency_exceeded') return '智能解析并发已达上限，本次使用了降级策略';
  if (reason === 'embedding_unavailable') return '语义检索暂不可用，本次仅用关键词匹配（结果可能不全）';
  if (reason === 'plan_generation_failed') return '查询计划生成异常，本次使用了简化策略';
  if (reason === 'present_failed') return '结果呈现环节降级，展示形式可能与预期不同';
  // 兜底：不允许不显示
  return '本次查询使用了降级策略，结果可能不完整';
}

export function DegradeBar({
  reason,
  actionTaken,
  partialResult,
  pollUrl,
  taskId,
  mode = 'inline',
  asyncHint,
}: DegradeBarProps) {
  const [showDetail, setShowDetail] = useState(false);
  const text = degradeText(reason, actionTaken);

  if (mode === 'async_card') {
    return (
      <div
        data-testid="c11-degrade-card"
        style={{
          background: tokens.color.degraded.bg,
          border: `1px solid ${tokens.color.degraded.border}`,
          borderRadius: tokens.radius.lg,
          padding: tokens.space.md,
          color: tokens.color.degraded.text,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: tokens.font.size.h2 }}>
          <ClockCircleOutlined aria-hidden />
          {text}
        </div>
        <div style={{ fontSize: 12, marginTop: 6, opacity: 0.9 }}>
          {taskId ? `任务号 ${taskId}，` : ''}
          {asyncHint ?? '完成后会通知你'}
        </div>
        {pollUrl && <div style={{ fontSize: 12, marginTop: 4, opacity: 0.7 }}>结果最长保留 1 小时</div>}
        {showDetail && <DetailBlock reason={reason} action={actionTaken} partialResult={partialResult} />}
        <Button
          type="link"
          size="small"
          style={{ fontSize: 12, padding: 0, marginTop: 4 }}
          onClick={() => setShowDetail((v) => !v)}
        >
          {showDetail ? '收起详情' : '展开详情'}
        </Button>
      </div>
    );
  }

  return (
    <div
      data-testid="c11-degrade-bar"
      role="status"
      style={{
        background: tokens.color.degraded.bg,
        border: `1px solid ${tokens.color.degraded.border}`,
        borderRadius: tokens.radius.md,
        padding: `${tokens.space.xxs}px ${tokens.space.xs}px`,
        color: tokens.color.degraded.text,
        fontSize: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <WarningOutlined aria-hidden />
        <span>{text}</span>
        <Button
          type="link"
          size="small"
          style={{ fontSize: 12, padding: 0 }}
          onClick={() => setShowDetail((v) => !v)}
        >
          {showDetail ? '收起详情' : '展开详情'}
        </Button>
      </div>
      {showDetail && <DetailBlock reason={reason} action={actionTaken} partialResult={partialResult} />}
    </div>
  );
}

function DetailBlock({
  reason,
  action,
  partialResult,
}: {
  reason: string;
  action: string;
  partialResult?: unknown;
}) {
  return (
    <div style={{ fontSize: 12, marginTop: 6 }}>
      <div>
        降级原因（原始值）：<code>{reason}</code> · 处置动作：<code>{action}</code>
      </div>
      {partialResult !== undefined && (
        <pre
          style={{
            margin: '4px 0 0',
            padding: 8,
            background: '#fff',
            borderRadius: tokens.radius.sm,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {JSON.stringify(partialResult, null, 2)}
        </pre>
      )}
    </div>
  );
}