/**
 * 知识库接口 —— 对应 app/api/routes/knowledge.py。
 * 上传为 multipart（c.FormFile("file")）。
 */
import { http, request, requestBlob, uploadWithProgress } from '@/lib/request';
import type { Paged, PageQuery } from '@/types/api';
import type { RAGRef } from '@/types/chat';
import type { Document, DocumentChunk, KBReq, KnowledgeBase } from '@/types/kb';

/** 知识库列表（分页） */
export const listKBs = (q?: PageQuery) => http.get<Paged<KnowledgeBase>>('/kbs', q);

/** 知识库详情 */
export const getKB = (id: number) => http.get<KnowledgeBase>(`/kbs/${id}`);

/** 创建知识库 */
export const createKB = (req: KBReq) => http.post<KnowledgeBase>('/kbs', req);

/** 删除知识库 */
export const deleteKB = (id: number) => http.delete(`/kbs/${id}`);

/** 上传文档（multipart，字段名必须是 file） */
export const uploadDoc = (
  kbId: number,
  file: File,
  progress: (value: number) => void = () => undefined,
  signal?: AbortSignal,
) => {
  const fd = new FormData();
  fd.append('file', file);
  return uploadWithProgress<Document>(`/kbs/${kbId}/documents`, fd, progress, signal);
};

/** 文档列表（分页） */
export const listDocs = (kbId: number, q?: PageQuery) =>
  http.get<Paged<Document>>(`/kbs/${kbId}/documents`, q);

/** 删除文档 */
export const deleteDoc = (kbId: number, docId: number) => http.delete(`/kbs/${kbId}/documents/${docId}`);

/** 检索测试台：POST /kbs/:id/retrieve {query} → Ref[] */
export const testRetrieve = (kbId: number, query: string) =>
  http.post<RAGRef[]>(`/kbs/${kbId}/retrieve`, { query });

/** 分块列表 */
export const listChunks = (docId: number, q?: PageQuery) =>
  http.get<Paged<DocumentChunk>>(`/documents/${docId}/chunks`, q);

export const getDocument = (id: number, signal?: AbortSignal) =>
  request<Document>(`/documents/${id}`, { signal });
export const getDocumentContent = (id: number, signal?: AbortSignal) =>
  requestBlob(`/documents/${id}/content`, signal);
export const retryDocument = (id: number) => http.post<Document>(`/documents/${id}/retry`);
export interface ChunkSource {
  chunk_id: number;
  document_id: number;
  kb_id: number;
  filename: string;
  file_type: string;
  page: number;
  content: string;
}
export const getChunkSource = (id: number, signal?: AbortSignal) =>
  request<ChunkSource>(`/chunks/${id}/source`, { signal });

/** Fetch every option, rather than silently hiding bindings beyond the first page. */
export async function allKBs(): Promise<KnowledgeBase[]> {
  const result: KnowledgeBase[] = [];
  for (let page = 1; ; page++) {
    const data = await listKBs({ page, page_size: 100 });
    result.push(...data.list);
    if (result.length >= data.total || !data.list.length) return result;
  }
}
