import { test, expect } from '@playwright/test';
import { readFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

/**
 * Governance: an agent may auto-commit ONLY files under `knowledge-base/`.
 *
 * The runtime stages + commits each agent's declared `commit_scope` (parsed
 * from <agent>/AGENT.md). This test mirrors the parser in
 * `system/src/nexus/runner.py` (_COMMIT_SCOPE_RE / _SCOPE_ITEM_RE) and
 * `system/src/nexus/shared/agent_tools.py` so it validates exactly what the committer
 * will stage. Any non-`knowledge-base/` entry is a leak and fails the suite.
 *
 * An empty scope (agent produces no vault content) is valid — the runner skips
 * the commit entirely.
 */

const AGENTS_DIR = join(__dirname, '..', '..', '..', 'agents');
const ALLOWED_PREFIX = 'knowledge-base/';

// Ported verbatim from runner.py — keep in sync if the runner regex changes.
const COMMIT_SCOPE_RE = /^commit_scope:\s*\n((?:[ \t]+-[^\n]+\n?)+)/m;
const SCOPE_ITEM_RE = /^\s+-\s+(.+)$/gm;

function readScope(agentMdPath: string): string[] {
  const content = readFileSync(agentMdPath, 'utf-8');
  const block = COMMIT_SCOPE_RE.exec(content);
  if (!block) return [];
  const items: string[] = [];
  SCOPE_ITEM_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = SCOPE_ITEM_RE.exec(block[1])) !== null) {
    const value = m[1].trim();
    if (value) items.push(value);
  }
  return items;
}

function discoverAgents(): string[] {
  return readdirSync(AGENTS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .filter((name) => existsSync(join(AGENTS_DIR, name, 'AGENT.md')))
    .sort();
}

test.describe('commit_scope — agents may only auto-commit knowledge-base/', () => {
  const agents = discoverAgents();

  test('agents are discovered', () => {
    expect(agents.length).toBeGreaterThan(0);
  });

  for (const agent of agents) {
    test(`${agent}: every commit_scope entry is under knowledge-base/`, () => {
      const scope = readScope(join(AGENTS_DIR, agent, 'AGENT.md'));
      const violations = scope.filter((p) => !p.startsWith(ALLOWED_PREFIX));
      expect(
        violations,
        `${agent} commit_scope contains non-vault path(s): ${JSON.stringify(violations)}`,
      ).toEqual([]);
    });
  }
});
