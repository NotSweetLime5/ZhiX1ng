/**
 * 基础 UI 原语 —— 样式由 styles/index.css 的组件层统一提供，
 * 组件只负责语义封装与少量状态，保证全站视觉一致。
 */
import { clsx } from 'clsx';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';
import { STATUS_LABEL } from '@/lib/format';
import { Icon } from './Icon';

/* ---- Button ---- */

type ButtonVariant = 'primary' | 'ghost' | 'danger';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  loading?: boolean;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'btn-primary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
};

export function Button({ variant = 'primary', loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      className={clsx(VARIANT_CLASS[variant], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

/* ---- Input / Textarea / Select ---- */

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx('field', className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx('field resize-none', className)} {...rest} />;
}

export { Select } from './Select';

/* ---- Badge ---- */

type BadgeTone = 'lime' | 'teal' | 'coral' | 'pulse' | 'violet' | 'gray';

const TONE_CLASS: Record<BadgeTone, string> = {
  lime: 'border-lime/40 text-lime bg-lime/10',
  teal: 'border-teal/40 text-teal bg-teal/10',
  coral: 'border-coral/40 text-coral bg-coral/10',
  pulse: 'border-pulse/40 text-pulse bg-pulse/10',
  violet: 'border-violet/40 text-violet bg-violet/10',
  gray: 'border-smoke text-fog bg-graphite',
};

export function Badge({ tone = 'gray', children, className }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const TONE_OF: Record<string, BadgeTone> = { ok: 'pulse', warn: 'lime', err: 'coral', info: 'teal' };

/** 状态徽标：直接消费 format.ts 的 STATUS_LABEL 映射 */
export function StatusBadge({ status }: { status: string }) {
  const info = STATUS_LABEL[status] ?? { text: status, tone: 'info' as const };
  return <Badge tone={TONE_OF[info.tone] ?? 'gray'}>{info.text}</Badge>;
}

/* ---- Spinner ---- */

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        'inline-block animate-spin rounded-full border-2 border-current border-t-transparent',
        className ?? 'h-4 w-4',
      )}
      aria-label="加载中"
    />
  );
}

/* ---- EmptyState ---- */

export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-20 text-center">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-smoke/50 bg-graphite/40 text-ash">{icon || <Icon name="model" className="h-6 w-6" />}</div>
      <p className="text-base font-medium text-bone">{title}</p>
      {hint && <p className="mt-3 max-w-sm text-sm leading-6 text-ash">{hint}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

/* ---- PageHeader ---- */

export function PageHeader({ title, desc, action }: { title: string; desc?: string; action?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-bone">{title}</h1>
        {desc && <p className="mt-3 text-sm leading-6 text-ash">{desc}</p>}
      </div>
      {action}
    </div>
  );
}

/* ---- Card ---- */

export function Card({ className, children, onClick }: { className?: string; children: ReactNode; onClick?: () => void }) {
  return (
    <div
      className={clsx(
        'panel p-5 transition-all duration-200 sm:p-6',
        onClick && 'cursor-pointer hover:border-fog/60',
        className,
      )}
      onClick={onClick}
    >
      {children}
    </div>
  );
}
