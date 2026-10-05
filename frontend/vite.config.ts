import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api to the FastAPI backend (override with VITE_PROXY_TARGET).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } } },
})
