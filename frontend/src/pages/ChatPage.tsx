/**
 * 会话问答页（06 §5 核心页；路由 /chat 与 /chat/:sessionId）
 * - P0 = 单栏 + 右抽屉；三列 grid 轨道已预埋（会话列表 P1 再开，不渲染 SessionRail）
 * - 一次完整结果区块顺序严格按 §5.3（不允许重排）
 * - 历史轮次只渲染计划摘要（A.5.2 不返回 SQL/数据 → 不得本地伪造完整结果）
 * - 前端零判断权：不给结论、不算指标、不推断图表类型
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Drawer, Modal, Tabs, message } from 'antd';
import { tokens } from '../theme/tokens';
import {
  AskBox,
  CaveatBar,
  ClarifyCard,
  DegradeBar,
  ErrorCard,
  FeedbackBar,
  HealthIndicator,
  InsightCard,
  QuotaIndicator,
  RefuseCard,
  ResultBlock,
  SqlCard,
  StageBar,
  TruncateBar,
  type FeedbackPayload,
} from '../components';
import { ApiError, apiGet, apiPost } from '../api/client';
import {
  openClarifyStream,
  openQueryStream,
  stopCurrentQuery,
  setToken,
  type StreamHandlers,
} from '../api/queryStream';
import { useChatStore, type Turn } from '../store/chatStore';
import { track } from '../utils/analytics';
import type { AsyncTaskResult, QueryOptions, SessionDetail, SseEvent } from '../api/types';

const API_BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`;

/** 空状态示例问题（06 §5.1 / 附录 B-5：静态，不做动态推荐） */
const EXAMPLES = [
  '上个月华东区 GMV 是多少，环比怎么样',
  '各渠道的订单量排名',
  '天猫渠道的客单价环比上个月变化',
  '看看竞品的销量',
  '帮我分析一下为什么销量下滑',
];

/** 澄清有效期 5 分钟（A.13） */
const CLARIFY_TTL_MS = 5 * 60 * 1000;
/** 异步轮询间隔（06 §4.11） */
const POLL_INTERVAL_MS = 3_000;
/** 结果保留期 1 小时（A.13） */
const POLL_MAX_MS = 60 * 60 * 1000;

const TIME_WORDS = /(上个月|本月|这个月|上周|本周|近\s*\d+\s*天|昨天|今天|去年|今年|季度|季度|月|周|日|年)/;

// ---------------------------------------------------------------------------
// §4.11 转异步的刷新恢复：sessionStorage 记录未完成的 task_id（最长跨 1 次刷新）
// ⚠️ 这里会写入提问原文（渲染用户气泡所需）；仅 sessionStorage、仅当前标签页、刷新后单次消费。
//    与 §2.5「禁止把业务信息写入 localStorage」不冲突，但已在 RELAY 中登记供上游确认。
// ---------------------------------------------------------------------------
const PENDING_TASK_KEY = 'cqPendingTask';

interface PendingTask {
  taskId: string;
  sessionId: string;
  question: string;
}

function persistPendingTask(p: PendingTask): void {
  try {
    sessionStorage.setItem(PENDING_TASK_KEY, JSON.stringify(p));
  } catch {
    // 隐私模式等场景写入失败：不阻断查询，仅丧失刷新恢复能力
  }
}

