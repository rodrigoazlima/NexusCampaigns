import { defineConfig } from '@playwright/test';

/**
 * Governance test suite - validates repo invariants of the agent runtime.
 * Split by test type: unit/ (pure-Node assertions against source/config,
 * no side effects) and e2e/ (spawns real processes - git, pwsh - against
 * isolated fixtures). No browser projects, no webServer; `npx playwright
 * install` is NOT required to run them.
 */
export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  reporter: 'list',
});
