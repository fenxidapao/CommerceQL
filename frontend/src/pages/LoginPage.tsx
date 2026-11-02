/**
 * 登录页（/login）—— 06 §9.1 登录页壳
 * - Phase B B3：接真实 `POST /api/v1/auth/login`；token 只放内存（`setToken`）
 * - 统一错误文案由后端给（未知用户与错密码同一句），前端不自行区分
 * - 开发态仍保留粘贴 token 的调试入口（VITE_ENABLE_DEBUG_PANEL === 'true'）
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Input } from 'antd';
import { ApiError, login } from '../api/client';
import { setToken } from '../api/queryStream';
import { tokens } from '../theme/tokens';

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [stubToken, setStubToken] = useState('');
  const debugEnabled = import.meta.env.VITE_ENABLE_DEBUG_PANEL === 'true';

  const onSubmit = async () => {
    if (!username.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const data = await login(username.trim(), password);
      setToken(data.access_token);
      navigate('/chat');
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ code: err.code, message: err.message });
      } else {
        setError({ code: 'INTERNAL', message: '登录失败，请稍后重试' });
      }
    } finally {
      setLoading(false);
    }
  };

  const onStubLogin = () => {
    setToken(stubToken.trim() || null);
    navigate('/chat');
  };

  return (
    <div
      data-testid="page-login"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: tokens.color.neutral.bg,
        padding: tokens.space.lg,
      }}
    >
      <div
        style={{
          width: 360,
          maxWidth: '100%',
          background: '#fff',
          border: `1px solid ${tokens.color.neutral.border}`,
          borderRadius: tokens.radius.lg,
          boxShadow: tokens.shadow.raise,
          padding: tokens.space.lg,
          textAlign: 'center',
        }}
      >
        <div style={{ fontSize: tokens.font.size.h1, lineHeight: `${tokens.font.lineHeight.h1}px`, fontWeight: tokens.font.weight.medium }}>
          CommerceQL
        </div>
        <div style={{ marginTop: tokens.space.xxs, fontSize: tokens.font.size.body, color: tokens.color.text.secondary }}>
          电商数据分析 Agent
        </div>

        <Input
          placeholder="用户名"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ marginTop: tokens.space.lg }}
          onPressEnter={() => void onSubmit()}
        />
        <Input.Password
          placeholder="密码"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ marginTop: tokens.space.xs }}
          onPressEnter={() => void onSubmit()}
        />
        {error && (
          <Alert
            data-testid="login-error"
            type="error"
            showIcon
            style={{ marginTop: tokens.space.sm, textAlign: 'left' }}
            message={error.message}
            description={`错误码：${error.code}`}
          />
        )}
        <Button
          type="primary"
          block
          loading={loading}
          disabled={!username.trim() || !password}
          style={{ marginTop: tokens.space.md }}
          onClick={() => void onSubmit()}
        >
          登录
        </Button>

        {debugEnabled && (
          <div style={{ marginTop: tokens.space.md, textAlign: 'left' }}>
            <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              调试入口（仅开发态可见）
            </div>
            <Input
              size="small"
              placeholder="粘贴测试 token"
              value={stubToken}
              onChange={(e) => setStubToken(e.target.value)}
              style={{ marginTop: tokens.space.xxs }}
            />
            <Button size="small" block style={{ marginTop: tokens.space.xs }} onClick={onStubLogin}>
              使用测试 token 进入
            </Button>
          </div>
        )}
      </div>

      <div
        style={{
          marginTop: tokens.space.md,
          fontSize: tokens.font.size.caption,
          color: tokens.color.text.tertiary,
          maxWidth: 360,
          textAlign: 'center',
        }}
      >
        课程演示账号由后端本地注册；注册开关默认关闭（AUTH_ALLOW_REGISTRATION）
      </div>
    </div>
  );
}
