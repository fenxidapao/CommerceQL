/**
 * C6 InsightCard 结论卡（06 §4.6）
 * - 结论下沿紧贴 CaveatBar（由页面组装保证同卡视觉），不得孤立展示结论
 * - 文案红线：命中因果/预测式表述时不渲染原文，降级为「结论格式异常，请以数据为准」+ 前端错误日志
 *   （前端唯一允许的"内容级校验"，且只拦截不改写）
 * - text 为空 → 不渲染结论卡，展示「本次未生成文字结论，请以图表与表格为准」
 * - citations 为空 → 「溯源」置灰 + Tooltip，不展示假溯源
 */
import { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { NodeIndexOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { tokens } from '../theme/tokens';
import type { Citation } from '../api/types';

/** 06 §4.6 给定实现：只拦截不改写 */
const FORBIDDEN_PATTERNS = [/因为[\s\S]{0,20}所以/, /导致/, /带动了/, /预计/, /下周将/, /是因为/];

export interface InsightCardProps {
  text: string;
  citations: Citation[];
}

export function InsightCard({ text, citations }: InsightCardProps) {
  const [showCitations, setShowCitations] = useState(false);

  if (!text || !text.trim()) {
    return (
      <div
        data-testid="c6-insight-empty"
        role="note"
        style={{ fontSize: 12, color: tokens.color.text.secondary, padding: '4px 0' }}
      >
        本次未生成文字结论，请以图表与表格为准
      </div>
    );
  }

  const violating = FORBIDDEN_PATTERNS.some((p) => p.test(text));
  if (violating) {
    console.error('[ui_insight_forbidden_pattern]', { text });
  }

  return (
    <div
      data-testid="c6-insight-card"
      style={{
        background: '#fff',
        borderLeft: `3px solid ${tokens.color.brand.border}`,
        borderRadius: tokens.radius.lg,
        padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary }}>系统结论</span>
        {citations.length > 0 ? (
          <Button
            type="text"
            size="small"
            icon={<NodeIndexOutlined />}
            onClick={() => setShowCitations((v) => !v)}
            aria-label="溯源"
            aria-expanded={showCitations}
          >
            溯源
          </Button>
        ) : (
          <Tooltip title="本次未返回溯源信息">
            <Button type="text" size="small" icon={<NodeIndexOutlined />} disabled aria-label="溯源">
              溯源
            </Button>
          </Tooltip>
        )}
      </div>

      {violating ? (
        <div
          data-testid="c6-insight-degraded"
          style={{
            fontSize: tokens.font.size.h2,
            lineHeight: `${tokens.font.lineHeight.h2}px`,
            color: tokens.color.degraded.text,
            background: tokens.color.degraded.bg,
            borderRadius: tokens.radius.md,
            padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
          }}
        >
          结论格式异常，请以数据为准
        </div>
      ) : (
        <div
          style={{
            fontSize: tokens.font.size.h2,
            lineHeight: `${tokens.font.lineHeight.h2}px`,
            color: tokens.color.text.primary,
          }}
        >
          {text}
        </div>
      )}

      {showCitations && citations.length > 0 && (
        <div
          data-testid="c6-citations"
          style={{
            marginTop: 8,
            borderTop: `1px solid ${tokens.color.neutral.border}`,
            paddingTop: 8,
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          {citations.map((c, i) => (
            <div key={`${c.metric}-${i}`} style={{ fontSize: 12, color: tokens.color.text.secondary }}>
              <Link to={`/semantic/metrics?q=${encodeURIComponent(c.metric)}`}>{c.metric}</Link>
              <span style={{ color: tokens.color.text.tertiary }}>
                {' '}
                ← {c.asset} · {c.bundle_version}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}