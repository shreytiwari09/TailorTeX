import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the backend runs on :8000; the dev server forwards API calls to it,
// so the app always talks to its own origin (same as in production, where the backend serves it).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/docs': 'http://localhost:8000',
      '/openapi.json': 'http://localhost:8000',
    },
  },
})
