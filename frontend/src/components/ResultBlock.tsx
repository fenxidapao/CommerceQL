/**
 * C5 ResultBlock 结果块（06 §4.5 / §6.4 / §6.5）
 * - 红线 R-2/P4：前端不做任何图表类型推断，严格按后端 chart.chart_type 三选一
 * - chart 缺失 / option 不完整 / chart_type 未知 → DataTable 降级 + info 提示（不白屏）
 * - 渲染失败 → ErrorBoundary 捕获 → DataTable 降级 + error 提示
 * - 空结果（row_count===0）→ 产品自有 info 空态块（不用 AntD 默认空表），禁止 ErrorCard/RefuseCard
 * - 前端不计算任何业务指标（含合计行）；只做显示格式化（千分位/小数位），不做单位换算
 */
import React from 'react';
import { Button, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { InfoCircleOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { tokens } from '../theme/tokens';
import type { ChartEvent, ChartType, DataEvent } from '../api/types';

// ---------------------------------------------------------------------------
// 显示格式化（纯显示层，不做任何业务换算）
// ---------------------------------------------------------------------------

const NUM_FMT = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });

/** 空值/异常值统一渲染规则（06 §6.4：null → '—'，NaN/Infinity → '—'） */
function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return Number.isFinite(v) ? NUM_FMT.format(v) : '—';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

const CHART_TYPES_CARTESIAN: ChartType[] = ['line', 'bar', 'stacked_bar', 'grouped_bar'];
const CHART_TYPES_ALL: ChartType[] = [...CHART_TYPES_CARTESIAN, 'pie'];

/** 后端约束子集可能不含 dataZoom；数据点 > 30 时按 06 §4.5 启用（仅交互能力，非业务计算） */
function withDataZoom(option: Record<string, unknown>): Record<string, unknown> {
  if (option.dataZoom) return option;
  const series = Array.isArray(option.series) ? (option.series as { data?: unknown[] }[]) : [];
  const points = series.reduce((n, s) => n + (Array.isArray(s.data) ? s.data.length : 0), 0);
  if (points <= 30) return option;
  return { ...option, dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }] };
}

/** chart option 完整性检查（防御契约破损，非推断） */
function optionIncomplete(chartType: ChartType, option: Record<string, unknown>): boolean {
  const hasSeries = Array.isArray(option.series) && (option.series as unknown[]).length > 0;
  if (!hasSeries) return true;
  if (chartType !== 'pie' && option.xAxis === undefined) return true;
  return false;
}

/** 空数据判定：series[].data 全空或全 0（06 §4.5 / §6.5：不画空坐标系） */
function seriesEmpty(option: Record<string, unknown>): boolean {
  const series = Array.isArray(option.series) ? (option.series as { data?: unknown[] }[]) : [];
  if (!series.length) return true;
  let hasAny = false;
  for (const s of series) {
    const arr = Array.isArray(s.data) ? s.data : [];
    for (const p of arr) {
      const v =
        typeof p === 'object' && p !== null ? (p as { value?: unknown }).value : p;
      if (v === null || v === undefined) continue;
      if (typeof v === 'number' && v === 0) continue;
      hasAny = true;
    }
  }
  return !hasAny;
}

// ---------------------------------------------------------------------------
// ErrorBoundary（ECharts 抛错 → 降级，不允许整页白屏）
// ---------------------------------------------------------------------------

