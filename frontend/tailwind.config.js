/**
 * Tailwind 设计系统 —— Zhixing 暗色控制台。
 *
 * 中性暗色底、蓝色选中态，统一文字与功能色层级。
 */
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        /* ---- 底色四级黑（由深到浅） ---- */
        void: '#14171c', // 页面背景
        carbon: '#14171c', // 导航与面板背景
        obsidian: '#1e2229', // 卡片
        graphite: '#1e2229', // 悬浮/输入框
        /* ---- 灰阶（由深到浅） ---- */
        smoke: '#374151', // 分隔线
        ash: '#94a3b8', // 参数与辅助文字
        fog: '#94a3b8', // 次要文字
        mist: '#e9ecef', // 正文
        bone: '#e9ecef', // 标题
        paper: '#e9ecef',
        /* ---- 功能色 ---- */
        lime: '#2563eb', // 蓝色强调与选中态（保留已有 token 名）
        teal: '#77cfc8', // 回顾/信息
        coral: '#eb5757', // 错误/危险
        pulse: '#82c99c', // 成功
        violet: '#acaff5', // 多智能体/特殊
      },
      fontFamily: {
        sans: [
          'Inter',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          '-apple-system',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
      },
      /* 动效曲线：快进缓出，交互丝滑的底味 */
      transitionTimingFunction: {
        'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        'blink-caret': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
      animation: {
        'blink-caret': 'blink-caret 1s step-end infinite',
      },
    },
  },
  plugins: [],
} satisfies Config;
