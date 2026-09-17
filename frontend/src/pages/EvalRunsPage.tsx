/**
 * 评测运行列表页（/eval/runs）—— 06 §11.3 第 1 级
 * - 数据源：A.9.3 GET /admin/eval/runs（Paged<EvalRunListItem>）
 * - **只渲染 headline 摘要**，点行才拉详情（避免 N+1，A.0.6）
 * - 发起评测：A.9.1 POST /admin/eval/run；dataset_id 候选值来自 A.9.2
 * - 前端零判断权：不做任何指标聚合；比例字段仅做显示格式化
 */
import { useCallback, useEffect, useState } from 'react';
import type { HTMLAttributes } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Form, Input, Modal, Select, Table, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { ApiError, apiGet, apiPost } from '../api/client';
import type { EvalDataset, EvalRunListItem, EvalRunRequest, EvalRunStatus, Paged } from '../api/types';
import { ErrorCard } from '../components';
import { tokens } from '../theme/tokens';

const PAGE_SIZE = 20; // A.9.3 默认值

type Tone = 'brand' | 'neutral' | 'success' | 'error' | 'degraded';

function toneColor(tone: Tone) {
  if (tone === 'brand') return tokens.color.brand;
  if (tone === 'success') return tokens.color.success;
  if (tone === 'error') return tokens.color.error;
  if (tone === 'degraded') return tokens.color.degraded;
  return tokens.color.neutral;
}

