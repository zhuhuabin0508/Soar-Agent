/** @type {import('tailwindcss').Config} */
// 设计令牌：统一品牌色 / 状态色 / z-index 层级 / 动画时长
// 所有页面与组件应优先使用令牌别名，避免色系混用
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // 品牌强调色（统一为 cyan 色系，替代 indigo/blue/cyan 混用）
      colors: {
        brand: {
          50: "#ecfeff",
          100: "#cffafe",
          200: "#a5f3fc",
          300: "#67e8f9",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
          800: "#155e75",
          900: "#164e63",
          950: "#083344",
        },
        // 状态色（统一语义，避免 green/emerald、red/rose 混用）
        success: {
          50: "#f0fdf4", 100: "#dcfce7", 200: "#bbf7d0", 300: "#86efac",
          400: "#4ade80", 500: "#22c55e", 600: "#16a34a", 700: "#15803d",
          800: "#166534", 900: "#14532d", 950: "#052e16",
        },
        warning: {
          50: "#fffbeb", 100: "#fef3c7", 200: "#fde68a", 300: "#fcd34d",
          400: "#fbbf24", 500: "#f59e0b", 600: "#d97706", 700: "#b45309",
          800: "#92400e", 900: "#78350f", 950: "#451a03",
        },
        danger: {
          50: "#fef2f2", 100: "#fee2e2", 200: "#fecaca", 300: "#fca5a5",
          400: "#f87171", 500: "#ef4444", 600: "#dc2626", 700: "#b91c1c",
          800: "#991b1b", 900: "#7f1d1d", 950: "#450a0a",
        },
      },
      // z-index 层级体系（消除 z-10/z-20/z-30/z-40/z-50 随意使用）
      zIndex: {
        base: "0",       // 常规内容
        dropdown: "20",  // 下拉菜单 / popover
        sticky: "30",    // 粘性头部 / 侧边栏
        drawer: "40",    // 抽屉
        modal: "50",     // 模态框
        toast: "60",     // Toast 通知（最高）
      },
      // 动画时长统一（交互反馈）
      transitionDuration: {
        DEFAULT: "150ms",
      },
      // 字号层级（强化语义）
      fontSize: {
        // 复用 Tailwind 默认值，此处仅占位确保可扩展
      },
    },
  },
  plugins: [],
}
