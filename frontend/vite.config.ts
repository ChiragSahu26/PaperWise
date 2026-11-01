import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The browser talks to /api on the dev server, which forwards to the PaperWise backend.
// This avoids CORS entirely. Override the target with PAPERWISE_API=http://host:port.
const target = process.env.PAPERWISE_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { '/api': { target, changeOrigin: true } },
  },
})
