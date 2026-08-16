import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发代理到后端（uvicorn 默认 8000）
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
