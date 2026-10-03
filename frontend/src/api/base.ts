/**
 * API 前缀的**唯一出处**（06 §9；所有请求都拼 `${API_BASE}/...`）。
 *
 * 🔴 为什么要有这一个文件，而不是每个客户端各写一遍模板串：
 *   改之前四处都写 `${import.meta.env.VITE_API_BASE_URL}/api/v1`，而**生产构建没有 `.env.production`**
 *   ⇒ Vite 把未定义的变量替换成 `undefined` ⇒ 产物里落的是字面量 `"undefined/api/v1"`
 *   （现测：`frontend/dist/assets/index-*.js` 内该串出现 3 次）。症状是"页面能打开、健康点恒灰、
 *   任何提问都失败"，而**类型层面看不出来** —— 旧声明把该变量写成必填 `string`，
 *   于是 `undefined` 被当成合法值。同源代理才是生产形态的正解
 *   （`deploy/nginx.conf` 已把 `/api` 反代到 `api:8000`）⇒ 缺省取空串 = 相对路径，
 *   并由 `.env.production` 显式钉住同一语义（两层都在，不靠兜底活着）。
 */
const RAW = import.meta.env.VITE_API_BASE_URL;

/** 去掉尾部斜杠：`http://host:8000/` ＋ `/api/v1` 会拼成双斜杠，Vite 不替我们管这件事。 */
export const API_ORIGIN = (typeof RAW === 'string' ? RAW : '').replace(/\/+$/, '');

export const API_BASE = `${API_ORIGIN}/api/v1`;
