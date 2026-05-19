/**
 * Vitest setup — runs once before any test file.
 *
 * - Extends `expect` with @testing-library/jest-dom matchers (toBeInTheDocument etc.)
 * - Resets fetch mocks between tests so a stale mock from one test
 *   doesn't leak into the next.
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  vi.restoreAllMocks()
})

// jsdom doesn't ship Notification; stub a permission-less version so
// NotificationProvider treats it as unsupported (the production code
// path tested unless a test explicitly opts in).
if (typeof (globalThis as unknown as { Notification?: unknown }).Notification === 'undefined') {
  ;(globalThis as unknown as { Notification?: unknown }).Notification = undefined
}
