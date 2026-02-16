import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({ mode }) => {
  // Default to plugin backend port for local dev.
  // You can override via VITE_CALL_ME_BASE_URL.
  const fallbackBaseUrl = 'http://127.0.0.1:8989'
  const baseUrl = process.env.VITE_CALL_ME_BASE_URL ?? fallbackBaseUrl
  const target = baseUrl

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(rootDir, './src'),
      },
    },
    test: {
      include: ['src/**/*.test.ts', '../../test/call_me/frontend/src/**/*.test.ts'],
      exclude: [...configDefaults.exclude, 'tests-e2e/**', '../../test/call_me/frontend/tests-e2e/**'],
    },
    server: {
      port: mode === 'production' ? 4173 : 5173,
      strictPort: true,
      proxy: {
        '/health': target,
        '/api': target,
      },
    },
    build: {
      outDir: path.resolve(rootDir, '../static'),
      emptyOutDir: true,
      sourcemap: true,
    },
  }
})
