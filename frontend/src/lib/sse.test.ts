import { afterEach, describe, expect, it, vi } from 'vitest';
import { runChatStream, SSEParser } from './sse';
import { bindAuthHooks } from './request';

afterEach(() => vi.unstubAllGlobals());
describe('incremental SSE', () => {
  it('handles split CRLF, multiline JSON, heartbeats and malformed terminal frames', () => {
    const parser = new SSEParser();
    expect(parser.feed(': ping\r\nevent: delta\r\ndata: {"content":\r')).toEqual([]);
    expect(parser.feed('\ndata: "中文"}\r\n\r')).toEqual([]);
    expect(parser.feed('\nevent: done\ndata: invalid\n\n')).toEqual([
      { event: 'delta', data: { content: '中文' } },
    ]);
    expect(parser.feed('event: done\ndata: {"finish_reason":"stop"}\n\n')).toHaveLength(1);
  });
  it('decodes Chinese split in the middle of a UTF-8 character and accepts done without an error', async () => {
    const bytes = new TextEncoder().encode(
      'event: delta\ndata: {"content":"中文"}\n\nevent: done\ndata: {}\n\n',
    );
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream({
            start(c) {
              for (const byte of bytes) c.enqueue(new Uint8Array([byte]));
              c.close();
            },
          }),
        ),
      ),
    );
    const events = vi.fn();
    await runChatStream({ content: 'test' }, events).done;
    expect(events.mock.calls.map(([e]) => e.event)).toEqual(['delta', 'done']);
    expect(events.mock.calls[0][0].data.content).toBe('中文');
  });
  it('reports premature EOF and does not mistake corrupt done for success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('event: done\ndata: bad-json\n\n')));
    const events = vi.fn();
    await runChatStream({ content: 'test' }, events).done;
    expect(events.mock.calls[0][0].event).toBe('error');
  });
  it('refreshes only a rejected handshake, before any stream has executed', async () => {
    let token = 'old';
    bindAuthHooks(
      () => token,
      vi.fn(),
      (t) => {
        token = t;
      },
    );
    localStorage.setItem('nx.refresh', 'refresh');
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ code: 0, data: { access_token: 'new', refresh_token: 'new-refresh' } }),
        ),
      )
      .mockResolvedValueOnce(new Response('event: done\ndata: {}\n\n'));
    vi.stubGlobal('fetch', fetch);
    await runChatStream({ content: 'test' }, vi.fn()).done;
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(new Headers(fetch.mock.calls[2][1].headers).get('Authorization')).toBe('Bearer new');
  });
});
