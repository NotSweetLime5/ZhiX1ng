import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button, EmptyState, Input, PageHeader, Spinner, StatusBadge } from '@/components/ui/primitives';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { UploadQueue } from '@/components/knowledge/UploadQueue';
import { SourceViewer, type SourceTarget } from '@/components/knowledge/SourceViewer';
import { deleteDoc, getKB, listChunks, listDocs, retryDocument, testRetrieve } from '@/api/kb';
import { fileSize, truncate } from '@/lib/format';
import { errMsg } from '@/lib/request';
import { toast } from '@/stores/ui';
import type { Document, DocumentChunk, KnowledgeBase } from '@/types/kb';
import type { RAGRef } from '@/types/chat';

const BUSY = new Set(['pending', 'parsing', 'chunking', 'embedding']);
const STAGES = ['pending', 'parsing', 'chunking', 'embedding', 'ready'];
const STAGE_LABELS = ['等待', '解析/OCR', '切块', '向量化', '可检索'];

export function KBDetailPage() {
  const { id } = useParams();
  const value = Number(id);
  if (!Number.isInteger(value) || value < 1)
    return <EmptyState title="无效的知识库" action={<Link to="/kbs">返回列表</Link>} />;
  // Route changes unmount all document requests and file queues belonging to the old KB.
  return <KBWorkspace key={value} kbId={value} />;
}
function KBWorkspace({ kbId }: { kbId: number }) {
  const [kb, setKb] = useState<KnowledgeBase>();
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState('');
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  const [delDoc, setDelDoc] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState<number>();
  const [source, setSource] = useState<SourceTarget | null>(null);
  const [chunkDoc, setChunkDoc] = useState<Document | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [chunkPage, setChunkPage] = useState(1);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkError, setChunkError] = useState('');
  const [chunksLoading, setChunksLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [retrieving, setRetrieving] = useState(false);
  const [refs, setRefs] = useState<RAGRef[] | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Recursive polling never overlaps. Stop when no document is being processed.
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const all: Document[] = [];
        for (let page = 1; ; page++) {
          const data = await listDocs(kbId, { page, page_size: 100 });
          if (!active) return;
          all.push(...data.list);
          if (all.length >= data.total || !data.list.length) break;
        }
        const latest = await getKB(kbId);
        if (!active) return;
        setDocs(all);
        setKb(latest);
        setRefreshError('');
        if (all.some((d) => BUSY.has(d.status)))
          timer = setTimeout(() => void load(), document.hidden ? 10_000 : 3000);
      } catch (e) {
        if (!active) return;
        setRefreshError(errMsg(e));
        timer = setTimeout(() => void load(), 10_000);
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [kbId, revision]);
  useEffect(() => {
    if (!chunkDoc) return;
    let active = true;
    setChunksLoading(true);
    setChunkError('');
    setChunks([]);
    void listChunks(chunkDoc.id, { page: chunkPage, page_size: 20 })
      .then((data) => {
        if (active) {
          setChunks(data.list);
          setChunkTotal(data.total);
        }
      })
      .catch((e) => {
        if (active) setChunkError(errMsg(e));
      })
      .finally(() => {
        if (active) setChunksLoading(false);
      });
    return () => {
      active = false;
    };
  }, [chunkDoc, chunkPage]);
  const remove = async () => {
    if (!delDoc) return;
    setDeleting(true);
    try {
      await deleteDoc(kbId, delDoc.id);
      if (alive.current) {
        setDelDoc(null);
        refresh();
      }
    } catch (e) {
      if (alive.current) toast.err(errMsg(e));
    } finally {
      if (alive.current) setDeleting(false);
    }
  };
  const retry = async (doc: Document) => {
    setRetrying(doc.id);
    try {
      await retryDocument(doc.id);
      if (alive.current) {
        toast.ok('已重新提交处理');
        refresh();
      }
    } catch (e) {
      if (alive.current) toast.err(errMsg(e));
    } finally {
      if (alive.current) setRetrying(undefined);
    }
  };
  const retrieve = async () => {
    if (!query.trim() || retrieving) return;
    setRetrieving(true);
    try {
      const result = await testRetrieve(kbId, query.trim());
      if (alive.current) setRefs(result);
    } catch (e) {
      if (alive.current) toast.err(errMsg(e));
    } finally {
      if (alive.current) setRetrieving(false);
    }
  };
  return (
    <div className="page-container">
      <PageHeader
        title={kb?.name ?? '知识库'}
        desc={kb?.description || '上传资料，观察处理状态，再检索并核查来源。'}
        action={
          <Link className="btn-ghost" to="/kbs">
            ← 返回列表
          </Link>
        }
      />
      <div className="mb-5 flex flex-wrap gap-4 text-xs text-ash">
        <span>{docs.length} 篇文档</span>
        <span>{docs.filter((d) => d.status === 'ready').length} 篇可检索</span>
        <span>{docs.filter((d) => BUSY.has(d.status)).length} 篇处理中</span>
        <span>{docs.filter((d) => d.status === 'failed').length} 篇失败</span>
      </div>
      <UploadQueue kbId={kbId} onUploaded={refresh} />
      {refreshError && (
        <div role="alert" className="mb-4 rounded-xl border border-coral/30 p-3 text-sm text-coral">
          {refreshError}{' '}
          <Button variant="ghost" onClick={refresh}>
            重新加载
          </Button>
        </div>
      )}
      <section className="panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="section-title">文档与处理状态</h2>
          <Button variant="ghost" onClick={refresh}>
            刷新
          </Button>
        </div>
        {loading ? (
          <div className="py-8 text-center">
            <Spinner />
          </div>
        ) : !docs.length ? (
          <EmptyState title="暂无文档" hint="从上方选择资料，系统会自动解析并建立索引" />
        ) : (
          <div className="space-y-3">
            {docs.map((doc) => (
              <article key={doc.id} className="rounded-xl border border-smoke/50 bg-carbon/30 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <button
                      className="break-all text-left text-sm font-medium text-bone hover:text-lime"
                      onClick={() => setSource({ document_id: doc.id, filename: doc.filename, page: 1 })}
                    >
                      {doc.filename} ↗
                    </button>
                    <p className="mt-1 text-xs text-ash">
                      {fileSize(doc.file_size)} · {doc.chunk_count} 个分块
                    </p>
                  </div>
                  <StatusBadge status={doc.status} />
                </div>
                {BUSY.has(doc.status) && (
                  <ol aria-label="处理阶段" className="mt-4 grid grid-cols-5 gap-1">
                    {STAGES.map((stage, index) => (
                      <li
                        key={stage}
                        className={`border-t-2 pt-2 text-[10px] sm:text-xs ${index <= STAGES.indexOf(doc.status) ? 'border-lime text-lime' : 'border-smoke text-ash'}`}
                      >
                        {STAGE_LABELS[index]}
                        {stage === doc.status && <span className="ml-1 animate-pulse">…</span>}
                      </li>
                    ))}
                  </ol>
                )}
                {doc.error && (
                  <details className="mt-3 rounded-lg bg-coral/5 p-3 text-xs text-coral">
                    <summary className="cursor-pointer">
                      {doc.status === 'failed' ? '处理失败 · 查看原因' : '最近一次处理信息'}
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap break-all">{doc.error}</p>
                  </details>
                )}
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setChunkPage(1);
                      setChunkDoc(doc);
                    }}
                  >
                    查看分块
                  </Button>
                  {doc.status === 'failed' && (
                    <Button
                      loading={retrying === doc.id}
                      disabled={retrying !== undefined}
                      onClick={() => void retry(doc)}
                    >
                      重试处理
                    </Button>
                  )}
                  <Button variant="danger" onClick={() => setDelDoc(doc)}>
                    删除
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
        <p className="mt-4 text-xs text-ash">处理中自动更新状态；阶段表示当前工作，不代表精确完成百分比。</p>
      </section>
      <section className="panel mt-6 p-5">
        <h2 className="section-title mb-4">检索与来源核查</h2>
        <div className="flex gap-2">
          <Input
            aria-label="检索内容"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入问题，验证资料是否能被找到"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) void retrieve();
            }}
          />
          <Button loading={retrieving} disabled={!query.trim()} onClick={() => void retrieve()}>
            检索
          </Button>
        </div>
        <div className="mt-4 space-y-3">
          {refs?.length === 0 && <EmptyState title="未找到相关内容" hint="请确认文档可检索，或换一个问题" />}
          {refs?.map((ref, i) => (
            <button
              key={`${ref.chunk_id}-${i}`}
              className="block w-full rounded-xl border border-smoke/50 p-4 text-left hover:border-lime/50"
              onClick={() => setSource(ref)}
            >
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="text-lime">[{i + 1}]</span>
                <span className="text-bone">{ref.filename}</span>
                <span className="text-ash">第 {ref.page} 页</span>
                <span className="ml-auto text-lime">查看原文 ↗</span>
              </div>
              <p className="mt-2 text-sm leading-6 text-fog">{truncate(ref.content, 240)}</p>
            </button>
          ))}
        </div>
      </section>
      <Modal
        open={!!chunkDoc}
        title={`分块 · ${chunkDoc?.filename ?? ''}`}
        onClose={() => setChunkDoc(null)}
        width="max-w-3xl"
      >
        {chunksLoading ? (
          <Spinner />
        ) : chunkError ? (
          <p role="alert" className="text-coral">
            {chunkError}
          </p>
        ) : !chunks.length ? (
          <EmptyState title="暂未生成分块" />
        ) : (
          <div className="space-y-3">
            {chunks.map((chunk) => (
              <div key={chunk.id} className="rounded-lg border border-smoke/40 p-3">
                <button
                  className="text-xs text-lime"
                  onClick={() => {
                    const target = {
                      document_id: chunk.document_id,
                      chunk_id: chunk.id,
                      filename: chunkDoc!.filename,
                      page: Number(chunk.meta.page) || 1,
                    };
                    setChunkDoc(null);
                    setSource(target);
                  }}
                >
                  分块 {chunk.seq + 1} · 第 {Number(chunk.meta.page) || 1} 页 · 查看来源 ↗
                </button>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-fog">
                  {chunk.content}
                </p>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4 flex items-center justify-between text-xs text-ash">
          <Button
            variant="ghost"
            disabled={chunkPage <= 1 || chunksLoading}
            onClick={() => setChunkPage((n) => n - 1)}
          >
            上一页
          </Button>
          <span>
            第 {chunkPage} 页 · 共 {chunkTotal} 块
          </span>
          <Button
            variant="ghost"
            disabled={chunkPage * 20 >= chunkTotal || chunksLoading}
            onClick={() => setChunkPage((n) => n + 1)}
          >
            下一页
          </Button>
        </div>
      </Modal>
      <SourceViewer source={source} onClose={() => setSource(null)} />
      <ConfirmDialog
        open={!!delDoc}
        title="删除文档"
        content={`确认删除「${delDoc?.filename ?? ''}」？新查询将不再使用它，原文和索引会在后台清理。`}
        danger
        loading={deleting}
        onCancel={() => setDelDoc(null)}
        onConfirm={() => void remove()}
      />
    </div>
  );
}
