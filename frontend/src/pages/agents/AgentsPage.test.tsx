import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AgentsPage } from './AgentsPage';

const api = vi.hoisted(() => ({ create: vi.fn(), models: vi.fn() }));
vi.mock('@/api/agent', () => ({
  listAgents: async () => ({ list: [], total: 0 }),
  listTools: async () => ({ list: [], total: 0 }),
  createAgent: api.create,
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
}));
vi.mock('@/api/kb', () => ({ allKBs: async () => [{ id: 12, name: 'AI 学习资料', doc_count: 8 }] }));
vi.mock('@/api/chat', () => ({ listChatModels: api.models }));
vi.mock('@/lib/gsap', () => ({
  gsap: {
    context: (cb: () => void) => {
      cb();
      return { revert() {} };
    },
    fromTo() {},
  },
  staggerEnter: () => ({ kill() {} }),
}));
vi.mock('@/components/ui/Select', () => ({
  Select: ({
    children,
    onValueChange,
    ...props
  }: {
    children: ReactNode;
    onValueChange: (s: string) => void;
  }) => (
    <select {...props} onChange={(e) => onValueChange(e.target.value)}>
      {children}
    </select>
  ),
}));
afterEach(cleanup);
function Destination() {
  return <div>{useLocation().search}</div>;
}
it('saves named model and KB selections as IDs, then opens the saved agent trial', async () => {
  api.models.mockResolvedValue([{ id: 21, label: 'DeepSeek', provider: '测试供应商' }]);
  api.create.mockResolvedValue({ id: 107 });
  render(
    <MemoryRouter initialEntries={['/agents']}>
      <Routes>
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/chat" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole('button', { name: /新建 Agent/ }));
  await screen.findByText('AI 学习资料');
  fireEvent.change(screen.getByLabelText('Agent 名称'), { target: { value: '学习助手' } });
  fireEvent.change(screen.getByLabelText('对话模型'), { target: { value: '21' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /AI 学习资料/ }));
  fireEvent.click(screen.getByRole('button', { name: '保存并试聊' }));
  await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
  expect(api.create.mock.calls[0][0]).toMatchObject({ model_config_id: 21, kb_ids: [12], name: '学习助手' });
  await screen.findByText('?agent=107');
});
it('keeps invalid input in the form and does not save it', async () => {
  api.create.mockReset();
  api.models.mockResolvedValue([{ id: 21, label: 'DeepSeek', provider: '测试' }]);
  render(
    <MemoryRouter>
      <AgentsPage />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole('button', { name: /新建 Agent/ }));
  await screen.findByText('AI 学习资料');
  fireEvent.click(screen.getByRole('button', { name: '保存并试聊' }));
  await screen.findByText('名称需要 1～128 个字符');
  expect(api.create).not.toHaveBeenCalled();
});
