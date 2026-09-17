/**
 * C12 ErrorCard 错误卡（06 §4.12，异常态 4/4）
 * - 覆盖 A.11 全 27 个错误码 + 未知码兜底（OK 为成功码，不在错误卡范围）
 * - trace_id 必须展示且可复制（A.14 第 10 条）；detail 仅 analyst / platform_admin 可见原文
 * - 最多 2 个动作按钮（主按钮 1 个）；「重试」由页面复用同一 Idempotency-Key
 * - 辨析：SESSION_CONFLICT(409) ≠ RATE_LIMITED(429)（不喂 QuotaIndicator）；
 *   EXEC_RESOURCE_EXCEEDED 已开始执行 ≠ COST_TOO_HIGH 一行未跑；
 *   空结果不是错误，不得走本卡
 */
import { useEffect, useState } from 'react';
import { Button, message as antdMessage } from 'antd';
import { useNavigate } from 'react-router-dom';
import { CloseCircleOutlined, CopyOutlined } from '@ant-design/icons';
import { tokens } from '../theme/tokens';

type Tone = 'error' | 'refuse' | 'degraded' | 'info' | 'clarify';

export interface ErrorCardProps {
  code: string;
  message: string;
  detail?: Record<string, unknown>;
  traceId: string;
  retryable: boolean;
  /** JWT 中的 role（判定必须基于 JWT，不依赖后端未返回字段） */
  role?: string;
  /** RATE_LIMITED 倒计时秒数（来自 Retry-After，按桶） */
  retryAfterSec?: number;
  onRetry?: () => void;
  /** 把建议文案填入 AskBox（不自动提交） */
  onRefill?: (text: string) => void;
}

/** 语义色按 A.11 逐码映射（其余默认 error） */
const CODE_TONE: Record<string, Tone> = {
  FORBIDDEN_SCOPE: 'refuse',
  PII_BLOCKED: 'refuse',
  SESSION_NOT_FOUND: 'refuse',
  NO_DATA_ASSET: 'refuse',
  TASK_NOT_FOUND: 'degraded',
  SESSION_CONFLICT: 'degraded',
  CLARIFY_EXPIRED: 'degraded',
  COST_TOO_HIGH: 'degraded',
  EXEC_RESOURCE_EXCEEDED: 'degraded',
  RATE_LIMITED: 'degraded',
  LLM_UPSTREAM_ERROR: 'degraded',
  LLM_CONCURRENCY_EXCEEDED: 'degraded',
  EXEC_TIMEOUT: 'degraded',
  TASK_NOT_CANCELLABLE: 'info',
  AMBIGUOUS_QUERY: 'clarify',
};

const HEADER_LABEL: Record<Tone, string> = {
  error: '出错了',
  refuse: '已被拦截',
  degraded: '需要调整',
  info: '提示',
  clarify: '需要确认一下',
};

function toneColor(tone: Tone) {
  if (tone === 'refuse') return tokens.color.refuse;
  if (tone === 'degraded') return tokens.color.degraded;
  if (tone === 'info') return tokens.color.info;
  if (tone === 'clarify') return tokens.color.clarify;
  return tokens.color.error;
}

/** 主文案：后端 message 优先；个别码按 06 表格给定制前缀 */
function primaryText(code: string, message: string, detail?: Record<string, unknown>): string {
  switch (code) {
    case 'INVALID_REQUEST':
      return `请求参数有误：${String(detail?.field ?? message)}`;
    case 'GATE_AST_REJECTED':
      return `查询被安全校验拒绝：${String(detail?.violation ?? message)}`;
    case 'GATE_POLICY_REJECTED':
      return `查询违反了数据使用策略：${String(detail?.reason ?? message)}`;
    case 'SQL_SYNTAX_ERROR':
      return `已尝试 ${String(detail?.attempts ?? '多')} 次修正仍未生成有效查询`;
    case 'EXEC_RESOURCE_EXCEEDED':
      return `查询在执行中超出资源上限，已被中止（${String(detail?.limit_type ?? '资源')}）`;
    default:
      return message;
  }
}

