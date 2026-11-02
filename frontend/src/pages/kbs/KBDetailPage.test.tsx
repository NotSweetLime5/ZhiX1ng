import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { KBDetailPage } from './KBDetailPage';

const api = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/api/kb', () => ({
  getKB: async () => ({ name: '学习资料' }),
  listDocs: api.list,
  listChunks: vi.fn(),
  deleteDoc: vi.fn(),
  retryDocument: vi.fn(),
  testRetrieve: vi.fn(),
}));
vi.mock('@/components/knowledge/UploadQueue', () => ({ UploadQueue: () => <div>上传队列</div> }));
vi.mock('@/components/knowledge/SourceViewer', () => ({ SourceViewer: () => null }));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
it('polls processing documents until ready, then stops polling', async () => {
  vi.useFakeTimers();
  const doc = { id: 31, filename: 'notes.txt', file_size: 80, chunk_count: 0, status: 'parsing' };
  api.list
    .mockResolvedValueOnce({ list: [doc], total: 1 })
    .mockResolvedValue({ list: [{ ...doc, status: 'ready', chunk_count: 2 }], total: 1 });
  render(
    <MemoryRouter
      initialEntries={['/kbs/12']}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/kbs/:id" element={<KBDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText('处理中自动更新状态；阶段表示当前工作，不代表精确完成百分比。')).toBeTruthy();
  expect(screen.getByLabelText('处理阶段')).toBeTruthy();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.queryByLabelText('处理阶段')).toBeNull();
  expect(screen.getByText(/2 个分块/)).toBeTruthy();
  const count = api.list.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(12_000);
  });
  expect(api.list).toHaveBeenCalledTimes(count);
  fireEvent.click(screen.getByRole('button', { name: '刷新' }));
  await act(async () => {
    await Promise.resolve();
  });
  expect(api.list).toHaveBeenCalledTimes(count + 1);
});
