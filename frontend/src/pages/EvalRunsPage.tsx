/**
 * 评测运行列表页（/eval/runs）—— 06 §11.3 第 1 级
 * - 数据源：A.9.3 GET /admin/eval/runs（Paged<EvalRunListItem>）
 * - **只渲染 headline 摘要**，点行才拉详情（避免 N+1，A.0.6）
 * - 发起评测：A.9.1 POST /admin/eval/run；dataset_id 候选值来自 A.9.2
 *   🔻 T-37（2026-10-05）：该端点当前只回**预检**（`run_id: null`／`status: "dry_run"`），
 *   故此页把响应渲染成"这批多少条调用＋多少钱"，**不写**"评测已发起"。
 * - 前端零判断权：不做任何指标聚合；比例字段仅做显示格式化
 */
import { useCallback, useEffect, useState } from 'react';
import type { HTMLAttributes } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Form, Input, Modal, Select, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { ApiError, apiGet, apiPost } from '../api/client';
import type {
  EvalDataset,
  EvalRunListItem,
  EvalRunPrecheck,
  EvalRunRequest,
  EvalRunStatus,
  Metric,
  Paged,
} from '../api/types';
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

/** 比例显示格式化（0.812 → 81.2%），非业务计算。
 *  🔻 T-34：`null` = 这一格产物里没有数 ⇒ 显示「未记录」；渲染成 `0.0%`/`NaN%` 是把"没数"伪装成测量。*/
function pct(v: Metric): string {
  return v === null || v === undefined ? '未记录' : `${(v * 100).toFixed(1)}%`;
}

function show(v: Metric | string | undefined, unit = ''): string {
  if (v === null || v === undefined || v === '') return '未记录';
  return `${v}${unit}`;
}

/** 报价显示格式化（不是业务计算）：`null` = 盘上没有真打批次 ⇒「无观测基准」。
 *  🔴 这里**不许**把 `null` 渲染成 `¥0`：那会把"没基准"伪装成"基准是零"。 */
function yuan(v: number | null | undefined): string {
  return v === null || v === undefined ? '无观测基准' : `¥${v.toFixed(6)}`;
}

function calls(v: number | null | undefined): string {
  return v === null || v === undefined ? '无观测基准' : `${v} 次`;
}

