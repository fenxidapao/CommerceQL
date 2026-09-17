/**
 * MSW handlers（仅供开发/测试；生产构建通过动态 import + DEV 门控排除）
 * 覆盖端点严格限于附录A契约；不 mock 契约外端点。
 */
import { http, HttpResponse } from 'msw';
import { sseStream, SSE_HEADERS } from './sse';
import {
  asyncTaskComplete,
  asyncTaskProcessing,
  clarifyFrames,
  degradedSuccessFrames,
  emptyRoleLimitedFrames,
  emptyTenantIsolatedFrames,
  emptyUnrestrictedFrames,
  errorGateFrames,
  pickScenario,
  refuseNoAssetFrames,
  refusePiiFrames,
  successFrames,
  switchedToAsyncFrames,
} from './fixtures';

const NOW = '2026-09-17T10:30:00+08:00';

function envelope<T>(data: T, code = 'OK', message = 'success') {
  return { code, message, trace_id: 'tr_mock_http', data, server_time: NOW };
}

/** 查询类限流头（喂 QuotaIndicator） */
const QUERY_RATE_HEADERS = {
  'X-RateLimit-Bucket': 'query',
  'X-RateLimit-Limit': '10',
  'X-RateLimit-Remaining': '7',
  'X-RateLimit-Reset': String(Math.floor(Date.now() / 1000) + 60),
};

/** 异步轮询计数：第 1 次 processing，第 2 次起 complete */
const pollCount = new Map<string, number>();

export function resetMockState() {
  pollCount.clear();
}

