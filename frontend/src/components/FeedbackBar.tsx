/**
 * C13 FeedbackBar 反馈条（06 §4.13）
 * - P0：仅「结果有误」+ 原因 + 备注；不渲染 SQL 编辑框（corrected_sql 属 P1）
 * - 👎 就地展开（不用 Modal）；提交成功文案必须含「进入人工审核」（A.6：修正不直接生效）
 * - 提交失败保留已填内容 + inline error + 重试
 * - RefuseCard / ClarifyCard / ErrorCard 不展示本组件（由页面组装保证）
 */
import { useState } from 'react';
import { Button, Input, Select, message } from 'antd';
import { DislikeOutlined, LikeOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { FeedbackReasonCode } from '../api/types';

/** 10 个 reason_code 的业务化文案（06 §4.13 表，直接把枚举丢给用户是不合格的） */
export const REASON_TEXT: Record<FeedbackReasonCode, string> = {
  wrong_metric_definition: '指标口径不对（比如 GMV 该不该含运费）',
  wrong_time_range: '时间范围不对（比如"上个月"理解错了）',
  wrong_dimension: '分组维度不对（比如按错了类目层级）',
  missing_synonym: '我问的词没被正确理解',
  wrong_join: '数据关联错了（数字对不上）',
  wrong_aggregation: '计算方式不对（该求和却算了平均等）',
  missing_default_filter: '漏了应有的过滤（比如把退款单也算进去了）',
  permission_issue: '权限判定有问题',
  data_quality: '源数据本身有问题',
  other: '其他（请在备注里说明）',
};

export interface FeedbackPayload {
  is_correct: boolean;
  reason_code?: FeedbackReasonCode;
  comment?: string;
}

export interface FeedbackBarProps {
  taskId: string;
  /** 提交失败（reject）时保留已填内容并展示 inline 错误 */
  onFeedback: (payload: FeedbackPayload) => Promise<void>;
}

export function FeedbackBar({ taskId, onFeedback }: FeedbackBarProps) {
  const [phase, setPhase] = useState<'idle' | 'correct' | 'expanded' | 'failed'>('idle');
  const [reason, setReason] = useState<FeedbackReasonCode | undefined>();
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submittedReason, setSubmittedReason] = useState<FeedbackReasonCode | undefined>();
  const [errorText, setErrorText] = useState<string | null>(null);

  const send = async (payload: FeedbackPayload) => {
    setSubmitting(true);
    setErrorText(null);
    try {
      await onFeedback(payload);
      setSubmitting(false);
      void message.info('已记录，会进入人工审核；审核通过后会改善同类问题');
      if (payload.is_correct) {
        setPhase('correct');
      } else {
        setSubmittedReason(payload.reason_code);
        setPhase('correct');
      }
    } catch {
      setSubmitting(false);
      setErrorText('提交失败，请重试');
      setPhase('failed');
    }
  };

  if (phase === 'correct') {
    return (
      <div
        data-testid="c13-feedback-bar"
        style={{ fontSize: 12, color: tokens.color.text.tertiary, display: 'flex', alignItems: 'center', gap: 8 }}
      >
        {submittedReason ? `已反馈（${REASON_TEXT[submittedReason]}）` : '已反馈，谢谢'}
        <Button
          type="link"
          size="small"
          style={{ fontSize: 12, padding: 0 }}
          onClick={() => {
            setSubmittedReason(undefined);
            setPhase('expanded');
          }}
        >
          修改反馈
        </Button>
      </div>
    );
  }

  if (phase === 'idle') {
    return (
      <div
        data-testid="c13-feedback-bar"
        style={{
          height: 40,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 12,
          color: tokens.color.text.secondary,
        }}
      >
        这个结果对吗？
        <Button
          type="text"
          aria-label="结果正确"
          icon={<LikeOutlined />}
          onClick={() => void send({ is_correct: true })}
          style={{ minWidth: 48, minHeight: 48 }}
        />
        <Button
          type="text"
          aria-label="结果有误"
          icon={<DislikeOutlined />}
          onClick={() => setPhase('expanded')}
          style={{ minWidth: 48, minHeight: 48 }}
        />
      </div>
    );
  }

  // 展开态（含提交失败保留内容）
  return (
    <div
      data-testid="c13-feedback-bar"
      style={{
        background: tokens.color.neutral.bg,
        borderTop: `1px solid ${tokens.color.neutral.border}`,
        padding: tokens.space.sm,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ fontSize: 12, color: tokens.color.text.secondary }}>哪里不对？（任务号 {taskId}）</div>
      <Select
        size="small"
        style={{ maxWidth: 380 }}
        placeholder="选择原因"
        value={reason}
        onChange={setReason}
        aria-label="反馈原因"
        options={(Object.keys(REASON_TEXT) as FeedbackReasonCode[]).map((k) => ({
          value: k,
          label: REASON_TEXT[k],
        }))}
      />
      <Input.TextArea
        rows={2}
        maxLength={200}
        showCount
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="备注（可选，最多 200 字）"
        aria-label="反馈备注"
      />
      {errorText && (
        <div role="alert" style={{ fontSize: 12, color: tokens.color.error.text }}>
          {errorText}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <Button
          size="small"
          type="primary"
          disabled={!reason}
          loading={submitting}
          onClick={() => void send({ is_correct: false, reason_code: reason, comment: comment || undefined })}
        >
          {errorText ? '重试' : '提交'}
        </Button>
        <Button
          size="small"
          onClick={() => {
            setPhase('idle');
            setErrorText(null);
          }}
        >
          取消
        </Button>
      </div>
    </div>
  );
}