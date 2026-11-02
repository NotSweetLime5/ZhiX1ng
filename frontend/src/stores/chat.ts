/** Each stream owns its view generation; old callbacks cannot mutate a new session. */
import { create } from 'zustand';
import { runChatStream, type StreamHandle } from '@/lib/sse';
import { deleteSession, listMessages, listSessions, renameSession as renameApi } from '@/api/chat';
import { toast } from '@/stores/ui';
import { errMsg } from '@/lib/request';
import type {
  AgentEventData,
  Message,
  PlanData,
  RAGRef,
  Session,
  ToolCallData,
  ToolResultData,
  UsageData,
} from '@/types/chat';

export interface StreamingMsg {
  sessionId: string;
  content: string;
  reasoning: string;
  plan?: PlanData;
  tools: Record<string, ToolCallData & Partial<ToolResultData>>;
  agentEvents: AgentEventData[];
  refs: RAGRef[];
  usage?: UsageData;
  status: 'streaming' | 'done' | 'error' | 'stopped';
  errorMessage?: string;
  expert?: string;
}
interface Attempt {
  content: string;
  agentId?: number;
  modelId?: number;
}
interface ChatState {
  sessions: Session[];
  sessionsTotal: number;
  activeSessionId?: string;
  messages: Message[];
  streaming: StreamingMsg | null;
  activeAgentId?: number;
  activeModelId?: number;
  loadingMessages: boolean;
  sending: boolean;
  error?: string;
  retryAttempt?: Attempt;
  loadSessions: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  newSession: () => void;
  reset: () => void;
  setActiveAgent: (id?: number) => void;
  setActiveModel: (id?: number) => void;
  send: (content: string) => Promise<void>;
  retry: () => Promise<void>;
  stop: () => void;
  refreshMessages: () => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  removeSession: (id: string) => Promise<void>;
}
let generation = 0;
let sessionListRequest = 0;
interface Run {
  generation: number;
  sessionId?: string;
  userMessageId?: number;
  stopped: boolean;
  handle?: StreamHandle;
  finished: Promise<void>;
}
let activeRun: Run | null = null;
const pending = new Map<string, Promise<void>>();
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const useChat = create<ChatState>((set, get) => ({
  sessions: [],
  sessionsTotal: 0,
  messages: [],
  streaming: null,
  loadingMessages: false,
  sending: false,
  loadSessions: async () => {
    const request = ++sessionListRequest;
    try {
      const page = await listSessions({ page: 1, page_size: 100 });
      if (request === sessionListRequest) set({ sessions: page.list, sessionsTotal: page.total });
    } catch (e) {
      if (request === sessionListRequest) toast.err(errMsg(e));
    }
  },
  selectSession: async (id) => {
    const mine = ++generation;
    activeRun?.handle?.abort();
    activeRun = null;
    const session = get().sessions.find((s) => s.id === id);
    set({
      activeSessionId: id,
      activeAgentId: session?.agent_id ?? undefined,
      activeModelId: undefined,
      messages: [],
      streaming: null,
      loadingMessages: true,
      sending: false,
      error: undefined,
      retryAttempt: undefined,
    });
    try {
      await pending.get(id);
      const messages = await listMessages(id);
      if (generation === mine) set({ messages });
    } catch (e) {
      if (generation === mine) set({ error: errMsg(e) });
    } finally {
      if (generation === mine) set({ loadingMessages: false });
    }
  },
  newSession: () => {
    ++generation;
    activeRun?.handle?.abort();
    activeRun = null;
    set({
      activeSessionId: undefined,
      messages: [],
      streaming: null,
      loadingMessages: false,
      sending: false,
      error: undefined,
      retryAttempt: undefined,
    });
  },
  reset: () => {
    get().newSession();
    ++sessionListRequest;
    set({ sessions: [], sessionsTotal: 0, activeAgentId: undefined, activeModelId: undefined });
  },
  setActiveAgent: (id) => set({ activeAgentId: id }),
  setActiveModel: (id) => set({ activeModelId: id }),
  send: async (content) => {
    content = content.trim();
    if (!content || activeRun || get().loadingMessages) return;
    const attempt: Attempt = { content, agentId: get().activeAgentId, modelId: get().activeModelId };
    let finish!: () => void;
    const run: Run = {
      generation: ++generation,
      sessionId: get().activeSessionId,
      stopped: false,
      finished: new Promise<void>((resolve) => {
        finish = resolve;
      }),
    };
    activeRun = run;
    const current = () => activeRun === run && generation === run.generation;
    const optimistic: Message = {
      id: -Date.now(),
      session_id: run.sessionId ?? '',
      role: 'user',
      content,
      prompt_tokens: 0,
      completion_tokens: 0,
      first_token_ms: 0,
      latency_ms: 0,
      status: 1,
      trace_id: '',
      created_at: new Date().toISOString(),
    };
    set((s) => ({
      messages: [...s.messages.filter((m) => m.id > 0), optimistic],
      streaming: emptyStreaming(),
      sending: true,
      error: undefined,
      retryAttempt: undefined,
    }));
    try {
      if (run.sessionId) await pending.get(run.sessionId);
      if (!current() || run.stopped) return;
      if (run.sessionId) pending.set(run.sessionId, run.finished);
      run.handle = runChatStream(
        { session_id: run.sessionId, agent_id: attempt.agentId, model_config_id: attempt.modelId, content },
        (ev) => {
          if (ev.event === 'meta') {
            run.sessionId = String(ev.data.session_id);
            run.userMessageId = Number(ev.data.message_id);
            pending.set(run.sessionId, run.finished);
          }
          if (!current() || run.stopped) return;
          set((s) => ({
            ...(ev.event === 'meta' ? { activeSessionId: run.sessionId } : {}),
            streaming: s.streaming ? reduce(s.streaming, ev.event, ev.data) : null,
          }));
        },
      );
      await run.handle.done;
      // An abort closes fetch before the backend's finally necessarily commits.
      // Wait for the assistant after this user id, never replace a new view's state.
      const final = current() ? get().streaming : null;
      if (final?.status === 'error') set({ error: final.errorMessage, retryAttempt: attempt });
      let rows: Message[] | undefined;
      if (run.sessionId) {
        for (let i = 0; i < 12; i++) {
          rows = await listMessages(run.sessionId);
          if (!run.userMessageId || rows.some((m) => m.role === 'assistant' && m.id > run.userMessageId!))
            break;
          rows = undefined;
          await delay(250);
        }
        if (!rows) throw new Error('回答已停止，但历史记录尚未同步。请稍后刷新；不会自动重新执行工具。');
        if (current()) set({ messages: rows, streaming: null });
        if (current()) await get().loadSessions();
      } else if (current()) {
        // No meta: keep the failed/stopped local attempt visible and retryable.
        set({ retryAttempt: attempt });
      }
    } catch (e) {
      if (current()) set({ error: errMsg(e), retryAttempt: attempt });
    } finally {
      if (current()) {
        const state = get().streaming;
        if (state)
          set({
            streaming: {
              ...state,
              status: run.stopped ? 'stopped' : 'error',
              tools: Object.fromEntries(
                Object.entries(state.tools).map(([id, tool]) => [
                  id,
                  { ...tool, status: tool.status ?? 'interrupted' },
                ]),
              ),
            },
          });
        set({ sending: false });
        activeRun = null;
      }
      finish();
      if (run.sessionId && pending.get(run.sessionId) === run.finished) pending.delete(run.sessionId);
    }
  },
  stop: () => {
    const run = activeRun;
    if (!run) return;
    run.stopped = true;
    run.handle?.abort();
    set((s) => ({
      streaming: s.streaming
        ? {
            ...s.streaming,
            status: 'stopped',
            tools: Object.fromEntries(
              Object.entries(s.streaming.tools).map(([id, t]) => [
                id,
                { ...t, status: t.status ?? 'interrupted' },
              ]),
            ),
          }
        : null,
    }));
  },
  retry: async () => {
    const attempt = get().retryAttempt;
    if (!attempt || activeRun) return;
    set({ streaming: null, activeAgentId: attempt.agentId, activeModelId: attempt.modelId });
    await get().send(attempt.content);
  },
  refreshMessages: async () => {
    const sid = get().activeSessionId;
    if (sid) await get().selectSession(sid);
    else set({ streaming: null, error: undefined });
  },
  renameSession: async (id, title) => {
    try {
      await renameApi(id, title);
      set((s) => ({ sessions: s.sessions.map((x) => (x.id === id ? { ...x, title } : x)) }));
    } catch (e) {
      toast.err(errMsg(e));
    }
  },
  removeSession: async (id) => {
    try {
      if (get().activeSessionId === id) get().newSession();
      await pending.get(id);
      await deleteSession(id);
      set((s) => ({
        sessions: s.sessions.filter((x) => x.id !== id),
        sessionsTotal: Math.max(0, s.sessionsTotal - 1),
      }));
    } catch (e) {
      toast.err(errMsg(e));
    }
  },
}));

