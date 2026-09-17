/**
 * 登录页（/login）—— 06 §9.1 登录页壳
 * - P0 为壳形态：主按钮走 OIDC 重定向形态；真实 IdP 未接入前只做提示
 * - 登录端点属架构未决项（D-H），token 只放内存（见 api/queryStream.ts）
 * - 开发态 stub token 入口仅在 VITE_ENABLE_DEBUG_PANEL === 'true' 时出现
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Input, message } from 'antd';
import { setToken } from '../api/queryStream';
import { tokens } from '../theme/tokens';

export function LoginPage() {
  const navigate = useNavigate();
  const [token, setTokenValue] = useState('');
  const debugEnabled = import.meta.env.VITE_ENABLE_DEBUG_PANEL === 'true';

  const onOidcLogin = () => {
    void message.info('登录方式待架构裁决（D-H）');
  };

  const onStubLogin = () => {
    setToken(token.trim() || null);
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

        <Button type="primary" block style={{ marginTop: tokens.space.lg }} onClick={onOidcLogin}>
          使用企业账号登录
        </Button>

        {/* 开发态 stub token 入口：默认环境变量下不显示 */}
        {debugEnabled && (
          <div style={{ marginTop: tokens.space.md, textAlign: 'left' }}>
            <div style={{ fontSize: tokens.font.size.caption, color: tokens.color.text.tertiary }}>
              调试入口（仅开发态可见）
            </div>
            <Input
              size="small"
              placeholder="粘贴测试 token"
              value={token}
              onChange={(e) => setTokenValue(e.target.value)}
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
        登录端点属架构未决项（D-H），当前为本地 stub，真实 OIDC 流程待裁决后接入
      </div>
    </div>
  );
}