/**
 * C3 StageBar 阶段条（06 §4.3）
 * - 只渲染契约 6 个 stage 聚合成的 5 段可见步骤，禁止暴露 LangGraph 内部节点名
 * - 步骤耗时 = 相邻两步 elapsed_ms 差值
 * - role="status" + aria-live="polite"
 */
import { CheckOutlined, MinusOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { Stage } from '../api/types';

interface StepDef {
  label: string;
  stages: Stage[];
}

/** 6 stage → 5 段可见步骤（顺序即展示顺序） */
const STEPS: StepDef[] = [
  { label: '理解问题', stages: ['intent'] },
  { label: '定位数据', stages: ['schema_linking', 'plan_ready'] },
  { label: '生成 SQL', stages: ['sql_ready'] },
  { label: '安全校验', stages: ['gate_passed'] },
  { label: '执行取数', stages: ['executing'] },
];

export interface StageBarProps {
  /** 已收到的 stage 事件（按到达顺序），elapsedMsList 与之一一对应 */
  received: Stage[];
  /** 每条 stage 事件的 elapsed_ms（按到达顺序） */
  elapsedMsList: number[];
  status: 'running' | 'done' | 'stopped';
  /** 澄清后重新执行时标注「已澄清 N 次」 */
  clarifyCount?: number;
}

function formatMs(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export function StageBar({ received, elapsedMsList, status, clarifyCount }: StageBarProps) {
  // 降级：未收到任何 stage（仅 ack）→ 骨架 + 「正在准备…」，不显示空 stepper
  if (received.length === 0) {
    return (
      <div
        data-testid="c3-stage-bar"
        role="status"
        aria-live="polite"
        aria-label="正在准备"
        style={{ height: tokens.size.stageBar, display: 'flex', alignItems: 'center', gap: 8 }}
      >
        <div className="cq-skeleton" style={{ width: 200, height: 16 }} />
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary }}>正在准备…</span>
      </div>
    );
  }

  // 找到每段的状态：done=该段所有关键 stage 已过；active=当前最新 stage 落在该段
  const lastStage = received[received.length - 1];
  const reachedIndex = (s: Stage) => {
    const i = STEPS.findIndex((st) => st.stages.includes(s));
    return i;
  };
  const currentIdx = reachedIndex(lastStage);

  const stepState = (idx: number): 'done' | 'active' | 'pending' | 'stopped' => {
    if (status === 'done') return 'done';
    if (status === 'stopped') {
      if (idx < currentIdx) return 'done';
      if (idx === currentIdx) return 'stopped';
      return 'pending';
    }
    if (idx < currentIdx) return 'done';
    if (idx === currentIdx) {
      // 该段的最后一个 stage 已到且后面还有段 → 该段算 done（流继续前进中）
      const step = STEPS[idx];
      const lastOfStep = step.stages[step.stages.length - 1];
      return received.includes(lastOfStep) && idx < STEPS.length - 1 ? 'done' : 'active';
    }
    return 'pending';
  };

  // 每段耗时：段内最后一条 stage 的 elapsed_ms − 上一段最后一条 stage 的 elapsed_ms
  const stepElapsed = (idx: number): number | null => {
    const step = STEPS[idx];
    let lastInStep = -1;
    for (let i = received.length - 1; i >= 0; i--) {
      if (step.stages.includes(received[i])) {
        lastInStep = i;
        break;
      }
    }
    if (lastInStep < 0) return null;
    const prevIdx = idx > 0 ? (() => {
      const prev = STEPS[idx - 1];
      for (let i = received.length - 1; i >= 0; i--) {
        if (prev.stages.includes(received[i])) return i;
      }
      return -1;
    })() : -1;
    const cur = elapsedMsList[lastInStep];
    const prev = prevIdx >= 0 ? elapsedMsList[prevIdx] : 0;
    return Math.max(0, cur - prev);
  };

  const totalElapsed = elapsedMsList[elapsedMsList.length - 1];
  const done = status === 'done';
  const neutral = done;

  return (
    <div
      data-testid="c3-stage-bar"
      role="status"
      aria-live="polite"
      aria-label={
        done
          ? `查询完成，总用时 ${formatMs(totalElapsed ?? 0)}`
          : status === 'stopped'
            ? '查询已停止'
            : `正在${STEPS[currentIdx]?.label ?? '处理'}，已用时 ${formatMs(totalElapsed ?? 0)}`
      }
      style={{ display: 'flex', alignItems: 'center', height: tokens.size.stageBar, gap: 0 }}
    >
      {clarifyCount ? (
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary, marginRight: 12 }}>
          已澄清 {clarifyCount} 次 · 已按你的选择重新校验并执行
        </span>
      ) : null}
      {STEPS.map((step, idx) => {
        const st = stepState(idx);
        const dotColor = neutral
          ? tokens.color.success.border
          : st === 'done'
            ? tokens.color.success.border
            : st === 'active'
              ? tokens.color.brand.solid
              : st === 'stopped'
                ? tokens.color.neutral.border
                : tokens.color.neutral.border;
        const elapsed = stepElapsed(idx);
        return (
          <div key={step.label} style={{ display: 'flex', alignItems: 'center' }}>
            {idx > 0 && (
              <span
                aria-hidden
                style={{
                  width: 24,
                  height: 2,
                  background:
                    st === 'pending' && status !== 'done' ? tokens.color.neutral.border : tokens.color.success.border,
                    margin: '0 4px',
                }}
              />
            )}
            <span
              aria-hidden
              className={st === 'active' && status === 'running' ? 'cq-breathe' : undefined}
              style={{
                width: 16,
                height: 16,
                borderRadius: '50%',
                border: `2px solid ${dotColor}`,
                background: st === 'pending' ? 'transparent' : dotColor,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: 10,
              }}
            >
              {st === 'done' || done ? <CheckOutlined /> : st === 'stopped' ? <MinusOutlined /> : null}
            </span>
            <span style={{ fontSize: 12, color: tokens.color.text.secondary, marginLeft: 4 }}>{step.label}</span>
            {(st === 'done' || done) && elapsed !== null && (
              <span style={{ fontSize: 12, color: tokens.color.text.tertiary, marginLeft: 4 }}>
                {formatMs(elapsed)}
              </span>
            )}
            {st === 'stopped' && (
              <span style={{ fontSize: 12, color: tokens.color.text.tertiary, marginLeft: 4 }}>已停止</span>
            )}
          </div>
        );
      })}
      {done && totalElapsed !== undefined && (
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary, marginLeft: 12 }}>
          总用时 {formatMs(totalElapsed)}
        </span>
      )}
    </div>
  );
}
