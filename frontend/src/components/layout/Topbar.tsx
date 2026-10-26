import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/stores/auth';
import { Icon } from '@/components/ui/Icon';

const TITLES: Record<string, string> = { chat: '智能对话', agents: '智能体', memories: '长期记忆', kbs: '知识库', workflows: '工作流', models: '模型管理', integrations: '集成中心', evaluations: 'Agent 评估' };

export function Topbar() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const navigate = useNavigate();
  const parts = useLocation().pathname.split('/').filter(Boolean);
  const title = TITLES[parts[0] === 'admin' ? parts[1] : parts[0]] || '工作空间';
  return (
    <header className="flex h-[76px] shrink-0 items-center justify-between gap-3 border-b border-smoke/40 bg-carbon/50 px-4 sm:px-8">
      <div className="flex min-w-0 items-center gap-3 text-sm"><span className="hidden text-ash sm:inline">工作空间</span><Icon name="chevron" className="hidden h-3 w-3 text-smoke sm:block" /><span className="truncate font-medium text-bone">{title}</span></div>
      {user && <div className="flex items-center gap-3 sm:gap-4">
        <div className="hidden text-right sm:block"><p className="text-xs font-medium text-bone">{user.username}</p><p className="mt-1 text-[10px] text-ash">{user.role === 'admin' ? '管理员' : '工作空间成员'}</p></div>
        <span className="flex h-9 w-9 items-center justify-center rounded-full border border-lime/20 bg-lime/10 text-xs font-semibold uppercase text-lime">{user.username.slice(0, 2)}</span>
        <div className="h-5 border-l border-smoke/50" />
        <button onClick={async () => { await logout(); navigate('/login'); }} className="icon-button" title="退出登录" aria-label="退出登录"><Icon name="logout" className="h-[18px] w-[18px]" /></button>
      </div>}
    </header>
  );
}
