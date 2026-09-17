/**
 * C2 SessionRail 会话列表（06 §4.2，优先级 P1：P0 不渲染，三列 grid 轨道已预埋）
 * - 契约来源 A.5.4：q（300ms 防抖，≤100 字符）/ sort（仅 last_turn_at | created_at）/
 *   limit 20 / offset 分页 + total 用于「已加载 N / 共 M」
 * - 旧口径标签：last_bundle_version !== currentBundleVersion
 * - ⚠️ 不得为每个会话调 GET /session/{id}（N+1）；不得把列表写入 localStorage（仅存折叠偏好）
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Input, Popconfirm, Segmented, Tooltip } from 'antd';
import {
  DeleteOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { SessionListItem } from '../api/types';

/** 06 §4.2 契约别名：字段与 A.5.4 items 逐字对应 */
export type SessionSummary = SessionListItem;
export type SessionSort = 'last_turn_at' | 'created_at';

export interface SessionRailProps {
  sessions: SessionSummary[];
  total: number;
  activeSessionId: string | null;
  currentBundleVersion: string;
  loading: boolean;
  loadingMore: boolean;
  query: string;
  sort: SessionSort;
  onQueryChange(v: string): void;
  onSortChange(v: SessionSort): void;
  onLoadMore(): void;
  onSelect(id: string): void;
  onCreate(): void;
  onDelete(id: string): Promise<void>;
  /** 可选追加：加载失败态（06 §4.2「加载失败」行）*/
  error?: string | null;
  onReload?: () => void;
  /** 可选追加：读取类桶 429 的 Retry-After 绝对秒级时间戳（06 §4.2「限流态」行）*/
  rateLimitResetAt?: number;
}

const RAIL_W = tokens.size.sessionRail;
const RAIL_W_COLLAPSED = tokens.size.sessionRailCollapsed;
const SEARCH_MAX = 100;
const PAGE_SIZE = 20;
const COLLAPSE_KEY = 'railCollapsed';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 分组：今天 / 近 7 天 / 更早（仅默认排序且无搜索时启用） */
function groupOf(iso: string, now: Date): '今天' | '近 7 天' | '更早' {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '更早';
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= startOfToday) return '今天';
  if (d.getTime() >= startOfToday - 6 * 86400_000) return '近 7 天';
  return '更早';
}