export function ErrorCard({
  code,
  message,
  detail,
  traceId,
  retryable,
  role,
  retryAfterSec,
  onRetry,
  onRefill,
}: ErrorCardProps) {
  const navigate = useNavigate();
  const [showDetail, setShowDetail] = useState(false);
  const [copied, setCopied] = useState(false);
  const [remain, setRemain] = useState(retryAfterSec ?? 0);

  useEffect(() => {
    if (!retryAfterSec) return;
    setRemain(retryAfterSec);
    const t = setInterval(() => setRemain((v) => Math.max(0, v - 1)), 1000);
    return () => clearInterval(t);
  }, [retryAfterSec]);

  // 成功码不渲染错误卡；幂等冲突静默处理（用户侧不展示错误）
  if (code === 'OK' || code === 'IDEMPOTENCY_CONFLICT') return null;

  const tone = CODE_TONE[code] ?? 'error';
  const c = toneColor(tone);
  const unknown = !CODE_TONE[code] && code !== 'INTERNAL' && !KNOWN_ERRORS.has(code);
  const maySeeDetail = role === 'analyst' || role === 'platform_admin';

  const copyTrace = async () => {
    await navigator.clipboard.writeText(`code=${code} trace_id=${traceId} message=${message}`);
    setCopied(true);
    void antdMessage.success('已复制错误信息', 1.5);
    setTimeout(() => setCopied(false), 1500);
  };

  // 动作按钮：最多 2 个，主按钮在前
  const actions: { label: string; primary?: boolean; disabled?: boolean; onClick: () => void }[] = [];
  const reask = () => onRefill?.('请换一种问法：');
  switch (code) {
    case 'AUTH_FAILED':
    case 'TOKEN_REVOKED':
      actions.push({ label: '重新登录', primary: true, onClick: () => navigate('/login') });
      break;
    case 'FORBIDDEN_SCOPE':
      actions.push({ label: '查看我能查什么', primary: true, onClick: () => navigate('/semantic/metrics') });
      break;
    case 'TASK_NOT_FOUND':
    case 'CLARIFY_EXPIRED':
    case 'EXEC_TIMEOUT':
      actions.push({ label: code === 'EXEC_TIMEOUT' ? '收窄范围重问' : '重新提问', primary: true, onClick: reask });
      break;
    case 'SESSION_NOT_FOUND':
      actions.push({ label: '新建会话', primary: true, onClick: () => navigate('/chat') });
      break;
    case 'RUN_NOT_FOUND':
      actions.push({ label: '返回运行列表', primary: true, onClick: () => navigate('/admin/eval') });
      break;
    case 'DATASET_NOT_FOUND':
      actions.push({ label: '刷新评测集列表', primary: true, onClick: () => navigate('/admin/eval') });
      break;
    case 'COST_TOO_HIGH':
    case 'EXEC_RESOURCE_EXCEEDED':
      actions.push({ label: '收窄时间范围', primary: true, onClick: () => onRefill?.('请把时间范围收窄到：') });
      actions.push({ label: '增加筛选条件', onClick: () => onRefill?.('请增加筛选条件：') });
      break;
    case 'SQL_SYNTAX_ERROR':
      if (retryable) actions.push({ label: '重试', primary: true, disabled: false, onClick: () => onRetry?.() });
      actions.push({ label: '换个问法', onClick: reask });
      break;
    case 'RATE_LIMITED':
      actions.push({
        label: remain > 0 ? `重试（${remain}s）` : '重试',
        primary: true,
        disabled: remain > 0,
        onClick: () => onRetry?.(),
      });
      break;
    case 'SESSION_CONFLICT':
      actions.push({ label: '重试', primary: true, onClick: () => onRetry?.() });
      break;
    case 'INTERNAL':
      if (retryable) actions.push({ label: '重试', primary: true, onClick: () => onRetry?.() });
      actions.push({ label: copied ? '已复制' : '复制错误信息', onClick: () => void copyTrace() });
      break;
    case 'LLM_UPSTREAM_ERROR':
    case 'LLM_CONCURRENCY_EXCEEDED':
    case 'DB_UNAVAILABLE':
      actions.push({ label: '重试', primary: true, onClick: () => onRetry?.() });
      break;
    default:
      if (retryable) actions.push({ label: '重试', primary: true, onClick: () => onRetry?.() });
      actions.push({ label: copied ? '已复制' : '复制错误信息', onClick: () => void copyTrace() });
      break;
  }

  return (
    <div
      data-testid="c12-error-card"
      role="alert"
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: tokens.radius.lg,
        padding: tokens.space.sm,
        color: c.text,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
        <CloseCircleOutlined aria-hidden />
        {HEADER_LABEL[tone]}
      </div>
      <div style={{ fontSize: tokens.font.size.h2, lineHeight: `${tokens.font.lineHeight.h2}px`, marginTop: 4 }}>
        {primaryText(code, message, detail)}
        {unknown && (
          <span style={{ fontSize: 12, marginLeft: 6, opacity: 0.8 }}>
            发生了未预期的错误（{code}）
          </span>
        )}
      </div>

      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
        <span style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>错误编号：{traceId}</span>
        <Button
          type="text"
          size="small"
          icon={<CopyOutlined />}
          aria-label="复制错误编号"
          onClick={() => void navigator.clipboard.writeText(traceId)}
          style={{ color: 'inherit', fontSize: 12 }}
        >
          复制
        </Button>
      </div>

      {detail && Object.keys(detail).length > 0 && (
        <div style={{ marginTop: 4 }}>
          <Button type="link" size="small" style={{ fontSize: 12, padding: 0 }} onClick={() => setShowDetail((v) => !v)}>
            {showDetail ? '收起详请' : '展开详请'}
          </Button>
          {showDetail &&
            (maySeeDetail ? (
              <pre
                data-testid="c12-error-detail"
                style={{
                  margin: '4px 0 0',
                  padding: 8,
                  background: '#fff',
                  borderRadius: tokens.radius.sm,
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {JSON.stringify(detail, null, 2)}
              </pre>
            ) : (
              <div style={{ fontSize: 12, opacity: 0.8 }}>技术细节已隐藏</div>
            ))}
        </div>
      )}

      {actions.length > 0 && (
        <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
          {actions.slice(0, 2).map((a) => (
            <Button
              key={a.label}
              size="small"
              type={a.primary ? 'primary' : 'default'}
              disabled={a.disabled}
              onClick={a.onClick}
            >
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/** A.11 已知错误码（未知码兜底用） */
const KNOWN_ERRORS = new Set([
  'INVALID_REQUEST',
  'AUTH_FAILED',
  'TOKEN_REVOKED',
  'FORBIDDEN_SCOPE',
  'PII_BLOCKED',
  'TASK_NOT_FOUND',
  'SESSION_NOT_FOUND',
  'RUN_NOT_FOUND',
  'DATASET_NOT_FOUND',
  'AMBIGUOUS_QUERY',
  'TASK_NOT_CANCELLABLE',
  'IDEMPOTENCY_CONFLICT',
  'SESSION_CONFLICT',
  'CLARIFY_EXPIRED',
  'CLARIFY_INVALID_OPTION',
  'GATE_AST_REJECTED',
  'GATE_POLICY_REJECTED',
  'COST_TOO_HIGH',
  'EXEC_RESOURCE_EXCEEDED',
  'NO_DATA_ASSET',
  'SQL_SYNTAX_ERROR',
  'RATE_LIMITED',
  'INTERNAL',
  'LLM_UPSTREAM_ERROR',
  'LLM_CONCURRENCY_EXCEEDED',
  'DB_UNAVAILABLE',
  'EXEC_TIMEOUT',
]);