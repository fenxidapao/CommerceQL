/**
 * 异常页面（/403、/404、/500）—— 06 §2.1 路由表
 * - 403 用 refuse 语义色、500 用 error 语义色、404 用 neutral
 * - 统一提供「返回会话页」动作
 */
import { useNavigate } from 'react-router-dom';
import { Button } from 'antd';
import { tokens } from '../theme/tokens';

interface Tone {
  bg: string;
  border: string;
  text: string;
}

function ErrorShell({
  testId,
  title,
  description,
  tone,
}: {
  testId: string;
  title: string;
  description: string;
  tone: Tone;
}) {
  const navigate = useNavigate();
  return (
    <div
      data-testid={testId}
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: tokens.color.neutral.bg,
        padding: tokens.space.lg,
      }}
    >
      <div
        style={{
          width: 420,
          maxWidth: '100%',
          background: tone.bg,
          border: `1px solid ${tone.border}`,
          color: tone.text,
          borderRadius: tokens.radius.lg,
          padding: tokens.space.lg,
          textAlign: 'center',
        }}
      >
        <div style={{ fontSize: tokens.font.size.h1, lineHeight: `${tokens.font.lineHeight.h1}px`, fontWeight: tokens.font.weight.medium }}>
          {title}
        </div>
        <div style={{ marginTop: tokens.space.xs, fontSize: tokens.font.size.body }}>{description}</div>
        <Button
          type="primary"
          style={{ marginTop: tokens.space.md }}
          onClick={() => navigate('/chat')}
        >
          返回会话页
        </Button>
      </div>
    </div>
  );
}

export function ForbiddenPage() {
  return (
    <ErrorShell
      testId="page-403"
      title="无权访问该页面"
      description="当前角色没有访问该页面的权限。如需查看，请联系管理员调整你的角色范围。"
      tone={tokens.color.refuse}
    />
  );
}

export function NotFoundPage() {
  return (
    <ErrorShell
      testId="page-404"
      title="页面不存在"
      description="链接可能已失效或地址输入有误，请检查后重试。"
      tone={tokens.color.neutral}
    />
  );
}

export function ServerErrorPage() {
  return (
    <ErrorShell
      testId="page-500"
      title="服务异常"
      description="服务端暂时无法处理该请求，请稍后重试。"
      tone={tokens.color.error}
    />
  );
}