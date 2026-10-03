/**
 * `src/api/base.ts` 的回归测试（A5 之后发现的 v1 阻断面）。
 *
 * 守的是这一件事：**没给 `VITE_API_BASE_URL` 时必须落到同源相对路径**，
 * 而不是拼出字面量 `"undefined/api/v1"`。改之前四处各写一遍模板串、
 * production 又没有 `.env.production` ⇒ 产物里就是 `"undefined/api/v1"`，
 * 页面能打开但每个请求都打到不存在的路径上（现测 dist 内该串 3 处）。
 * 类型声明把它写成必填 `string` ⇒ 这类错误过不了运行期、也过不了类型检查，只能靠断言。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

async function loadBase(): Promise<typeof import('./base')> {
  vi.resetModules();
  return import('./base');
}

describe('API_BASE 的推导（唯一出处 = base.ts）', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
  });

  it('变量缺失 ⇒ 同源相对路径，绝不是 "undefined/api/v1"', async () => {
    const { API_BASE, API_ORIGIN } = await loadBase();
    expect(API_ORIGIN).toBe('');
    expect(API_BASE).toBe('/api/v1');
    expect(API_BASE).not.toContain('undefined');
  });

  it('给了绝对地址 ⇒ 原样拼 /api/v1', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000');
    const { API_BASE } = await loadBase();
    expect(API_BASE).toBe('http://localhost:8000/api/v1');
  });

  it('尾部斜杠要归一（双斜杠会让 nginx 的 location 匹配走偏）', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.internal:8000///');
    const { API_BASE } = await loadBase();
    expect(API_BASE).toBe('http://api.internal:8000/api/v1');
  });

  it('显式空串 ⇒ 与"缺失"同义（.env.example 里那条"生产留空"的写法要成立）', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    const { API_BASE } = await loadBase();
    expect(API_BASE).toBe('/api/v1');
  });
});
