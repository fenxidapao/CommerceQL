/**
 * 口径字典页（/semantic/metrics）—— 06 §11.2，**纯只读**
 * - 数据源：A.7.1 GET /semantic/metrics、A.7.2 GET /semantic/assets
 * - 前端零判断权：只渲染后端字段，不做任何业务指标聚合/计算
 * - ⚠️ A.7.2 的 denied_columns 一律不渲染（附录 B-10：存在性泄露）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, HTMLAttributes } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Collapse, Drawer, Input, Select, Table, Tabs } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { ApiError, apiGet } from '../api/client';
import type { MetricItem, Paged, SemanticAsset } from '../api/types';
import { ErrorCard } from '../components';
import { tokens } from '../theme/tokens';

const PAGE_SIZE = 50; // A.0.5 默认值
const SEARCH_DEBOUNCE_MS = 300;

type Tone = 'brand' | 'neutral' | 'success' | 'error';

function toneColor(tone: Tone) {
  if (tone === 'brand') return tokens.color.brand;
  if (tone === 'success') return tokens.color.success;
  if (tone === 'error') return tokens.color.error;
  return tokens.color.neutral;
}

/** 标签胶囊（纯展示） */
function Chip({ text, tone = 'neutral' }: { text: string; tone?: Tone }) {
  const c = toneColor(tone);
  return (
    <span
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: c.text,
        borderRadius: tokens.radius.sm,
        padding: '0 6px',
        fontSize: tokens.font.size.caption,
        lineHeight: `${tokens.font.lineHeight.caption}px`,
        whiteSpace: 'nowrap',
      }}
    >
      {text}
    </span>
  );
}

/** 单位显示（CNY → 元，其余原样） */
function unitText(unit: string): string {
  return unit === 'CNY' ? '元' : unit;
}

function firstLine(note: string): string {
  return note.split('\n')[0];
}

function fmtTime(iso: string): string {
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : iso;
}

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError({ code: 'INTERNAL', message: err instanceof Error ? err.message : '请求失败', httpStatus: 0 });
}

const cardStyle: CSSProperties = {
  background: '#fff',
  border: `1px solid ${tokens.color.neutral.border}`,
  borderRadius: tokens.radius.lg,
  padding: tokens.space.md,
};

