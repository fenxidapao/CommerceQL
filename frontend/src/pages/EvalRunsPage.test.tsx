/**
 * T-37 A5（第 14 轮真机走查抓到的缺陷）：评测弹窗的**评测集候选**必须真的渲染出来。
 *
 * 为什么有一件：第 14 轮在浏览器里点开「发起评测」，`GET /admin/eval/datasets` 回 **200 且 `data.items` 两条**，
 * 但下拉里是「暂无数据」⇒ 表单里 `dataset_id` 是必填项，选不了就提交不了 ⇒ **A.9.1 的预检面板在真机上打不开**。
 * 这不是"页面没数据"，而是**组件把自己的请求取消了**：
 * `setDatasetsLoading(true)` 改的 state 同时在 effect 的依赖数组里 ⇒
 * 依赖变化 → React 先跑上一轮的 cleanup（`cancelled = true`）→ 本轮又被 `datasetsLoading` 的守卫挡回去 →
 * 上一轮 Promise 落地时 `if (!cancelled)` 全部跳过 ⇒ `datasets` 永远停在 `null`、`datasetsLoading` 永远停在 `true`。
 * 缺陷的坏形状是**静默**的：HTTP 200、无 console 报错、UI 只是"空下拉"。
 *
 * 四臂分工（臂 1 是复现件：修法不落地它必须红）
 *  1. 200 两条 ⇒ 下拉里出现两条候选（**pre-fix 红**）；
 *  2. 对照：200 但 `items = []` ⇒ 下拉显示「暂无数据」⇒ 证明臂 1 的红不是"永远空"的假阳；
 *  3. 失败支路：403 ⇒ 错误卡出现（不是静默空列表）；
 *  4. 选完集点「生成预检」⇒ `POST /admin/eval/run` 的请求体带 `dry_run: true`，且面板渲染（A.9.1 补记的预检语义）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { EvalRunsPage } from './EvalRunsPage';
import type { EvalDataset } from '../api/types';

const realScroll = Element.prototype.scrollIntoView;
const realResize = globalThis.ResizeObserver;
const realMatchMedia = window.matchMedia;

beforeEach(() => {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* no-op：jsdom 无布局 */
  };
  globalThis.ResizeObserver =
    realResize ??
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  // jsdom 没有 matchMedia，而 antd 的 Grid/useBreakpoint 一挂载就订阅它（不是被测代码的缺陷）。
  window.matchMedia =
    realMatchMedia ??
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList);
});

afterEach(() => {
  cleanup();
  Element.prototype.scrollIntoView = realScroll;
  if (realResize) globalThis.ResizeObserver = realResize;
  if (realMatchMedia) window.matchMedia = realMatchMedia;
  vi.unstubAllGlobals();
});

const DS_FROZEN: EvalDataset = {
  dataset_id: 'ds_v1_frozen',
  version: '1',
  frozen_at: '2026-09-16',
  case_count: 166,
  content_hash: 'sha256:' + '4'.repeat(64),
  purpose: '主验收',
  status: 'frozen',
};
const DS_RED: EvalDataset = {
  ...DS_FROZEN,
  dataset_id: 'ds_v1_red_team',
  case_count: 66,
  purpose: '红队安全集',
};

function envelope(data: unknown) {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      trace_id: 'tr_test',
      data,
      server_time: '2026-10-05T15:25:39+00:00',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

interface StubOpts {
  datasets?: { status: number; body?: unknown };
  precheck?: unknown;
}

/**
 * 预检响应的夹具值 = **第 14 轮活体现读**（2026-10-05 23:2x +0800，共享 `:8000`，
 * `curl -X POST /api/v1/admin/eval/run -d '{"dataset_id":"ds_v1_frozen","dry_run":true}'`），
 * 只把 `basis.artifacts` 裁到一份。⚠️ 刻意**不自己编**：夹具值一旦是手搓的，面板就能在真响应下崩、
 * 或反过来在假响应下绿（`PrecheckPanel` 逐格读 `quote.basis.artifacts[i].cost_cny_per_case`）。
 */
const PRECHECK_LIVE_SHAPE = {
  run_id: null,
  status: 'dry_run',
  launched: false,
  echo: { dataset_id: 'ds_v1_frozen', model: null, prompt_version: null, bundle_version: null, note: null, dry_run: true },
  quote: {
    dataset_id: 'ds_v1_frozen',
    cases_total: 166,
    basis: {
      mode: 'same_dataset',
      why: '基准批次的 frozen_evidence 与被请求集内容哈希一致 ⇒ 可直接比',
      artifacts_available: 3,
      distinct_batches: 2,
      artifacts: [
        {
          artifact: 'results_v1',
          generated_at: '2026-10-03T16:29:35+00:00',
          git_rev: 'b97920d',
          cases: 166,
          llm_calls: 620,
          cost_cny_total: 0.391504,
          cost_cny_per_case: { min: 0.000755, median: 0.002134, max: 0.005418 },
          dataset_content_hash: 'sha256:43e153de0203258c3497bd271d73c9a62f5307f907cbe5bff7cad6f5a9fe8609',
          tier_observed: 'off_peak',
        },
      ],
    },
    estimate: {
      llm_calls_low: 538,
      llm_calls_high: 620,
      cost_cny_off_peak_low: 0.337171,
      cost_cny_off_peak_high: 0.391504,
      cost_cny_off_peak_conservative: 0.901214,
      cost_cny_peak_upper_bound: 0.783008,
      method: '每案实测值 × cases_total（批内求和／条数，不是模型侧估算）',
    },
    tier: {
      now: 'off_peak',
      at_peak_now: false,
      rule: 'app/llm/budget.classify_tier（北京工作日 09–12／14–18 = 峰）',
      peak_multiplier: {
        model: 'deepseek-flash',
        off_peak_cache_miss_usd_per_mtok: '0.15',
        peak_cache_miss_usd_per_mtok: '0.30',
        multiplier: '2.00',
        source: 'app/llm/budget.py 的 PRICES（逐格照抄 PRD §12.3）',
      },
    },
    model_attribution: {
      requested_model: null,
      evidenced_by_basis: false,
      detail: '观测批次的 config 不自报 model ⇒ 这些钱对应哪个模型不可证',
    },
  },
  launch_blockers: [
    { missing: 'eval_run_registry', detail: '库里没有评测运行表 ⇒ run_id 无出处' },
    { missing: 'in_process_runner', detail: '执行体在进程外 ⇒ app 不 import 它' },
    { missing: 'approved_spend', detail: '本轮零额度 ⇒ 真发起在 schema 面不可表达' },
  ],
  how_to_launch: '评测运行登记表 ＋ 进程内执行通道 ＋ 已批额度三件齐',
} as const;

/** 只装这个页面会打的三件事：列表 / 评测集候选 / 预检。逐条记 URL 与请求体。 */
function stub(opts: StubOpts = {}) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });
      if (url.includes('/admin/eval/datasets')) {
        const st = opts.datasets?.status ?? 200;
        if (st !== 200) {
          return new Response(
            JSON.stringify({ code: 'FORBIDDEN_SCOPE', message: '仅平台管理员', trace_id: null, detail: null }),
            { status: st, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return envelope(opts.datasets?.body ?? { items: [DS_FROZEN, DS_RED], total: 2 });
      }
      if (url.includes('/admin/eval/run') && method === 'POST') {
        return envelope(opts.precheck ?? PRECHECK_LIVE_SHAPE);
      }
      if (url.includes('/admin/eval/runs')) return envelope({ items: [], total: 0, limit: 20, offset: 0, has_more: false });
      return envelope({});
    }),
  );
  return { calls };
}

