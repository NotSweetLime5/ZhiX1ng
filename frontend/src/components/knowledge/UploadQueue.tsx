import { useEffect, useRef, useState } from 'react';
import { uploadDoc } from '@/api/kb';
import { errMsg } from '@/lib/request';
import { fileSize } from '@/lib/format';
import { Button } from '@/components/ui/primitives';

interface Item {
  id: number;
  file: File;
  percent: number;
  status: 'queued' | 'uploading' | 'uploaded' | 'failed';
  error?: string;
}
export function UploadQueue({ kbId, onUploaded }: { kbId: number; onUploaded: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const queue = useRef<Item[]>([]);
  const serial = useRef(0);
  const running = useRef(false);
  const mounted = useRef(false);
  const controller = useRef<AbortController>();
  const callback = useRef(onUploaded);
  callback.current = onUploaded;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  const publish = () => {
    if (mounted.current) setItems(queue.current.map((item) => ({ ...item })));
  };
  const drain = async () => {
    if (running.current) return;
    running.current = true;
    try {
      while (mounted.current) {
        const item = queue.current.find((item) => item.status === 'queued');
        if (!item) break;
        item.status = 'uploading';
        publish();
        controller.current = new AbortController();
        try {
          await uploadDoc(
            kbId,
            item.file,
            (value) => {
              item.percent = value;
              publish();
            },
            controller.current.signal,
          );
          item.status = 'uploaded';
          item.percent = 100;
          if (mounted.current) callback.current();
        } catch (e) {
          item.status = 'failed';
          item.error = errMsg(e);
        }
        publish();
      }
    } finally {
      running.current = false;
    }
  };
  const enqueue = (files: FileList | File[]) => {
    for (const file of Array.from(files).slice(0, 20)) {
      const valid =
        /\.(pdf|docx|txt|md|markdown|html|htm)$/i.test(file.name) &&
        file.size > 0 &&
        file.size <= 20 * 1024 * 1024;
      queue.current.push({
        id: ++serial.current,
        file,
        percent: 0,
        status: valid ? 'queued' : 'failed',
        error: valid ? undefined : '格式不支持或大小超出 1 字节～20 MB，无法上传。',
      });
    }
    publish();
    void drain();
  };
  return (
    <section
      className="mb-5 rounded-2xl border border-dashed border-smoke bg-graphite/40 p-5"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        enqueue(e.dataTransfer.files);
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-bone">拖入资料，或选择多个文件</h3>
          <p className="mt-2 text-xs text-ash">
            PDF / DOCX / TXT / Markdown / HTML · 每个不超过 20 MB，每次最多 20 个。上传后自动显示处理状态。
          </p>
        </div>
        <label className="btn-primary cursor-pointer">
          选择文件
          <input
            aria-label="选择知识文档"
            type="file"
            multiple
            className="hidden"
            accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm"
            onChange={(e) => {
              if (e.target.files) enqueue(e.target.files);
              e.target.value = '';
            }}
          />
        </label>
      </div>
      {items.length > 0 && (
        <div className="mt-4 space-y-3" aria-live="polite">
          {items.map((item) => (
            <div key={item.id} className="rounded-lg border border-smoke/40 p-3">
              <div className="flex items-center gap-3 text-xs">
                <span className="min-w-0 flex-1 truncate text-bone">{item.file.name}</span>
                <span className="text-ash">{fileSize(item.file.size)}</span>
                <span className={item.status === 'failed' ? 'text-coral' : 'text-ash'}>
                  {item.status === 'queued'
                    ? '等待上传'
                    : item.status === 'uploaded'
                      ? '已接收，处理状态见下方'
                      : item.status === 'failed'
                        ? '未完成'
                        : item.percent === 100
                          ? '文件已传输，正在确认接收'
                          : `上传 ${item.percent}%`}
                </span>
              </div>
              {item.status === 'uploading' && (
                <progress
                  aria-label={`${item.file.name} 上传进度`}
                  value={item.percent}
                  max={100}
                  className="mt-2 h-1.5 w-full accent-lime"
                />
              )}
              {item.error && (
                <p role="alert" className="mt-2 break-words text-xs text-coral">
                  {item.error}
                </p>
              )}
            </div>
          ))}
          <Button
            variant="ghost"
            disabled={items.some((item) => item.status === 'uploading' || item.status === 'queued')}
            onClick={() => {
              queue.current = [];
              publish();
            }}
          >
            清空上传记录
          </Button>
        </div>
      )}
    </section>
  );
}
