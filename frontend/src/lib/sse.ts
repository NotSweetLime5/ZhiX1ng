/**
 * SSE 流式解析 —— POST /chat/stream 的字节流 → 事件回调。
 *
 * 为什么不用 EventSource：浏览器原生 EventSource 只支持 GET，
 * 而对话是 POST + JSON body，因此用 fetch + ReadableStream 手动解析。
 * 帧格式与 app/services/chat.py 的 sse() 对齐：
 *
 *   event: <type>\n
 *   data: <json>\n
 *   \n            ← 空行即帧边界
 *
 * 关键坑：TCP 分包可能把一帧劈成两半，必须缓冲半帧（split 后 pop 留尾）。
 */
import type { SSEEventType } from '@/types/chat';
import { authenticatedFetch, errMsg } from './request';

export interface SSEEvent {
  event: SSEEventType;
  data: Record<string, unknown>;
}

export interface StreamHandle {
  /** 中断流（用户点停止按钮） */
  abort: () => void;
  /** 流结束信号（done/error/中断/网络断 都会 resolve） */
  done: Promise<void>;
}

/**
 * 发起流式对话并逐事件回调。
 *
 * @param body   对话请求 {session_id?, agent_id?, content, model_config_id?}
 * @param onEvent 每解析出一个完整帧回调一次
 * Authentication is injected by the request layer. Only a 401 handshake is replayed;
 * a partially consumed generation is never automatically retried.
 */
export function runChatStream(
  body: {
    session_id?: string;
    agent_id?: number;
    content: string;
    model_config_id?: number;
  },
  onEvent: (e: SSEEvent) => void,
): StreamHandle {
  const controller = new AbortController();
  let resolveDone!: () => void;
  const done = new Promise<void>((r) => {
    resolveDone = r;
  });

  // 流处理主体：独立异步任务，结束/异常时都 resolve done
  void (async () => {
    try {
      const res = await authenticatedFetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      // 非 200：可能是 token 过期/无权限，读 JSON 包络抛给 UI
      if (res.status !== 200) {
        let msg = `连接失败（HTTP ${res.status}）`;
        try {
          const env = await res.json();
          if (env?.message) msg = env.message;
        } catch {
          /* body 不是 JSON，用默认文案 */
        }
        onEvent({ event: 'error', data: { code: res.status, message: msg } });
        return;
      }

      if (!res.body) throw new Error('响应没有可读取的内容');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();
      let terminal = false;
      const dispatch = (text: string) => {
        for (const event of parser.feed(text)) {
          if (terminal || controller.signal.aborted) break;
          onEvent(event);
          if (event.event === 'done' || event.event === 'error') terminal = true;
        }
      };
      try {
        while (!terminal && !controller.signal.aborted) {
          const { done: eof, value } = await reader.read();
          if (eof) {
            dispatch(decoder.decode());
            break;
          }
          dispatch(decoder.decode(value, { stream: true }));
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }

      // 流结束但没等到 done/error 才算异常断开（此前无条件补发，
      // 导致每次正常回答完也弹"连接中断，回答可能不完整"）
      if (!terminal && !controller.signal.aborted) {
        onEvent({
          event: 'error',
          data: { code: -1, message: '连接中断，回答可能不完整，请重发' },
        });
      }
    } catch (e) {
      // 用户主动停止：保留临时内容，由 store 等待服务端收尾并同步历史。
      if (!controller.signal.aborted) {
        onEvent({
          event: 'error',
          data: { code: -1, message: errMsg(e) },
        });
      }
    } finally {
      resolveDone();
    }
  })();

  return { abort: () => controller.abort(), done };
}

/** Incremental SSE parser; retains split CRLF and UTF-8-decoded partial frames. */
export class SSEParser {
  private buffer = '';
  feed(text: string): SSEEvent[] {
    this.buffer += text;
    const result: SSEEvent[] = [];
    let boundary: RegExpExecArray | null;
    while ((boundary = /\r?\n\r?\n/.exec(this.buffer))) {
      const frame = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      let event = '';
      const data: string[] = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (!event || !data.length) continue;
      try {
        const value: unknown = JSON.parse(data.join('\n'));
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          result.push({ event: event as SSEEventType, data: value as Record<string, unknown> });
        }
      } catch {
        /* Malformed frames are not terminal acknowledgments. */
      }
    }
    return result;
  }
}