function readPendingTask(sessionId: string): PendingTask | null {
  try {
    const raw = sessionStorage.getItem(PENDING_TASK_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as PendingTask;
    return p.sessionId === sessionId && p.taskId ? p : null;
  } catch {
    return null;
  }
}

function clearPendingTask(): void {
  try {
    sessionStorage.removeItem(PENDING_TASK_KEY);
  } catch {
    /* 同上 */
  }
}

export function ChatPage() {
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  const {
    sessionId,
    setSessionId,
    historyTurns,
    setHistoryTurns,
    sessionLoading,
    setSessionLoading,
    sessionMissing,
    setSessionMissing,
    turns,
    streaming,
    rateLimit,
    setRateLimit,
    startTurn,
    applyEvent,
    patchTurn,
    setStreaming,
    reset,
  } = useChatStore();

  const [fillText, setFillText] = useState<string | null>(null);
  const [drawerTurnKey, setDrawerTurnKey] = useState<string | null>(null);
  const [healthLevel, setHealthLevel] = useState<'ok' | 'degraded' | 'unhealthy' | 'unknown'>('unknown');
  const [sessionCreateError, setSessionCreateError] = useState<string | null>(null);
  const [creatingSession, setCreatingSession] = useState(false);
  const [authExpired, setAuthExpired] = useState(false);
  const [tick, setTick] = useState(() => Date.now());
  const [showNewContent, setShowNewContent] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stuckToBottomRef = useRef(true);
  /** 最后一轮历史摘要的锚点（§5.4 滚动锚点） */
  const lastHistoryRef = useRef<HTMLDivElement>(null);
  /** 后台查询在标签页不可见时完成 → 恢复可见后补一次 toast（§4.11） */
  const pendingNotifyRef = useRef(false);
  const firstEventTrackedRef = useRef<Set<string>>(new Set());

  // ---- 会话加载 / 历史摘要（切换会话或刷新后从 URL 恢复） ----
  useEffect(() => {
    if (routeSessionId && routeSessionId !== sessionId) {
      reset();
      setSessionId(routeSessionId);
      setSessionLoading(true);
      setSessionMissing(false);
      apiGet<SessionDetail>(`/session/${routeSessionId}`)
        .then((d) => {
          setHistoryTurns(d.turns ?? []);
          setSessionLoading(false);
          // §5.4 滚动锚点：切换会话/刷新后定位到最后一轮的顶部，而非页面顶部
          requestAnimationFrame(() => lastHistoryRef.current?.scrollIntoView({ block: 'start' }));
          // §4.11 刷新恢复：若本会话有未完成的后台任务，恢复轮询（最长跨 1 次刷新）
          const pending = readPendingTask(routeSessionId);
          if (pending) {
            const k = startTurn(pending.question, routeSessionId);
            patchTurn(k, { outcome: 'async_pending', taskId: pending.taskId, fromAsync: true });
            startPolling(k, pending.taskId);
          }
        })
        .catch((err: unknown) => {
          setSessionLoading(false);
          if (err instanceof ApiError && (err.code === 'SESSION_NOT_FOUND' || err.httpStatus === 404)) {
            setSessionMissing(true);
          } else if (err instanceof ApiError && err.code === 'AUTH_FAILED') {
            setAuthExpired(true);
          } else {
            message.error('会话加载失败');
          }
        });
    } else if (!routeSessionId && sessionId !== null) {
      // 回到新会话
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSessionId]);

  // ---- 流式期间的计时（5s 静默提示、3s 首事件提示、耗时展示） ----
  useEffect(() => {
    if (!streaming) return;
    const t = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, [streaming]);

  // ---- 滚动：贴底时自动滚动，用户上移 > 150px 则停并提示 ----
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stuckToBottomRef.current) {
      bottomRef.current?.scrollIntoView({ block: 'end' });
      setShowNewContent(false);
    } else if (turns.length > 0) {
      setShowNewContent(true);
    }
  }, [turns]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      stuckToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
      if (stuckToBottomRef.current) setShowNewContent(false);
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden && pendingNotifyRef.current) {
        pendingNotifyRef.current = false;
        message.info('你有一个后台查询已完成');
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  // ---- 场景：AUTH_FAILED 用 Modal 提示（不立即跳登录页，会丢当前视图） ----
  useEffect(() => {
    if (!authExpired) return;
    if (sessionId) sessionStorage.setItem('pendingSessionId', sessionId);
  }, [authExpired, sessionId]);

  const registerContractWatch = useCallback((evt: SseEvent) => {
    if (evt.event === 'meta') {
      // A.1.5 红线 1：不得展示任何"间接量"（被过滤行数/比例…）
      const raw = evt.data.scope as unknown as Record<string, unknown> | undefined;
      if (raw) {
        const indirect = ['filtered_rows', 'total_before', 'visible_ratio', 'hidden_count'].filter((k) => k in raw);
        if (indirect.length) {
          track('ui_contract_violation', { at: 'meta.scope', fields: indirect.join(',') });
          console.error('[ui_contract_violation] scope 含间接量字段，已忽略不渲染', indirect);
        }
      }
    }
    if (evt.event === 'data' && (evt.data as unknown as Record<string, unknown>).filtered_rows !== undefined) {
      track('ui_contract_violation', { at: 'data', fields: 'filtered_rows' });
      console.error('[ui_contract_violation] data 含间接量字段，已忽略不渲染');
    }
  }, []);

  /** 统一的事件处理（/query 与 /clarify 共用） */
  const makeHandlers = useCallback(
    (turnKey: string): StreamHandlers => ({
      onEvent: (evt: SseEvent) => {
        if (!firstEventTrackedRef.current.has(turnKey)) {
          firstEventTrackedRef.current.add(turnKey);
          track('ui_first_event', { event: evt.event });
        }
        registerContractWatch(evt);
        applyEvent(turnKey, evt);
        if (evt.event === 'stage' && evt.data.stage === 'sql_ready') {
          track('ui_sql_shown', {});
        }
        if (evt.event === 'data') {
          track('ui_data_shown', { row_count: evt.data.row_count, truncated: evt.data.truncated });
        }
      },
      onTerminal: (reason) => {
        const t = useChatStore.getState().turns.find((x) => x.key === turnKey);
        const totalMs = t ? Date.now() - t.startedAt : 0;
        track('ui_terminal', { outcome: reason, total_ms: totalMs });
        setStreaming(false);
        if (reason === 'complete') {
          const degraded = t?.degraded;
          if (degraded && degraded.action_taken === 'switched_to_async' && degraded.task_id) {
            // 转异步：就地升级为「后台执行中」卡片 + 启动轮询（AskBox 解除串行锁定）
            patchTurn(turnKey, { outcome: 'async_pending' });
            startPolling(turnKey, degraded.task_id);
            // §4.11 页面刷新：用 sessionStorage 记住未完成的 task_id（最长跨 1 次刷新后恢复轮询）
            if (sessionId) persistPendingTask({ taskId: degraded.task_id, sessionId, question: t?.question ?? '' });
          } else {
            patchTurn(turnKey, { outcome: 'done' });
          }
        }
      },
      onTransportError: (err) => {
        setStreaming(false);
        if (err.message === 'session_conflict_after_retry') {
          patchTurn(turnKey, { outcome: 'failed', transportError: 'SESSION_CONFLICT' });
        } else if (err.message === 'no_event_timeout') {
          patchTurn(turnKey, { outcome: 'failed', transportError: 'no_event_timeout' });
        } else {
          patchTurn(turnKey, { outcome: 'failed', transportError: err.message });
        }
      },
      onRateLimit: (info) => setRateLimit(info),
      onSessionConflictRetry: (attempt, retryAfterMs) => {
        message.info(`该会话正在处理上一个问题，${Math.round(retryAfterMs / 1000)} 秒后自动重试（第 ${attempt} 次）`);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [applyEvent, patchTurn, registerContractWatch, setRateLimit, setStreaming],
  );

  /** 异步结果轮询（06 §4.11 转异步完整交互） */
  const startPolling = useCallback(
    (turnKey: string, taskId: string) => {
      const startedAt = Date.now();
      const poll = async () => {
        if (document.hidden) {
          pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);
          return;
        }
        try {
          const res = await apiGet<AsyncTaskResult>(`/query/${taskId}`);
          if (res.status === 'complete') {
            patchTurn(turnKey, {
              outcome: 'done',
              fromAsync: true,
              data: res.data,
              chart: res.chart,
              insight: res.insight,
              meta: res.meta,
              sql: res.sql,
            });
            clearPendingTask();
            // §4.11 可见性优化：结果返回时标签页不可见 → 恢复可见后 toast 提示
            if (document.hidden) pendingNotifyRef.current = true;
            else message.info('你有一个后台查询已完成');
            track('ui_async_poll_result', { status: 'complete' });
            return;
          }
          if (res.status === 'failed') {
            patchTurn(turnKey, { outcome: 'failed', transportError: 'async_failed' });
            clearPendingTask();
            track('ui_async_poll_result', { status: 'failed' });
            return;
          }
          if (res.status === 'cancelled') {
            patchTurn(turnKey, { outcome: 'stopped' });
            clearPendingTask();
            track('ui_async_poll_result', { status: 'cancelled' });
            return;
          }
          if (res.status === 'refused' || res.status === 'clarify' || res.status === 'degraded') {
            // 异步终态语义由后端给，前端不自行映射成结果块
            patchTurn(turnKey, { outcome: res.status === 'refused' ? 'refuse' : 'done', fromAsync: true });
            return;
          }
        } catch (err) {
          if (err instanceof ApiError && err.code === 'TASK_NOT_FOUND') {
            patchTurn(turnKey, { outcome: 'failed', transportError: 'TASK_NOT_FOUND' });
            clearPendingTask();
            return;
          }
        }
        if (Date.now() - startedAt > POLL_MAX_MS) {
          patchTurn(turnKey, { outcome: 'failed', transportError: 'async_expired' });
          clearPendingTask();
          return;
        }
        pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      };
      pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    },
    [patchTurn],
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  /** 提交问题：会话创建 → SSE 流 */
  const handleSubmit = useCallback(
    async (question: string, opts: QueryOptions) => {
      let sid = sessionId;
      if (!sid) {
        // 会话创建中：不允许带着 sessionId=null 去 POST /query；失败不降级为本地会话
        setCreatingSession(true);
        setSessionCreateError(null);
        try {
          const created = await apiPost<{ session_id: string }>('/session', {});
          sid = created.session_id;
          setSessionId(sid);
          navigate(`/chat/${sid}`, { replace: true });
        } catch (err) {
          setCreatingSession(false);
          setSessionCreateError(err instanceof Error ? err.message : '无法创建会话');
          return;
        }
        setCreatingSession(false);
      }

      const key = startTurn(question, sid);
      firstEventTrackedRef.current.delete(key);
      stuckToBottomRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      await openQueryStream({ question, sessionId: sid, options: opts }, makeHandlers(key), controller.signal);
      setStreaming(false);
    },
    [sessionId, setSessionId, startTurn, makeHandlers, navigate, setStreaming],
  );

  const handleAbort = useCallback(() => {
    const activeKey = useChatStore.getState().activeKey;
    const t = useChatStore.getState().turns.find((x) => x.key === activeKey);
    void stopCurrentQuery(t?.taskId);
    if (activeKey) patchTurn(activeKey, { outcome: 'stopped' });
    setStreaming(false);
  }, [patchTurn, setStreaming]);

  /** 澄清应答：新开一条流（clarify 是 terminal:true，原流已终止） */
  const handleClarifyAnswer = useCallback(
    async (turnKey: string, clarifyId: string, answer: { selected_value?: string; free_text?: string }) => {
      track('ui_clarify_answered', { by: answer.free_text ? 'free_text' : 'option' });
      patchTurn(turnKey, {
        clarify: undefined,
        data: undefined,
        chart: undefined,
        insight: undefined,
        meta: undefined,
        stages: [],
        elapsedMsList: [],
        outcome: 'running',
      });
      setStreaming(true);
      stuckToBottomRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      const t = useChatStore.getState().turns.find((x) => x.key === turnKey);
      await openClarifyStream(clarifyId, answer, makeHandlers(turnKey), controller.signal, sessionId);
      patchTurn(turnKey, { clarifyCount: (t?.clarifyCount ?? 0) + 1 });
      setStreaming(false);
    },
    [makeHandlers, patchTurn, sessionId, setStreaming],
  );

  const askDisabledReason = useMemo(() => {
    if (healthLevel === 'unhealthy') return 'no_scope' as const;
    if (rateLimit && rateLimit.remaining <= 0) return 'rate_limited' as const;
    return undefined;
  }, [healthLevel, rateLimit]);

  const drawerTurn = turns.find((t) => t.key === drawerTurnKey) ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#fff' }}>
      {/* Header 56px（06 §3.4：Header 高度落在 8pt 网格内） */}
      <header
        style={{
          height: tokens.size.header,
          display: 'flex',
          alignItems: 'center',
          gap: tokens.space.md,
          padding: `0 ${tokens.space.md}px`,
          borderBottom: `1px solid ${tokens.color.neutral.border}`,
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: tokens.font.size.h1, fontWeight: tokens.font.weight.medium }}>CommerceQL</span>
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary }}>电商数据分析</span>
        <nav style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.space.md }}>
          <Link to="/semantic/metrics" style={{ fontSize: 13 }}>
            口径字典
          </Link>
          <Link to="/eval/runs" style={{ fontSize: 13 }}>
            评测
          </Link>
          <QuotaIndicator rateLimit={rateLimit} />
          <HealthIndicator onLevelChange={setHealthLevel} />
        </nav>
      </header>

      {/* 三列 grid 轨道预埋：rail(240) | 主对话 | detailDrawer(0=抽屉覆盖)；P0 只开中列 */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: `0px 1fr 0px`,
        }}
      >
        <div style={{ display: 'none' }} data-rail-placeholder="session-rail-p1" />
        <main
          ref={scrollRef}
          style={{ overflowY: 'auto', padding: `${tokens.space.lg}px ${tokens.space.md}px` }}
        >
          <div style={{ maxWidth: 880, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: tokens.space.lg }}>
            {sessionMissing ? (
              <div style={{ textAlign: 'center', padding: tokens.space.xxl }} data-testid="chat-session-missing">
                <div style={{ fontSize: tokens.font.size.h1 }}>该会话不存在或已删除</div>
                <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>
                  会话记录可能已过期
                </div>
                <Button type="primary" style={{ marginTop: 12 }} onClick={() => navigate('/chat')}>
                  开始新会话
                </Button>
              </div>
            ) : (
              <>
                {sessionLoading && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.space.md }}>
                    {[0, 1].map((i) => (
                      <div key={i} className="cq-skeleton" style={{ height: 200 }} />
                    ))}
                  </div>
                )}

                {/* 历史轮次：只渲染计划摘要（A.5.2 不返回 SQL 与数据） */}
                {historyTurns.length > 0 && (
                  <section data-testid="chat-history">
                    <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginBottom: 8 }}>
                      历史记录只保留查询计划摘要，完整结果请重新提问
                    </div>
                    {historyTurns.map((h, i) => (
                      <div
                        key={h.task_id}
                        ref={i === historyTurns.length - 1 ? lastHistoryRef : undefined}
                        style={{
                          border: `1px solid ${tokens.color.neutral.border}`,
                          borderRadius: tokens.radius.md,
                          padding: tokens.space.sm,
                          marginBottom: tokens.space.xs,
                        }}
                      >
                        <div style={{ fontSize: 13 }}>{h.question}</div>
                        <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }}>
                          {planSummaryText(h.plan_summary)} ｜ 结果：{h.outcome} ｜ {h.at}
                        </div>
                      </div>
                    ))}
                  </section>
                )}

                {turns.length === 0 && !sessionLoading && requestIdle(historyTurns.length) && (
                  <EmptyState onPick={(q) => setFillText(q)} />
                )}

                {turns.map((t, idx) => (
                  <TurnView
                    key={t.key}
                    turn={t}
                    prevTurn={idx > 0 ? turns[idx - 1] : undefined}
                    now={tick}
                    onNarrow={() => setFillText('请把时间范围收窄，或增加筛选条件：')}
                    onSuggest={(s) => setFillText(s)}
                    onClarifyAnswer={(clarifyId, answer) => void handleClarifyAnswer(t.key, clarifyId, answer)}
                    onReaskClarify={() => setFillText(t.question)}
                    onRetry={() => setFillText(t.question)}
                    onOpenDrawer={() => setDrawerTurnKey(t.key)}
                    onFeedback={async (payload) => {
                      await apiPost('/feedback', { task_id: t.taskId ?? '', ...payload });
                      track('ui_feedback_submit', {
                        reason_code: payload.reason_code ?? 'none',
                        is_correct: payload.is_correct,
                      });
                      if (payload.reason_code === 'permission_issue') {
                        track('ui_permission_feedback', {});
                      }
                    }}
                  />
                ))}

                {sessionCreateError && (
                  <ErrorCard
                    code="INTERNAL"
                    message={`无法创建会话：${sessionCreateError}`}
                    traceId=""
                    retryable
                    onRetry={() => setSessionCreateError(null)}
                  />
                )}
                <div ref={bottomRef} />
              </>
            )}
          </div>
        </main>
        <div />
      </div>

      {showNewContent && (
        <button
          type="button"
          onClick={() => {
            stuckToBottomRef.current = true;
            bottomRef.current?.scrollIntoView({ block: 'end' });
            setShowNewContent(false);
          }}
          style={{
            position: 'fixed',
            right: tokens.space.lg,
            bottom: 144,
            zIndex: tokens.z.sticky,
            background: '#fff',
            border: `1px solid ${tokens.color.brand.border}`,
            color: tokens.color.brand.solid,
            borderRadius: tokens.radius.full,
            padding: '6px 12px',
            cursor: 'pointer',
            boxShadow: tokens.shadow.overlay,
          }}
        >
          ↓ 有新内容
        </button>
      )}

      {/* AskBox 常驻底部（C1） */}
      <footer
        style={{
          borderTop: `1px solid ${tokens.color.neutral.border}`,
          padding: `${tokens.space.sm}px ${tokens.space.md}px`,
          flexShrink: 0,
        }}
      >
        <div style={{ maxWidth: 880, margin: '0 auto' }}>
          <AskBox
            sessionId={sessionId}
            streaming={streaming || creatingSession}
            disabled={askDisabledReason !== undefined}
            disabledReason={askDisabledReason}
            rateLimitResetAt={rateLimit?.reset}
            onSubmit={(q, opts) => void handleSubmit(q, opts)}
            onAbort={handleAbort}
            examples={turns.length === 0 ? EXAMPLES : undefined}
            fillText={fillText}
            onFillConsumed={() => setFillText(null)}
          />
        </div>
      </footer>

      {/* 登录过期：Modal 提示，不立即跳转（06 §5.5） */}
      <Modal
        open={authExpired}
        title="登录已过期"
        okText="重新登录"
        cancelText="继续浏览"
        onOk={() => {
          setToken(null);
          navigate('/login');
        }}
        onCancel={() => setAuthExpired(false)}
      >
        当前页面的数据可能已过期，重新登录后可返回本会话。
      </Modal>

      {/* 详情抽屉：口径与血缘（C7 全文层） */}
      <Drawer
        open={drawerTurn !== null}
        onClose={() => setDrawerTurnKey(null)}
        width={tokens.size.detailDrawer}
        title="详情"
      >
        {drawerTurn && (
          <Tabs
            items={[
              {
                key: 'caveats',
                label: '口径与血缘',
                children: (
                  <div data-testid="chat-detail-caveats" style={{ fontSize: 13 }}>
                    <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginBottom: 8 }}>
                      口径说明全文（常驻摘要见结果区，此处为完整条目）
                    </div>
                    {(drawerTurn.insight?.caveats ?? []).length === 0 && <div>本次未返回口径说明</div>}
                    {(drawerTurn.insight?.caveats ?? []).map((c, i) => (
                      <div key={i} style={{ marginBottom: 6 }}>
                        · {c}
                      </div>
                    ))}
                    <div style={{ marginTop: tokens.space.md, fontSize: 12, color: tokens.color.text.tertiary }}>
                      溯源（指标 → 来源资产 → 语义包版本）：
                    </div>
                    {(drawerTurn.insight?.citations ?? []).map((c, i) => (
                      <div key={i} style={{ fontSize: 12, marginTop: 4 }}>
                        <Link to={`/semantic/metrics?q=${encodeURIComponent(c.metric)}`}>{c.metric}</Link> ← {c.asset} ·{' '}
                        {c.bundle_version}
                      </div>
                    ))}
                    <div style={{ marginTop: tokens.space.md, fontSize: 12, color: tokens.color.text.tertiary }}>
                      指标的 definition_note / default_predicates 属语义层端点（A.7.1），为避免 N+1 未在本抽屉拉取，
                      请到<Link to="/semantic/metrics">口径字典</Link>查看。
                    </div>
                  </div>
                ),
              },
              {
                key: 'query',
                label: '查询信息',
                children: (
                  <div style={{ fontSize: 12 }}>
                    <div>任务号：{drawerTurn.taskId ?? '—'}</div>
                    <div>语义包版本：{drawerTurn.meta?.bundle_version ?? '—'}</div>
                    <div>耗时：{drawerTurn.meta ? `${(drawerTurn.meta.latency_ms / 1000).toFixed(1)}s` : '—'}</div>
                    <div>成本：{drawerTurn.meta?.cost_cny !== undefined ? `¥${drawerTurn.meta.cost_cny}` : '—'}</div>
                    <div>trace_id：{drawerTurn.meta?.trace_id ?? '—'}</div>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}

/** 会话为空且历史也为空 → 展示空状态（多态文案见 §5.1） */
function requestIdle(historyCount: number): boolean {
  return historyCount === 0;
}

function planSummaryText(p?: { metrics?: string[]; dimensions?: string[]; time_range?: { start: string; end: string } }): string {
  if (!p) return '计划摘要：—';
  const m = p.metrics?.length ? p.metrics.join('、') : '—';
  const d = p.dimensions?.length ? p.dimensions.join('、') : '—';
  const t = p.time_range ? `${p.time_range.start} ~ ${p.time_range.end}` : '—';
  return `计划：${m} × ${d} × ${t}`;
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div data-testid="chat-empty" style={{ textAlign: 'center', paddingTop: tokens.space.xxl }}>
      <div aria-hidden style={{ fontSize: 40, color: tokens.color.neutral.border }}>
        ⌕
      </div>
      <div style={{ fontSize: tokens.font.size.h1, fontWeight: tokens.font.weight.medium, marginTop: 8 }}>
        问我关于经营数据的问题
      </div>
      <div style={{ fontSize: 13, color: tokens.color.text.secondary, marginTop: 4 }}>
        支持订单、商品、流量三类数据。用大白话问就行。
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: tokens.space.xs,
          maxWidth: 520,
          margin: `${tokens.space.lg}px auto 0`,
        }}
      >
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            style={{
              textAlign: 'left',
              padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
              border: `1px solid ${tokens.color.neutral.border}`,
              borderRadius: tokens.radius.md,
              background: '#fff',
              cursor: 'pointer',
              fontSize: 13,
              color: tokens.color.text.primary,
            }}
          >
            {q}
          </button>
        ))}
      </div>
      {/* §5.1 底部数据边界行：**契约无"当前租户店铺 / 数据新鲜度"来源**（A 无对应端点字段）
          → 不编造具体值：只做不含数值的边界声明，并把新鲜度指向每轮结果的口径条。
          已在 QA 记 BLOCKED、RELAY 登记为上游缺口。 */}
      <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: tokens.space.lg }}>
        数据范围：本租户（店铺级隔离）｜ 数据截至时间以每次结果的口径条为准
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 单轮渲染（区块顺序严格按 06 §5.3）
// ---------------------------------------------------------------------------

