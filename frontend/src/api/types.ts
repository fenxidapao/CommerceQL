/**
 * CommerceQL 前端契约类型
 * 规范源：docs/02_附录A_接口契约详解.md（v1.5，唯一契约源）
 * 枚举值与 backend/app/core/enums.py 逐字对齐。
 * ⚠️ 前端只有渲染权，任何字段不得在前端"推断/聚合"产生。
 */

// ---------------------------------------------------------------------------
// 枚举（逐字对齐 enums.py / 附录A）
// ---------------------------------------------------------------------------

/** 处理阶段（附录A A.1.2，6 个值） */
export type Stage =
  | 'intent'
  | 'schema_linking'
  | 'plan_ready'
  | 'sql_ready'
  | 'gate_passed'
  | 'executing';

/** SSE 事件类型（12 个） */
export type SseEventType =
  | 'ack'
  | 'stage'
  | 'data'
  | 'chart'
  | 'insight'
  | 'meta'
  | 'degraded'
  | 'complete'
  | 'clarify'
  | 'refuse'
  | 'error'
  | 'heartbeat';

/** 错误码（附录A A.11，共 28 个） */
export type ErrorCode =
  | 'OK'
  | 'INVALID_REQUEST'
  | 'AUTH_FAILED'
  | 'TOKEN_REVOKED'
  | 'FORBIDDEN_SCOPE'
  | 'PII_BLOCKED'
  | 'TASK_NOT_FOUND'
  | 'SESSION_NOT_FOUND'
  | 'RUN_NOT_FOUND'
  | 'DATASET_NOT_FOUND'
  | 'AMBIGUOUS_QUERY'
  | 'TASK_NOT_CANCELLABLE'
  | 'IDEMPOTENCY_CONFLICT'
  | 'SESSION_CONFLICT'
  | 'CLARIFY_EXPIRED'
  | 'CLARIFY_INVALID_OPTION'
  | 'GATE_AST_REJECTED'
  | 'GATE_POLICY_REJECTED'
  | 'COST_TOO_HIGH'
  | 'EXEC_RESOURCE_EXCEEDED'
  | 'NO_DATA_ASSET'
  | 'SQL_SYNTAX_ERROR'
  | 'RATE_LIMITED'
  | 'INTERNAL'
  | 'LLM_UPSTREAM_ERROR'
  | 'LLM_CONCURRENCY_EXCEEDED'
  | 'DB_UNAVAILABLE'
  | 'EXEC_TIMEOUT';

/** 轮次结果（Outcome，5 个） */
export type Outcome = 'success' | 'clarify' | 'refuse' | 'degraded' | 'failed';

/**
 * 异步任务状态（附录A A.2 规范源）。
 * ⚠️ 注意：enums.py 的 TaskStatus 值集（pending/running/succeeded/...）与
 * 附录A A.2（queued/processing/complete/...）不一致，前端以附录A为准，
 * 差异已在 RELAY.md 登记给上游。
 */
export type AsyncTaskStatus =
  | 'queued'
  | 'processing'
  | 'complete'
  | 'clarify'
  | 'refused'
  | 'failed'
  | 'cancelled'
  | 'degraded';

/** 拒答原因（4 个） */
export type RefuseReason = 'no_data_asset' | 'out_of_scope' | 'pii_blocked' | 'open_analysis';

/** 澄清原因（2 个；附录A示例中出现的 ambiguous_field_binding 归入 ambiguity） */
export type ClarifyReason = 'time_ambiguous' | 'ambiguity';

/** 降级原因（8 个） */
export type DegradedReason =
  | 'cost_too_high'
  | 'llm_unavailable'
  | 'llm_concurrency_exceeded'
  | 'latency_exceeded'
  | 'embedding_unavailable'
  | 'plan_generation_failed'
  | 'present_failed'
  | 'cache_fallback';

/** 降级处置动作（7 个） */
export type ActionTaken =
  | 'reduced_candidates'
  | 'switched_to_weak_model'
  | 'used_cache'
  | 'switched_to_async'
  | 'sparse_only'
  | 'template_only'
  | 'table_only';

/** 检索模式（2 个） */
export type RetrievalMode = 'hybrid' | 'sparse_only';

/** 图表类型（7 个） */
export type ChartType = 'line' | 'bar' | 'stacked_bar' | 'grouped_bar' | 'pie' | 'kpi' | 'table';

/** 图表偏好（A.1.1，8 个；与 ChartType 不得合并） */
export type ChartPreference =
  | 'auto'
  | 'line'
  | 'bar'
  | 'stacked_bar'
  | 'pie'
  | 'table'
  | 'kpi'
  | 'none';