function renderPage() {
  // 与 `main.tsx:30` 同形：antd 的 locale 在根上给，缺了它「暂无数据」会变成英文 "No data" ⇒ 断言尺会失真。
  return render(
    <ConfigProvider locale={zhCN}>
      <MemoryRouter initialEntries={['/eval/runs']}>
        <Routes>
          <Route path="/eval/runs" element={<EvalRunsPage />} />
        </Routes>
      </MemoryRouter>
    </ConfigProvider>,
  );
}

/** 点「发起评测」开弹窗，再点开评测集下拉（antd Select 要先 mousedown 才渲染候选）。 */
async function openDatasetDropdown() {
  fireEvent.click(await screen.findByRole('button', { name: /发起评测/ }));
  await waitFor(() => expect(screen.getByText(/当前只出预检报价/)).toBeInTheDocument());
  const selector = document.querySelector('.ant-select-selector');
  expect(selector, '弹窗里的 Select 没挂上').toBeTruthy();
  fireEvent.mouseDown(selector as Element);
  // 等下拉真的展开：空列表时 antd 渲染的是「暂无数据」而不是 0 个节点，两者都要能区分。
  await waitFor(() => expect(document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')).toBeTruthy());
}

/** 这一把尺只量一件事：下拉里**当前**渲染出几条候选（臂 1 与臂 2 共用同一把尺）。 */
function optionLabels(): string[] {
  return [...document.querySelectorAll('.ant-select-item-option')].map((el) => el.textContent ?? '');
}

describe('T-37 A5：评测弹窗的评测集候选', () => {
  it('200 两条候选 ⇒ 下拉里必须渲染出这两条（第 14 轮浏览器里是"暂无数据"）', async () => {
    stub();
    renderPage();
    await openDatasetDropdown();
    await waitFor(() => expect(optionLabels()).toHaveLength(2));
    expect(optionLabels().join(' | ')).toContain('ds_v1_frozen（1，166 例）');
    expect(optionLabels().join(' | ')).toContain('ds_v1_red_team（1，66 例）');
  });

  it('对照：200 但 items 为空 ⇒ 下拉 0 条候选 ＋ "暂无数据"（证明上一条不是永远空的假阳）', async () => {
    stub({ datasets: { status: 200, body: { items: [], total: 0 } } });
    renderPage();
    await openDatasetDropdown();
    await waitFor(() => expect(document.querySelectorAll('.ant-empty').length).toBeGreaterThan(0));
    expect(optionLabels()).toHaveLength(0);
  });

  it('403 ⇒ 弹窗里出错误，而不是静默的空下拉', async () => {
    stub({ datasets: { status: 403 } });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /发起评测/ }));
    await screen.findByText(/仅平台管理员/);
  });

  it('选完集点「生成预检」⇒ 请求体带 dry_run=true 且渲染预检面板', async () => {
    const { calls } = stub();
    renderPage();
    await openDatasetDropdown();
    await waitFor(() => expect(optionLabels()).toHaveLength(2));
    const target = [...document.querySelectorAll('.ant-select-item-option')].find((el) =>
      (el.textContent ?? '').includes('ds_v1_frozen'),
    );
    fireEvent.click(target as Element);
    for (const [name, value] of [
      ['模型', 'deepseek-flash'],
      ['Prompt 版本', 'gen_sql_v1'],
      ['口径包版本', '2026.09.14.1'],
    ] as const) {
      const input = screen.getByLabelText(new RegExp(name));
      fireEvent.change(input, { target: { value } });
    }
    fireEvent.click(await screen.findByRole('button', { name: /生成预检/ }));
    await screen.findByTestId('eval-precheck');
    const post = calls.find((c) => c.method === 'POST' && c.url.includes('/admin/eval/run'));
    expect(post?.body).toMatchObject({ dataset_id: 'ds_v1_frozen', dry_run: true });
  });
});
