/**
 * Vitest setup — runs once before any test file.
 *
 * - Extends `expect` with @testing-library/jest-dom matchers (toBeInTheDocument etc.)
 * - Resets fetch mocks between tests so a stale mock from one test
 *   doesn't leak into the next.
 *
 * Note on the Notification API: jsdom doesn't ship it natively, so
 * `'Notification' in window` returns false and NotificationProvider takes
 * the 'unsupported' path. We do NOT stub Notification=undefined — that
 * would make the `in` check return true (property exists, value is
 * undefined) and crash the production code when it accesses .permission.
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  vi.restoreAllMocks()
})
