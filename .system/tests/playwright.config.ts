import { defineConfig } from '@playwright/test';

/**
 * Governance test suite — validates repo invariants of the agent runtime.
 * These are pure-Node assertions (filesystem), so no browser projects, no
 * webServer, and `npx playwright install` is NOT required to run them.
 */
export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  reporter: 'list',
});
