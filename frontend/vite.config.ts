import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // amazon-cognito-identity-js references the Node global `global`, which
  // browsers don't have — alias it to globalThis so the bundle doesn't crash
  // at module-eval time.
  define: {
    global: 'globalThis',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    exclude: ['node_modules', 'e2e'],
  },
})
