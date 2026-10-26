/**
 * 会话列表 —— 侧栏：新对话按钮 + 会话项（改名/删除）。
 */
import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { relativeTime } from '@/lib/format';
import { useChat } from '@/stores/chat';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Icon } from '@/components/ui/Icon';

export function SessionList({ className, onClose }: { className?: string; onClose?: () => void }) {
  const {
    sessions,
    activeSessionId,
    selectSession,
    newSession,
    renameSession,
    removeSession,
    loadSessions,
  } = useChat();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [delId, setDelId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 首次挂载拉列表 + 列表入场 stagger
  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const commitRename = async () => {
    if (editingId && draft.trim()) {
      await renameSession(editingId, draft.trim());
    }
    setEditingId(null);
  };

  return (
    <div className={clsx('h-full w-[240px] shrink-0 flex-col border-r border-smoke/40 bg-carbon', className)}>
      {/* 新对话 */}
      <div className="p-4">
        <div className="mb-4 flex h-8 items-center justify-between"><span className="text-xs font-medium text-fog">我的会话</span><span className="rounded-md bg-graphite px-2 py-0.5 text-[10px] tabular-nums text-ash">{sessions.length}</span><button className="icon-button lg:hidden" aria-label="关闭会话列表" onClick={onClose}><Icon name="close" className="h-4 w-4" /></button></div>
        <button
          className="btn-primary w-full text-xs"
          onClick={() => { newSession(); onClose?.(); }}
        >
          <Icon name="plus" className="h-4 w-4" /> 新建对话
        </button>
      </div>

      {/* 会话项 */}
      <div ref={listRef} className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {sessions.map((s) => {
          const active = s.id === activeSessionId;
          return (
            <div
              key={s.id}
              className={clsx(
                'group cursor-pointer rounded-xl border px-3 py-3 transition-colors duration-150',
                active ? 'border-lime bg-lime text-bone' : 'border-transparent text-fog hover:bg-obsidian/70',
              )}
              onClick={() => editingId !== s.id && void selectSession(s.id)}
            >
              {editingId === s.id ? (
                <input
                  autoFocus
                  className="field h-7 px-2 py-0 text-xs"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => e.key === 'Enter' && void commitRename()}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs leading-5">{s.title}</p>
                    <p className={clsx('text-[10px]', active ? 'text-bone' : 'text-ash')}>
                      {s.message_count} 条 · {relativeTime(s.last_msg_at ?? s.created_at)}
                    </p>
                  </div>
                  {/* 悬浮操作 */}
                  <div className="flex shrink-0 gap-2 opacity-70 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                    <button
                      className={clsx('text-[10px] hover:text-bone', active ? 'text-bone' : 'text-ash')}
                      title="重命名"
                      aria-label={`重命名会话 ${s.title}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(s.id);
                        setDraft(s.title);
                      }}
                    >
                      ✎
                    </button>
                    <button
                      className={clsx('text-[10px] hover:text-coral', active ? 'text-bone' : 'text-ash')}
                      title="删除"
                      aria-label={`删除会话 ${s.title}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setDelId(s.id);
                      }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {sessions.length === 0 && (
          <div className="mx-2 mt-6 rounded-xl border border-dashed border-smoke/60 px-4 py-6 text-center"><Icon name="chat" className="mx-auto mb-3 h-6 w-6 text-ash/60" /><p className="text-xs text-fog">还没有会话</p><p className="mt-2 text-[11px] leading-5 text-ash">开始一次对话，<br />灵感与记录会保存在这里。</p></div>
        )}
      </div>

      <ConfirmDialog
        open={delId !== null}
        title="删除会话"
        content="删除后该会话的全部消息不可恢复，确认删除？"
        danger
        confirmText="删除"
        onCancel={() => setDelId(null)}
        onConfirm={async () => {
          if (delId) await removeSession(delId);
          setDelId(null);
        }}
      />
    </div>
  );
}
