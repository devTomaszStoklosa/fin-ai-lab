import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Backend is `fin-ai-lab web` (uvicorn, 127.0.0.1:8000) -- proxy instead
    // of CORS, since the app never needs to be reachable from anywhere else
    // (02-spec.md REQ-050).
    proxy: {
      '/api': 'http://127.0.0.1:8010',
      '/health': 'http://127.0.0.1:8010',
    },
  },
})
