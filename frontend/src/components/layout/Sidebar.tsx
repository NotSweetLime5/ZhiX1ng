import { NavLink } from 'react-router-dom';
import { useAuth } from '@/stores/auth';
import { BrandMark, Icon, type IconName } from '@/components/ui/Icon';
import { BRAND_NAME, BRAND_VERSION } from '@/lib/brand';

const NAV: { to: string; label: string; icon: IconName; isAdmin?: boolean }[] = [
  { to: '/chat', label: '智能对话', icon: 'chat' },
  { to: '/agents', label: '智能体', icon: 'agent' },
  { to: '/kbs', label: '知识库', icon: 'book' },
  { to: '/memories', label: '长期记忆', icon: 'memory' },
  { to: '/workflows', label: '工作流', icon: 'workflow' },
  { to: '/admin/models', label: '模型管理', icon: 'model', isAdmin: true },
  { to: '/admin/integrations', label: '集成中心', icon: 'plug', isAdmin: true },
  { to: '/admin/evaluations', label: 'Agent 评估', icon: 'check', isAdmin: true },
];

export function Sidebar() {
  const user = useAuth((s) => s.user);
  const navGroup = (admin: boolean) => NAV.filter((n) => Boolean(n.isAdmin) === admin).map((n) => (
    <NavLink key={n.to} to={n.to} title={n.label} aria-label={n.label} className="nav-item">
      <Icon name={n.icon} className="h-[18px] w-[18px] shrink-0" />
      <span className="hidden md:block">{n.label}</span>
    </NavLink>
  ));
  return (
    <aside className="flex h-full w-[68px] shrink-0 flex-col border-r border-smoke/40 bg-carbon md:w-[224px]">
      <NavLink to="/chat" aria-label={`${BRAND_NAME} 首页`} className="flex h-[76px] shrink-0 items-center justify-center gap-3 md:justify-start md:px-6">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-lime/20 bg-lime/10 text-lime"><BrandMark className="h-6 w-6" /></span>
        <div className="hidden md:block"><p className="text-[15px] font-semibold tracking-tight text-bone">{BRAND_NAME}</p><p className="mt-0.5 text-[9px] tracking-[.2em] text-ash">AI WORKSPACE</p></div>
      </NavLink>
      <nav aria-label="主导航" className="min-h-0 flex-1 overflow-y-auto px-2 py-4 md:px-4">
        <p className="section-title mb-3 hidden px-3 md:block">工作空间</p>
        <div className="space-y-1">{navGroup(false)}</div>
        {user?.role === 'admin' && <><div className="mx-3 my-6 border-t border-smoke/40" /><p className="section-title mb-3 hidden px-3 md:block">管理与配置</p><div className="space-y-1">{navGroup(true)}</div></>}
      </nav>
      <div className="m-4 hidden rounded-2xl border border-smoke/40 bg-obsidian/50 p-4 md:block">
        <div className="flex items-center gap-2 text-xs font-medium text-mist"><Icon name="spark" className="h-4 w-4 text-lime" />把想法变成行动</div>
        <p className="mt-2 text-[11px] leading-5 text-ash">连接工具与知识，构建你的智能工作空间。</p>
        <div className="mt-4 flex items-center justify-between border-t border-smoke/40 pt-3 text-[10px] text-ash"><span>{BRAND_NAME}</span><span className="rounded-md bg-graphite px-1.5 py-0.5">v{BRAND_VERSION}</span></div>
      </div>
    </aside>
  );
}