function emptyStreaming(): StreamingMsg {
  return {
    sessionId: '',
    content: '',
    reasoning: '',
    tools: {},
    agentEvents: [],
    refs: [],
    status: 'streaming',
  };
}

/** SSE 事件归约器：单事件 → 新状态（不可变） */
export function reduce(cur: StreamingMsg, event: string, data: Record<string, unknown>): StreamingMsg {
  switch (event) {
    case 'meta':
      return {
        ...cur,
        sessionId: String(data.session_id ?? ''),
        expert: data.expert ? String(data.expert) : undefined,
      };

    case 'delta':
      return { ...cur, content: cur.content + String(data.content ?? '') };

    case 'reasoning':
      return { ...cur, reasoning: cur.reasoning + String(data.content ?? '') };

    case 'plan':
      return { ...cur, plan: data as unknown as PlanData };

    case 'tool_call': {
      const tc = data as unknown as ToolCallData;
      return { ...cur, tools: { ...cur.tools, [tc.id]: { ...tc } } };
    }

    case 'tool_result': {
      const tr = data as unknown as ToolResultData;
      const node = cur.tools[tr.id];
      if (!node) return cur;
      return {
        ...cur,
        tools: { ...cur.tools, [tr.id]: { ...node, ...tr } },
      };
    }

    case 'agent_event':
      return {
        ...cur,
        expert: data.type === 'delegate' ? String(data.expert ?? '') : cur.expert,
        agentEvents: [...cur.agentEvents, data as unknown as AgentEventData],
      };

    case 'refs':
      return { ...cur, refs: (data.items as RAGRef[]) ?? [] };

    case 'usage':
      return { ...cur, usage: data as unknown as UsageData };

    case 'done':
      return { ...cur, status: 'done' };

    case 'error':
      return {
        ...cur,
        status: 'error',
        errorMessage: String(data.message ?? '对话失败'),
      };

    default:
      return cur; // 未知事件静默忽略（协议向后兼容）
  }
}
