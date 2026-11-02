/**
 * 数据表（Schema）详情页（/schema）—— Phase B B5
 * - 数据源：GET /semantic/assets（列表）+ GET /semantic/assets/{logical_name}（详情）
 * - 列为后端投影后的结果：被拒列/敏感列**不会出现**，前端不做二次判断
 * - 只读页面，不触发任何查询
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Empty, Spin, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ApiError, getAssetDetail, apiGet } from '../api/client';
import type { AssetColumnDetail, AssetDetail, AssetJoinDetail, Paged } from '../api/types';
import { tokens } from '../theme/tokens';

interface AssetRow {
  logical_name: string;
  physical_asset: string;
  grain: string;
  domain: string;
  certified: boolean;
  column_count: number;
}

const columnColumns: ColumnsType<AssetColumnDetail> = [
  { title: '列', dataIndex: 'name', key: 'name', width: 180 },
  { title: '类型', dataIndex: 'type', key: 'type', width: 90 },
  {
    title: '注释',
    dataIndex: 'comment',
    key: 'comment',
    render: (v: string | null) => v ?? '—',
  },
  {
    title: '枚举',
    dataIndex: 'enum',
    key: 'enum',
    render: (v: Record<string, string>) =>
      Object.keys(v ?? {}).length === 0
        ? '—'
        : Object.keys(v).map((k) => <Tag key={k}>{k}</Tag>),
  },
];

const joinColumns: ColumnsType<AssetJoinDetail> = [
  { title: '左', dataIndex: 'left', key: 'left' },
  { title: '右', dataIndex: 'right', key: 'right' },
  { title: '类型', dataIndex: 'type', key: 'type', width: 80 },
  {
    title: '关联列',
    dataIndex: 'on_columns',
    key: 'on_columns',
    render: (v: string[]) => (v ?? []).join(', ') || '—',
  },
];

export function SchemaPage() {
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<Paged<AssetRow>>('/semantic/assets')
      .then((data) => {
        if (cancelled) return;
        setAssets(data.items);
        setActive(data.items[0]?.logical_name ?? null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? { code: err.code, message: err.message }
            : { code: 'INTERNAL', message: '资产列表加载失败' },
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!active) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getAssetDetail(active)
      .then((data) => !cancelled && setDetail(data))
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? { code: err.code, message: err.message }
            : { code: 'INTERNAL', message: '资产详情加载失败' },
        );
      })
      .finally(() => !cancelled && setDetailLoading(false));
    return () => {
      cancelled = true;
    };
  }, [active]);

  return (
    <div data-testid="page-schema" style={{ minHeight: '100vh', background: tokens.color.neutral.bg }}>
      <header
        style={{
          height: tokens.size.header,
          display: 'flex',
          alignItems: 'center',
          gap: tokens.space.md,
          padding: `0 ${tokens.space.md}px`,
          background: '#fff',
          borderBottom: `1px solid ${tokens.color.neutral.border}`,
        }}
      >
        <Link to="/chat" style={{ fontSize: 13 }}>
          ← 返回问答
        </Link>
        <span style={{ fontSize: tokens.font.size.h1, fontWeight: tokens.font.weight.medium }}>
          数据表
        </span>
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary }}>
          只读 · 被拒列不展示
        </span>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: tokens.space.md, padding: tokens.space.md }}>
        <aside style={{ background: '#fff', borderRadius: tokens.radius.md, padding: tokens.space.sm }}>
          {loading && <Spin size="small" />}
          {!loading && assets.length === 0 && !error && <Empty description="没有可用资产" />}
          {assets.map((a) => (
            <button
              key={a.logical_name}
              type="button"
              data-testid={`schema-asset-${a.logical_name}`}
              onClick={() => setActive(a.logical_name)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 10px',
                marginBottom: 4,
                border: 'none',
                borderRadius: tokens.radius.sm,
                cursor: 'pointer',
                background: active === a.logical_name ? tokens.color.brand.bg : 'transparent',
              }}
            >
              <div style={{ fontSize: 13 }}>{a.logical_name}</div>
              <div style={{ fontSize: 11, color: tokens.color.text.tertiary }}>
                {a.physical_asset}
              </div>
            </button>
          ))}
        </aside>

        <main style={{ background: '#fff', borderRadius: tokens.radius.md, padding: tokens.space.md, minHeight: 400 }}>
          {error && (
            <Alert
              type="error"
              showIcon
              message={error.message}
              description={`错误码：${error.code}`}
              style={{ marginBottom: tokens.space.md }}
            />
          )}
          {detailLoading && <Spin />}
          {!detailLoading && !detail && !error && <Empty description="请选择左侧资产" />}
          {!detailLoading && detail && (
            <>
              <div style={{ fontSize: tokens.font.size.h1 }}>{detail.logical_name}</div>
              <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>
                {detail.physical_asset} · {detail.domain} · 粒度 {detail.grain} · 约 {detail.row_estimate} 行
                {detail.certified ? ' · 已认证' : ''}
              </div>
              <div style={{ marginTop: tokens.space.sm, fontSize: 13 }}>{detail.description}</div>

              <h4 style={{ marginTop: tokens.space.lg }}>列（{detail.columns.length}）</h4>
              <Table
                rowKey="name"
                size="small"
                pagination={false}
                columns={columnColumns}
                dataSource={detail.columns}
              />

              <h4 style={{ marginTop: tokens.space.lg }}>Join 路径（{detail.joins.length}）</h4>
              <Table
                rowKey={(r) => `${r.left}-${r.right}`}
                size="small"
                pagination={false}
                columns={joinColumns}
                dataSource={detail.joins}
                locale={{ emptyText: '无已认证 Join' }}
              />

              <h4 style={{ marginTop: tokens.space.lg }}>关联指标</h4>
              <div>
                {detail.metrics.length === 0
                  ? '—'
                  : detail.metrics.map((m) => (
                      <Tag key={m.name} color="blue">
                        {m.display_name}（{m.name}）
                      </Tag>
                    ))}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
