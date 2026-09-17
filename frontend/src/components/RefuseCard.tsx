/**
 * C10 RefuseCard 拒答卡（06 §4.10，异常态 2/4）
 * - 拒答不是错误：中性灰 refuse 语义，空心问号圆，无「重试」按钮
 * - 正文渲染 refuse.message 原文，前端不重写
 * - 替代问法点击 = 填入 AskBox 但不自动提交
 */
import { QuestionCircleOutlined, RightOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { tokens } from '../theme/tokens';
import type { RefuseReason } from '../api/types';

export interface RefuseCardProps {
  reason: RefuseReason;
  /** refuse.message 原文 */
  message: string;
  suggestions: string[];
  /** 点击建议问法：填入 AskBox（不自动提交） */
  onPickSuggestion?: (text: string) => void;
}

const REASON_HINT: Partial<Record<RefuseReason, string>> = {
  no_data_asset: '原因：系统里没有这类数据',
  out_of_scope: '原因：超出你的数据权限范围', // 不透露内容（A.11 FORBIDDEN_SCOPE）
  pii_blocked: '原因：涉及受保护的敏感字段',
  open_analysis: '原因：这是一个开放式分析问题，系统只做数据查询，不做归因与预测',
};

export function RefuseCard({ reason, message, suggestions, onPickSuggestion }: RefuseCardProps) {
  return (
    <div
      data-testid="c10-refuse-card"
      role="status"
      style={{
        borderRadius: tokens.radius.lg,
        background: tokens.color.refuse.bg,
        border: `1px solid ${tokens.color.refuse.border}`,
        color: tokens.color.refuse.text,
        padding: tokens.space.md,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: tokens.color.text.secondary }}>
        <QuestionCircleOutlined aria-hidden />
        系统无法回答这个问题
      </div>
      <div style={{ fontSize: tokens.font.size.h2, lineHeight: `${tokens.font.lineHeight.h2}px`, marginTop: 8 }}>
        {message}
      </div>
      {REASON_HINT[reason] && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>{REASON_HINT[reason]}</div>
      )}
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {suggestions.length > 0 ? (
          suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onPickSuggestion?.(s)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                border: 'none',
                background: 'transparent',
                color: tokens.color.brand.solid,
                fontSize: 13,
                cursor: 'pointer',
                padding: '4px 0',
                textAlign: 'left',
              }}
            >
              <RightOutlined style={{ fontSize: 10 }} aria-hidden />
              {s}
            </button>
          ))
        ) : (
          <div style={{ fontSize: 12, color: tokens.color.text.secondary }}>
            可以试着换个说法，或查看 <Link to="/semantic/metrics">口径字典</Link> 了解系统能回答什么
          </div>
        )}
      </div>
    </div>
  );
}
