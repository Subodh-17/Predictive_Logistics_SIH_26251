import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api to the FastAPI backend (override with VITE_PROXY_TARGET).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } } },
  build: {
    // Split vendor libraries into separate chunks for better long-term caching.
    // React is NOT split separately — Vite already hoists it into the main chunk via its module graph.
    rollupOptions: {
      output: {
        manualChunks: {
          // Charting library: recharts + d3 shims (~158 KB gzip)
          charts: ['recharts'],
          // Mapping library: leaflet + react-leaflet (~45 KB gzip)
          map: ['leaflet', 'react-leaflet'],
        },
      },
    },
    // Raise advisory limit; the charts chunk is large by nature (d3 is bundled inside recharts)
    chunkSizeWarningLimit: 600,
  },
})