export function SemanticPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get('q') ?? '';

  const [keyword, setKeyword] = useState(q);
  const [domain, setDomain] = useState('');
  const [offset, setOffset] = useState(0);
  const [tab, setTab] = useState<'metrics' | 'assets'>('metrics');

  const [metrics, setMetrics] = useState<Paged<MetricItem> | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [metricsError, setMetricsError] = useState<ApiError | null>(null);
  const [assets, setAssets] = useState<Paged<SemanticAsset> | null>(null);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsError, setAssetsError] = useState<ApiError | null>(null);

  // 数据域下拉选项：仅做「当前已返回条目 domain 去重」的 UI 筛选选项，不是业务指标
  const [domainOptions, setDomainOptions] = useState<string[]>([]);
  const [selected, setSelected] = useState<MetricItem | null>(null);

  // URL 的 q 变化（含从结论卡「溯源」跳转带参）→ 同步搜索框
  useEffect(() => {
    setKeyword(q);
  }, [q]);

  // 300ms 防抖 → 写回 URL 的 q（便于分享/回跳），并重置分页
  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (keyword === q) return;
      const next = new URLSearchParams(searchParams);
      if (keyword) next.set('q', keyword);
      else next.delete('q');
      setSearchParams(next, { replace: true });
      setOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    };
  }, [keyword, q, searchParams, setSearchParams]);

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    setMetricsError(null);
    try {
      const data = await apiGet<Paged<MetricItem>>('/semantic/metrics', {
        q: q || undefined,
        domain: domain || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setMetrics(data);
    } catch (err) {
      setMetricsError(toApiError(err));
      setMetrics(null);
    } finally {
      setMetricsLoading(false);
    }
  }, [q, domain, offset]);

  useEffect(() => {
    void loadMetrics();
  }, [loadMetrics]);

  // 累积已见数据域（纯 UI 选项，避免筛选后其余选项消失）
  useEffect(() => {
    if (!metrics) return;
    setDomainOptions((prev) => {
      const merged = new Set([...prev, ...metrics.items.map((m) => m.domain)]);
      return merged.size === prev.length ? prev : Array.from(merged).sort();
    });
  }, [metrics]);

  const loadAssets = useCallback(async () => {
    setAssetsLoading(true);
    setAssetsError(null);
    try {
      const data = await apiGet<Paged<SemanticAsset>>('/semantic/assets', {
        q: q || undefined,
        domain: domain || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      });
      setAssets(data);
    } catch (err) {
      setAssetsError(toApiError(err));
      setAssets(null);
    } finally {
      setAssetsLoading(false);
    }
  }, [q, domain]);

  useEffect(() => {
    if (tab === 'assets') void loadAssets();
  }, [tab, loadAssets]);

  const clearFilters = () => {
    setKeyword('');
    setDomain('');
    setOffset(0);
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  // ---- 指标列表 ----
  const renderMetrics = () => {
    if (metricsLoading) {
      return (
        <div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="cq-skeleton" style={{ height: 72, marginBottom: tokens.space.xs }} />
          ))}
        </div>
      );
    }
    if (metricsError) {
      // 403 FORBIDDEN_SCOPE → refuse 语义；其余 → error 语义 + 重试
      if (metricsError.code === 'FORBIDDEN_SCOPE') {
        return (
          <div>
            <ErrorCard
              code="FORBIDDEN_SCOPE"
              message="该数据域的指标对你不可见"
              traceId={metricsError.traceId}
              retryable={false}
            />
            <div style={{ marginTop: tokens.space.xs, fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              你的角色在当前租户内只能查看被授权数据域的口径定义。
            </div>
          </div>
        );
      }
      return (
        <ErrorCard
          code={metricsError.code}
          message={metricsError.message}
          traceId={metricsError.traceId}
          retryable
          onRetry={() => void loadMetrics()}
        />
      );
    }
    if (!metrics || metrics.items.length === 0) {
      return (
        <div data-testid="semantic-empty" style={{ textAlign: 'center', padding: tokens.space.lg }}>
          <div style={{ fontSize: tokens.font.size.h3, color: tokens.color.text.secondary }}>没有找到匹配的指标</div>
          <Button type="link" size="small" onClick={clearFilters} style={{ fontSize: tokens.font.size.caption }}>
            清除筛选
          </Button>
          <div
            style={{
              marginTop: tokens.space.xs,
              background: tokens.color.info.bg,
              border: `1px solid ${tokens.color.info.border}`,
              color: tokens.color.info.text,
              borderRadius: tokens.radius.md,
              padding: tokens.space.xs,
              fontSize: tokens.font.size.caption,
              display: 'inline-block',
            }}
          >
            系统只能回答已认证指标的问题，未收录的指标请查看是否能换个说法
          </div>
        </div>
      );
    }
    return (
      <div>
        {metrics.items.map((m) => (
          <div
            key={m.name}
            data-testid="semantic-metric-card"
            role="button"
            tabIndex={0}
            onClick={() => setSelected(m)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setSelected(m);
              }
            }}
            style={{
              minHeight: 72,
              padding: tokens.space.sm,
              marginBottom: tokens.space.xs,
              border: `1px solid ${tokens.color.neutral.border}`,
              borderRadius: tokens.radius.md,
              background: '#fff',
              cursor: 'pointer',
            }}
          >
            <div
              style={{
                fontSize: tokens.font.size.h3,
                fontWeight: tokens.font.weight.medium,
                color: tokens.color.text.primary,
              }}
            >
              {m.display_name}
            </div>
            <div
              title={m.definition_note}
              style={{
                marginTop: 2,
                fontSize: tokens.font.size.caption,
                color: tokens.color.text.tertiary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {firstLine(m.definition_note)}
            </div>
            <div style={{ marginTop: tokens.space.xs, display: 'flex', gap: tokens.space.xs }}>
              <Chip text={m.domain} tone="brand" />
              <Chip text={m.owner} />
            </div>
          </div>
        ))}

        <div
          style={{
            marginTop: tokens.space.sm,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: tokens.font.size.caption,
            color: tokens.color.text.tertiary,
          }}
        >
          <span>
            已加载 {metrics.items.length} / 共 {metrics.total}
          </span>
          <span style={{ display: 'flex', gap: tokens.space.xs }}>
            <Button size="small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              上一页
            </Button>
            <Button
              size="small"
              disabled={offset + PAGE_SIZE >= metrics.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              下一页
            </Button>
          </span>
        </div>
      </div>
    );
  };

  // ---- 资产列表 ----
  // ⚠️ 附录 B-10 / 06 §9.3：denied_columns 为存在性泄露（列名本身即信息），**刻意不展示**；
  //    允许展示的只有 column_count（列数）。
  const assetColumns: ColumnsType<SemanticAsset> = [
    { title: '逻辑名', dataIndex: 'logical_name', key: 'logical_name', render: (v: string) => <span>{v}</span> },
    { title: '物理资产', dataIndex: 'physical_asset', key: 'physical_asset' },
    { title: '粒度', dataIndex: 'grain', key: 'grain' },
    { title: '新鲜度 SLA', dataIndex: 'freshness_sla', key: 'freshness_sla' },
    { title: 'Owner', dataIndex: 'owner', key: 'owner' },
    {
      title: '认证',
      dataIndex: 'certified',
      key: 'certified',
      render: (v: boolean) => <Chip text={v ? '✓ 已认证' : '✗ 未认证'} tone={v ? 'success' : 'error'} />,
    },
    { title: '数据域', dataIndex: 'domain', key: 'domain' },
    { title: '列数', dataIndex: 'column_count', key: 'column_count' },
  ];

  const renderAssets = () => {
    if (assetsLoading) {
      return (
        <div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="cq-skeleton" style={{ height: 40, marginBottom: tokens.space.xs }} />
          ))}
        </div>
      );
    }
    if (assetsError) {
      return (
        <ErrorCard
          code={assetsError.code}
          message={assetsError.message}
          traceId={assetsError.traceId}
          retryable
          onRetry={() => void loadAssets()}
        />
      );
    }
    if (!assets || assets.items.length === 0) {
      return (
        <div data-testid="semantic-empty" style={{ textAlign: 'center', padding: tokens.space.lg }}>
          <div style={{ fontSize: tokens.font.size.h3, color: tokens.color.text.secondary }}>没有找到匹配的数据资产</div>
          <Button type="link" size="small" onClick={clearFilters} style={{ fontSize: tokens.font.size.caption }}>
            清除筛选
          </Button>
        </div>
      );
    }
    return (
      <div>
        <Table<SemanticAsset>
          size="small"
          rowKey="logical_name"
          columns={assetColumns}
          dataSource={assets.items}
          pagination={false}
          onRow={() => ({ 'data-testid': 'semantic-asset-row' }) as HTMLAttributes<HTMLElement>}
        />
        <div style={{ marginTop: tokens.space.sm, fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
          共 {assets.total} 项已认证数据资产
        </div>
      </div>
    );
  };

  return (
    <div data-testid="page-semantic" style={{ padding: tokens.space.lg, background: tokens.color.neutral.bg, minHeight: '100%' }}>
      <div style={{ ...cardStyle }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.space.sm, flexWrap: 'wrap' }}>
          <h1 style={{ fontSize: tokens.font.size.h1, lineHeight: `${tokens.font.lineHeight.h1}px`, margin: 0 }}>
            口径字典
          </h1>
          <span style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
            这里说明系统里的指标到底是什么、怎么算的（只读）
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: tokens.space.xs }}>
            <Input
              size="small"
              allowClear
              maxLength={100}
              prefix={<SearchOutlined aria-hidden />}
              placeholder="搜索指标 / 同义词"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              aria-label="搜索指标"
              style={{ width: 220 }}
            />
            <Select
              size="small"
              allowClear
              placeholder="数据域"
              style={{ width: 150 }}
              value={domain || undefined}
              onChange={(v?: string) => {
                setDomain(v ?? '');
                setOffset(0);
              }}
              options={domainOptions.map((d) => ({ label: d, value: d }))}
            />
          </div>
        </div>

        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as 'metrics' | 'assets')}
          style={{ marginTop: tokens.space.sm }}
          items={[
            { key: 'metrics', label: '指标', children: renderMetrics() },
            { key: 'assets', label: '数据资产', children: renderAssets() },
          ]}
        />
      </div>

      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        width={tokens.size.detailDrawer}
        title={
          selected ? (
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: tokens.font.size.h2, fontWeight: tokens.font.weight.medium }}>
                {selected.display_name}
              </span>
              <span style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
                ({selected.name})
              </span>
              <Chip text={unitText(selected.unit)} tone="brand" />
            </div>
          ) : null
        }
        footer={
          selected ? (
            <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              口径包版本 {selected.bundle_version} · 更新于 {fmtTime(selected.updated_at)}
            </div>
          ) : null
        }
      >
        {selected && (
          <div data-testid="semantic-drawer">
            {/* definition_note 完整正文：用户来这一页的目的 */}
            <div
              style={{
                fontSize: tokens.font.size.body,
                lineHeight: `${tokens.font.lineHeight.body}px`,
                color: tokens.color.text.primary,
                whiteSpace: 'pre-wrap',
              }}
            >
              {selected.definition_note}
            </div>

            <div style={{ marginTop: tokens.space.sm, display: 'flex', gap: tokens.space.xs, flexWrap: 'wrap' }}>
              <Chip text={`域：${selected.domain}`} tone="brand" />
              <Chip text={`Owner：${selected.owner}`} />
              <Chip text={`单位：${unitText(selected.unit)}`} />
            </div>

            <Collapse
              ghost
              style={{ marginTop: tokens.space.sm }}
              items={[
                {
                  key: 'logic',
                  label: '计算逻辑',
                  children: (
                    <div>
                      <pre
                        style={{
                          margin: 0,
                          padding: tokens.space.xs,
                          background: tokens.color.neutral.bg,
                          borderRadius: tokens.radius.sm,
                          fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
                          fontSize: tokens.font.size.mono,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                        }}
                      >
                        {selected.expression}
                      </pre>
                      <div style={{ marginTop: tokens.space.xs, fontSize: tokens.font.size.caption, color: tokens.color.text.secondary }}>
                        默认聚合：{selected.default_aggregation}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'predicates',
                  label: `默认过滤规则（${selected.default_predicates.length} 条）`,
                  children: (
                    <ul style={{ margin: 0, paddingLeft: tokens.space.md, fontSize: tokens.font.size.caption }}>
                      {selected.default_predicates.map((p) => (
                        <li key={p} style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>
                          {p}
                        </li>
                      ))}
                    </ul>
                  ),
                },
                {
                  key: 'synonyms',
                  label: '同义词',
                  children: (
                    <div style={{ display: 'flex', gap: tokens.space.xxs, flexWrap: 'wrap' }}>
                      {selected.synonyms.map((s) => (
                        <Chip key={s} text={s} />
                      ))}
                    </div>
                  ),
                },
              ]}
            />
          </div>
        )}
      </Drawer>
    </div>
  );
}