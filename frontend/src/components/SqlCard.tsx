/**
 * C4 SqlCard SQL 卡片（06 §4.4，P0 只读）
 * - 收到 stage=sql_ready 立即渲染（由页面驱动）
 * - confidence 默认不展示（决策见 §4.4，附录 B-6）
 * - 浅色容器 + 行号 + 离线正则高亮 + 复制 + PostgreSQL 标签
 */
import { useMemo, useState } from 'react';
import { Button, Tag, message } from 'antd';
import { CopyOutlined, DownOutlined, UpOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';

export interface SqlCardProps {
  sql: string;
  dialect: 'postgresql';
  /** ⚠️ 默认不展示（未校准，见 06 §4.4 决策）；仅透传备查 */
  confidence?: number;
  /** 默认展开；>20 行时强制收起为 6 行 */
  collapsed?: boolean;
  readonly: true;
}

const COLLAPSED_LINES = 6;
const AUTO_COLLAPSE_THRESHOLD = 20;

const KEYWORDS =
  /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|LEFT JOIN|RIGHT JOIN|INNER JOIN|ON|AND|OR|NOT|IN|AS|CASE|WHEN|THEN|ELSE|END|SUM|COUNT|AVG|MAX|MIN|DISTINCT|BETWEEN|LIKE|DESC|ASC|HAVING|WITH|UNION)\b/gi;

/** 离线语法高亮：关键字 / 字符串 / 数字 / 注释 */
function highlight(sql: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const rest = sql;
  let k = 0;
  const pattern = /('(?:[^']|'')*')|(--[^\n]*)|(\b\d+(?:\.\d+)?\b)/g;
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  const pushKeywords = (text: string) => {
    text.split(KEYWORDS).forEach((part, i) => {
      if (!part) return;
      const isKw = i % 2 === 1;
      nodes.push(
        isKw ? (
          <span key={k++} style={{ color: tokens.color.brand.solid, fontWeight: tokens.font.weight.medium }}>
            {part.toUpperCase()}
          </span>
        ) : (
          <span key={k++}>{part}</span>
        ),
      );
    });
  };
  while ((m = pattern.exec(rest)) !== null) {
    if (m.index > lastIdx) pushKeywords(rest.slice(lastIdx, m.index));
    const [full, str, comment] = m;
    const color = str ? tokens.color.success.border : comment ? tokens.color.text.tertiary : tokens.color.degraded.border;
    nodes.push(
      <span key={k++} style={{ color }}>
        {full}
      </span>,
    );
    lastIdx = m.index + full.length;
  }
  if (lastIdx < rest.length) pushKeywords(rest.slice(lastIdx));
  return nodes;
}

export function SqlCard({ sql, collapsed }: SqlCardProps) {
  const lines = useMemo(() => sql.split('\n'), [sql]);
  const long = lines.length > AUTO_COLLAPSE_THRESHOLD;
  const [expanded, setExpanded] = useState(!long && collapsed !== true);
  const [copied, setCopied] = useState(false);

  const visibleLines = expanded ? lines : lines.slice(0, COLLAPSED_LINES);

  const copy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    void message.success('已复制', 1.5);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      data-testid="c4-sql-card"
      style={{
        borderRadius: tokens.radius.lg,
        background: tokens.color.neutral.bg,
        border: `1px solid ${tokens.color.neutral.border}`,
        padding: tokens.space.sm,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 4 }}>
        <Tag color="blue" style={{ marginInlineEnd: 0 }}>
          PostgreSQL
        </Tag>
        <Button size="small" type="text" icon={<CopyOutlined />} onClick={copy} aria-label="复制 SQL">
          {copied ? '已复制' : '复制'}
        </Button>
      </div>
      <pre
        role="region"
        aria-label="系统生成的 SQL 语句，只读"
        style={{
          margin: 0,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          fontSize: tokens.font.size.mono,
          lineHeight: `${tokens.font.lineHeight.mono}px`,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          color: tokens.color.text.primary,
        }}
      >
        {visibleLines.map((line, i) => (
          <div key={i} style={{ display: 'flex' }}>
            <span
              aria-hidden
              style={{
                userSelect: 'none',
                width: 32,
                flexShrink: 0,
                color: tokens.color.text.tertiary,
                fontSize: 12,
                textAlign: 'right',
                paddingRight: 8,
              }}
            >
              {i + 1}
            </span>
            <span style={{ flex: 1 }}>{highlight(line)}</span>
          </div>
        ))}
      </pre>
      {long && (
        <Button
          type="link"
          size="small"
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          onClick={() => setExpanded((v) => !v)}
          style={{ padding: 0, fontSize: 12 }}
        >
          {expanded ? '收起' : `展开全部（共 ${lines.length} 行）`}
        </Button>
      )}
      <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>
        本语句由系统生成，仅供参考；实际执行的语句与参数绑定后的结果可能存在差异。
      </div>
    </div>
  );
}
