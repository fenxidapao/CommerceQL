/**
 * 会话流状态（zustand）——06 §2.4「全局状态与局部状态的划分」
 * - 只存放"流内事件累积出的渲染数据"，不做任何业务推断/聚合
 * - 每个 SSE 事件按类型写入当前轮次；terminal 判定由 queryStream 负责（此处只落 UI 状态）
 */
import { create } from 'zustand';
import type {
  ChartEvent,
  ClarifyEvent,
  DataEvent,
  DegradedEvent,
  ErrorEvent,
  InsightEvent,
  MetaEvent,
  PlanSummary,
  RateLimitInfo,
  RefuseEvent,
  SessionTurn,
  SseEvent,
  Stage,
} from '../api/types';

export type TurnOutcome =
  | 'running'
  | 'done'
  | 'stopped'
  | 'clarify'
  | 'refuse'
  | 'failed'
  | 'async_pending';

export interface Turn {
  key: string;
  question: string;
  outcome: TurnOutcome;
  taskId?: string;
  sessionId?: string;
  stages: Stage[];
  elapsedMsList: number[];
  planSummary?: PlanSummary;
  sql?: string;
  dialect?: string;
  /** 收到 stage=sql_ready 的时刻（埋点 ui_sql_shown） */
  sqlShownAt?: number;
  /** 收到 data 的时刻（埋点 ui_data_shown，与 sqlShownAt 之差用于自查代理缓冲） */
  dataShownAt?: number;
  data?: DataEvent;
  chart?: ChartEvent;
  insight?: InsightEvent;
  meta?: MetaEvent;
  degraded?: DegradedEvent;
  clarify?: ClarifyEvent;
  /** 收到 clarify 事件的时刻（事件本身无时间戳；有效期由此 +5min 推导，仅用于倒计时展示） */
  clarifyReceivedAt?: number;
  refuse?: RefuseEvent;
  error?: ErrorEvent;
  /** 传输层错误（非契约错误码） */
  transportError?: string;
  /** 澄清后重新执行的次数（复用同一条 StageBar，追加而非新建） */
  clarifyCount: number;
  /** 转异步后轮询拿到的结果：结果块顶部保留一条降级条 */
  fromAsync?: boolean;
  startedAt: number;
  /** 最后一次收到任意事件（含心跳）的时刻，供"5s 静默"软提示使用 */
  lastEventAt?: number;
}

interface ChatState {
  sessionId: string | null;
  /** GET /session/{id} 返回的历史轮次（**只有计划摘要**，不得本地伪造完整结果） */
  historyTurns: SessionTurn[];
  sessionLoading: boolean;
  sessionMissing: boolean;
  turns: Turn[];
  streaming: boolean;
  rateLimit: RateLimitInfo | null;
  activeKey: string | null;

  setSessionId: (id: string | null) => void;
  setSessionLoading: (v: boolean) => void;
  setSessionMissing: (v: boolean) => void;
  setHistoryTurns: (t: SessionTurn[]) => void;
  setRateLimit: (info: RateLimitInfo | null) => void;
  startTurn: (question: string, sessionId: string | null) => string;
  applyEvent: (key: string, evt: SseEvent) => void;
  patchTurn: (key: string, patch: Partial<Turn>) => void;
  setStreaming: (v: boolean) => void;
  reset: () => void;
}

let turnSeq = 0;

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId: null,
  historyTurns: [],
  sessionLoading: false,
  sessionMissing: false,
  turns: [],
  streaming: false,
  rateLimit: null,
  activeKey: null,

  setSessionId: (id) => set({ sessionId: id }),
  setSessionLoading: (v) => set({ sessionLoading: v }),
  setSessionMissing: (v) => set({ sessionMissing: v }),
  setHistoryTurns: (t) => set({ historyTurns: t }),
  setRateLimit: (info) => set({ rateLimit: info }),

  startTurn: (question, sessionId) => {
    turnSeq += 1;
    const key = `turn_${turnSeq}`;
    const turn: Turn = {
      key,
      question,
      outcome: 'running',
      sessionId: sessionId ?? undefined,
      stages: [],
      elapsedMsList: [],
      clarifyCount: 0,
      startedAt: Date.now(),
    };
    set({ turns: [...get().turns, turn], streaming: true, activeKey: key });
    return key;
  },

  applyEvent: (key, evt) => {
    const turns = get().turns;
    const turn = turns.find((t) => t.key === key);
    if (!turn) return;
    // stage 是"追加"语义，单独处理
    const patch = evt.event === 'stage' ? appendStage(turn, evt) : reduceEvent(evt);
    // 任何事件（含 heartbeat）都刷新"最后活动时刻"，供页面 5s 静默提示使用
    const next: Partial<Turn> = { ...(patch ?? {}), lastEventAt: Date.now() };
    set({ turns: turns.map((t) => (t.key === key ? { ...t, ...next } : t)) });
  },

  patchTurn: (key, patch) =>
    set({ turns: get().turns.map((t) => (t.key === key ? { ...t, ...patch } : t)) }),

  setStreaming: (v) => set({ streaming: v }),

  reset: () =>
    set({
      sessionId: null,
      historyTurns: [],
      sessionLoading: false,
      sessionMissing: false,
      turns: [],
      streaming: false,
      rateLimit: null,
      activeKey: null,
    }),
}));

/**
 * 单个 SSE 事件 → 轮次增量。
 * ⚠️ 终止判定不在这里（唯一规则在 queryStream：data.terminal === true）；
 * 本函数只把事件内容落成 UI 数据，degraded 不改变 outcome（流继续）。
 */
function reduceEvent(evt: SseEvent): Partial<Turn> | null {
  switch (evt.event) {
    case 'ack':
      return { taskId: evt.data.task_id, sessionId: evt.data.session_id };
    case 'data':
      return { data: evt.data, dataShownAt: Date.now() };
    case 'chart':
      return { chart: evt.data };
    case 'insight':
      return { insight: evt.data };
    case 'meta':
      return { meta: evt.data };
    case 'degraded':
      // degraded 恒 terminal:false → 只记录，不改 outcome（06 §4.11）
      return { degraded: evt.data };
    case 'clarify':
      // 澄清事件无时间戳字段（A.4），有效期从"前端收到时刻"起算（5 分钟）
      return { clarify: evt.data, outcome: 'clarify', clarifyReceivedAt: Date.now() };
    case 'refuse':
      return { refuse: evt.data, outcome: 'refuse' };
    case 'error':
      return { error: evt.data, outcome: 'failed' };
    case 'complete':
      return { outcome: 'done' };
    case 'heartbeat':
      return null; // 心跳只保活不驱动 UI
    default:
      return null;
  }
}

/** stage 事件需要"追加"语义，单独处理（store 内 map 合并无法表达追加） */
export function appendStage(turn: Turn, evt: Extract<SseEvent, { event: 'stage' }>): Partial<Turn> {
  return {
    stages: [...turn.stages, evt.data.stage],
    elapsedMsList: [...turn.elapsedMsList, evt.data.elapsed_ms],
    planSummary: evt.data.plan_summary ?? turn.planSummary,
    sql: evt.data.sql ?? turn.sql,
    dialect: evt.data.dialect ?? turn.dialect,
    ...(evt.data.stage === 'sql_ready' ? { sqlShownAt: Date.now() } : {}),
  };
}