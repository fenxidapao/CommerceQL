/**
 * C15 HealthIndicator 健康状态点（06 §4.15，v1.2.2）
 * - 唯一数据源：GET /healthz（A.8.4 聚合详情），60s 轮询，页面隐藏时暂停
 * - ok=实心绿点 / degraded=空心琥珀点（软依赖失败，不是故障）/ unhealthy=实心红点+禁用 AskBox / 请求失败=灰点
 * - 只在状态跨级变化时播报（aria-live polite）
 */
import { useEffect, useRef, useState } from 'react';
import { Popover } from 'antd';
import { tokens } from '../theme/tokens';
import type { HealthzResponse } from '../api/types';

const API_BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`;
const POLL_INTERVAL_MS = 60_000;

type DotLevel = 'ok' | 'degraded' | 'unhealthy' | 'unknown';

const LEVEL_LABEL: Record<DotLevel, string> = {
  ok: '服务正常',
  degraded: '部分能力降级中',
  unhealthy: '服务不可用',
  unknown: '状态未知',
};

export interface HealthIndicatorProps {
  /** unhealthy（硬依赖失败）时通知页面禁用 AskBox（06 §4.1 服务不可用态） */
  onLevelChange?: (level: DotLevel) => void;
}

export function HealthIndicator({ onLevelChange }: HealthIndicatorProps) {
  const [level, setLevel] = useState<DotLevel>('unknown');
  const [detail, setDetail] = useState<HealthzResponse | null>(null);
  const levelRef = useRef<DotLevel>('unknown');

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      if (document.hidden) return; // 页面隐藏时暂停，恢复可见时下一轮立即打
      try {
        const resp = await fetch(`${API_BASE}/healthz`);
        if (stopped) return;
        if (resp.status === 503) {
          setLevel('unhealthy');
          setDetail(await resp.json().catch(() => null));
        } else if (resp.ok) {
          const body = (await resp.json()) as HealthzResponse;
          setDetail(body);
          setLevel(body.status === 'degraded' ? 'degraded' : 'ok');
        } else {
          setLevel('unknown');
          setDetail(null);
        }
      } catch {
        if (!stopped) {
          // 请求失败/超时 → 灰点"状态未知"，不显示红色（区分"服务挂了"与"我看不到它"）
          setLevel('unknown');
          setDetail(null);
        }
      }
    };

    const loop = async () => {
      await tick();
      if (!stopped) timer = setTimeout(loop, POLL_INTERVAL_MS);
    };
    void loop();

    const onVisible = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  useEffect(() => {
    if (levelRef.current !== level) {
      levelRef.current = level;
      onLevelChange?.(level);
    }
  }, [level, onLevelChange]);

  const colorMap: Record<DotLevel, { border: string; fill: string }> = {
    ok: { border: tokens.color.success.border, fill: tokens.color.success.border },
    degraded: { border: tokens.color.degraded.border, fill: 'transparent' }, // 空心琥珀点
    unhealthy: { border: tokens.color.error.border, fill: tokens.color.error.border },
    unknown: { border: tokens.color.neutral.border, fill: tokens.color.neutral.border },
  };
  const c = colorMap[level];

  const softDeps: Array<[string, boolean | undefined, string]> = detail
    ? [
        ['llm_reachable', detail.checks.llm_reachable, '智能解析（LLM）'],
        ['embedding_reachable', detail.checks.embedding_reachable, '向量检索（Embedding）'],
      ]
    : [];

  return (
    <Popover
      content={
        <div style={{ fontSize: 12, maxWidth: 260 }}>
          <div style={{ marginBottom: 4 }}>{LEVEL_LABEL[level]}</div>
          {level === 'degraded' &&
            softDeps.map(([key, ok, label]) => (
              <div key={key} style={{ color: ok ? tokens.color.text.tertiary : tokens.color.degraded.text }}>
                {label}：{ok ? '正常' : '异常'}
              </div>
            ))}
          {level === 'unhealthy' && <div>硬依赖失败，提问暂不可用，请稍后再试</div>}
        </div>
      }
      trigger="hover"
    >
      <span
        data-testid="c15-health-indicator"
        role="status"
        aria-live="polite"
        aria-label={`服务状态：${LEVEL_LABEL[level]}`}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 8px', cursor: 'default' }}
      >
        <span
          aria-hidden
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            border: `2px solid ${c.border}`,
            background: c.fill,
            display: 'inline-block',
          }}
        />
        <span style={{ fontSize: 12, color: tokens.color.text.tertiary }}>{LEVEL_LABEL[level]}</span>
      </span>
    </Popover>
  );
}
