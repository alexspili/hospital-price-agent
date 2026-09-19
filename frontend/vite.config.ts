import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `npm run dev` serves the page on 5173 and hands /api to a running `hpa serve`.
// `npm run build` writes frontend/dist, which the server itself serves at /.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { include: ['src/**/*.test.ts'] },
})
