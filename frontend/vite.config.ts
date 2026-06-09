/// <reference types="vitest" />
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'happy-dom',
    globals: false,
    // Scope vitest to colocated unit tests. Playwright e2e specs live under
    // tests/e2e/*.spec.ts and would otherwise be swept up by vitest's default
    // include (which matches *.spec.ts) and fail — they need a real browser.
    include: ['src/**/*.test.ts'],
  },
})
