import { useEffect, useState } from 'react';
import { getChunkSource, getDocument, getDocumentContent } from '@/api/kb';
import { errMsg } from '@/lib/request';
import { Modal } from '@/components/ui/Modal';
import { Button, Spinner } from '@/components/ui/primitives';

export interface SourceTarget {
  document_id: number;
  chunk_id?: number;
  filename: string;
  page?: number;
  content?: string;
}

/** Authenticated blob URLs keep credentials out of iframe URLs and support native PDF page navigation. */
export function SourceViewer({ source, onClose }: { source: SourceTarget | null; onClose: () => void }) {
  return (
    <Modal open={!!source} onClose={onClose} title={`资料来源 · ${source?.filename ?? ''}`} width="max-w-5xl">
      {source && <SourceContent key={`${source.document_id}:${source.chunk_id ?? 0}`} source={source} />}
    </Modal>
  );
}

function SourceContent({ source }: { source: SourceTarget }) {
  const [info, setInfo] = useState<{ file_type: string; page?: number; content?: string }>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [requestId, setRequestId] = useState(0);
  const [original, setOriginal] = useState<Blob>();
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        if (source.chunk_id) {
          const data = await getChunkSource(source.chunk_id, controller.signal);
          if (data.document_id !== source.document_id) throw new Error('引用与文档不匹配');
          setInfo(data);
        } else {
          const doc = await getDocument(source.document_id, controller.signal);
          setInfo({ file_type: doc.file_type, page: source.page, content: source.content });
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(errMsg(e));
      }
    };
    void load();
    return () => controller.abort();
  }, [source]);
  useEffect(() => {
    if (!original) return;
    const value = URL.createObjectURL(original);
    setUrl(value);
    let active = true;
    if (info?.file_type !== 'pdf' && info?.file_type !== 'docx') {
      void original.text().then((value) => {
        if (active) setText(value);
      });
    }
    return () => {
      active = false;
      URL.revokeObjectURL(value);
    };
  }, [original, info?.file_type]);
  useEffect(() => {
    if (!requestId) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void getDocumentContent(source.document_id, controller.signal)
      .then((blob) => {
        if (!controller.signal.aborted) setOriginal(blob);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errMsg(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [requestId, source.document_id]);
  return (
    <div className="space-y-4">
      {!info && !error && <Spinner />}
      {info && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm text-ash">
            <span>{source.filename}</span>
            <span>第 {info.page || source.page || 1} 页</span>
            <Button variant="ghost" loading={loading} onClick={() => setRequestId((n) => n + 1)}>
              读取原文件
            </Button>
            {url && (
              <a className="btn-ghost" href={url} download={source.filename}>
                下载原文件
              </a>
            )}
          </div>
          {info.content && (
            <section className="rounded-xl border border-lime/30 bg-lime/5 p-4">
              <h3 className="mb-2 text-xs text-lime">引用段落</h3>
              <p className="whitespace-pre-wrap break-words text-sm leading-7 text-bone">{info.content}</p>
            </section>
          )}
          {url && info.file_type === 'pdf' && (
            <>
              <p className="text-xs text-ash">
                使用浏览器 PDF 阅读器定位来源页；若无法预览，可下载原文件核对。
              </p>
              <iframe
                title="原始 PDF"
                src={`${url}#page=${Math.max(1, info.page || source.page || 1)}`}
                className="h-[55vh] w-full rounded-lg bg-graphite"
              />
            </>
          )}
          {url && info.file_type === 'docx' && (
            <p className="text-sm text-ash">DOCX 请下载后打开，引用段落可在上方核对。</p>
          )}
          {url && !['pdf', 'docx'].includes(info.file_type) && (
            <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-graphite p-4 text-sm text-fog">
              {text}
            </pre>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-coral">
          {error}
        </p>
      )}
    </div>
  );
}
