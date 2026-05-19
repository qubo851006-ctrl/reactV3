/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Test config separate from vite.config.ts so production build doesn't
 * pull in the jsdom env or testing-library globals.
 *
 * Pre-flight setup needed once:
 *   npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
 *
 * Run tests:
 *   npm test           # (after adding "test": "vitest" to package.json scripts)
 *   npx vitest run     # one-shot
 *   npx vitest         # watch mode
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/main.tsx', 'src/**/*.d.ts'],
    },
  },
})
