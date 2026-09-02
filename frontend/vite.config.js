import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：开启 /api 代理方便本地联调后端
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