interface TurnViewProps {
  turn: Turn;
  prevTurn?: Turn;
  now: number;
  onNarrow: () => void;
  onSuggest: (s: string) => void;
  onClarifyAnswer: (clarifyId: string, answer: { selected_value?: string; free_text?: string }) => void;
  onReaskClarify: () => void;
  onRetry: () => void;
  onOpenDrawer: () => void;
  onFeedback: (payload: FeedbackPayload) => Promise<void>;
}

function TurnView(props: TurnViewProps) {
  const { turn, prevTurn, now, onNarrow, onSuggest, onClarifyAnswer, onReaskClarify, onRetry, onOpenDrawer, onFeedback } =
    props;
  const [stageCollapsed, setStageCollapsed] = useState(true);
  const [clarifyError, setClarifyError] = useState<string | undefined>();

  const running = turn.outcome === 'running';
  const totalElapsed = turn.elapsedMsList.length ? turn.elapsedMsList[turn.elapsedMsList.length - 1] : 0;
  /** 距最后一次收到事件（含心跳）的静默时长；>90s 由 queryStream 看门狗兜底终止 */
  const silentMs = running ? now - (turn.lastEventAt ?? turn.startedAt) : 0;
  const noStageYet = running && turn.stages.length === 0 && now - turn.startedAt > 3_000;

  // 澄清后重新执行的说明（§4.9）
  const clarifyRound = turn.clarifyCount > 0;

  // 条件继承可见化（§5.4：本轮未说时间词但复用了上一轮时间范围）
  const inherited =
    !!prevTurn &&
    !!turn.insight &&
    !TIME_WORDS.test(turn.question) &&
    !!prevTurn.insight &&
    sameTimeCaveat(turn.insight.caveats, prevTurn.insight.caveats);

  return (
    <section data-testid="chat-turn" style={{ display: 'flex', flexDirection: 'column', gap: tokens.space.xs }}>
      {/* 1. 用户气泡 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div
          style={{
            maxWidth: '78%',
            background: tokens.color.brand.bg,
            color: tokens.color.brand.text,
            borderRadius: tokens.radius.lg,
            padding: `${tokens.space.xs}px ${tokens.space.sm}px`,
            fontSize: tokens.font.size.body,
          }}
        >
          {turn.question}
        </div>
      </div>

      {/* 计划变更提示（§5.4） */}
      {turn.planSummary && prevTurn?.planSummary && planSummaryText(turn.planSummary) !== planSummaryText(prevTurn.planSummary) && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>本轮计划：{planSummaryText(turn.planSummary)}</div>
      )}
      {clarifyRound && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>已按你的选择重新校验并执行</div>
      )}

      {/* 2. StageBar（完成后折叠为一行摘要） */}
      {turn.outcome !== 'clarify' && turn.outcome !== 'refuse' && (
        <>
          {stageCollapsed && (turn.outcome === 'done' || turn.outcome === 'stopped' || turn.outcome === 'async_pending') ? (
            <button
              type="button"
              onClick={() => setStageCollapsed(false)}
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                textAlign: 'left',
                cursor: 'pointer',
                fontSize: 12,
                color: tokens.color.text.tertiary,
              }}
            >
              已用 {(totalElapsed / 1000).toFixed(1)}s ｜ 完成 {turn.stages.length} 步（点击展开）
            </button>
          ) : (
            <StageBar
              received={turn.stages}
              elapsedMsList={turn.elapsedMsList}
              status={turn.outcome === 'stopped' ? 'stopped' : turn.outcome === 'done' ? 'done' : 'running'}
              clarifyCount={turn.clarifyCount}
            />
          )}
          {noStageYet && running && (
            <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>
              网络可能较慢，请稍候
            </div>
          )}
          {running && silentMs > 5000 && (
            <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>
              仍在处理…（已用 {((now - turn.startedAt) / 1000).toFixed(0)}s）
            </div>
          )}
        </>
      )}

      {/* 3. SqlCard（收到 sql_ready 立即渲染，不等 data） */}
      {turn.sql && turn.dialect === 'postgresql' && <SqlCard sql={turn.sql} dialect="postgresql" readonly />}

      {/* 4. DegradeBar：Inline 条；转异步后升级为「后台执行中」卡片 */}
      {turn.degraded && turn.outcome !== 'async_pending' && (
        <DegradeBar
          reason={turn.degraded.reason}
          actionTaken={turn.degraded.action_taken}
          partialResult={turn.degraded.partial_result}
          pollUrl={turn.degraded.poll_url}
          taskId={turn.degraded.task_id}
        />
      )}
      {turn.outcome === 'async_pending' && turn.degraded && (
        <DegradeBar
          mode="async_card"
          reason={turn.degraded.reason}
          actionTaken={turn.degraded.action_taken}
          pollUrl={turn.degraded.poll_url}
          taskId={turn.degraded.task_id}
        />
      )}
      {turn.fromAsync && (
        <div style={{ fontSize: 12, color: tokens.color.degraded.text }}>
          本次查询因耗时较长转入了后台执行
        </div>
      )}

      {/* 5. TruncateBar */}
      {turn.data && (
        <TruncateBar
          truncated={turn.data.truncated}
          rowCount={turn.data.row_count}
          maxRows={5000}
          chartType={turn.chart?.chart_type}
          onNarrow={onNarrow}
        />
      )}

      {/* 6. ResultBlock */}
      <ResultBlock data={turn.data} chart={turn.chart} onSuggest={onSuggest} />

      {/* 7. InsightCard + CaveatBar（同卡） */}
      {turn.insight && (
        <div
          style={{
            background: '#fff',
            border: `1px solid ${tokens.color.neutral.border}`,
            borderRadius: tokens.radius.lg,
            padding: tokens.space.sm,
            display: 'flex',
            flexDirection: 'column',
            gap: tokens.space.xs,
          }}
        >
          {inherited && (
            <div>
              <span
                style={{
                  fontSize: 12,
                  background: tokens.color.neutral.bg,
                  border: `1px solid ${tokens.color.neutral.border}`,
                  borderRadius: tokens.radius.sm,
                  padding: '0 6px',
                  color: tokens.color.text.secondary,
                }}
              >
                沿用上轮条件
              </span>
            </div>
          )}
          <InsightCard text={turn.insight.text} citations={turn.insight.citations} />
          <CaveatBar
            caveats={turn.insight.caveats}
            scope={turn.meta?.scope}
            onOpenDrawer={onOpenDrawer}
            onContractViolation={(t) => {
              track('ui_contract_violation', { at: 'caveats', sample: 'indirect_metric' });
              console.error('[ui_contract_violation] caveats 含间接量描述，已忽略', t);
            }}
          />
        </div>
      )}

      {/* 8. FeedbackBar（仅正常成功态；异常态不展示） */}
      {turn.outcome === 'done' && turn.taskId && turn.data && turn.data.row_count > 0 && !turn.clarify && !turn.refuse && !turn.error && (
        <FeedbackBar taskId={turn.taskId} onFeedback={onFeedback} />
      )}

      {/* 9. 辅助信息行 */}
      {turn.meta && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>
          耗时 {(turn.meta.latency_ms / 1000).toFixed(1)}s
          {turn.meta.cost_cny !== undefined ? ` ｜ 成本 ¥${turn.meta.cost_cny}` : ''} ｜ 语义包{' '}
          {turn.meta.bundle_version}
          {turn.taskId ? ` ｜ 任务号 ${turn.taskId}` : ''}
        </div>
      )}

      {/* 终态：澄清 / 拒答 / 错误 / 已停止 */}
      {turn.outcome === 'clarify' && turn.clarify && (
        <ClarifyCard
          clarifyId={turn.clarify.clarify_id}
          question={turn.clarify.question}
          reason={String(turn.clarify.reason)}
          options={turn.clarify.options}
          expiresAt={(turn.clarifyReceivedAt ?? Date.now()) + CLARIFY_TTL_MS}
          errorText={clarifyError}
          onAnswer={(v) => {
            setClarifyError(undefined);
            onClarifyAnswer(turn.clarify!.clarify_id, v);
          }}
          onReask={onReaskClarify}
        />
      )}
      {turn.outcome === 'refuse' && turn.refuse && (
        <RefuseCard
          reason={turn.refuse.reason}
          message={turn.refuse.message}
          suggestions={turn.refuse.suggestions}
          onPickSuggestion={onSuggest}
        />
      )}
      {turn.outcome === 'failed' && turn.error && (
        <ErrorCard
          code={turn.error.code}
          message={turn.error.message}
          detail={turn.error.detail}
          traceId={turn.meta?.trace_id ?? turn.error.code}
          retryable={turn.error.retryable}
          // P0 无"当前用户角色"来源（A 契约无 /me；登录端点 D-H 未定）→ 角色未知时一律隐藏 detail（安全默认）
          role={undefined}
          onRetry={onRetry}
          onRefill={onSuggest}
        />
      )}
      {turn.outcome === 'failed' && !turn.error && (
        <ErrorCard
          code={
            turn.transportError === 'SESSION_CONFLICT'
              ? 'SESSION_CONFLICT'
              : turn.transportError === 'TASK_NOT_FOUND' || turn.transportError === 'async_expired'
                ? 'TASK_NOT_FOUND'
                : 'INTERNAL'
          }
          message={
            turn.transportError === 'no_event_timeout'
              ? '长时间没有收到任何事件，已终止本次查询'
              : turn.transportError === 'SESSION_CONFLICT'
                ? '该会话正在处理上一个问题，请稍候'
                : turn.transportError === 'async_expired'
                  ? '结果已过期（超过 1 小时），请重新提问'
                  : turn.transportError === 'async_failed'
                    ? '后台查询执行失败'
                    : '查询过程中发生错误'
          }
          traceId={turn.taskId ?? ''}
          retryable={turn.transportError === 'SESSION_CONFLICT' || turn.transportError === 'async_failed'}
          onRetry={onRetry}
          onRefill={onSuggest}
        />
      )}
      {turn.outcome === 'stopped' && (
        <div
          role="status"
          style={{
            fontSize: 12,
            color: tokens.color.text.secondary,
            background: tokens.color.neutral.bg,
            border: `1px solid ${tokens.color.neutral.border}`,
            borderRadius: tokens.radius.md,
            padding: `${tokens.space.xxs}px ${tokens.space.xs}px`,
          }}
        >
          查询已取消
          <Button type="link" size="small" style={{ fontSize: 12, padding: '0 4px' }} onClick={onReaskClarify}>
            重新提问
          </Button>
        </div>
      )}

      {/* 澄清后再次收到新澄清 → 替换上一张（不累积）；异常码保留卡片（§4.9） */}
      {turn.outcome === 'failed' && turn.error?.code === 'CLARIFY_INVALID_OPTION' && turn.clarify && (
        <ClarifyCard
          clarifyId={turn.clarify.clarify_id}
          question={turn.clarify.question}
          reason={String(turn.clarify.reason)}
          options={turn.clarify.options}
          expiresAt={(turn.clarifyReceivedAt ?? Date.now()) + CLARIFY_TTL_MS}
          errorText="该选项已失效，请重新选择"
          onAnswer={(v) => onClarifyAnswer(turn.clarify!.clarify_id, v)}
        />
      )}
    </section>
  );
}

/** 两轮 caveats 的「时间范围」条目是否相同（纯字符串比较，不做业务推断） */
function sameTimeCaveat(a: string[], b: string[]): boolean {
  const pick = (arr: string[]) => arr.find((x) => x.startsWith('时间范围：'));
  const pa = pick(a);
  const pb = pick(b);
  return !!pa && pa === pb;
}

export { API_BASE };