function Badge({ text, tone }: { text: string; tone: Tone }) {
  const c = toneColor(tone);
  return (
    <span
      data-testid="eval-run-badge"
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

/** 比例显示格式化（0.812 → 81.2%），非业务计算 */
function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function fmtTime(iso?: string): string {
  if (!iso) return '—';
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : iso;
}

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError({ code: 'INTERNAL', message: err instanceof Error ? err.message : '请求失败', httpStatus: 0 });
}

const STATUS_TEXT: Record<EvalRunStatus, string> = {
  queued: '运行中',
  running: '运行中',
  complete: '已完成',
  failed: '运行失败',
};

export function EvalRunsPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm<EvalRunRequest>();

  const [runs, setRuns] = useState<Paged<EvalRunListItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [offset, setOffset] = useState(0);
  /** 管理员桶 429：就地提示，不弹全局错误（A.0.6） */
  const [rateLimited, setRateLimited] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [datasets, setDatasets] = useState<EvalDataset[] | null>(null);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState<ApiError | null>(null);
  const datasetId = Form.useWatch('dataset_id', form);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<Paged<EvalRunListItem>>('/admin/eval/runs', { limit: PAGE_SIZE, offset });
      setRuns(data);
    } catch (err) {
      const e = toApiError(err);
      if (e.httpStatus === 429) {
        setRateLimited(`操作过于频繁，${e.retryAfterSec ?? 60} 秒后可重试`);
      } else {
        setError(e);
        setRuns(null);
      }
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const openModal = () => {
    setModalError(null);
    setModalOpen(true);
  };

  // 打开弹窗时按需拉取评测集候选值（A.9.2）
  useEffect(() => {
    if (!modalOpen || datasets !== null || datasetsLoading) return;
    let cancelled = false;
    setDatasetsLoading(true);
    apiGet<{ items: EvalDataset[]; total: number }>('/admin/eval/datasets')
      .then((d) => {
        if (!cancelled) setDatasets(d.items);
      })
      .catch((err: unknown) => {
        if (!cancelled) setModalError(toApiError(err));
      })
      .finally(() => {
        if (!cancelled) setDatasetsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [modalOpen, datasets, datasetsLoading]);

  const submit = async (values: EvalRunRequest) => {
    setSubmitting(true);
    setModalError(null);
    try {
      await apiPost<{ run_id: string; status: EvalRunStatus }>('/admin/eval/run', values);
      void message.success('评测已发起');
      setModalOpen(false);
      form.resetFields();
      await loadRuns();
    } catch (err) {
      const e = toApiError(err);
      if (e.httpStatus === 429) {
        setRateLimited(`操作过于频繁，${e.retryAfterSec ?? 60} 秒后可重试`);
      } else {
        setModalError(e);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const selectedDataset = datasets?.find((d) => d.dataset_id === datasetId);

  const columns: ColumnsType<EvalRunListItem> = [
    {
      title: '运行',
      dataIndex: 'run_id',
      key: 'run_id',
      width: 140,
      render: (v: string) => <span style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>{v}</span>,
    },
    {
      title: '模型 / 版本',
      key: 'versions',
      width: 180,
      render: (_, r) => (
        <div style={{ fontSize: tokens.font.size.caption, lineHeight: `${tokens.font.lineHeight.caption}px` }}>
          <div>{r.model}</div>
          <div style={{ color: tokens.color.text.tertiary }}>{r.prompt_version}</div>
          <div style={{ color: tokens.color.text.tertiary }}>口径包 {r.bundle_version}</div>
        </div>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 96,
      render: (_, r) => (
        <Badge
          text={STATUS_TEXT[r.status]}
          tone={r.status === 'failed' ? 'error' : r.status === 'complete' ? 'success' : 'degraded'}
        />
      ),
    },
    {
      title: '门禁',
      key: 'gate',
      width: 96,
      render: (_, r) =>
        r.gate_passed ? <Badge text="已过门禁" tone="success" /> : <Badge text="未过门禁" tone="error" />,
    },
    {
      title: 'headline 摘要',
      key: 'headline',
      render: (_, r) =>
        r.headline ? (
          <div style={{ display: 'flex', gap: tokens.space.sm, flexWrap: 'wrap' }}>
            {[
              ['EX', pct(r.headline.ex)],
              ['拒答真阳性率', pct(r.headline.refusal_true_positive_rate)],
              ['危险 SQL 放行', String(r.headline.dangerous_sql_passed)],
              ['跨租户泄露', String(r.headline.cross_tenant_leaks)],
              ['P95 延迟', `${r.headline.p95_latency_ms} ms`],
              ['总成本', `${r.headline.cost_total_cny} 元`],
            ].map(([label, value]) => (
              <span key={label} style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.secondary }}>
                {label} <strong style={{ color: tokens.color.text.primary }}>{value}</strong>
              </span>
            ))}
          </div>
        ) : (
          <span style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>摘要不可用</span>
        ),
    },
    {
      title: '时间窗',
      key: 'window',
      width: 190,
      render: (_, r) => (
        <span style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.secondary }}>
          {fmtTime(r.started_at)} ~ {fmtTime(r.ended_at)}
        </span>
      ),
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      width: 180,
      render: (v?: string) => <span style={{ fontSize: tokens.font.size.caption }}>{v ?? '—'}</span>,
    },
  ];

  const renderBody = () => {
    if (loading && !runs) {
      return (
        <div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="cq-skeleton" style={{ height: 40, marginBottom: tokens.space.xs }} />
          ))}
        </div>
      );
    }
    if (error) {
      return (
        <ErrorCard
          code={error.code}
          message={error.message}
          traceId={error.traceId}
          retryable={error.httpStatus >= 500 || error.httpStatus === 0}
          onRetry={() => void loadRuns()}
        />
      );
    }
    if (runs && runs.total === 0) {
      return (
        <div style={{ textAlign: 'center', padding: tokens.space.xl }}>
          <div style={{ fontSize: tokens.font.size.h3, color: tokens.color.text.secondary }}>还没有评测运行记录</div>
          <Button type="primary" style={{ marginTop: tokens.space.sm }} onClick={openModal}>
            发起第一次评测
          </Button>
        </div>
      );
    }
    if (!runs) return null;

    const failedKeys = runs.items.filter((r) => r.status === 'failed').map((r) => r.run_id);

    return (
      <div>
        <Table<EvalRunListItem>
          size="small"
          rowKey="run_id"
          columns={columns}
          dataSource={runs.items}
          pagination={false}
          onRow={(record) =>
            ({
              'data-testid': 'eval-run-row',
              style: { cursor: 'pointer' },
              onClick: () => navigate(`/eval/reports/${record.run_id}`),
            }) as HTMLAttributes<HTMLElement>
          }
          expandable={{
            showExpandColumn: false,
            expandedRowKeys: failedKeys,
            expandedRowRender: (record) => (
              <ErrorCard
                code="INTERNAL"
                message="评测运行失败"
                traceId={record.run_id}
                retryable={false}
              />
            ),
          }}
        />
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
            已加载 {runs.items.length} / 共 {runs.total}
          </span>
          <span style={{ display: 'flex', gap: tokens.space.xs }}>
            <Button size="small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              上一页
            </Button>
            <Button
              size="small"
              disabled={offset + PAGE_SIZE >= runs.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              下一页
            </Button>
          </span>
        </div>
      </div>
    );
  };

  return (
    <div
      data-testid="page-eval-runs"
      style={{ padding: tokens.space.lg, background: tokens.color.neutral.bg, minHeight: '100%' }}
    >
      <div
        style={{
          background: '#fff',
          border: `1px solid ${tokens.color.neutral.border}`,
          borderRadius: tokens.radius.lg,
          padding: tokens.space.md,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.space.sm }}>
          <h1 style={{ fontSize: tokens.font.size.h1, lineHeight: `${tokens.font.lineHeight.h1}px`, margin: 0 }}>
            评测运行
          </h1>
          <span style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
            只展示后端返回的 headline 摘要，点行查看完整报告
          </span>
          <Button type="primary" style={{ marginLeft: 'auto' }} onClick={openModal}>
            发起评测
          </Button>
        </div>

        {rateLimited && (
          <div
            role="status"
            style={{
              marginTop: tokens.space.sm,
              background: tokens.color.degraded.bg,
              border: `1px solid ${tokens.color.degraded.border}`,
              color: tokens.color.degraded.text,
              borderRadius: tokens.radius.md,
              padding: `${tokens.space.xxs}px ${tokens.space.xs}px`,
              fontSize: tokens.font.size.caption,
            }}
          >
            {rateLimited}
          </div>
        )}

        <div style={{ marginTop: tokens.space.sm }}>{renderBody()}</div>
      </div>

      <Modal
        open={modalOpen}
        title="发起评测"
        okText="发起"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => form.submit()}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form<EvalRunRequest> form={form} layout="vertical" onFinish={(v) => void submit(v)}>
          <Form.Item
            name="dataset_id"
            label="评测集"
            rules={[{ required: true, message: '请选择评测集' }]}
          >
            <Select
              loading={datasetsLoading}
              placeholder="选择评测集"
              options={(datasets ?? []).map((d) => ({
                value: d.dataset_id,
                // draft 评测集不得作为门禁依据 → 置灰 + 提示（A.9.2）
                disabled: d.status === 'draft',
                label:
                  d.status === 'draft'
                    ? `${d.dataset_id}（${d.version}，${d.case_count} 例）（草稿评测集，仅供调试，不可作为门禁依据）`
                    : `${d.dataset_id}（${d.version}，${d.case_count} 例）`,
              }))}
            />
          </Form.Item>

          {selectedDataset && (
            <div
              style={{
                marginTop: -tokens.space.xs,
                marginBottom: tokens.space.sm,
                fontSize: tokens.font.size.caption,
                color: tokens.color.text.secondary,
              }}
            >
              <div>评测集内容哈希（证明本次用的评测集未被动过）：{selectedDataset.content_hash}</div>
              <div style={{ color: tokens.color.text.tertiary }}>
                冻结时间 {fmtTime(selectedDataset.frozen_at)} · 用途 {selectedDataset.purpose}
              </div>
            </div>
          )}

          <Form.Item name="model" label="模型" rules={[{ required: true, message: '请填写模型' }]}>
            <Input placeholder="如 deepseek-flash" />
          </Form.Item>
          <Form.Item name="prompt_version" label="Prompt 版本" rules={[{ required: true, message: '请填写 Prompt 版本' }]}>
            <Input placeholder="如 gen_sql_v7" />
          </Form.Item>
          <Form.Item name="bundle_version" label="口径包版本" rules={[{ required: true, message: '请填写口径包版本' }]}>
            <Input placeholder="如 2026.09.14.1" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={200} placeholder="本次评测的目的（可留空）" />
          </Form.Item>
        </Form>

        {modalError && (
          <ErrorCard
            code={modalError.code}
            message={modalError.message}
            traceId={modalError.traceId}
            retryable={false}
          />
        )}
      </Modal>
    </div>
  );
}