/** 数据范围披露级别（A.1.5，3 个） */
export type ScopeLevel = 'tenant_isolated' | 'role_limited' | 'unrestricted';

/** 角色（A.0.2，7 个） */
export type Role =
  | 'platform_admin'
  | 'shop_owner'
  | 'operator'
  | 'marketer'
  | 'finance'
  | 'support'
  | 'analyst';

/** 健康状态（A.8.4，3 个） */
export type HealthStatus = 'ok' | 'degraded' | 'unhealthy';

/** feedback reason_code（A.6，10 个） */
export type FeedbackReasonCode =
  | 'wrong_metric_definition'
  | 'wrong_time_range'
  | 'wrong_dimension'
  | 'missing_synonym'
  | 'wrong_join'
  | 'wrong_aggregation'
  | 'missing_default_filter'
  | 'permission_issue'
  | 'data_quality'
  | 'other';

/** 评测集状态（A.9.2） */
export type DatasetStatus = 'frozen' | 'draft';

/** 评测运行状态（A.9.3） */
export type EvalRunStatus = 'queued' | 'running' | 'complete' | 'failed';

/** 评测网格 verdict（A.9.4） */
export type GridVerdict = 'pass' | 'fail';

/** 评测难度轴取值（A.9.4） */
export type DifficultyStruct = 'easy' | 'medium' | 'hard' | 'extra_hard';
export type DifficultySemantic = 'low' | 'medium' | 'high';

/** 限流桶（A.0.6，4 个） */
export type RateLimitBucket = 'query' | 'read' | 'write' | 'admin';

// ---------------------------------------------------------------------------
// A.0 通用结构
// ---------------------------------------------------------------------------

/** 通用响应包裹（A.0.4） */
export interface ApiEnvelope<T> {
  code: ErrorCode;
  message: string;
  trace_id: string;
  data: T;
  server_time: string;
}

/** 分页数据（A.0.5） */
export interface Paged<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** 限流响应头解析结果（A.0.6）；bucket 非 'query' 时不得喂 QuotaIndicator */
export interface RateLimitInfo {
  bucket: RateLimitBucket | string;
  limit: number;
  remaining: number;
  /** epoch 秒 */
  reset: number;
}

// ---------------------------------------------------------------------------
// A.1 POST /query（SSE）
// ---------------------------------------------------------------------------

export interface QueryOptions {
  max_candidates?: number;
  allow_clarify?: boolean;
  chart_preference?: ChartPreference;
  timezone?: string;
  explain?: boolean;
  max_rows?: number;
  async_if_slow?: boolean;
  async_threshold_ms?: number;
}

export interface QueryRequest {
  question: string;
  session_id?: string | null;
  options?: QueryOptions;
}

export interface PlanSummary {
  metrics: string[];
  dimensions: string[];
  time_range?: { start: string; end: string };
  compare?: string | null;
  bundle_version?: string;
}

export interface GateDetail {
  ast: string;
  policy: string;
  cost?: { est_rows: number; verdict: string };
}

export interface ScopeInfo {
  level: ScopeLevel;
  applied: boolean;
  /** tenant_isolated 时必须为 null（A.1.5 红线3） */
  notice: string | null;
  disclosable: boolean;
}

export interface ColumnDef {
  name: string;
  type: string;
}

export interface Citation {
  metric: string;
  asset: string;
  bundle_version: string;
}

export interface ClarifyOption {
  value: string;
  label: string;
  asset?: string;
}

// ---- SSE 各事件 data 载荷（均含 terminal；缺失视为 false + 告警，A.1.4） ----

interface SseBase {
  /** 唯一流终止判据。缺失按 false 处理并告警 */
  terminal?: boolean;
}

export interface AckData extends SseBase {
  task_id: string;
  session_id: string;
}

export interface StageData extends SseBase {
  stage: Stage;
  elapsed_ms: number;
  candidates_count?: number;
  plan_summary?: PlanSummary;
  sql?: string;
  dialect?: string;
  confidence?: number;
  gate_detail?: GateDetail;
}

export interface DataEvent extends SseBase {
  columns: ColumnDef[];
  rows: unknown[][];
  row_count: number;
  /** 仅表示因 LIMIT 截断，与 RLS 过滤无关（A.1.5 红线2） */
  truncated: boolean;
  amount_unit?: string;
}

