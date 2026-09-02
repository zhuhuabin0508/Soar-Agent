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
})
