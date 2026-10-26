import type { SVGProps } from 'react';

const paths = {
  chat: 'M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6A8.4 8.4 0 0 1 12.5 3H13a8.5 8.5 0 0 1 8 8z',
  agent: 'M12 3v3m-2-3h4M5 10H3v5h2m14-5h2v5h-2M8 18v3m8-3v3M8 11v2m8-2v2M9 16h6M7 6h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z',
  memory: 'M12 3a9 9 0 1 0 9 9M12 7v5l3 2M16 3h5v5m0-5-5 5',
  book: 'M12 6v15M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z',
  workflow: 'M9 3H3v6h6ZM21 15h-6v6h6ZM15 3h6v6h-6ZM6 9v9h9M9 6h6',
  model: 'M12 3 3 8l9 5 9-5-9-5ZM3 12l9 5 9-5M3 16l9 5 9-5',
  plug: 'M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0V8ZM12 17v4',
  check: 'm8 12 3 3 5-6M9 3h6m-9 1H5v17h14V4h-1',
  plus: 'M12 5v14M5 12h14',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  up: 'M12 19V5m-6 6 6-6 6 6',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z',
  code: 'm8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z',
  close: 'm6 6 12 12M6 18 18 6',
  history: 'M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2',
  logout: 'M9 5H4v14h5m5-14 5 7-5 7M8 12h11',
  chevron: 'm9 5 7 7-7 7',
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}><path d={paths[name]} /></svg>;
}

export function BrandMark({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M7 9h18L7 23h18" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /><path d="m7 9 9-5 9 5m-18 14 9 5 9-5" stroke="currentColor" strokeWidth="1.5" strokeOpacity=".5" strokeLinecap="round" /></svg>;
}
