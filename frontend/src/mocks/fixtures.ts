/**
 * MSW 场景 fixture（仅供开发/测试，不进入生产构建产物）
 * 场景清单见 scenarios.md；触发方式：question 关键词 或 X-Mock-Scenario 头。
 */
import type { MockFrame } from './sse';

const NOW = '2026-09-17T10:30:00+08:00';

const SQL_TEXT = `SELECT r.region_name,
       SUM(o.pay_amount) AS gmv
FROM v_order_paid o
JOIN v_region r ON r.region_id = o.region_id
WHERE o.pay_time >= $1 AND o.pay_time < $2
  AND o.refund_status <> 'refunded'
  AND o.tenant_id = current_setting('app.tenant_id')
GROUP BY r.region_name
LIMIT 1000`;

/** 成功全链（ack→6 stage→data→chart→insight→meta→complete），role_limited 提示 */
export function successFrames(taskId = 'tk_mock001', sessionId = 'ss_mock001'): MockFrame[] {
  return [
    { event: 'ack', data: { task_id: taskId, session_id: sessionId, terminal: false } },
    { event: 'stage', data: { stage: 'intent', elapsed_ms: 143, terminal: false }, delayMs: 60 },
    {
      event: 'stage',
      data: { stage: 'schema_linking', elapsed_ms: 486, candidates_count: 12, terminal: false },
      delayMs: 120,
    },
    {
      event: 'stage',
      data: {
        stage: 'plan_ready',
        elapsed_ms: 1520,
        plan_summary: {
          metrics: ['gmv'],
          dimensions: ['region'],
          time_range: { start: '2026-08-01', end: '2026-08-31' },
          compare: 'mom',
        },
        terminal: false,
      },
      delayMs: 150,
    },
    {
      event: 'stage',
      data: { stage: 'sql_ready', elapsed_ms: 2180, dialect: 'postgresql', confidence: 0.87, sql: SQL_TEXT, terminal: false },
      delayMs: 150,
    },
    {
      event: 'stage',
      data: {
        stage: 'gate_passed',
        elapsed_ms: 2320,
        gate_detail: { ast: 'pass', policy: 'pass', cost: { est_rows: 4210, verdict: 'execute' } },
        terminal: false,
      },
      delayMs: 100,
    },
    { event: 'stage', data: { stage: 'executing', elapsed_ms: 2350, terminal: false }, delayMs: 100 },
    {
      event: 'data',
      data: {
        columns: [
          { name: 'region_name', type: 'text' },
          { name: 'gmv', type: 'numeric' },
          { name: 'mom_change', type: 'numeric' },
        ],
        rows: [
          ['华东', 18234500.0, -0.082],
          ['华南', 12003000.0, 0.145],
          ['华北', 9800000.0, 0.031],
        ],
        row_count: 3,
        truncated: false,
        amount_unit: 'CNY',
        terminal: false,
      },
      delayMs: 200,
    },
    {
      event: 'chart',
      data: {
        chart_type: 'bar',
        option: {
          xAxis: { type: 'category', data: ['华东', '华南', '华北'] },
          yAxis: { type: 'value', name: 'GMV（元）' },
          series: [{ type: 'bar', data: [18234500, 12003000, 9800000] }],
        },
        terminal: false,
      },
      delayMs: 60,
    },
    {
      event: 'insight',
      data: {
        text: '华东区上月 GMV 1823.45 万元，环比下降 8.2%；华南区 1200.30 万元，环比上升 14.5%。',
        caveats: ['口径：按下单支付时间、含运费、剔除已退款', '时间范围：2026-08-01 至 2026-08-31', '数据新鲜度：截至 2026-09-17 06:00'],
        citations: [{ metric: 'gmv', asset: 'v_order_paid', bundle_version: '2026.09.14.1' }],
        terminal: false,
      },
      delayMs: 80,
    },
    {
      event: 'meta',
      data: {
        bundle_version: '2026.09.14.1',
        cost_cny: 0.048,
        tokens: { input: 13820, output: 2310, cache_hit: 9100 },
        latency_ms: 4210,
        trace_id: 'tr_mock001',
        scope: { level: 'role_limited', applied: true, notice: '当前结果已按你的数据范围过滤', disclosable: true },
        terminal: false,
      },
      delayMs: 40,
    },
    { event: 'complete', data: { terminal: true }, delayMs: 40 },
  ];
}

