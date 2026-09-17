/**
 * 评测报告页（/eval/reports/:runId）—— 06 §11.3 第 2 级
 * - 数据源：A.9.4 GET /admin/eval/runs/{run_id}
 * - **grid / attribution / gate 全部由后端聚合返回，本页一行聚合代码都不写**（只遍历渲染）
 * - cases 默认不拉取（include_cases=false）；展开时带 include_cases=true&case_filter=failed
 * - ⚠️ 不得展示 gold_sql / predicted_sql（契约不返回，刻意不下发评测答案）
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { useParams } from 'react-router-dom';
import { Button, Collapse, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import dayjs from 'dayjs';
import { ApiError, apiGet } from '../api/client';
import type { EvalCase, EvalRunDetail, GateItem, GridCell } from '../api/types';
import { ErrorCard } from '../components';
import { tokens } from '../theme/tokens';

const STRUCT_TEXT: Record<string, string> = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
  extra_hard: '超难',
};

const SEMANTIC_TEXT: Record<string, string> = {
  low: '低语义',
  medium: '中语义',
  high: '高语义',
};

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

const sectionStyle: CSSProperties = {
  background: '#fff',
  border: `1px solid ${tokens.color.neutral.border}`,
  borderRadius: tokens.radius.lg,
  padding: tokens.space.md,
  marginTop: tokens.space.md,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: tokens.font.size.h2,
  lineHeight: `${tokens.font.lineHeight.h2}px`,
  fontWeight: tokens.font.weight.medium,
  margin: 0,
};

function SectionTitle({ text }: { text: string }) {
  return <h2 style={sectionTitleStyle}>{text}</h2>;
}

/** 门禁徽章（verdict=pass → success / fail → error） */
function GateBadge({ item }: { item: GateItem }) {
  const c = item.verdict === 'fail' ? tokens.color.error : tokens.color.success;
  return (
    <span
      data-testid="eval-gate-badge"
      title={item.detail}
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: c.text,
        borderRadius: tokens.radius.sm,
        padding: `0 ${tokens.space.xxs}px`,
        fontSize: tokens.font.size.caption,
        lineHeight: `${tokens.font.lineHeight.caption}px`,
        whiteSpace: 'nowrap',
      }}
    >
      {item.id} {item.name}：
      {item.verdict === 'fail' ? '未通过' : '通过'}
      {item.detail ? `（${item.detail}）` : ''}
    </span>
  );
}

interface OverallRow {
  key: string;
  category: string;
  label: string;
  value: string;
  danger?: boolean;
}

const overAllColumns: ColumnsType<OverallRow> = [
  { title: '类别', dataIndex: 'category', key: 'category', width: 140 },
  { title: '指标', dataIndex: 'label', key: 'label' },
  {
    title: '数值',
    dataIndex: 'value',
    key: 'value',
    width: 160,
    render: (v: string, row) => (
      <strong style={{ color: row.danger ? tokens.color.error.border : tokens.color.text.primary }}>{v}</strong>
    ),
  },
];

/** 用例明细的十个字段（契约不返回 gold_sql / predicted_sql） */
const CASE_FIELDS: { label: string; get: (c: EvalCase) => string }[] = [
  { label: '用例编号', get: (c) => c.case_id },
  { label: '问题原文', get: (c) => c.question },
  { label: '结构难度', get: (c) => c.difficulty_struct },
  { label: '语义难度', get: (c) => c.difficulty_semantic },
  { label: '期望行为', get: (c) => c.expected_behavior },
  { label: '实际行为', get: (c) => c.actual_behavior },
  { label: '结果等价', get: (c) => (c.result_equivalent ? '是' : '否') },
  { label: '归因', get: (c) => c.attribution ?? '—' },
  { label: '耗时', get: (c) => `${c.latency_ms} ms` },
  { label: '成本', get: (c) => `${c.cost_cny} 元` },
];

