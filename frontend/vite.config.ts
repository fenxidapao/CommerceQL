import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 🔴 刻意**不写 rewrite**：生产侧 `deploy/nginx.conf:36` 是
        //   `location /api/ { proxy_pass http://commerceql_api; }` —— 不带 URI 的 proxy_pass
        //   会把原始路径**整段**转给上游，即 `/api/v1/healthz` 原样到后端（后端就挂在 `/api/v1` 上）。
        //   这里原先有一句 `rewrite: (p) => p.replace(/^\/api/, '')`，于是 dev 把 `/api` 剥掉
        //   ⇒ 上游收到 `/v1/healthz` = 404。而 `src/api/base.ts` 在没给 `VITE_API_BASE_URL` 时
        //   取**同源相对路径**（新克隆正是这种状态：`.env.development` 被 `.gitignore` 的
        //   `.env.*` 规则挡在库外，只有 `.env.example` 入库）⇒ 新克隆跑 `npm run dev` 会全站 404。
        //   两条路径必须同形：dev 与 prod 都说 `/api/v1/...`，谁都不剥前缀。
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    globals: false,
    css: false,
  },
});