/** 澄清（紫） */
export const clarifyFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock002', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'schema_linking', elapsed_ms: 430, terminal: false }, delayMs: 120 },
  {
    event: 'clarify',
    data: {
      clarify_id: 'cl_mock001',
      question: '你说的「城市」是指收货城市还是店铺所在城市？',
      reason: 'ambiguity',
      options: [
        { value: 'shipping_city', label: '收货城市', asset: 'v_order_paid.order_receiver_city' },
        { value: 'shop_city', label: '店铺所在城市', asset: 'v_shop.city' },
      ],
      terminal: true,
    },
    delayMs: 150,
  },
];

/** 拒答（灰）：无数据资产 */
export const refuseNoAssetFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock003', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'schema_linking', elapsed_ms: 380, terminal: false }, delayMs: 120 },
  {
    event: 'refuse',
    data: {
      reason: 'no_data_asset',
      message: '系统没有「竞品销量」相关数据资产，无法回答该问题。',
      suggestions: ['你可以试着问：本店 Top 10 商品的销量对比', '你可以试着问：同类目商品的销量分布'],
      terminal: true,
    },
    delayMs: 150,
  },
];

/** 拒答（灰）：PII */
export const refusePiiFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock004', session_id: 'ss_mock001', terminal: false } },
  {
    event: 'refuse',
    data: {
      reason: 'pii_blocked',
      message: '该问题涉及受保护的敏感字段，无法提供。',
      suggestions: ['你可以试着问：按城市汇总的订单量（不含个人信息）'],
      terminal: true,
    },
    delayMs: 150,
  },
];

/** 错误（红）：GATE_AST_REJECTED */
export const errorGateFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock005', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'sql_ready', elapsed_ms: 1900, dialect: 'postgresql', confidence: 0.62, sql: 'SELECT ...', terminal: false }, delayMs: 150 },
  {
    event: 'error',
    data: {
      code: 'GATE_AST_REJECTED',
      message: '查询被安全校验拒绝：检测到未授权的表访问。',
      detail: { violation: 'table_not_in_allowlist', table: 'raw_user_profile' },
      retryable: false,
      terminal: true,
    },
    delayMs: 150,
  },
];

/** 降级但成功（琥珀）：reduced_candidates，流继续到 complete */
export function degradedSuccessFrames(): MockFrame[] {
  const frames = successFrames('tk_mock006', 'ss_mock001');
  // 在 executing 之后插入 degraded（不终止），仍走 data→meta→complete
  const idx = frames.findIndex((f) => f.event === 'data');
  frames.splice(idx, 0, {
    event: 'degraded',
    data: { reason: 'cost_too_high', action_taken: 'reduced_candidates', terminal: false },
    delayMs: 80,
  });
  return frames;
}

/** 转异步：degraded(switched_to_async, terminal:false) → complete(terminal:true) */
export const switchedToAsyncFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_async001', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'executing', elapsed_ms: 8100, terminal: false }, delayMs: 150 },
  {
    event: 'degraded',
    data: {
      reason: 'latency_exceeded',
      action_taken: 'switched_to_async',
      terminal: false,
      task_id: 'tk_async001',
      poll_url: '/api/v1/query/tk_async001',
    },
    delayMs: 150,
  },
  { event: 'complete', data: { terminal: true }, delayMs: 60 },
];

/** 空结果 + role_limited（中性提示） */
export const emptyRoleLimitedFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock007', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'executing', elapsed_ms: 1800, terminal: false }, delayMs: 150 },
  {
    event: 'data',
    data: {
      columns: [
        { name: 'region_name', type: 'text' },
        { name: 'gmv', type: 'numeric' },
      ],
      rows: [],
      row_count: 0,
      truncated: false,
      amount_unit: 'CNY',
      terminal: false,
    },
    delayMs: 120,
  },
  {
    event: 'meta',
    data: {
      bundle_version: '2026.09.14.1',
      cost_cny: 0.021,
      latency_ms: 1900,
      trace_id: 'tr_mock007',
      scope: { level: 'role_limited', applied: true, notice: '当前结果已按你的数据范围过滤', disclosable: true },
      terminal: false,
    },
    delayMs: 60,
  },
  { event: 'complete', data: { terminal: true }, delayMs: 40 },
];

