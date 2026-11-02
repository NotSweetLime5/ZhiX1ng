import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { listChatModels } from '@/api/chat';
import { Select } from '@/components/ui/primitives';
import { Icon } from '@/components/ui/Icon';
import { useChat } from '@/stores/chat';
import type { ChatModelItem } from '@/types/chat';
import { BRAND_NAME } from '@/lib/brand';

export function Composer({
  disabled,
  draft,
  onDraftApplied,
}: {
  disabled?: boolean;
  draft?: string;
  onDraftApplied?: () => void;
}) {
  const { send, stop, sending, loadingMessages, activeModelId, setActiveModel } = useChat();
  const [value, setValue] = useState('');
  const [models, setModels] = useState<ChatModelItem[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const busy = sending || loadingMessages || disabled;
  useEffect(() => {
    void listChatModels()
      .then(setModels)
      .catch(() => setModels([]));
  }, []);
  useEffect(() => {
    if (draft) {
      setValue(draft);
      taRef.current?.focus();
      onDraftApplied?.();
    }
  }, [draft, onDraftApplied]);
  useEffect(() => {
    const el = taRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 160) + 'px';
    }
  }, [value]);
  const submit = () => {
    const text = value.trim();
    if (!text || busy) return;
    setValue('');
    void send(text);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };
  return (
    <div className="shrink-0 px-4 pb-5 pt-2 sm:px-8 sm:pb-6">
      <div
        className={clsx(
          'mx-auto w-full max-w-[800px] rounded-2xl border bg-graphite p-3 shadow-[0_8px_32px_rgba(0,0,0,.18)] transition-all sm:p-4',
          busy
            ? 'border-smoke/60'
            : 'border-smoke/80 focus-within:border-lime/50 focus-within:shadow-[0_0_0_3px_rgba(37,99,235,.08)]',
        )}
      >
        <textarea
          ref={taRef}
          rows={2}
          value={value}
          disabled={busy}
          aria-label="消息内容"
          placeholder={busy ? '正在生成回答…' : `有什么想法？交给 ${BRAND_NAME}。`}
          className="mb-2 max-h-40 min-h-[58px] w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 text-bone outline-none placeholder:text-ash disabled:opacity-50"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Icon name="model" className="hidden h-4 w-4 shrink-0 text-ash sm:block" />
            <Select
              aria-label="本次对话模型"
              className="w-full max-w-[230px] border-transparent bg-transparent py-1.5 text-xs"
              value={activeModelId ?? ''}
              disabled={busy}
              onValueChange={(value) => setActiveModel(value ? Number(value) : undefined)}
            >
              <option value="">跟随 Agent 配置</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} · {m.provider}
                  {m.is_default ? '（默认）' : ''}
                </option>
              ))}
            </Select>
          </div>
          {sending ? (
            <button
              className="btn-danger min-h-9 shrink-0 px-3 py-1.5 text-xs"
              onClick={stop}
              title="停止生成"
            >
              <span className="h-2.5 w-2.5 rounded-sm bg-coral" />
              停止
            </button>
          ) : (
            <button
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-lime text-bone transition-all hover:bg-[#1d4ed8] active:scale-95 disabled:bg-graphite disabled:text-ash"
              disabled={busy || !value.trim()}
              onClick={submit}
              aria-label="发送消息"
              title="发送消息（Enter）"
            >
              <Icon name="up" className="h-[18px] w-[18px]" />
            </button>
          )}
        </div>
        {models.length === 0 && (
          <p className="mt-2 px-1 text-[11px] text-ash">暂无可用模型，请在「模型管理」中配置</p>
        )}
      </div>
      <p className="mx-auto mt-3 max-w-[800px] text-center text-[10px] text-ash">
        <span className="hidden sm:inline">
          Enter 发送 · Shift + Enter 换行<span className="mx-3 text-smoke">|</span>
        </span>
        AI 生成的内容请核实后使用
      </p>
    </div>
  );
}
