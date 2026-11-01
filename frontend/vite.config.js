import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs on :8000; in Docker nginx proxies /api and /ws.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 900 },
})
