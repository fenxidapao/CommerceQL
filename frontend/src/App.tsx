/**
 * 路由装配（06 §2.1 页面清单，P0 五页 + 三错误页）
 * - P1 的 /admin/audit、/settings 不在此装配（分期未落地，避免造出无数据源的页面）
 * - 未匹配 → 404（不静默跳转）
 * - 角色门禁：/eval/* 为管理员视角，P0 无"当前用户角色"来源（契约无 /me，登录端点 D-H 未决），
 *   故此处不加前端角色判断（前端零判断权）；后端 403 时由页面渲染 ErrorCard(FORBIDDEN_SCOPE)
 */
import { Navigate, Route, Routes } from 'react-router-dom';
import {
  ChatPage,
  EvalReportPage,
  EvalRunsPage,
  ForbiddenPage,
  LoginPage,
  NotFoundPage,
  SemanticPage,
  ServerErrorPage,
} from './pages';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/chat/:sessionId" element={<ChatPage />} />
      <Route path="/semantic/metrics" element={<SemanticPage />} />
      <Route path="/eval/runs" element={<EvalRunsPage />} />
      <Route path="/eval/reports/:runId" element={<EvalReportPage />} />
      <Route path="/403" element={<ForbiddenPage />} />
      <Route path="/404" element={<NotFoundPage />} />
      <Route path="/500" element={<ServerErrorPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}