interface BoundaryProps {
  fallback: React.ReactNode;
  children: React.ReactNode;
}
class ChartErrorBoundary extends React.Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err: unknown) {
    console.error('[ui_chart_render_failed]', err);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function InfoBar({ tone, text, testId }: { tone: 'info' | 'degraded' | 'error'; text: string; testId: string }) {
  const c = tone === 'info' ? tokens.color.info : tone === 'degraded' ? tokens.color.degraded : tokens.color.error;
  return (
    <div
      data-testid={testId}
      role="status"
      style={{
        marginBottom: 8,
        borderRadius: tokens.radius.md,
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: c.text,
        padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
        fontSize: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <InfoCircleOutlined aria-hidden />
      <span>{text}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChartCard
// ---------------------------------------------------------------------------

export interface ChartCardProps {
  chart: ChartEvent;
}

const CHART_TYPE_CN: Record<ChartType, string> = {
  line: '折线图',
  bar: '柱状图',
  stacked_bar: '堆叠柱状图',
  grouped_bar: '分组柱状图',
  pie: '饼图',
  kpi: '单值卡',
  table: '数据表',
};

export function ChartCard({ chart }: ChartCardProps) {
  const option = chart.option as Record<string, unknown>;
  const yAxis = option.yAxis as { name?: string } | { name?: string }[] | undefined;
  const yName = Array.isArray(yAxis) ? yAxis.map((y) => y?.name).filter(Boolean).join(' / ') : yAxis?.name;
  const hasLegend = option.legend !== undefined;
  const meta = chart.meta;
  // 图表对屏幕阅读器不可达 → role="img" + 概述（仅用后端给的字段，不自造结论）
  const ariaLabel = [
    CHART_TYPE_CN[chart.chart_type] ?? '图表',
    meta?.metric ? `指标 ${meta.metric}` : '',
    meta?.time_range ? `时间范围 ${meta.time_range.start} 至 ${meta.time_range.end}` : '',
    '精确数值请查看下方「查看数据表」',
  ]
    .filter(Boolean)
    .join('，');

  return (
    <div data-testid="c5-chart-card" role="img" aria-label={ariaLabel}>
      {!yName && (
        <InfoBar tone="info" text="图表未标注单位，请以表格数值为准" testId="c5-chart-unit-missing" />
      )}
      <ReactECharts
        option={{ ...withDataZoom(option), animation: false } as unknown as import('echarts').EChartsOption}
        style={{ height: hasLegend ? 420 : 320, width: '100%' }}
        notMerge
        lazyUpdate
        autoResize
      />
      <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>
        悬浮查看数值、点击图例可隐藏序列。
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KpiCard
// ---------------------------------------------------------------------------

export interface KpiCardProps {
  data: DataEvent;
  /** 单位来自后端（data.amount_unit / chart.meta.unit），前端不换算 */
  unit?: string;
  /** 同环比：契约当前无对应数值字段（A.1.2 chart.meta 无 compare）→ 仅在调用方显式传入时渲染 */
  compare?: { deltaRatio: number; baseLabel: string };
}

function unitLabel(unit?: string): string {
  if (!unit) return '';
  if (unit === 'CNY') return '元';
  if (unit === 'ratio') return '%';
  return unit;
}

export function KpiCard({ data, unit, compare }: KpiCardProps) {
  const label = (data.columns[0]?.name ?? '') as string;
  const raw = data.rows[0]?.[0];
  const text = fmtCell(raw);
  const suffix = unitLabel(unit);
  return (
    <div
      data-testid="c5-kpi-card"
      style={{
        textAlign: 'center',
        padding: `${tokens.space.lg}px 0`,
        background: '#fff',
        borderRadius: tokens.radius.lg,
        border: `1px solid ${tokens.color.neutral.border}`,
      }}
    >
      <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>{label}</div>
      <div className="tabular-nums" style={{ fontSize: tokens.font.size.kpi, fontWeight: tokens.font.weight.medium, color: tokens.color.text.primary }}>
        {text}
        {suffix && (
          <span style={{ fontSize: 14, fontWeight: tokens.font.weight.regular, marginLeft: 4 }}>{suffix}</span>
        )}
      </div>
      {compare && (
        <div style={{ fontSize: 12, color: tokens.color.text.secondary, marginTop: 4 }}>
          <span
            className="tabular-nums"
            style={{ color: compare.deltaRatio >= 0 ? tokens.color.chart.up : tokens.color.chart.down }}
          >
            {compare.deltaRatio >= 0 ? '↑' : '↓'} {Math.abs(compare.deltaRatio * 100).toFixed(1)}%
          </span>
          <span style={{ marginLeft: 6 }}>{compare.baseLabel}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DataTable
// ---------------------------------------------------------------------------

export interface DataTableProps {
  data: DataEvent;
}

export function DataTable({ data }: DataTableProps) {
  const [sortedBy, setSortedBy] = React.useState<string | null>(null);

  const columns: ColumnsType<Record<string, unknown>> = data.columns.map((c, ci) => ({
    title: c.name,
    dataIndex: `c${ci}`,
    key: `c${ci}`,
    // 列类型严格按 data.columns[].type（06 §4.5），非推断
    align: c.type === 'numeric' ? 'right' : 'left',
    className: c.type === 'numeric' ? 'tabular-nums' : undefined,
    ellipsis: true,
    width: ci === 0 ? undefined : c.type === 'numeric' ? 140 : undefined,
    sorter: (a, b) => {
      const av = a[`c${ci}`];
      const bv = b[`c${ci}`];
      if (typeof av === 'number' && typeof bv === 'number') return av - bv;
      return String(av ?? '').localeCompare(String(bv ?? ''));
    },
    render: (v: unknown) => (
      // 空值 → '—'（不显示 null/NULL/NaN）；超长文本单行省略 + title 全文（不用 Tooltip）
      <span title={v === null || v === undefined ? undefined : String(v)}>{fmtCell(v)}</span>
    ),
  }));

  const rows = data.rows.map((r, i) => {
    const o: Record<string, unknown> = { __k: i };
    data.columns.forEach((_, ci) => {
      o[`c${ci}`] = r[ci];
    });
    return o;
  });

  const many = rows.length > 50; // > 50 行启用前端分页，首屏只渲染当前页

  return (
    <div data-testid="c5-data-table">
      {sortedBy && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginBottom: 4 }}>
          已按 {sortedBy} 排序（仅对当前已返回的 {rows.length} 行，非数据库排序）
        </div>
      )}
      <Table<Record<string, unknown>>
        size="small"
        rowKey="__k"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        pagination={
          many
            ? { pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100'], size: 'small' }
            : false
        }
        locale={{ emptyText: ' ' }}
        onChange={(_p, _f, sorter) => {
          const s = Array.isArray(sorter) ? sorter[0] : sorter;
          const idx = s?.columnKey ? Number(String(s.columnKey).slice(1)) : NaN;
          setSortedBy(s?.order ? (data.columns[idx]?.name ?? null) : null);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 空结果空态块（06 §6.5：不用 AntD 默认空表；禁止自创权限相关措辞）
// ---------------------------------------------------------------------------

function EmptyBlock({ onSuggest }: { onSuggest?: (text: string) => void }) {
  const suggestions = ['放宽时间范围', '去掉某个筛选条件'];
  return (
    <div
      data-testid="c5-empty-block"
      style={{
        padding: tokens.space.lg,
        textAlign: 'center',
        background: tokens.color.info.bg,
        border: `1px solid ${tokens.color.info.border}`,
        borderRadius: tokens.radius.lg,
        color: tokens.color.info.text,
      }}
    >
      <div style={{ fontSize: tokens.font.size.h2 }}>该条件下没有数据</div>
      <div style={{ fontSize: 12, marginTop: 4, opacity: 0.85 }}>
        可能原因：时间范围内没有订单 / 筛选条件过严
      </div>
      {onSuggest && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8, justifyContent: 'center' }}>
          {suggestions.map((s) => (
            <Button key={s} size="small" onClick={() => onSuggest(s)}>
              {s}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ResultBlock
// ---------------------------------------------------------------------------

export interface ResultBlockProps {
  data?: DataEvent | null;
  chart?: ChartEvent | null;
  /** 空态建议（「放宽时间范围」等）填入 AskBox，不自动提交 */
  onSuggest?: (text: string) => void;
}

export function ResultBlock({ data, chart, onSuggest }: ResultBlockProps) {
  const [showTable, setShowTable] = React.useState(false);
  if (!data) return null;

  // 空结果：正常完成路径，不是错误（§4.12 辨析 #2/#3）
  if (data.row_count === 0 || data.rows.length === 0) {
    return (
      <div data-testid="c5-result-block">
        <EmptyBlock onSuggest={onSuggest} />
      </div>
    );
  }

  // 整列为 null → info 提示（06 §6.4）
  const allNullCol = data.columns.find((_, ci) => data.rows.every((r) => r[ci] === null || r[ci] === undefined));
  // 非有限数值（NaN/Infinity）→ degraded 提示，提示后端 NULLIF 未生效（§6.4）
  const hasBadNumber = data.rows.some((r) =>
    r.some((v) => typeof v === 'number' && !Number.isFinite(v)),
  );

  const unit = chart?.meta?.unit ?? data.amount_unit;

  let body: React.ReactNode;
  let fallbackNote: React.ReactNode = null;

  if (!chart) {
    // chart 事件缺失 → DataTable 降级（决策 D8）
    body = <DataTable data={data} />;
    fallbackNote = <InfoBar tone="info" text="本次未能生成图表，已用表格展示" testId="c5-chart-missing" />;
  } else {
    const ct = chart.chart_type;
    if (!(CHART_TYPES_ALL as string[]).includes(ct)) {
      // chart_type 不在枚举内（未来新增）→ 不认识就不画，不猜
      console.warn('[ui_unknown_chart_type]', ct);
      body = <DataTable data={data} />;
      fallbackNote = <InfoBar tone="info" text="图表数据不完整，已用表格展示" testId="c5-chart-unknown" />;
    } else if (ct === 'kpi') {
      if (data.rows.length > 1) {
        // kpi 只承载 1 行 1 列；rows>1 属契约破损 → 降级 + 前端日志
        console.warn('[ui_kpi_contract_violation] rows =', data.rows.length);
        body = <DataTable data={data} />;
        fallbackNote = <InfoBar tone="info" text="图表数据不完整，已用表格展示" testId="c5-kpi-degraded" />;
      } else {
        body = <KpiCard data={data} unit={unit} />;
      }
    } else if (optionIncomplete(ct, chart.option)) {
      body = <DataTable data={data} />;
      fallbackNote = <InfoBar tone="info" text="图表数据不完整，已用表格展示" testId="c5-chart-incomplete" />;
    } else if (seriesEmpty(chart.option)) {
      body = <EmptyBlock onSuggest={onSuggest} />;
    } else {
      const table = <DataTable data={data} />;
      body = (
        <>
          <ChartErrorBoundary
            fallback={
              <>
                <InfoBar tone="error" text="图表渲染失败，已用表格展示" testId="c5-chart-error" />
                {table}
              </>
            }
          >
            <ChartCard chart={chart} />
          </ChartErrorBoundary>
          {/* 06 §13.1 硬要求：图表可达性 → 必须提供等价数据表切换 */}
          <div>
            <Button type="link" size="small" style={{ fontSize: 12, padding: 0 }} onClick={() => setShowTable((v) => !v)}>
              {showTable ? '收起数据表' : '查看数据表'}
            </Button>
          </div>
          {showTable && table}
        </>
      );
    }
  }

  return (
    <div data-testid="c5-result-block" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {fallbackNote}
      {allNullCol && (
        <InfoBar
          tone="info"
          text={`该指标在当前条件下无法计算（${allNullCol.name} 全为空值）`}
          testId="c5-null-column"
        />
      )}
      {hasBadNumber && (
        <InfoBar tone="degraded" text="数值异常，可能因分母为 0" testId="c5-bad-number" />
      )}
      {body}
    </div>
  );
}