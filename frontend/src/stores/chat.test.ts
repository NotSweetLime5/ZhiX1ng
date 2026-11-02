import { beforeEach, expect, it, vi } from 'vitest';
import type { SSEEvent } from '@/lib/sse';
import type { Message } from '@/types/chat';

const mocks = vi.hoisted(() => ({ messages: vi.fn(), sessions: vi.fn(), stream: vi.fn() }));
vi.mock('@/api/chat', () => ({
  listMessages: mocks.messages,
  listSessions: mocks.sessions,
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
}));
vi.mock('@/lib/sse', () => ({ runChatStream: mocks.stream }));
import { useChat } from './chat';
const message = (id: number, sid: string, role: 'user' | 'assistant' = 'assistant', status = 1) =>
  ({ id, session_id: sid, role, content: sid, status }) as Message;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
let emit: (event: SSEEvent) => void;
let finish: ReturnType<typeof deferred<void>>;
let abort: ReturnType<typeof vi.fn>;
beforeEach(() => {
  useChat.getState().newSession();
  useChat.setState({ sessions: [], messages: [], activeAgentId: 7, activeModelId: 21 });
  finish = deferred<void>();
  abort = vi.fn(() => finish.resolve());
  mocks.sessions.mockResolvedValue({ list: [], total: 0 });
  mocks.messages.mockImplementation(async (sid) => [message(11, sid)]);
  mocks.stream.mockImplementation((_body, callback) => {
    emit = callback;
    return { abort, done: finish.promise };
  });
});
it('late deltas and old finalization cannot replace the newly selected session', async () => {
  const running = useChat.getState().send('old question');
  emit({ event: 'meta', data: { session_id: 'old', message_id: 10 } });
  await useChat.getState().selectSession('new');
  emit({ event: 'delta', data: { content: 'late old answer' } });
  await running;
  expect(abort).toHaveBeenCalled();
  expect(useChat.getState().activeSessionId).toBe('new');
  expect(useChat.getState().messages[0].session_id).toBe('new');
  expect(useChat.getState().streaming).toBeNull();
});
it('ignores a slower history request after another session was selected', async () => {
  const old = deferred<Message[]>();
  mocks.messages.mockImplementation((sid) =>
    sid === 'slow' ? old.promise : Promise.resolve([message(11, sid)]),
  );
  const a = useChat.getState().selectSession('slow');
  await Promise.resolve();
  await useChat.getState().selectSession('fast');
  old.resolve([message(12, 'slow')]);
  await a;
  expect(useChat.getState().messages[0].session_id).toBe('fast');
});

it('clears the previous account and prevents its late stream from restoring messages', async () => {
  const running = useChat.getState().send('private question');
  emit({ event: 'meta', data: { session_id: 'private', message_id: 10 } });
  useChat.getState().reset();
  emit({ event: 'delta', data: { content: 'old account answer' } });
  await running;
  expect(useChat.getState().messages).toEqual([]);
  expect(useChat.getState().sessions).toEqual([]);
  expect(useChat.getState().activeAgentId).toBeUndefined();
  expect(useChat.getState().streaming).toBeNull();
});
it('stops without an automatic resend and waits for the persisted interrupted assistant', async () => {
  const running = useChat.getState().send('calculate');
  emit({ event: 'meta', data: { session_id: 'one', message_id: 10 } });
  emit({ event: 'delta', data: { content: 'partial' } });
  mocks.messages.mockResolvedValue([message(10, 'one', 'user'), message(11, 'one', 'assistant', 2)]);
  useChat.getState().stop();
  expect(useChat.getState().streaming?.content).toBe('partial');
  await running;
  expect(mocks.stream).toHaveBeenCalledTimes(1);
  expect(useChat.getState().messages[useChat.getState().messages.length - 1]?.status).toBe(2);
  expect(useChat.getState().sending).toBe(false);
});
it('keeps failure retry context, and retries only after an explicit action', async () => {
  const running = useChat.getState().send('calculate');
  emit({ event: 'error', data: { message: 'provider down' } });
  finish.resolve();
  await running;
  expect(useChat.getState().error).toBe('provider down');
  expect(mocks.stream).toHaveBeenCalledTimes(1);
  finish = deferred<void>();
  const retry = useChat.getState().retry();
  expect(mocks.stream.mock.calls[1][0]).toMatchObject({
    content: 'calculate',
    agent_id: 7,
    model_config_id: 21,
  });
  emit({ event: 'meta', data: { session_id: 'retry', message_id: 10 } });
  emit({ event: 'done', data: {} });
  finish.resolve();
  await retry;
});