export interface ChartEvent extends SseBase {
  chart_type: ChartType;
  /** 受约束的 ECharts option 子集（A.10），前端仅渲染 */
  option: Record<string, unknown>;
  version?: string;
  meta?: {
    metric?: string;
    unit?: string;
    time_range?: { start: string; end: string };
    truncated?: boolean;
    row_count?: number;
  };
}

export interface InsightEvent extends SseBase {
  text: string;
  caveats: string[];
  citations: Citation[];
}

export interface MetaEvent extends SseBase {
  bundle_version: string;
  cost_cny?: number;
  tokens?: { input: number; output: number; cache_hit?: number };
  latency_ms: number;
  trace_id: string;
  scope: ScopeInfo;
}

export interface DegradedEvent extends SseBase {
  reason: DegradedReason;
  action_taken: ActionTaken;
  /** action_taken=switched_to_async 时必带 */
  task_id?: string;
  poll_url?: string;
  partial_result?: unknown;
}

export interface CompleteData extends SseBase {
  terminal: true;
}

export interface ClarifyEvent extends SseBase {
  clarify_id: string;
  question: string;
  options: ClarifyOption[];
  reason: ClarifyReason | string;
}

export interface RefuseEvent extends SseBase {
  reason: RefuseReason;
  message: string;
  suggestions: string[];
}

export interface ErrorEvent extends SseBase {
  code: ErrorCode;
  message: string;
  detail?: Record<string, unknown>;
  retryable: boolean;
}

export type HeartbeatData = SseBase;

/** 判别联合：按 event 类型分发 data 载荷 */
export type SseEvent =
  | { event: 'ack'; data: AckData }
  | { event: 'stage'; data: StageData }
  | { event: 'data'; data: DataEvent }
  | { event: 'chart'; data: ChartEvent }
  | { event: 'insight'; data: InsightEvent }
  | { event: 'meta'; data: MetaEvent }
  | { event: 'degraded'; data: DegradedEvent }
  | { event: 'complete'; data: CompleteData }
  | { event: 'clarify'; data: ClarifyEvent }
  | { event: 'refuse'; data: RefuseEvent }
  | { event: 'error'; data: ErrorEvent }
  | { event: 'heartbeat'; data: HeartbeatData };

// ---------------------------------------------------------------------------
// A.2 异步任务状态
// ---------------------------------------------------------------------------

export interface AsyncTaskResult {
  task_id: string;
  status: AsyncTaskStatus;
  stage?: Stage;
  queued_at?: string;
  started_at?: string;
  progress?: number;
  /** status=complete 时与 SSE 的 data/chart/insight/meta 同构 */
  sql?: string;
  data?: DataEvent;
  chart?: ChartEvent;
  insight?: InsightEvent;
  meta?: MetaEvent;
  audit_ref?: string;
}

// ---------------------------------------------------------------------------
// A.4 POST /clarify
// ---------------------------------------------------------------------------

export interface ClarifyRequest {
  clarify_id: string;
  selected_value?: string | null;
  free_text?: string | null;
}

// ---------------------------------------------------------------------------
// A.5 会话管理
// ---------------------------------------------------------------------------

export interface SessionTurn {
  task_id: string;
  question: string;
  outcome: Outcome;
  /** 只返回计划摘要，不返回原始 SQL（PRD FR-10.1） */
  plan_summary: PlanSummary;
  at: string;
}

export interface SessionDetail {
  session_id: string;
  turns: SessionTurn[];
  context_cursor: string;
}

export interface SessionListItem {
  session_id: string;
  /** 服务端生成，客户端不可写（B-19） */
  title: string;
  turn_count: number;
  last_turn_at: string;
  created_at: string;
  last_bundle_version: string;
}

// ---------------------------------------------------------------------------
// A.6 feedback
// ---------------------------------------------------------------------------

export interface FeedbackRequest {
  task_id: string;
  is_correct: boolean;
  reason_code?: FeedbackReasonCode;
  comment?: string;
  corrected_sql?: string;
  correct_result_hint?: string;
}

export interface FeedbackResponse {
  feedback_id: string;
  queued_for_review: boolean;
}

// ---------------------------------------------------------------------------
// A.7 语义层
// ---------------------------------------------------------------------------

export interface MetricItem {
  name: string;
  display_name: string;
  expression: string;
  default_aggregation: string;
  unit: string;
  owner: string;
  domain: string;
  definition_note: string;
  default_predicates: string[];
  synonyms: string[];
  bundle_version: string;
  updated_at: string;
}

