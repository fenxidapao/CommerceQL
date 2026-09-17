/**
 * C1 AskBox 提问框（06 §4.1）
 * - 流式中：输入框可打字不可提交，按钮变「停止」（error 语义描边）
 * - 限流：禁用 + 倒计时（据 rateLimitResetAt）；预算熔断 / 服务不可用：禁用 + 专属文案
 * - 409 SESSION_CONFLICT 不走任何禁用态（由 queryStream 自动重试，§10.4）
 * - 500 字上限；>450 显示计数；Enter 提交 / Shift+Enter 换行；↑ 回溯历史（本会话 ≤20 条）
 * - 高级选项（explain / chart_preference / max_rows≤5000）仅 VITE_ENABLE_DEBUG_PANEL 可见
 */
import { useEffect, useRef, useState } from 'react';
import { Button, InputNumber, Popover, Select, Switch } from 'antd';
import { SendOutlined, StopOutlined, SettingOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { ChartPreference, QueryOptions } from '../api/types';

const MAX_LEN = 500;
const HISTORY_MAX = 20;

const CHART_PREF_OPTIONS: { value: ChartPreference; label: string }[] = [
  { value: 'auto', label: '自动' },
  { value: 'line', label: '折线' },
  { value: 'bar', label: '柱状' },
  { value: 'stacked_bar', label: '堆叠柱' },
  { value: 'pie', label: '饼环' },
  { value: 'table', label: '表格' },
  { value: 'kpi', label: '单值' },
  { value: 'none', label: '不画图' },
];

export interface AskBoxProps {
  sessionId: string | null;
  streaming: boolean;
  disabled: boolean;
  disabledReason?: 'rate_limited' | 'budget_exhausted' | 'no_scope';
  /** 秒级时间戳，来自 X-RateLimit-Reset */
  rateLimitResetAt?: number;
  onSubmit: (question: string, opts: QueryOptions) => void;
  onAbort: () => void;
  /** 空状态示例问题（3–5 条，静态，由页面传入） */
  examples?: string[];
  /** 外部回填（建议问法 / 收窄范围重问）：填入但不提交 */
  fillText?: string | null;
  onFillConsumed?: () => void;
}

export function AskBox({
  streaming,
  disabled,
  disabledReason,
  rateLimitResetAt,
  onSubmit,
  onAbort,
  examples,
  fillText,
  onFillConsumed,
}: AskBoxProps) {
  const [value, setValue] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [, setHistoryIdx] = useState(-1);
  const [now, setNow] = useState(() => Date.now());
  const [explain, setExplain] = useState(true);
  const [chartPref, setChartPref] = useState<ChartPreference>('auto');
  const [maxRows, setMaxRows] = useState(5000);
  const ref = useRef<HTMLTextAreaElement>(null);

  const debugPanel = import.meta.env.VITE_ENABLE_DEBUG_PANEL === 'true';

  // 页面加载后自动聚焦
  useEffect(() => {
    ref.current?.focus();
  }, []);

  // 限流倒计时心跳
  useEffect(() => {
    if (disabledReason !== 'rate_limited' || !rateLimitResetAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [disabledReason, rateLimitResetAt]);

  // 外部回填（不自动提交，让用户自己确认）
  useEffect(() => {
    if (fillText) {
      setValue(fillText);
      onFillConsumed?.();
      ref.current?.focus();
    }
  }, [fillText, onFillConsumed]);

  const trimmed = value.trim();
  const canSubmit = !disabled && !streaming && trimmed.length > 0;

  const submit = () => {
    if (!canSubmit) return;
    setHistory((h) => [trimmed, ...h].slice(0, HISTORY_MAX));
    setHistoryIdx(-1);
    onSubmit(trimmed, { explain, chart_preference: chartPref, max_rows: maxRows });
    setValue('');
    ref.current?.focus(); // 提交成功后保持停留并清空，便于连续追问
  };

  const remainSec = rateLimitResetAt ? Math.max(0, rateLimitResetAt - Math.floor(now / 1000)) : 0;
  const mm = String(Math.floor(remainSec / 60)).padStart(2, '0');
  const ss = String(remainSec % 60).padStart(2, '0');

  const hint = streaming
    ? '正在处理上一轮，完成后可继续提问'
    : disabled && disabledReason === 'rate_limited'
      ? `请求过于频繁，${mm}:${ss} 后可重试`
      : disabled && disabledReason === 'budget_exhausted'
        ? '今日额度已用尽，请联系管理员'
        : disabled && disabledReason === 'no_scope'
          ? '服务暂时不可用，请稍后再试'
          : null;

  return (
    <div data-testid="c1-ask-box" style={{ width: '100%' }}>
      {examples && examples.length > 0 && !value && (
        <div style={{ marginBottom: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {examples.map((q) => (
            <Button
              key={q}
              size="small"
              type="text"
              style={{ color: tokens.color.brand.solid, fontSize: 12 }}
              onClick={() => setValue(q)}
            >
              {q}
            </Button>
          ))}
        </div>
      )}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          border: `1px solid ${tokens.color.neutral.border}`,
          borderRadius: tokens.radius.lg,
          padding: 8,
          background: '#fff',
        }}
      >
        <textarea
          ref={ref}
          value={value}
          rows={1}
          maxLength={MAX_LEN}
          disabled={disabled}
          placeholder={disabled ? '当前不可提问' : '用一句话描述你想看的数据，例如：上个月各品类的 GMV'}
          aria-label="提问输入框"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (streaming) return; // 流式中回车不提交（下方有可见文案说明）
              submit();
            } else if (e.key === 'ArrowUp' && !value) {
              // 历史回溯：仅同一会话，最多 20 条，纯前端
              e.preventDefault();
              setHistoryIdx((i) => {
                const next = Math.min(i + 1, history.length - 1);
                if (history[next]) setValue(history[next]);
                return next;
              });
            }
          }}
          onInput={(e) => {
            // 1–4 行自适应，超过内部滚动
            const el = e.currentTarget;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, 4 * 22 + 8)}px`;
          }}
          style={{
            flex: 1,
            border: 'none',
            outline: 'none',
            resize: 'none',
            fontSize: tokens.font.size.body,
            lineHeight: '22px',
            fontFamily: 'inherit',
            background: 'transparent',
          }}
        />
        {value.length > 450 && (
          <span style={{ fontSize: 12, color: tokens.color.text.tertiary, alignSelf: 'center' }}>
            {value.length}/{MAX_LEN}
          </span>
        )}
        {debugPanel && (
          <Popover
            trigger="click"
            title="高级选项"
            content={
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 240 }}>
                <label style={{ fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  我看得懂 SQL（展示 SQL 卡片）
                  <Switch size="small" checked={explain} onChange={setExplain} />
                </label>
                <label style={{ fontSize: 12 }}>
                  图表偏好
                  <Select
                    size="small"
                    value={chartPref}
                    options={CHART_PREF_OPTIONS}
                    onChange={setChartPref}
                    style={{ width: '100%', marginTop: 4 }}
                  />
                </label>
                <label style={{ fontSize: 12 }}>
                  数据量上限（≤ 5000）
                  <InputNumber
                    size="small"
                    min={1}
                    max={5000}
                    value={maxRows}
                    onChange={(v) => setMaxRows(Math.min(v ?? 5000, 5000))}
                    style={{ width: '100%', marginTop: 4 }}
                  />
                </label>
              </div>
            }
          >
            <Button type="text" size="small" icon={<SettingOutlined />} aria-label="高级选项" />
          </Popover>
        )}
        {streaming ? (
          <Button danger icon={<StopOutlined />} onClick={onAbort} aria-label="停止当前查询">
            停止
          </Button>
        ) : (
          <Button
            type="primary"
            icon={<SendOutlined />}
            disabled={!canSubmit}
            onClick={submit}
            aria-label="发送问题"
          >
            发送
          </Button>
        )}
      </div>
      {hint && (
        <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginTop: 4 }} role="status">
          {hint}
        </div>
      )}
    </div>
  );
}