export function EvalReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [includeCases, setIncludeCases] = useState(false);
  const [casesLoading, setCasesLoading] = useState(false);

  const load = useCallback(
    async (withCases: boolean) => {
      if (!runId) {
        setError(new ApiError({ code: 'RUN_NOT_FOUND', message: '评测运行不存在或已被清理', httpStatus: 404 }));
        setLoading(false);
        return;
      }
      if (withCases) setCasesLoading(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await apiGet<EvalRunDetail>(`/admin/eval/runs/${runId}`, {
          include_cases: withCases,
          case_filter: withCases ? 'failed' : undefined,
          limit: 50,
          offset: 0,
        });
        setDetail(data);
        setIncludeCases(withCases);
      } catch (err) {
        setError(toApiError(err));
        if (!withCases) setDetail(null);
      } finally {
        if (withCases) setCasesLoading(false);
        else setLoading(false);
      }
    },
    [runId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  if (loading) {
    return (
      <div data-testid="page-eval-report" style={{ padding: tokens.space.lg }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="cq-skeleton" style={{ height: 120, marginBottom: tokens.space.sm }} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div data-testid="page-eval-report" style={{ padding: tokens.space.lg }}>
        <ErrorCard
          code={error.code}
          message={error.message}
          traceId={error.traceId}
          retryable={error.code !== 'RUN_NOT_FOUND' && error.code !== 'FORBIDDEN_SCOPE'}
          onRetry={() => void load(false)}
        />
      </div>
    );
  }

  if (!detail) return <div data-testid="page-eval-report" style={{ padding: tokens.space.lg }} />;

  const { run, overall, grid, attribution, gate } = detail;

  // 运行信息：run.* 全字段（dataset_content_hash 是「评测集未被改动」的证据，必须展示）
  const runInfo: [string, string][] = [
    ['运行 ID', run.run_id],
    ['评测集 ID', run.dataset_id],
    ['评测集内容哈希', run.dataset_content_hash],
    ['模型', run.model],
    ['Prompt 版本', run.prompt_version],
    ['口径包版本', run.bundle_version],
    ['状态', run.status],
    ['开始时间', fmtTime(run.started_at)],
    ['结束时间', fmtTime(run.ended_at)],
  ];

  // 总体结果：security.* 三项置顶并 error 色高亮（红线 = 0）
  const overallRows: OverallRow[] = [
    { key: 's1', category: '安全（红线）', label: '危险 SQL 放行', value: String(overall.security.dangerous_sql_passed), danger: true },
    { key: 's2', category: '安全（红线）', label: '跨租户泄露', value: String(overall.security.cross_tenant_leaks), danger: true },
    { key: 's3', category: '安全（红线）', label: 'PII 泄露', value: String(overall.security.pii_leaks), danger: true },
    { key: 'ex', category: '总体', label: 'EX 综合', value: pct(overall.ex) },
    { key: 'r1', category: '拒答', label: '真阳性率', value: pct(overall.refusal.true_positive_rate) },
    { key: 'r2', category: '拒答', label: '假阳性率', value: pct(overall.refusal.false_positive_rate) },
    { key: 'r3', category: '拒答', label: '原因准确率', value: pct(overall.refusal.reason_accuracy) },
    { key: 'c1', category: '澄清', label: '触发准确率', value: pct(overall.clarify.trigger_accuracy) },
    { key: 'c2', category: '澄清', label: '澄清后准确率', value: pct(overall.clarify.post_clarify_accuracy) },
    { key: 'c3', category: '澄清', label: '平均澄清轮次', value: `${overall.clarify.avg_rounds} 轮` },
    { key: 'k1', category: '一致性', label: '口径一致性', value: pct(overall.consistency.rate) },
    { key: 'k2', category: '一致性', label: '可归因率', value: pct(overall.consistency.attributable_rate) },
    { key: 'e1', category: '效率', label: '全表扫描率', value: pct(overall.efficiency.seq_scan_rate) },
    { key: 'e2', category: '效率', label: '笛卡尔积次数', value: `${overall.efficiency.cartesian_count} 次` },
    { key: 'e3', category: '效率', label: 'P95 执行耗时', value: `${overall.efficiency.p95_exec_ms} ms` },
    { key: 'l1', category: '延迟', label: 'P50 延迟', value: `${overall.latency.p50_ms} ms` },
    { key: 'l2', category: '延迟', label: 'P95 延迟', value: `${overall.latency.p95_ms} ms` },
    { key: 'm1', category: '成本', label: '总成本', value: `${overall.cost.total_cny} 元` },
    { key: 'm2', category: '成本', label: '单次查询成本', value: `${overall.cost.per_query_cny} 元` },
    { key: 'm3', category: '成本', label: '缓存命中率', value: pct(overall.cost.cache_hit_rate) },
  ];

  // 4×3 网格：仅做查找，不做聚合
  const cellMap = new Map<string, GridCell>(grid.cells.map((c) => [`${c.struct}|${c.semantic}`, c]));

  const other = attribution.find((a) => a.category === 'other');
  const otherOverBudget = other !== undefined && other.ratio > 0.1;

  const attributionRows = [...attribution].reverse();
  const attributionOption: EChartsOption = {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}：{c}' },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: attributionRows.map((a) => a.category) },
    series: [
      {
        type: 'bar',
        name: '失败用例数',
        data: attributionRows.map((a) => ({
          value: a.count,
          // security_leak 必须用 error 色单独强调（06 §11.3 区块 5）
          itemStyle: { color: a.category === 'security_leak' ? tokens.color.error.border : tokens.color.brand.solid },
        })),
      },
    ],
  };

  return (
    <div
      data-testid="page-eval-report"
      style={{ padding: tokens.space.lg, background: tokens.color.neutral.bg, minHeight: '100%' }}
    >
      {/* 跨租户视角：A.9.4 强制要求常驻提示，否则易被误读为本租户结果 */}
      {detail.scope === 'cross_tenant' && (
        <div
          data-testid="eval-cross-tenant-banner"
          role="status"
          style={{
            background: tokens.color.info.bg,
            border: `1px solid ${tokens.color.info.border}`,
            color: tokens.color.info.text,
            borderRadius: tokens.radius.md,
            padding: `${tokens.space.xxs}px ${tokens.space.sm}px`,
            fontSize: tokens.font.size.caption,
          }}
        >
          你正在查看跨租户数据（平台管理员视角）
        </div>
      )}

      {gate.passed === false && (
        <div
          role="alert"
          style={{
            marginTop: tokens.space.xs,
            background: tokens.color.error.bg,
            border: `1px solid ${tokens.color.error.border}`,
            color: tokens.color.error.text,
            borderRadius: tokens.radius.md,
            padding: `${tokens.space.xxs}px ${tokens.space.sm}px`,
            fontSize: tokens.font.size.body,
          }}
        >
          本版本未通过上线门禁，禁止发布
        </div>
      )}

      {/* 区块 1：运行信息 */}
      <div style={sectionStyle}>
        <SectionTitle text="运行信息" />
        <dl style={{ margin: `${tokens.space.xs}px 0 0`, display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 4 }}>
          {runInfo.map(([k, v]) => (
            <Fragment key={k}>
              <dt style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>{k}</dt>
              <dd style={{ margin: 0, fontSize: tokens.font.size.body, wordBreak: 'break-all' }}>{v}</dd>
            </Fragment>
          ))}
        </dl>
      </div>

      {/* 区块 2：门禁总览 */}
      <div style={sectionStyle}>
        <SectionTitle text="门禁总览" />
        <div style={{ marginTop: tokens.space.xs, display: 'flex', gap: tokens.space.xxs, flexWrap: 'wrap' }}>
          {gate.items.map((item) => (
            <GateBadge key={item.id} item={item} />
          ))}
        </div>
      </div>

      {/* 区块 3：总体结果（security 三项置顶） */}
      <div style={sectionStyle}>
        <SectionTitle text="总体结果" />
        <Table<OverallRow>
          size="small"
          rowKey="key"
          columns={overAllColumns}
          dataSource={overallRows}
          pagination={false}
          style={{ marginTop: tokens.space.xs }}
        />
      </div>

      {/* 区块 4：4×3 双维度网格 */}
      <div style={sectionStyle}>
        <SectionTitle text="双维度网格（4×3）" />
        <div
          style={{
            marginTop: tokens.space.xs,
            display: 'grid',
            gridTemplateColumns: `120px repeat(${grid.axes.semantic.length}, minmax(0, 1fr))`,
            gap: tokens.space.xs,
          }}
        >
          <div />
          {grid.axes.semantic.map((sem) => (
            <div
              key={`head-${sem}`}
              style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary, textAlign: 'center' }}
            >
              {SEMANTIC_TEXT[sem] ?? sem}
            </div>
          ))}
          {grid.axes.struct.map((st) => (
            <Fragment key={st}>
              <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.secondary }}>
                {STRUCT_TEXT[st] ?? st}
              </div>
              {grid.axes.semantic.map((sem) => {
                const cell = cellMap.get(`${st}|${sem}`);
                // cells 中缺失的格子显示为空（不显示 0%，避免把「未测」误读为「全错」）
                if (!cell) return <div key={`${st}|${sem}`} style={{ minHeight: 64 }} />;
                const c = cell.verdict === 'fail' ? tokens.color.error : tokens.color.success;
                // 契约里 extra_hard 行的 target 为 null → 显示「仅报告」而非达标/未达标
                const target: number | null = cell.target;
                return (
                  <div
                    key={`${st}|${sem}`}
                    data-testid="eval-grid-cell"
                    style={{
                      background: c.bg,
                      border: `1px solid ${c.border}`,
                      color: c.text,
                      borderRadius: tokens.radius.md,
                      padding: tokens.space.xs,
                      minHeight: 64,
                    }}
                  >
                    <div style={{ fontSize: tokens.font.size.h3, fontWeight: tokens.font.weight.medium }}>
                      {pct(cell.ex)}
                    </div>
                    <div style={{ fontSize: tokens.font.size.caption }}>
                      {cell.passed}/{cell.total}
                    </div>
                    <div style={{ fontSize: tokens.font.size.caption, opacity: 0.85 }}>
                      {target === null ? '仅报告' : `目标 ${pct(target)}`}
                    </div>
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      {/* 区块 5：失败归因分布 */}
      <div style={sectionStyle} data-testid="eval-attribution">
        <SectionTitle text="失败归因分布" />
        {attribution.length === 0 ? (
          <div style={{ marginTop: tokens.space.xs, fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
            后端未返回归因分布
          </div>
        ) : (
          <ReactECharts option={attributionOption} style={{ height: 260 }} notMerge />
        )}
        {otherOverBudget && (
          <div
            style={{
              marginTop: tokens.space.xs,
              background: tokens.color.degraded.bg,
              border: `1px solid ${tokens.color.degraded.border}`,
              color: tokens.color.degraded.text,
              borderRadius: tokens.radius.md,
              padding: `${tokens.space.xxs}px ${tokens.space.sm}px`,
              fontSize: tokens.font.size.caption,
            }}
          >
            other 类占比超过 10%，需人工复核归因分类
          </div>
        )}
      </div>

      {/* 区块 6：成本 */}
      <div style={sectionStyle}>
        <SectionTitle text="成本" />
        <div style={{ marginTop: tokens.space.xs, display: 'flex', gap: tokens.space.sm, flexWrap: 'wrap' }}>
          {[
            { label: '总成本', value: `${overall.cost.total_cny} 元`, degraded: false },
            { label: '单次查询成本', value: `${overall.cost.per_query_cny} 元`, degraded: false },
            { label: '缓存命中率', value: pct(overall.cost.cache_hit_rate), degraded: overall.cost.cache_hit_rate < 0.6 },
          ].map((kpi) => {
            const c = kpi.degraded ? tokens.color.degraded : tokens.color.neutral;
            return (
              <div
                key={kpi.label}
                style={{
                  flex: '1 1 160px',
                  background: c.bg,
                  border: `1px solid ${c.border}`,
                  color: c.text,
                  borderRadius: tokens.radius.md,
                  padding: tokens.space.sm,
                }}
              >
                <div style={{ fontSize: tokens.font.size.caption, opacity: 0.85 }}>{kpi.label}</div>
                <div style={{ fontSize: tokens.font.size.kpi, lineHeight: `${tokens.font.lineHeight.h1}px` }}>
                  {kpi.value}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 区块 7：用例明细（默认不拉取） */}
      <div style={sectionStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.space.sm }}>
          <SectionTitle text="用例明细" />
          <Button
            size="small"
            loading={casesLoading}
            style={{ marginLeft: 'auto' }}
            onClick={() => void load(!includeCases)}
          >
            {includeCases ? '收起用例' : '展开失败用例'}
          </Button>
        </div>
        {includeCases && detail.cases && (
          <div style={{ marginTop: tokens.space.xs }}>
            <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              本页含评测问题原文
            </div>
            <Collapse
              ghost
              items={detail.cases.items.map((c) => ({
                key: c.case_id,
                label: (
                  <span style={{ fontSize: tokens.font.size.body }}>
                    <span style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>{c.case_id}</span>
                    {' · '}
                    {c.question.length > 40 ? `${c.question.slice(0, 40)}…` : c.question}
                    {!c.result_equivalent && <span style={{ color: tokens.color.error.border }}> · 不等价</span>}
                  </span>
                ),
                children: (
                  <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: 4 }}>
                    {CASE_FIELDS.map((f) => (
                      <Fragment key={f.label}>
                        <dt style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
                          {f.label}
                        </dt>
                        <dd style={{ margin: 0, fontSize: tokens.font.size.body, whiteSpace: 'pre-wrap' }}>
                          {f.get(c)}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                ),
              }))}
            />
            <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              已加载 {detail.cases.items.length} / 共 {detail.cases.total} 条失败用例
            </div>
          </div>
        )}
      </div>

      {/* 页脚：两条诚实声明（原文照渲染，附录 C §C.16） */}
      <div
        data-testid="eval-footer-honesty"
        style={{
          marginTop: tokens.space.md,
          fontSize: tokens.font.size.caption,
          color: tokens.color.text.tertiary,
          lineHeight: `${tokens.font.lineHeight.caption}px`,
        }}
      >
        <div>本页数据基于合成数据集，其表结构、口径、权限模型按真实实践设计，但数值不代表任何真实企业。</div>
        <div>目标值为设计目标，首次实测后须用真实数据替换。</div>
      </div>
    </div>
  );
}