export function SessionRail(props: SessionRailProps) {
  const {
    sessions,
    total,
    activeSessionId,
    currentBundleVersion,
    loading,
    loadingMore,
    query,
    sort,
    onQueryChange,
    onSortChange,
    onLoadMore,
    onSelect,
    onCreate,
    onDelete,
    error,
    onReload,
    rateLimitResetAt,
  } = props;

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1');
  const [keyword, setKeyword] = useState(query);
  const [tick, setTick] = useState(() => Date.now());
  const debounceRef = useRef<number | null>(null);

  // 300ms 防抖 → onQueryChange
  useEffect(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => onQueryChange(keyword.slice(0, SEARCH_MAX)), 300);
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    };
  }, [keyword, onQueryChange]);

  // 限流态倒计时
  useEffect(() => {
    if (!rateLimitResetAt) return;
    const t = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, [rateLimitResetAt]);

  const toggleCollapsed = () => {
    setCollapsed((v) => {
      localStorage.setItem(COLLAPSE_KEY, v ? '0' : '1');
      return !v;
    });
  };

  const searching = keyword.trim().length > 0;
  const grouped = !searching && sort === 'last_turn_at';
  const now = new Date(tick);
  const groups: { title: string; items: SessionSummary[] }[] = [];
  if (grouped) {
    for (const g of ['今天', '近 7 天', '更早'] as const) {
      const items = sessions.filter((s) => groupOf(s.last_turn_at, now) === g);
      if (items.length) groups.push({ title: g, items });
    }
  } else {
    groups.push({ title: '', items: sessions });
  }

  if (collapsed) {
    return (
      <div
        data-testid="c2-session-rail"
        style={{ width: RAIL_W_COLLAPSED, borderRight: `1px solid ${tokens.color.neutral.border}`, padding: 8 }}
      >
        <Tooltip title="展开会话列表" placement="right">
          <Button type="text" icon={<MenuUnfoldOutlined />} onClick={toggleCollapsed} aria-label="展开会话列表" />
        </Tooltip>
        <Tooltip title="新建会话" placement="right">
          <Button
            type="text"
            icon={<PlusOutlined />}
            onClick={onCreate}
            aria-label="新建会话"
            style={{ marginTop: 8 }}
          />
        </Tooltip>
      </div>
    );
  }

  const renderItem = (s: SessionSummary) => {
    const active = s.session_id === activeSessionId;
    const oldBundle = s.last_bundle_version !== currentBundleVersion;
    return (
      <div
        key={s.session_id}
        role="button"
        tabIndex={0}
        aria-current={active ? 'true' : undefined}
        onClick={() => onSelect(s.session_id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(s.session_id);
          }
        }}
        style={{
          position: 'relative',
          padding: '8px 24px 8px 10px',
          borderLeft: `2px solid ${active ? tokens.color.brand.solid : 'transparent'}`,
          background: active ? tokens.color.brand.bg : 'transparent',
          cursor: 'pointer',
        }}
      >
        <div
          title={s.title}
          style={{
            fontSize: tokens.font.size.body,
            color: tokens.color.text.primary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {s.title}
        </div>
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 2 }}>
          {fmtTime(s.last_turn_at)} · {s.turn_count} 轮
          {oldBundle && (
            <Tooltip title={`该会话的答案基于 ${s.last_bundle_version} 口径，当时的口径可能已变更`}>
              <span
                data-testid="c2-old-bundle-tag"
                style={{
                  marginLeft: 6,
                  background: tokens.color.degraded.bg,
                  border: `1px solid ${tokens.color.degraded.border}`,
                  color: tokens.color.degraded.text,
                  borderRadius: tokens.radius.sm,
                  padding: '0 4px',
                  fontSize: 11,
                }}
              >
                基于旧口径
              </span>
            </Tooltip>
          )}
        </div>
        <Popconfirm
          title="删除这个会话？已产生的审计记录不会被删除。"
          okText="删除"
          cancelText="取消"
          onConfirm={() => onDelete(s.session_id)}
        >
          <Button
            type="text"
            size="small"
            icon={<DeleteOutlined />}
            aria-label="删除会话"
            onClick={(e) => e.stopPropagation()}
            style={{ position: 'absolute', right: 4, top: 8 }}
          />
        </Popconfirm>
      </div>
    );
  };

  const rateLimited = rateLimitResetAt ? rateLimitResetAt - Math.floor(tick / 1000) : 0;

  return (
    <div
      data-testid="c2-session-rail"
      style={{
        width: RAIL_W,
        borderRight: `1px solid ${tokens.color.neutral.border}`,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      <div style={{ padding: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Input
          size="small"
          allowClear
          maxLength={SEARCH_MAX}
          prefix={<SearchOutlined aria-hidden />}
          placeholder="搜索会话"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          aria-label="搜索会话"
        />
        <Tooltip title="新建会话">
          <Button type="text" size="small" icon={<PlusOutlined />} onClick={onCreate} aria-label="新建会话" />
        </Tooltip>
        <Tooltip title="折叠会话列表">
          <Button type="text" size="small" icon={<MenuFoldOutlined />} onClick={toggleCollapsed} aria-label="折叠会话列表" />
        </Tooltip>
      </div>
      <div style={{ padding: '0 8px 8px' }}>
        <Segmented
          size="small"
          block
          value={sort}
          onChange={(v) => onSortChange(v as SessionSort)}
          options={[
            { label: '最近活跃', value: 'last_turn_at' },
            { label: '创建时间', value: 'created_at' },
          ]}
        />
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} className="cq-skeleton" style={{ height: 56 }} />
            ))}
          </div>
        ) : error ? (
          <div
            role="alert"
            style={{
              margin: 8,
              padding: 8,
              borderRadius: tokens.radius.md,
              background: tokens.color.error.bg,
              border: `1px solid ${tokens.color.error.border}`,
              color: tokens.color.error.text,
              fontSize: 12,
            }}
          >
            会话列表加载失败
            {onReload && (
              <Button size="small" type="link" onClick={onReload} style={{ fontSize: 12, padding: '0 4px' }}>
                重试
              </Button>
            )}
          </div>
        ) : sessions.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center' }}>
            {searching ? (
              <>
                <div style={{ fontSize: 13, color: tokens.color.text.secondary }}>没有匹配的会话</div>
                <Button type="link" size="small" onClick={() => setKeyword('')} style={{ fontSize: 12 }}>
                  清除搜索
                </Button>
              </>
            ) : (
              <>
                <div style={{ fontSize: 13, color: tokens.color.text.secondary }}>还没有查询记录</div>
                <Button type="primary" size="small" icon={<MessageOutlined />} onClick={onCreate} style={{ marginTop: 8 }}>
                  开始第一个问题
                </Button>
              </>
            )}
          </div>
        ) : (
          groups.map((g) => (
            <div key={g.title || 'all'}>
              {g.title && (
                <div
                  style={{
                    position: 'sticky',
                    top: 0,
                    zIndex: tokens.z.sticky,
                    background: '#fff',
                    padding: '4px 10px',
                    fontSize: 12,
                    color: tokens.color.text.tertiary,
                  }}
                >
                  {g.title}
                </div>
              )}
              {g.items.map(renderItem)}
            </div>
          ))
        )}
        {rateLimited > 0 && (
          <div role="status" style={{ padding: '4px 10px', fontSize: 12, color: tokens.color.text.tertiary }}>
            刷新过于频繁，{rateLimited} 秒后自动重试
          </div>
        )}
      </div>

      <div style={{ padding: 8, borderTop: `1px solid ${tokens.color.neutral.border}`, fontSize: 12, color: tokens.color.text.tertiary }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>
            已加载 {sessions.length} / 共 {total}
          </span>
          {sessions.length < total && (
            <Button type="link" size="small" loading={loadingMore} onClick={onLoadMore} style={{ fontSize: 12, padding: 0 }}>
              加载更多
            </Button>
          )}
        </div>
        <div style={{ marginTop: 4, opacity: 0.8 }}>每页 {PAGE_SIZE} 条</div>
      </div>
    </div>
  );
}