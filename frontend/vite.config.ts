import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the backend runs on :8000; the dev server forwards API calls to it,
// so the app always talks to its own origin (same as in production, where the backend serves it).
const backend = process.env.TAILORTEX_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
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