export interface SemanticAsset {
  logical_name: string;
  physical_asset: string;
  grain: string;
  freshness_sla: string;
  owner: string;
  certified: boolean;
  domain: string;
  column_count: number;
  /** ⚠️ 口径字典页不得展示本字段（权限边界） */
  denied_columns?: string[];
}

// ---------------------------------------------------------------------------
// A.8 健康检查（前端只调 GET /healthz，B-23）
// ---------------------------------------------------------------------------

export interface HealthzResponse {
  status: HealthStatus;
  checks: {
    graph_compiled?: boolean;
    metadata_db?: boolean;
    checkpointer_reachable?: boolean;
    redis_reachable?: boolean;
    semantic_bundle_loaded?: boolean;
    llm_reachable?: boolean;
    embedding_reachable?: boolean;
    embedding_model?: string;
    embedding_dim?: number;
  };
  degraded_dependencies: string[];
  bundle_version: string;
  version: string;
}

// ---------------------------------------------------------------------------
// A.9 管理端点（评测）
// ---------------------------------------------------------------------------

export interface EvalRunRequest {
  dataset_id: string;
  model: string;
  prompt_version: string;
  bundle_version: string;
  note?: string;
}

export interface EvalDataset {
  dataset_id: string;
  version: string;
  frozen_at: string;
  case_count: number;
  content_hash: string;
  purpose: string;
  /** draft 评测集不得作为门禁依据，前端置灰 */
  status: DatasetStatus;
}

export interface EvalHeadline {
  ex: number;
  refusal_true_positive_rate: number;
  dangerous_sql_passed: number;
  cross_tenant_leaks: number;
  p95_latency_ms: number;
  cost_total_cny: number;
}

export interface EvalRunListItem {
  run_id: string;
  dataset_id: string;
  model: string;
  prompt_version: string;
  bundle_version: string;
  status: EvalRunStatus;
  gate_passed: boolean;
  started_at: string;
  ended_at?: string;
  headline?: EvalHeadline;
  note?: string;
}

export interface GridCell {
  struct: DifficultyStruct;
  semantic: DifficultySemantic;
  total: number;
  passed: number;
  ex: number;
  target: number;
  verdict: GridVerdict;
}

export interface AttributionItem {
  category: string;
  count: number;
  ratio: number;
}

export interface GateItem {
  id: string;
  name: string;
  verdict: GridVerdict;
  detail?: string;
}

export interface EvalCase {
  case_id: string;
  question: string;
  difficulty_struct: DifficultyStruct;
  difficulty_semantic: DifficultySemantic;
  expected_behavior: string;
  actual_behavior: string;
  result_equivalent: boolean;
  attribution?: string;
  latency_ms: number;
  cost_cny: number;
}

/** A.9.4 聚合部分：grid/attribution/gate 均由后端聚合，前端零聚合代码 */
export interface EvalRunDetail {
  run: {
    run_id: string;
    dataset_id: string;
    dataset_content_hash: string;
    model: string;
    prompt_version: string;
    bundle_version: string;
    status: EvalRunStatus;
    started_at: string;
    ended_at?: string;
  };
  /** 平台管理员跨租户视角时显式标注 */
  scope?: 'cross_tenant';
  overall: {
    ex: number;
    refusal: { true_positive_rate: number; false_positive_rate: number; reason_accuracy: number };
    clarify: { trigger_accuracy: number; post_clarify_accuracy: number; avg_rounds: number };
    consistency: { rate: number; attributable_rate: number };
    efficiency: { seq_scan_rate: number; cartesian_count: number; p95_exec_ms: number };
    security: { dangerous_sql_passed: number; cross_tenant_leaks: number; pii_leaks: number };
    latency: { p50_ms: number; p95_ms: number };
    cost: { total_cny: number; per_query_cny: number; cache_hit_rate: number };
  };
  grid: {
    axes: { struct: DifficultyStruct[]; semantic: DifficultySemantic[] };
    cells: GridCell[];
  };
  attribution: AttributionItem[];
  gate: { passed: boolean; items: GateItem[] };
  /** include_cases=true 时才返回；不返回 gold_sql / predicted_sql */
  cases?: Paged<EvalCase>;
}

// ---------------------------------------------------------------------------
// 环境变量（import.meta.env，VITE_* 禁放密钥）
// ---------------------------------------------------------------------------

export interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_APP_ENV: 'dev' | 'development' | 'staging' | 'production';
  readonly VITE_ENABLE_DEBUG_PANEL?: string;
  readonly VITE_ENABLE_MSW?: string;
}
