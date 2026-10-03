/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * ⚠️ **刻意写成可选**：`npm run build`（production mode）不会读 `.env.development`，
   * 而本仓库此前**没有** `.env.production` ⇒ 该变量在构建期确实是 `undefined`。
   * 旧声明写成必填 `string`，于是 `${undefined}/api/v1` 这种拼法在类型层面一路绿灯、
   * 到运行时才变成字面量 `"undefined/api/v1"`（现测在 dist 里 3 处）。
   * 唯一读它的地方是 `src/api/base.ts`（带缺省与尾斜杠归一），别再在别处直接拼。
   */
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_APP_ENV?: 'dev' | 'prod';
  readonly VITE_ENABLE_DEBUG_PANEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
