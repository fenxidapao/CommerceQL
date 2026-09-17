/**
 * C7 CaveatBar 口径条（06 §4.7，常驻不可折叠）
 * - 硬约束：insight.caveats 必须展示（A.14 第 8 条 / FR-8.2）
 * - 摘要层纯前端从前缀抽取（不给后端加契约）；全文进抽屉由页面负责
 * - meta.scope.notice：仅当 disclosable===true 且 notice!==null 时原样渲染，一字不改（A.1.5）
 * - 不得展示任何"间接量"（被过滤行数/比例等）
 */
import { useState } from 'react';
import { Button } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';

export interface CaveatBarProps {
  caveats: string[];
  /** meta.scope：disclosable===false 或 notice===null → 不渲染任何范围提示 */
  scope?: { disclosable: boolean; notice: string | null } | null;
  /** 数据新鲜度 > 24h 判定基准（默认 now） */
  now?: number;
  onOpenDrawer?: () => void;
  /** scope 载荷里出现间接量字段的告警钩子（A.1.5 红线 1） */
  onContractViolation?: (detail: string) => void;
}

interface Pill {
  text: string;
  tone: 'neutral' | 'info' | 'degraded';
}

const FRESHNESS_RE = /数据新鲜度：\s*(.+)$/;
const TIME_RE = /时间范围：\s*(.+)$/;
const CALIBER_RE = /口径：\s*(.+)$/;

function parseCaveats(raw: string[], now: number, onViolation?: (s: string) => void): Pill[] {
  const pills: Pill[] = [];
  let otherCount = 0;
  for (const item of raw) {
    const t = item.trim();
    if (!t) continue;
    let m = CALIBER_RE.exec(t);
    if (m) {
      pills.push({ text: `口径 · ${m[1]}`, tone: 'neutral' });
      continue;
    }
    m = TIME_RE.exec(t);
    if (m) {
      pills.push({ text: `时间 · ${m[1]}`, tone: 'neutral' });
      continue;
    }
    m = FRESHNESS_RE.exec(t);
    if (m) {
      const ts = Date.parse(m[1]);
      const stale = Number.isFinite(ts) && now - ts > 24 * 3600_000;
      pills.push({ text: stale ? `数据截至 ${m[1]}（可能滞后）` : `数据截至 ${m[1]}`, tone: stale ? 'degraded' : 'neutral' });
      continue;
    }
    // 其他条目：最多 2 条，其余 +N（这里允许展开——它是摘要溢出，不是主口径）
    if (onViolation && /被过滤|过滤前|可见比例/.test(t)) {
      onViolation(t);
      continue;
    }
    otherCount += 1;
    if (otherCount <= 2) pills.push({ text: t, tone: 'neutral' });
  }
  const extra = Math.max(0, otherCount - 2);
  return extra > 0 ? [...pills, { text: `+${extra}`, tone: 'neutral' }] : pills;
}

export function CaveatBar({ caveats, scope, now, onOpenDrawer, onContractViolation }: CaveatBarProps) {
  const [expanded, setExpanded] = useState(false);
  const baseNow = now ?? Date.now();

  const scopePill: Pill | null =
    scope && scope.disclosable === true && scope.notice !== null
      ? { text: `范围 · ${scope.notice}`, tone: 'info' }
      : null;

  if (!caveats || caveats.length === 0) {
    return (
      <div
        data-testid="c7-caveat-bar"
        role="note"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 12,
          color: tokens.color.degraded.text,
          background: tokens.color.degraded.bg,
          border: `1px solid ${tokens.color.degraded.border}`,
          borderRadius: tokens.radius.md,
          padding: `${tokens.space.xxs}px ${tokens.space.xs}px`,
        }}
      >
        <InfoCircleOutlined aria-hidden />
        <span>本次未返回口径说明，数值请谨慎使用</span>
        {scopePill && <PillView pill={scopePill} />}
      </div>
    );
  }

  const parsed = parseCaveats(caveats, baseNow, onContractViolation);
  const shown = expanded ? parsed.filter((p) => !p.text.startsWith('+')) : parsed;

  return (
    <div
      data-testid="c7-caveat-bar"
      role="note"
      style={{ display: 'flex', alignItems: 'center', gap: tokens.space.xs, flexWrap: 'wrap' }}
    >
      <InfoCircleOutlined aria-hidden style={{ color: tokens.color.info.border, fontSize: 12 }} />
      {scopePill && <PillView pill={scopePill} />}
      {shown.map((p, i) => (
        <PillView key={`${p.text}-${i}`} pill={p} />
      ))}
      {expanded
        ? parsed.length < caveats.length && (
            <Button type="link" size="small" style={{ fontSize: 12, padding: 0 }} onClick={() => setExpanded(false)}>
              收起
            </Button>
          )
        : parsed.some((p) => p.text.startsWith('+')) && (
            <Button type="link" size="small" style={{ fontSize: 12, padding: 0 }} onClick={() => setExpanded(true)}>
              展开
            </Button>
          )}
      {onOpenDrawer && (
        <Button type="link" size="small" style={{ fontSize: 12, padding: 0 }} onClick={onOpenDrawer}>
          查看完整口径 →
        </Button>
      )}
    </div>
  );
}

function PillView({ pill }: { pill: Pill }) {
  const c =
    pill.tone === 'info' ? tokens.color.info : pill.tone === 'degraded' ? tokens.color.degraded : tokens.color.neutral;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 24,
        borderRadius: tokens.radius.full,
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: pill.tone === 'neutral' ? tokens.color.text.secondary : c.text,
        fontSize: 12,
        padding: '4px 8px',
      }}
    >
      {pill.text}
    </span>
  );
}