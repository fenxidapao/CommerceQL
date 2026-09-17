/**
 * C9 ClarifyCard 澄清卡（06 §4.9，异常态 1/4）
 * - 语义色 clarify（紫），不是红/黄：澄清是"需要你补一句话"，不是出错
 * - 5 分钟倒计时（expiresAt 可注入，测试不必真等 5 分钟）：>60s neutral / ≤60s degraded 加粗 / 归零禁用
 *   + 「澄清已超时」+ 「重新提问」
 * - 选项 ≤4（>4 只渲染前 4 并记日志）；selected_value 与 free_text 二选一（A.4）
 * - role="alert"；倒计时 aria-live="off"（每秒播报会打断屏幕阅读器），仅在剩余 60s 时播报一次
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Input } from 'antd';
import { CommentOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';
import type { ClarifyOption } from '../api/types';

export interface ClarifyCardProps {
  clarifyId: string;
  question: string;
  /** clarify.reason 原文（如 ambiguous_field_binding），UI 只透传不解释 */
  reason: string;
  options: ClarifyOption[];
  /** 前端计算：收到事件时刻 + 5 分钟（A.13） */
  expiresAt: number;
  onAnswer: (v: { selected_value?: string; free_text?: string }) => void;
  /** 超时后的「重新提问」：把原问题填回 AskBox，不自动提交 */
  onReask?: () => void;
  /** CLARIFY_INVALID_OPTION(422) 等 inline 错误：保留卡片，不清空已输入内容 */
  errorText?: string;
  submitting?: boolean;
}

const MAX_OPTIONS = 4;

export function ClarifyCard({
  question,
  reason,
  options,
  expiresAt,
  onAnswer,
  onReask,
  errorText,
  submitting,
}: ClarifyCardProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [freeMode, setFreeMode] = useState(false);
  const [freeText, setFreeText] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const announced = useRef(false);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const remainMs = Math.max(0, expiresAt - now);
  const remainSec = Math.floor(remainMs / 1000);
  const expired = remainSec <= 0;
  const soon = !expired && remainSec <= 60;

  useEffect(() => {
    if (soon && !announced.current) announced.current = true;
  }, [soon]);

  const mm = String(Math.floor(remainSec / 60)).padStart(2, '0');
  const ss = String(remainSec % 60).padStart(2, '0');

  const shown = options.slice(0, MAX_OPTIONS);
  if (options.length > MAX_OPTIONS) {
    console.warn('[ui_clarify_options_overflow]', options.length);
  }

  const canSubmit = !expired && !submitting && (freeMode ? freeText.trim().length > 0 : selected !== null);

  const submit = () => {
    if (!canSubmit) return;
    if (freeMode) onAnswer({ free_text: freeText.trim() });
    else if (selected !== null) onAnswer({ selected_value: selected });
  };

  return (
    <div
      data-testid="c9-clarify-card"
      role="alert"
      style={{
        opacity: expired ? 0.6 : 1,
        background: expired ? tokens.color.neutral.bg : tokens.color.clarify.bg,
        border: `1px solid ${expired ? tokens.color.neutral.border : tokens.color.clarify.border}`,
        borderRadius: tokens.radius.lg,
        padding: tokens.space.sm,
        color: tokens.color.clarify.text,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <CommentOutlined aria-hidden />
          需要确认一下
        </span>
        <span
          data-testid="c9-countdown"
          aria-live="off"
          className="tabular-nums"
          style={{
            fontSize: 12,
            color: soon ? tokens.color.degraded.text : tokens.color.neutral.text,
            fontWeight: soon ? 500 : 400,
          }}
        >
          {expired ? '已超时' : `剩余 ${mm}:${ss}`}
        </span>
      </div>
      <span className="sr-only" aria-live="polite">
        {soon ? '澄清将在 1 分钟后超时' : ''}
      </span>

      <div
        style={{
          fontSize: tokens.font.size.h2,
          lineHeight: `${tokens.font.lineHeight.h2}px`,
          margin: '4px 0 8px',
          color: tokens.color.text.primary,
        }}
      >
        {question}
      </div>
      <div style={{ fontSize: 12, color: tokens.color.text.tertiary, marginBottom: 8 }}>原因：{reason}</div>

      {expired ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: tokens.color.text.secondary }}>
          澄清已超时
          {onReask && (
            <Button type="primary" size="small" onClick={onReask}>
              重新提问
            </Button>
          )}
        </div>
      ) : (
        <>
          <div role="radiogroup" aria-label="澄清选项">
            {shown.map((o) => {
              const active = !freeMode && selected === o.value;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    setSelected(o.value);
                    setFreeMode(false);
                  }}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    height: 44,
                    marginBottom: 8,
                    padding: '4px 10px',
                    borderRadius: tokens.radius.md,
                    border: `1px solid ${active ? tokens.color.clarify.border : tokens.color.neutral.border}`,
                    background: active ? '#fff' : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontSize: tokens.font.size.body, color: tokens.color.text.primary }}>{o.label}</div>
                  {o.asset && <div style={{ fontSize: 12, color: tokens.color.text.tertiary }}>{o.asset}</div>}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => {
              setFreeMode((v) => !v);
              setSelected(null);
            }}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              fontSize: 12,
              color: tokens.color.brand.solid,
              marginBottom: 8,
            }}
          >
            都不是，我补充说明
          </button>
          {freeMode && (
            <Input
              size="small"
              maxLength={200}
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder="补充说明（与选项二选一）"
              aria-label="澄清补充说明"
              style={{ marginBottom: 8 }}
            />
          )}

          {errorText && (
            <div data-testid="c9-clarify-error" style={{ fontSize: 12, color: tokens.color.error.text, marginBottom: 8 }}>
              {errorText}
            </div>
          )}

          <Button type="primary" size="small" disabled={!canSubmit} loading={submitting} onClick={submit}>
            提交
          </Button>
        </>
      )}
    </div>
  );
}