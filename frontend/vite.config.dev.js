import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev 专用配置：通过 docker 网络容器名访问 dev backend，避开 vite.config.js 写死的 localhost:8000
// 启动方式：vite --config vite.config.dev.js
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // 容器内访问 dev backend 容器（soar-backend-dev），同在 config_default 网络
    proxy: {
      '/api': { target: 'http://soar-backend-dev:8000', changeOrigin: true },
    },
  },
  optimizeDeps: {
    // 预构建所有大依赖：刷新页面时浏览器直接命中缓存的 ESM 产物，
    // 避免 Vite 每次冷启动重新扫描/转换 node_modules（echarts 等大包最耗时）
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'zustand',
      'echarts',
      'echarts-for-react',
      'reactflow',
      'lucide-react',
      'tslib',
    ],
    // 锁定依赖版本一致性，避免重复打包
    dedupe: ['react', 'react-dom'],
  },
  // 开发服务器预热：启动/空闲时提前转换高频访问的源码模块，
  // 首次刷新无需等待即时编译
  warmup: {
    clientFiles: [
      './src/main.jsx',
      './src/App.jsx',
      './src/components/AppShell.jsx',
      './src/store/authStore.js',
      './src/api/client.js',
      './src/pages/Login.jsx',
    ],
  },
})
