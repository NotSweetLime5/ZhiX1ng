import { StrictMode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SourceViewer } from './SourceViewer';
import { UploadQueue } from './UploadQueue';

const api = vi.hoisted(() => ({ source: vi.fn(), doc: vi.fn(), content: vi.fn(), upload: vi.fn() }));
vi.mock('@/api/kb', () => ({
  getChunkSource: api.source,
  getDocument: api.doc,
  getDocumentContent: api.content,
  uploadDoc: api.upload,
}));
vi.mock('@/lib/gsap', () => ({
  gsap: {
    context: (callback: () => void) => {
      callback();
      return { revert() {} };
    },
    fromTo() {},
  },
}));
afterEach(cleanup);

it('verifies chunk provenance, downloads authenticated content, and cleans up blob URLs under StrictMode', async () => {
  api.source.mockResolvedValue({
    document_id: 31,
    file_type: 'pdf',
    page: 3,
    content: 'Verified source paragraph',
  });
  api.content.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
  const create = vi.fn(() => 'blob:source-preview');
  const revoke = vi.fn();
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  const result = render(
    <StrictMode>
      <SourceViewer
        source={{ document_id: 31, chunk_id: 501, filename: 'source.pdf', page: 3 }}
        onClose={() => undefined}
      />
    </StrictMode>,
  );
  await screen.findByText('Verified source paragraph');
  fireEvent.click(screen.getByRole('button', { name: '读取原文件' }));
  await waitFor(() =>
    expect(screen.getByTitle('原始 PDF').getAttribute('src')).toBe('blob:source-preview#page=3'),
  );
  expect(api.content.mock.calls[0][0]).toBe(31);
  result.unmount();
  expect(revoke).toHaveBeenCalledWith('blob:source-preview');
  vi.unstubAllGlobals();
});
it('shows source access errors without exposing an old excerpt or download', async () => {
  api.source.mockRejectedValue(new Error('引用内容已删除或不存在'));
  render(
    <SourceViewer
      source={{ document_id: 31, chunk_id: 501, filename: 'source.pdf', content: 'old private excerpt' }}
      onClose={() => undefined}
    />,
  );
  await screen.findByRole('alert');
  expect(screen.queryByText('old private excerpt')).toBeNull();
  expect(screen.queryByRole('button', { name: '读取原文件' })).toBeNull();
});
it('queues multiple files sequentially, reports one upload error, and continues with the next', async () => {
  let release!: () => void;
  const first = new Promise<void>((resolve) => {
    release = resolve;
  });
  api.upload
    .mockReset()
    .mockImplementationOnce(async (_kb, _file, progress) => {
      progress(50);
      await first;
      throw new Error('first failed');
    })
    .mockResolvedValueOnce({ id: 32 });
  const uploaded = vi.fn();
  render(<UploadQueue kbId={12} onUploaded={uploaded} />);
  fireEvent.change(screen.getByLabelText('选择知识文档'), {
    target: { files: [new File(['a'], 'one.txt'), new File(['b'], 'two.md')] },
  });
  expect(api.upload).toHaveBeenCalledTimes(1);
  expect(screen.getByText('上传 50%')).toBeTruthy();
  release();
  await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(2));
  await screen.findByText('first failed');
  await waitFor(() => expect(uploaded).toHaveBeenCalledTimes(1));
});
it('rejects unsupported/empty documents without making a request', () => {
  api.upload.mockReset();
  render(<UploadQueue kbId={12} onUploaded={() => undefined} />);
  fireEvent.change(screen.getByLabelText('选择知识文档'), {
    target: { files: [new File(['x'], 'code.exe'), new File([], 'empty.txt')] },
  });
  expect(screen.getAllByRole('alert')).toHaveLength(2);
  expect(api.upload).not.toHaveBeenCalled();
});
