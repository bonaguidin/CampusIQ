import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Bridges to the FastAPI orchestrator (CampusIQ_career/api.py), run separately
    // via `uv run uvicorn CampusIQ_career.api:app --reload --port 8000`.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