function fmtTime(iso?: string | null): string {
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

const BASIS_MODE_TEXT: Record<string, string> = {
  same_dataset: '基准与本次同集（内容哈希一致）',
  extrapolated_from_other_dataset: '本次这集没真打过 ⇒ 按另一集的每案口径外推（方向 = 上界）',
  no_live_batch: '盘上没有真打过的批次 ⇒ 无观测基准',
};

/** §A.9.1 补记（T-37）的预检面板：**只读响应，不做任何本地计算**（07 的"前端零判断权"）。 */
function PrecheckPanel({ data }: { data: EvalRunPrecheck }) {
  const { quote } = data;
  const est = quote.estimate;
  const line = (label: string, value: string) => (
    <div style={{ display: 'flex', gap: tokens.space.xs }}>
      <span style={{ color: tokens.color.text.tertiary, minWidth: 76 }}>{label}</span>
      <span style={{ color: tokens.color.text.primary }}>{value}</span>
    </div>
  );
  return (
    <div
      data-testid="eval-precheck"
      style={{
        marginTop: tokens.space.sm,
        padding: tokens.space.sm,
        border: `1px solid ${tokens.color.neutral.border}`,
        borderRadius: tokens.radius.md,
        background: tokens.color.neutral.bg,
        fontSize: tokens.font.size.caption,
        lineHeight: `${tokens.font.lineHeight.caption}px`,
      }}
    >
      <div style={{ fontWeight: tokens.font.weight.medium, marginBottom: tokens.space.xs }}>
        预检结果 —— 未发起评测（run_id 为空，零出站、零花费）
      </div>
      {line('题数', `${quote.cases_total} 题`)}
      {line('LLM 调用', `${calls(est.llm_calls_low)} ～ ${calls(est.llm_calls_high)}`)}
      {line('非峰报价', `${yuan(est.cost_cny_off_peak_low)} ～ ${yuan(est.cost_cny_off_peak_high)}`)}
      {line('保守口径', yuan(est.cost_cny_off_peak_conservative))}
      {line('峰档上界', yuan(est.cost_cny_peak_upper_bound))}
      {line(
        '当前档位',
        `${quote.tier.now}${quote.tier.at_peak_now ? '（现在就是峰档）' : ''} · 峰/非峰乘数 ×${quote.tier.peak_multiplier.multiplier}`,
      )}
      {line(
        '基准',
        `${BASIS_MODE_TEXT[quote.basis.mode] ?? quote.basis.mode} · ${quote.basis.artifacts_available} 份产物 / ${quote.basis.distinct_batches} 批独立观测`,
      )}
      {quote.basis.artifacts.length > 0 && (
        <div style={{ marginTop: tokens.space.xs, color: tokens.color.text.tertiary }}>
          出处：
          {quote.basis.artifacts
            .map((a) => `${a.artifact}（${a.git_rev ?? 'rev 未记录'}，${a.cost_cny_total ?? '未记录'} 元）`)
            .join(' · ')}
        </div>
      )}
      <div style={{ marginTop: tokens.space.xs, color: tokens.color.text.tertiary }}>{quote.basis.why}</div>
      <div style={{ marginTop: tokens.space.xs, color: tokens.color.text.secondary }}>
        模型归属：{quote.model_attribution.detail}
      </div>
      <div style={{ marginTop: tokens.space.xs }}>
        {data.launch_blockers.map((b) => (
          <div key={b.missing} style={{ color: tokens.color.text.tertiary }}>
            · 缺 {b.missing}：{b.detail}
          </div>
        ))}
      </div>
    </div>
  );
}

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
  /** §A.9.1 补记（T-37）：这一支今天只回预检 ⇒ 结果留在弹窗里看，不写进列表（列表里没有假批次）。 */
  const [precheck, setPrecheck] = useState<EvalRunPrecheck | null>(null);
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
    setPrecheck(null);
    setModalOpen(true);
  };

  // 打开弹窗时按需拉取评测集候选值（A.9.2）
  //
  // 🔴 第 14 轮真机走查抓到的缺陷与这里的形状（`e01c198` 起就在，A.9.2 端点接上后才第一次可见）：
  // `datasetsLoading` **既在这个 effect 的依赖数组里、又在 effect 体内被 `setDatasetsLoading(true)` 改**
  // ⇒ 依赖一变 React 先跑上一轮的 cleanup（`cancelled = true`），本轮又被 `datasetsLoading` 的守卫挡回去，
  // 于是上一轮 Promise 落地时 `.then`／`.catch`／`.finally` 里那三个 `if (!cancelled)` **全部跳过**
  // ⇒ 候选恒空（HTTP 200 也空）、403 也静默、loading 永远停在 true。
  // ⇒ 规矩：**不要把"本次请求自己的状态"放进依赖数组**；loading 在两个分支里各自复位，
  //   `ignore` 只用来挡"弹窗已关／组件已卸载"之后的写入。
  useEffect(() => {
    if (!modalOpen || datasets !== null) return;
    let ignore = false;
    setDatasetsLoading(true);
    apiGet<{ items: EvalDataset[]; total: number }>('/admin/eval/datasets')
      .then((d) => {
        setDatasetsLoading(false);
        if (!ignore) setDatasets(d.items);
      })
      .catch((err: unknown) => {
        setDatasetsLoading(false);
        if (!ignore) setModalError(toApiError(err));
      });
    return () => {
      ignore = true;
    };
  }, [modalOpen, datasets]);

  const submit = async (values: EvalRunRequest) => {
    setSubmitting(true);
    setModalError(null);
    try {
      // 🔴 今天这一支**不会**发起评测：响应是预检（`launched: false`），
      // 所以这里不关弹窗、不刷列表、不写"评测已发起"——那三件事都会把预检说成已执行。
      const data = await apiPost<EvalRunPrecheck>('/admin/eval/run', { ...values, dry_run: true });
      setPrecheck(data);
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
          <div>{show(r.model)}</div>
          <div style={{ color: tokens.color.text.tertiary }}>{show(r.prompt_version)}</div>
          <div style={{ color: tokens.color.text.tertiary }}>口径包 {show(r.bundle_version)}</div>
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
      // 🔻 T-34：三态。`gate_passed === null` 是"这一批没有门禁判定"，
      // 旧代码的两分支会把它渲染成红色「未过门禁」——那是把"没算"说成"算出坏了"。
      render: (_, r) =>
        r.gate_passed === true ? (
          <Badge text="已过门禁" tone="success" />
        ) : r.gate_passed === false ? (
          <Badge text="未过门禁" tone="error" />
        ) : (
          <Badge text="无门禁判定" tone="neutral" />
        ),
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
              ['危险 SQL 放行', show(r.headline.dangerous_sql_passed)],
              ['跨租户泄露', show(r.headline.cross_tenant_leaks)],
              ['P95 延迟', show(r.headline.p95_latency_ms, ' ms')],
              ['总成本', show(r.headline.cost_total_cny, ' 元')],
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
        title="发起评测 —— 当前只出预检报价"
        okText="生成预检"
        cancelText="关闭"
        confirmLoading={submitting}
        onOk={() => form.submit()}
        onCancel={() => {
          setModalOpen(false);
          setPrecheck(null);
        }}
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

        {precheck && <PrecheckPanel data={precheck} />}

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