export const handlers = [
  // ---- A.1 POST /query（SSE） ----
  http.post('*/api/v1/query', async ({ request }) => {
    const body = (await request.json()) as { question?: string };
    const scenario = pickScenario(body.question ?? '', request.headers.get('X-Mock-Scenario'));

    if (scenario === 'session_conflict') {
      // 409 SESSION_CONFLICT：Retry-After: 3，**不返回** X-RateLimit-*
      return HttpResponse.json(
        { code: 'SESSION_CONFLICT', message: '该会话正在处理上一个问题，请稍候', trace_id: 'tr_mock409', server_time: NOW },
        { status: 409, headers: { 'Retry-After': '3' } },
      );
    }
    if (scenario === 'rate_limited') {
      return HttpResponse.json(
        { code: 'RATE_LIMITED', message: '查询类配额超限', trace_id: 'tr_mock429', server_time: NOW },
        {
          status: 429,
          headers: {
            'Retry-After': '30',
            'X-RateLimit-Bucket': 'query',
            'X-RateLimit-Limit': '10',
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': String(Math.floor(Date.now() / 1000) + 30),
          },
        },
      );
    }

    const frames =
      scenario === 'clarify'
        ? clarifyFrames
        : scenario === 'refuse_no_data_asset'
          ? refuseNoAssetFrames
          : scenario === 'refuse_pii'
            ? refusePiiFrames
            : scenario === 'error_gate_ast'
              ? errorGateFrames
              : scenario === 'degraded_success'
                ? degradedSuccessFrames()
                : scenario === 'switched_to_async'
                  ? switchedToAsyncFrames
                  : scenario === 'empty_role_limited'
                    ? emptyRoleLimitedFrames
                    : scenario === 'empty_tenant_isolated'
                      ? emptyTenantIsolatedFrames
                      : scenario === 'empty_unrestricted'
                        ? emptyUnrestrictedFrames
                        : successFrames();

    return new HttpResponse(sseStream(frames), {
      status: 200,
      headers: { ...SSE_HEADERS, ...QUERY_RATE_HEADERS },
    });
  }),

  // ---- A.4 POST /clarify（SSE，澄清后继续走完成功链路） ----
  http.post('*/api/v1/clarify', async () => {
    return new HttpResponse(sseStream(successFrames('tk_mock_clarified', 'ss_mock001')), {
      status: 200,
      headers: { ...SSE_HEADERS, ...QUERY_RATE_HEADERS },
    });
  }),

  // ---- A.2 GET /query/{task_id} 异步轮询 ----
  http.get('*/api/v1/query/:taskId', ({ params }) => {
    const taskId = String(params.taskId);
    const n = (pollCount.get(taskId) ?? 0) + 1;
    pollCount.set(taskId, n);
    const payload = n < 2 ? asyncTaskProcessing : asyncTaskComplete;
    return HttpResponse.json({ ...payload, data: { ...payload.data, task_id: taskId } });
  }),

  // ---- A.3 POST /query/{task_id}/cancel ----
  http.post('*/api/v1/query/:taskId/cancel', ({ params }) => {
    return HttpResponse.json(envelope({ task_id: String(params.taskId), status: 'cancelled' }));
  }),

  // ---- A.5 会话管理 ----
  http.post('*/api/v1/session', () => {
    return HttpResponse.json(envelope({ session_id: 'ss_mock001', created_at: NOW }));
  }),

  http.get('*/api/v1/sessions', () => {
    return HttpResponse.json(
      envelope({
        items: [
          {
            session_id: 'ss_mock001',
            title: '上个月华东区GMV环比',
            turn_count: 3,
            last_turn_at: NOW,
            created_at: NOW,
            last_bundle_version: '2026.09.14.1',
          },
          {
            session_id: 'ss_mock002',
            title: '近7天各渠道转化率',
            turn_count: 1,
            last_turn_at: '2026-09-16T18:02:11+08:00',
            created_at: '2026-09-16T18:00:00+08:00',
            last_bundle_version: '2026.09.14.1',
          },
        ],
        total: 2,
        limit: 20,
        offset: 0,
        has_more: false,
      }),
    );
  }),

  http.get('*/api/v1/session/:sessionId', ({ params }) => {
    return HttpResponse.json(
      envelope({
        session_id: String(params.sessionId),
        turns: [
          {
            task_id: 'tk_mock001',
            question: '上个月华东区GMV是多少，环比怎么样',
            outcome: 'success',
            plan_summary: {
              metrics: ['gmv'],
              dimensions: ['region'],
              time_range: { start: '2026-08-01', end: '2026-08-31' },
              compare: 'mom',
              bundle_version: '2026.09.14.1',
            },
            at: NOW,
          },
        ],
        context_cursor: 'tu_1',
      }),
    );
  }),

  http.delete('*/api/v1/session/:sessionId', ({ params }) => {
    return HttpResponse.json(envelope({ session_id: String(params.sessionId), closed: true }));
  }),

  // ---- A.6 feedback ----
  http.post('*/api/v1/feedback', () => {
    return HttpResponse.json(envelope({ feedback_id: 'fb_mock001', queued_for_review: true }));
  }),

  // ---- A.7 语义层 ----
  http.get('*/api/v1/semantic/metrics', () => {
    return HttpResponse.json(
      envelope({
        items: [
          {
            name: 'gmv',
            display_name: 'GMV',
            expression: 'SUM(pay_amount)',
            default_aggregation: 'sum',
            unit: 'CNY',
            owner: 'finance@tenant',
            domain: 'orders',
            definition_note: '按下单支付时间统计；含运费；剔除已退款订单',
            default_predicates: ["o.pay_status = 'paid'", "o.refund_status <> 'refunded'", 'o.is_test_order = false'],
            synonyms: ['成交额', '销售额', '交易额', 'GMV', 'gmv'],
            bundle_version: '2026.09.14.1',
            updated_at: '2026-09-14T10:00:00+08:00',
          },
          {
            name: 'paid_order_cnt',
            display_name: '支付订单量',
            expression: 'COUNT(DISTINCT order_id)',
            default_aggregation: 'count',
            unit: '单',
            owner: 'ops@tenant',
            domain: 'orders',
            definition_note: '按下单支付时间统计；剔除已退款订单',
            default_predicates: ["o.pay_status = 'paid'", "o.refund_status <> 'refunded'"],
            synonyms: ['订单量', '单量', '支付单数'],
            bundle_version: '2026.09.14.1',
            updated_at: '2026-09-14T10:00:00+08:00',
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
    );
  }),

  http.get('*/api/v1/semantic/assets', () => {
    return HttpResponse.json(
      envelope({
        items: [
          {
            logical_name: 'order_paid',
            physical_asset: 'v_order_paid',
            grain: 'sub_order',
            freshness_sla: 'PT6H',
            owner: 'data-team@tenant',
            certified: true,
            domain: 'orders',
            column_count: 28,
            denied_columns: ['receiver_phone', 'receiver_address'],
          },
          {
            logical_name: 'shop',
            physical_asset: 'v_shop',
            grain: 'shop',
            freshness_sla: 'P1D',
            owner: 'data-team@tenant',
            certified: true,
            domain: 'shops',
            column_count: 15,
            denied_columns: [],
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
    );
  }),

  // ---- A.8.4 GET /healthz（前端健康点只调这个） ----
  http.get('*/api/v1/healthz', () => {
    return HttpResponse.json({
      status: 'ok',
      checks: {
        graph_compiled: true,
        metadata_db: true,
        checkpointer_reachable: true,
        redis_reachable: true,
        semantic_bundle_loaded: true,
        llm_reachable: true,
        embedding_reachable: true,
        embedding_model: 'bge-m3',
        embedding_dim: 1024,
      },
      degraded_dependencies: [],
      bundle_version: '2026.09.14.1',
      version: '1.0.0',
    });
  }),

  // ---- A.9 管理端点（评测） ----
  http.get('*/api/v1/admin/eval/datasets', () => {
    return HttpResponse.json(
      envelope({
        items: [
          {
            dataset_id: 'ds_v1_frozen',
            version: 'v1',
            frozen_at: '2026-09-14T10:00:00+08:00',
            case_count: 150,
            content_hash: 'sha256:9f2caa01',
            purpose: '主验收（双维度 4×3 分层）',
            status: 'frozen',
          },
          {
            dataset_id: 'ds_v2_draft',
            version: 'v2',
            frozen_at: '2026-09-16T09:00:00+08:00',
            case_count: 60,
            content_hash: 'sha256:ab77c3d2',
            purpose: '增量回归（草稿）',
            status: 'draft',
          },
        ],
        total: 2,
      }),
    );
  }),

  http.get('*/api/v1/admin/eval/runs', () => {
    return HttpResponse.json(
      envelope({
        items: [
          {
            run_id: 'run_mock001',
            dataset_id: 'ds_v1_frozen',
            model: 'deepseek-flash',
            prompt_version: 'gen_sql_v7',
            bundle_version: '2026.09.14.1',
            status: 'complete',
            gate_passed: false,
            started_at: '2026-09-14T16:00:00+08:00',
            ended_at: '2026-09-14T16:12:31+08:00',
            headline: {
              ex: 0.812,
              refusal_true_positive_rate: 0.96,
              dangerous_sql_passed: 0,
              cross_tenant_leaks: 0,
              p95_latency_ms: 6800,
              cost_total_cny: 12.4,
            },
            note: '回归：新增同义词表后',
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
      }),
    );
  }),

  http.get('*/api/v1/admin/eval/runs/:runId', () => {
    return HttpResponse.json(
      envelope({
        run: {
          run_id: 'run_mock001',
          dataset_id: 'ds_v1_frozen',
          dataset_content_hash: 'sha256:9f2caa01',
          model: 'deepseek-flash',
          prompt_version: 'gen_sql_v7',
          bundle_version: '2026.09.14.1',
          status: 'complete',
          started_at: '2026-09-14T16:00:00+08:00',
          ended_at: '2026-09-14T16:12:31+08:00',
        },
        scope: 'cross_tenant',
        overall: {
          ex: 0.812,
          refusal: { true_positive_rate: 0.96, false_positive_rate: 0.04, reason_accuracy: 0.93 },
          clarify: { trigger_accuracy: 0.91, post_clarify_accuracy: 0.82, avg_rounds: 1.1 },
          consistency: { rate: 0.95, attributable_rate: 1.0 },
          efficiency: { seq_scan_rate: 0.04, cartesian_count: 0, p95_exec_ms: 2100 },
          security: { dangerous_sql_passed: 0, cross_tenant_leaks: 0, pii_leaks: 0 },
          latency: { p50_ms: 3900, p95_ms: 6800 },
          cost: { total_cny: 12.4, per_query_cny: 0.048, cache_hit_rate: 0.63 },
        },
        grid: {
          axes: {
            struct: ['easy', 'medium', 'hard', 'extra_hard'],
            semantic: ['low', 'medium', 'high'],
          },
          cells: [
            { struct: 'easy', semantic: 'low', total: 12, passed: 12, ex: 1.0, target: 0.95, verdict: 'pass' },
            { struct: 'easy', semantic: 'medium', total: 11, passed: 10, ex: 0.909, target: 0.9, verdict: 'pass' },
            { struct: 'easy', semantic: 'high', total: 10, passed: 8, ex: 0.8, target: 0.8, verdict: 'pass' },
            { struct: 'medium', semantic: 'low', total: 12, passed: 11, ex: 0.917, target: 0.9, verdict: 'pass' },
            { struct: 'medium', semantic: 'medium', total: 12, passed: 10, ex: 0.833, target: 0.8, verdict: 'pass' },
            { struct: 'medium', semantic: 'high', total: 11, passed: 8, ex: 0.727, target: 0.7, verdict: 'pass' },
            { struct: 'hard', semantic: 'low', total: 11, passed: 9, ex: 0.818, target: 0.8, verdict: 'pass' },
            { struct: 'hard', semantic: 'medium', total: 10, passed: 7, ex: 0.7, target: 0.7, verdict: 'pass' },
            { struct: 'hard', semantic: 'high', total: 9, passed: 5, ex: 0.556, target: 0.6, verdict: 'fail' },
            { struct: 'extra_hard', semantic: 'low', total: 9, passed: 6, ex: 0.667, target: 0.6, verdict: 'pass' },
            { struct: 'extra_hard', semantic: 'medium', total: 8, passed: 4, ex: 0.5, target: 0.5, verdict: 'pass' },
            { struct: 'extra_hard', semantic: 'high', total: 7, passed: 3, ex: 0.429, target: 0.4, verdict: 'pass' },
          ],
        },
        attribution: [
          { category: 'schema_linking_miss', count: 9, ratio: 0.31 },
          { category: 'metric_definition', count: 6, ratio: 0.21 },
          { category: 'time_semantics', count: 5, ratio: 0.17 },
          { category: 'sql_generation', count: 4, ratio: 0.14 },
          { category: 'over_refusal', count: 3, ratio: 0.1 },
          { category: 'other', count: 2, ratio: 0.07 },
        ],
        gate: {
          passed: false,
          items: [
            { id: 'G-1', name: '全部 P0 用例通过', verdict: 'fail', detail: '3 条未过' },
            { id: 'G-2', name: 'Easy×低语义 ≥ 95%', verdict: 'pass' },
            { id: 'G-3', name: '危险 SQL 放行 = 0', verdict: 'pass' },
            { id: 'G-4', name: '跨租户泄露 = 0', verdict: 'pass' },
            { id: 'G-5', name: '拒答准确率 ≥ 95%', verdict: 'pass' },
            { id: 'G-6', name: 'P95 延迟 ≤ 8s', verdict: 'pass' },
            { id: 'G-7', name: '口径一致性 ≥ 95%', verdict: 'pass' },
          ],
        },
      }),
    );
  }),

  http.post('*/api/v1/admin/eval/run', () => {
    return HttpResponse.json(envelope({ run_id: 'run_mock002', status: 'queued' }));
  }),
];
