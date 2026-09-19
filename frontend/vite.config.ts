import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'

// In development the backend runs on :8000; the dev server forwards API calls to it,
// so the app always talks to its own origin (same as in production, where the backend serves it).
const backend = process.env.TAILORTEX_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Two entries: the product (index.html) and the no-login demo (demo.html), each with its own styles.
    rollupOptions: { input: { main: resolve(__dirname, 'index.html'), demo: resolve(__dirname, 'demo.html') } },
  },
  server: {
    port: Number(process.env.PORT ?? 5173),
    proxy: {
      '/api': backend,
      '/health': backend,
      '/docs': backend,
      '/openapi.json': backend,
    },
  },
})
