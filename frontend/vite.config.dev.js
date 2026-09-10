import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Dev 专用配置：通过 docker 网络容器名访问 dev backend，避开 vite.config.js 写死的 localhost:8000
// 启动方式：vite --config vite.config.dev.js
const __dirname = path.dirname(fileURLToPath(import.meta.url))
// HTTPS 固定证书：由 mkcert -install 生成（信任 mkcert 本地 CA 后浏览器不再提示"不安全"）
// 见 frontend/certs/ 下 server.crt / server.key（及其 CA 根证书 mkcert-CA.crt 可分发信任）
const certKey = path.join(__dirname, 'certs', 'server.key')
const certCrt = path.join(__dirname, 'certs', 'server.crt')

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // HTTPS：若固定证书存在则启用，否则回退（避免容器启动失败）
    ...(fs.existsSync(certKey) && fs.existsSync(certCrt)
      ? {
          https: {
            key: fs.readFileSync(certKey),
            cert: fs.readFileSync(certCrt),
          },
        }
      : {}),
    // 容器内访问 dev backend 容器（soar-backend-dev），同在 config_default 网络
    // 注：HTTPS 页面下 /api 为相对路径，浏览器用 https 请求 Vite，Vite 再以 http 转发到后端
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
