/**
 * 埋点（06 §13.2 埋点清单）
 * - ⚠️ 红线：**禁止上报 question 原文**（只允许枚举值、耗时、计数等）
 * - 当前阶段只做本地日志（无上报端点，不擅自调用契约外端点）；接入后端后替换 send 实现即可
 */

export interface TrackProps {
  [k: string]: string | number | boolean | undefined;
}

/** 06 §13.2 允许的埋点事件名（白名单，防止随手造事件） */
export type TrackEvent =
  | 'ui_first_event'
  | 'ui_terminal'
  | 'ui_sql_shown'
  | 'ui_data_shown'
  | 'ui_refuse_not_expected'
  | 'ui_feedback_submit'
  | 'ui_permission_feedback'
  | 'ui_contract_violation'
  | 'ui_chart_render_failed'
  | 'ui_clarify_answered'
  | 'ui_async_poll_result';

/** 禁止出现的敏感键（question 原文/答案内容） */
const FORBIDDEN_KEYS = ['question', 'text', 'sql', 'answer', 'comment', 'title'];

export function track(event: TrackEvent, props: TrackProps = {}): void {
  for (const k of Object.keys(props)) {
    if (FORBIDDEN_KEYS.includes(k)) {
      console.warn('[ui_track_forbidden_key]', event, k);
      return;
    }
  }
  // 无上报端点（不属于契约端点清单）→ 本地日志，便于联调复核
  console.debug('[track]', event, props);
}