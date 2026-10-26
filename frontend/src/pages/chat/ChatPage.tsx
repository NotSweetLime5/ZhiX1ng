import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { useChat } from '@/stores/chat';
import { listAgents } from '@/api/agent';
import type { Agent } from '@/types/agent';
import { SessionList } from './SessionList';
import { Composer } from './Composer';
import { HistoryBubble, StreamingBubble } from './MessageBubble';
import { Badge, Select } from '@/components/ui/primitives';
import { BrandMark, Icon, type IconName } from '@/components/ui/Icon';

const SUGGESTIONS: { icon: IconName; title: string; desc: string; prompt: string }[] = [
  { icon: 'book', title: '梳理知识', desc: '从问题出发，找到清晰的答案', prompt: '帮我梳理这个主题的关键概念、常见问题和学习路径：' },
  { icon: 'code', title: '解决问题', desc: '分析思路，拆解代码与方案', prompt: '请帮我分析下面的问题，给出解决思路和具体步骤：' },
  { icon: 'workflow', title: '规划任务', desc: '把复杂目标拆成可执行的步骤', prompt: '请把下面的目标拆成一份可执行的计划，说明每一步的输入、输出和依赖：' },
];

function PlanCard() {
  const plan = useChat((s) => s.streaming?.plan);
  if (!plan) return null;
  return <div className="panel border-lime/20 p-5">
    <div className="mb-4 flex items-center gap-3"><Icon name="workflow" className="text-lime" /><Badge tone="lime">执行计划</Badge><span className="text-sm font-medium text-bone">{plan.goal}</span></div>
    <ol className="space-y-3">{plan.steps?.map((step, i) => <li key={step.id} className="flex items-start gap-3 text-sm text-fog"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-lime/10 font-mono text-xs text-lime">{i + 1}</span><div className="pt-0.5">{step.description}{step.depends_on?.length > 0 && <p className="mt-1 text-xs text-ash">依赖 {step.depends_on.join(', ')}</p>}</div></li>)}</ol>
  </div>;
}

function AgentSelector() {
  const { activeAgentId, setActiveAgent, streaming } = useChat();
  const [agents, setAgents] = useState<Agent[]>([]);
  useEffect(() => { void listAgents({ page: 1, page_size: 100 }).then((p) => setAgents(p.list)).catch(() => setAgents([])); }, []);
  return <div className="flex min-w-0 items-center gap-2">
    <span className="hidden shrink-0 text-xs text-ash sm:block">当前智能体</span>
    <Select aria-label="选择智能体" className="w-[150px] py-2 text-xs sm:w-[220px]" value={activeAgentId ?? ''} disabled={streaming !== null} onValueChange={(value) => setActiveAgent(value ? Number(value) : undefined)}>
      <option value="">平台默认</option>
      {agents.map((a) => <option key={a.id} value={a.id}>{a.name}{a.type === 'host' ? ' · 智能路由' : ''}</option>)}
    </Select>
  </div>;
}

export function ChatPage() {
  const { messages, streaming, sessions, activeSessionId } = useChat();
  const [draft, setDraft] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages.length, streaming?.content, streaming?.tools, streaming?.plan]);
  useEffect(() => { setHistoryOpen(false); }, [activeSessionId]);
  const hasContent = messages.length > 0 || streaming !== null;
  const session = sessions.find((s) => s.id === activeSessionId);

  return (
    <div className="relative flex h-full min-h-0">
      {historyOpen && <button className="absolute inset-0 z-20 bg-void/70 backdrop-blur-sm lg:hidden" aria-label="关闭会话列表" onClick={() => setHistoryOpen(false)} />}
      <SessionList className={clsx(historyOpen ? 'absolute inset-y-0 left-0 z-30 flex shadow-2xl' : 'hidden', 'lg:relative lg:z-auto lg:flex lg:shadow-none')} onClose={() => setHistoryOpen(false)} />
      <div className="chat-surface flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-[64px] shrink-0 items-center justify-between gap-3 border-b border-smoke/30 px-4 sm:px-7">
          <div className="flex min-w-0 items-center gap-3"><button className="icon-button lg:hidden" title="历史会话" aria-label="打开历史会话" onClick={() => setHistoryOpen(true)}><Icon name="history" /></button><Icon name="chat" className="hidden h-4 w-4 shrink-0 text-ash sm:block" /><span className="truncate text-sm text-fog">{session?.title || '新对话'}</span></div>
          <AgentSelector />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-7 sm:px-8">
          {!hasContent ? (
            <div className="mx-auto flex min-h-full w-full max-w-[800px] flex-col items-center justify-center py-8">
              <div className="welcome-mark mb-6 h-16 w-16 sm:mb-8 sm:h-24 sm:w-24"><BrandMark className="h-9 w-9 sm:h-12 sm:w-12" /><span className="absolute -right-2 top-2 flex h-6 w-6 items-center justify-center rounded-lg border border-lime/20 bg-carbon"><Icon name="spark" className="h-3.5 w-3.5" /></span></div>
              <p className="mb-3 text-[10px] font-medium tracking-[.25em] text-lime/80">YOUR AI WORKSPACE</p>
              <h1 className="text-center text-[28px] font-semibold tracking-tight text-bone sm:text-[36px]">让想法，开始行动。</h1>
              <p className="mt-4 max-w-md text-center text-sm leading-7 text-ash">提问、检索资料，或把复杂任务拆成可执行的步骤。<br className="hidden sm:block" />你的智能工作空间，从这里开始。</p>
              <div className="mt-10 grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
                {SUGGESTIONS.map((s) => <button key={s.title} className="suggestion-card group grid grid-cols-[36px_1fr_16px] items-center gap-3 sm:flex sm:flex-col sm:items-start sm:gap-0" onClick={() => setDraft(s.prompt)}>
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-smoke/40 bg-graphite/60 text-lime sm:mb-5 sm:h-10 sm:w-10"><Icon name={s.icon} /></span>
                  <span className="min-w-0"><span className="block text-sm font-medium text-bone">{s.title}</span><span className="mt-1 block text-xs leading-5 text-ash sm:mt-2">{s.desc}</span></span>
                  <Icon name="arrow" className="h-4 w-4 text-ash transition-transform group-hover:translate-x-1 group-hover:text-lime sm:absolute sm:right-5 sm:top-6" />
                </button>)}
              </div>
              <p className="mt-5 text-[11px] text-ash/80">选择一个灵感，或直接输入你的问题</p>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-[800px] space-y-7">{messages.map((m) => <HistoryBubble key={m.id} msg={m} />)}{streaming?.plan && <PlanCard />}{streaming && <StreamingBubble s={streaming} />}<div ref={bottomRef} /></div>
          )}
        </div>
        <Composer draft={draft} onDraftApplied={() => setDraft('')} />
      </div>
    </div>
  );
}
