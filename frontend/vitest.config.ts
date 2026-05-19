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
  // Enable the React 17+ automatic JSX runtime so test files don't need
  // `import React from 'react'`. Without this Vitest falls back to the
  // classic transform, which expects React in scope and fails with
  // "React is not defined" the moment a .tsx test renders JSX.
  esbuild: {
    jsx: 'automatic',
  },
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
