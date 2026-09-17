/** SSE 帧拼装工具（仅供 MSW mock 与测试使用） */

export interface MockFrame {
  event: string;
  data: unknown;
  /** 发送前等待毫秒数（模拟流式间隔） */
  delayMs?: number;
}

export function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** 把帧列表拼成一次性 SSE 文本（用于测试解析器） */
export function sseText(frames: MockFrame[]): string {
  return frames.map((f) => sseFrame(f.event, f.data)).join('');
}

/** 生成可读流形式的 SSE body（用于 MSW 响应，模拟真实流式到达） */
export function sseStream(frames: MockFrame[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    async start(controller) {
      for (const f of frames) {
        if (f.delayMs) {
          await new Promise((resolve) => setTimeout(resolve, f.delayMs));
        }
        controller.enqueue(encoder.encode(sseFrame(f.event, f.data)));
      }
      controller.close();
    },
  });
}

export const SSE_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-cache',
  Connection: 'keep-alive',
} as const;
