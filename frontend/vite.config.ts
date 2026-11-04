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
  server: {
    proxy: {
      // Local-dev-only shim for browser uploads to object storage.
      //
      // Uploads are a browser PUT straight to storage against a presigned URL
      // (see src/api/uploads.ts) — cross-origin, with a Content-Type header, so
      // the browser sends a CORS preflight first. Moto validates the presigned
      // signature on that OPTIONS request and rejects it with
      // SignatureDoesNotMatch, because the signature was computed for the PUT.
      // Real S3 answers preflight unauthenticated, so this is a Moto-only
      // limitation — and it is fatal: no browser upload can ever succeed
      // against Moto directly, which is why manifest import worked under curl
      // but not in the app or in e2e.
      //
      // Routing the PUT through the dev server makes it same-origin, so no
      // preflight is sent at all. scripts/local_server.py rewrites the
      // presigned URLs it returns to this prefix (LOCAL_UPLOAD_PROXY_BASE).
      // Nothing here ships: deployed builds use the real storage URL and the
      // real bucket's CORS rule (infrastructure/aws/modules/s3/main.tf).
      '/__storage': {
        target: process.env.VITE_STORAGE_PROXY_TARGET ?? 'http://localhost:5100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/__storage/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    exclude: ['node_modules', 'e2e'],
  },
})
