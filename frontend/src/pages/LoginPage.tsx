import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { gsap, shake } from '@/lib/gsap';
import { useAuth } from '@/stores/auth';
import { toast } from '@/stores/ui';
import { errMsg } from '@/lib/request';
import { Button, Input } from '@/components/ui/primitives';
import { BrandMark, Icon } from '@/components/ui/Icon';
import { BRAND_NAME } from '@/lib/brand';

export function LoginPage() {
  const navigate = useNavigate();
  const { user, bootstrapped, login, register } = useAuth();
  const cardRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(cardRef.current, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : .5, ease: 'power3.out' });
    });
    return () => ctx.revert();
  }, []);
  if (bootstrapped && user) return <Navigate to="/chat" replace />;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) { if (cardRef.current) shake(cardRef.current); toast.err('请填写用户名与密码'); return; }
    setLoading(true);
    try {
      if (mode === 'register') { await register({ username, email, password }); toast.ok('注册成功'); }
      await login({ username, password });
      navigate('/chat');
    } catch (err) { if (cardRef.current) shake(cardRef.current); toast.err(errMsg(err)); }
    finally { setLoading(false); }
  };
  return (
    <div className="grid min-h-[100dvh] lg:grid-cols-2">
      <section className="relative hidden overflow-hidden border-r border-smoke/40 bg-carbon p-12 lg:flex lg:flex-col xl:p-16">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_30%_50%,rgba(37,99,235,.07),transparent_70%)]" />
        <div className="relative flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl border border-lime/20 bg-lime/10 text-lime"><BrandMark className="h-7 w-7" /></span><span className="text-lg font-semibold tracking-tight text-bone">{BRAND_NAME}</span></div>
        <div className="relative my-auto max-w-lg py-16">
          <p className="mb-6 text-xs tracking-[.25em] text-lime">THINK. CONNECT. CREATE.</p>
          <h1 className="text-4xl font-semibold leading-[1.5] tracking-tight text-bone xl:text-5xl">你的想法，<br />值得更进一步。</h1>
          <p className="mt-6 max-w-sm text-sm leading-7 text-fog">让智能体连接知识、工具与工作流，<br />把每一次提问，变成向前的一步。</p>
          <div className="mt-12 grid grid-cols-3 gap-3">
            {([{ icon: 'agent', title: '智能体', text: '专属任务助手' }, { icon: 'book', title: '知识库', text: '连接你的资料' }, { icon: 'workflow', title: '工作流', text: '有序执行任务' }] as const).map((item) => <div key={item.title} className="rounded-2xl border border-smoke/50 bg-obsidian/70 p-4"><Icon name={item.icon} className="mb-5 h-5 w-5 text-lime" /><p className="text-sm text-bone">{item.title}</p><p className="mt-2 text-[11px] text-ash">{item.text}</p></div>)}
          </div>
        </div>
        <p className="relative text-[11px] tracking-wider text-ash">{BRAND_NAME} · YOUR AI WORKSPACE</p>
      </section>
      <section className="flex items-center justify-center bg-void px-6 py-12">
        <div ref={cardRef} className="w-full max-w-[360px]">
          <div className="mb-10 flex items-center gap-3 lg:hidden"><BrandMark className="h-8 w-8 text-lime" /><span className="text-lg font-semibold text-bone">{BRAND_NAME}</span></div>
          <span className="mb-7 inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-smoke/60 bg-obsidian text-lime"><Icon name="spark" className="h-6 w-6" /></span>
          <h2 className="text-3xl font-semibold tracking-tight text-bone">{mode === 'login' ? '欢迎回来' : '创建你的账号'}</h2>
          <p className="mb-8 mt-3 text-sm text-ash">{mode === 'login' ? `登录 ${BRAND_NAME}，继续你的灵感与工作。` : '开始构建属于你的智能工作空间。'}</p>
          <form onSubmit={submit} className="space-y-5">
            <div><label htmlFor="username" className="field-label">用户名</label><Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="输入用户名" autoComplete="username" required className="py-3" /></div>
            {mode === 'register' && <div><label htmlFor="email" className="field-label">邮箱</label><Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" required className="py-3" /></div>}
            <div><label htmlFor="password" className="field-label">密码</label><Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="输入密码" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required className="py-3" /></div>
            <Button type="submit" loading={loading} className="w-full py-3">{mode === 'login' ? '登录工作空间' : '创建账号'}<Icon name="arrow" className="h-4 w-4" /></Button>
          </form>
          <div className="mt-7 text-center text-xs text-ash">{mode === 'login' ? '还没有账号？' : '已有账号？'}<button className="ml-2 font-medium text-lime hover:underline" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? '立即注册' : '返回登录'}</button></div>
          <div className="mt-10 flex items-center gap-3"><div className="h-px flex-1 bg-smoke/40" /><span className="text-[10px] tracking-[.15em] text-ash">{BRAND_NAME}</span><div className="h-px flex-1 bg-smoke/40" /></div>
        </div>
      </section>
    </div>
  );
}