/** 空结果 + tenant_isolated（notice 必须为 null，响应与"真的没有数据"不可区分） */
export const emptyTenantIsolatedFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock008', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'executing', elapsed_ms: 1750, terminal: false }, delayMs: 150 },
  {
    event: 'data',
    data: {
      columns: [
        { name: 'region_name', type: 'text' },
        { name: 'gmv', type: 'numeric' },
      ],
      rows: [],
      row_count: 0,
      truncated: false,
      amount_unit: 'CNY',
      terminal: false,
    },
    delayMs: 120,
  },
  {
    event: 'meta',
    data: {
      bundle_version: '2026.09.14.1',
      cost_cny: 0.019,
      latency_ms: 1850,
      trace_id: 'tr_mock008',
      scope: { level: 'tenant_isolated', applied: true, notice: null, disclosable: false },
      terminal: false,
    },
    delayMs: 60,
  },
  { event: 'complete', data: { terminal: true }, delayMs: 40 },
];

/** 空结果 + unrestricted（无过滤，notice null） */
export const emptyUnrestrictedFrames: MockFrame[] = [
  { event: 'ack', data: { task_id: 'tk_mock009', session_id: 'ss_mock001', terminal: false } },
  { event: 'stage', data: { stage: 'executing', elapsed_ms: 1600, terminal: false }, delayMs: 150 },
  {
    event: 'data',
    data: {
      columns: [{ name: 'gmv', type: 'numeric' }],
      rows: [],
      row_count: 0,
      truncated: false,
      amount_unit: 'CNY',
      terminal: false,
    },
    delayMs: 120,
  },
  {
    event: 'meta',
    data: {
      bundle_version: '2026.09.14.1',
      cost_cny: 0.018,
      latency_ms: 1700,
      trace_id: 'tr_mock009',
      scope: { level: 'unrestricted', applied: false, notice: null, disclosable: true },
      terminal: false,
    },
    delayMs: 60,
  },
  { event: 'complete', data: { terminal: true }, delayMs: 40 },
];

/** 异步任务轮询载荷（GET /query/{task_id}） */
export const asyncTaskProcessing = {
  code: 'OK',
  message: 'success',
  trace_id: 'tr_async001',
  server_time: NOW,
  data: {
    task_id: 'tk_async001',
    status: 'processing',
    stage: 'executing',
    queued_at: NOW,
    started_at: NOW,
    progress: 0.7,
  },
};

export const asyncTaskComplete = {
  code: 'OK',
  message: 'success',
  trace_id: 'tr_async001',
  server_time: NOW,
  data: {
    task_id: 'tk_async001',
    status: 'complete',
    queued_at: NOW,
    started_at: NOW,
    sql: SQL_TEXT,
    data: {
      columns: [
        { name: 'region_name', type: 'text' },
        { name: 'gmv', type: 'numeric' },
      ],
      rows: [
        ['华东', 18234500.0],
        ['华南', 12003000.0],
      ],
      row_count: 2,
      truncated: false,
      amount_unit: 'CNY',
    },
    chart: {
      chart_type: 'bar',
      option: {
        xAxis: { type: 'category', data: ['华东', '华南'] },
        yAxis: { type: 'value', name: 'GMV（元）' },
        series: [{ type: 'bar', data: [18234500, 12003000] }],
      },
    },
    insight: {
      text: '华东区 GMV 1823.45 万元，华南区 1200.30 万元。',
      caveats: ['口径：按下单支付时间、含运费、剔除已退款'],
      citations: [{ metric: 'gmv', asset: 'v_order_paid', bundle_version: '2026.09.14.1' }],
    },
    meta: {
      bundle_version: '2026.09.14.1',
      cost_cny: 0.052,
      latency_ms: 21000,
      trace_id: 'tr_async001',
      scope: { level: 'unrestricted', applied: false, notice: null, disclosable: true },
    },
    audit_ref: 'audit_mock001',
  },
};

/** 场景选择：question 关键词 → 场景名（与 scenarios.md 一一对应） */
export function pickScenario(question: string, headerScenario?: string | null): string {
  if (headerScenario) return headerScenario;
  if (question.includes('竞品')) return 'refuse_no_data_asset';
  if (question.includes('手机号') || question.includes('身份证')) return 'refuse_pii';
  if (question.includes('城市')) return 'clarify';
  if (question.includes('非法表')) return 'error_gate_ast';
  if (question.includes('降级')) return 'degraded_success';
  if (question.includes('转异步') || question.includes('慢查询')) return 'switched_to_async';
  if (question.includes('409')) return 'session_conflict';
  if (question.includes('429')) return 'rate_limited';
  if (question.includes('空结果')) return 'empty_role_limited';
  if (question.includes('跨租户')) return 'empty_tenant_isolated';
  if (question.includes('无限制空')) return 'empty_unrestricted';
  return 'success';
}
