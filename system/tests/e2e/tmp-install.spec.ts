import { test, expect } from '@playwright/test';
import { execFileSync, spawnSync } from 'child_process';
import { mkdtempSync, writeFileSync, mkdirSync, readFileSync, existsSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * Real end-to-end run of tmp-install.ps1: clones a repo and (re)installs the
 * service. Running it against the live GitHub repo / real Windows service
 * would be destructive and network-dependent, so this drives the actual
 * script logic (git clone, uninstall-then-install ordering, exit-code
 * propagation) against a local file:// git fixture and a stub
 * setup-service.ps1, asserting on real filesystem/process outcomes instead of
 * matching the script's source text. `-RepoUrl`/`-Branch`/`-TmpRoot` params
 * exist on the script solely to make this isolation possible; defaults match
 * the original hardcoded values.
 */

const SCRIPT_PATH = join(__dirname, '..', '..', '..', '..', 'tmp-install.ps1');

const STUB_SETUP_SERVICE = `
param(
    [switch]$Uninstall,
    [switch]$CleanInstall
)
$mode = if ($Uninstall) { 'Uninstall' } elseif ($CleanInstall) { 'CleanInstall' } else { 'None' }
Add-Content -Path $env:STUB_LOG -Value $mode
$code = 0
if ($mode -eq 'Uninstall' -and $env:STUB_UNINSTALL_EXIT) { $code = [int]$env:STUB_UNINSTALL_EXIT }
if ($mode -eq 'CleanInstall' -and $env:STUB_CLEANINSTALL_EXIT) { $code = [int]$env:STUB_CLEANINSTALL_EXIT }
exit $code
`;

function makeFixtureRepo(): string {
  const repoDir = mkdtempSync(join(tmpdir(), 'nexus-fixture-'));
  mkdirSync(join(repoDir, 'agents', 'runtime', 'tools'), { recursive: true });
  writeFileSync(join(repoDir, 'agents', 'runtime', 'tools', 'setup-service.ps1'), STUB_SETUP_SERVICE);
  const gitEnv = {
    ...process.env,
    GIT_AUTHOR_NAME: 'test', GIT_AUTHOR_EMAIL: 'test@example.com',
    GIT_COMMITTER_NAME: 'test', GIT_COMMITTER_EMAIL: 'test@example.com',
  };
  execFileSync('git', ['init', '-q', '-b', 'master', repoDir], { env: gitEnv });
  execFileSync('git', ['-C', repoDir, 'add', '-A'], { env: gitEnv });
  execFileSync('git', ['-C', repoDir, 'commit', '-q', '-m', 'fixture'], { env: gitEnv });
  return repoDir;
}

function runInstall(opts: {
  repoUrl: string;
  tmpRoot: string;
  stubLog: string;
  uninstallExit?: number;
  cleanInstallExit?: number;
}): { status: number; stdout: string; stderr: string } {
  const result = spawnSync(
    'pwsh',
    ['-NoProfile', '-File', SCRIPT_PATH, '-RepoUrl', opts.repoUrl, '-Branch', 'master', '-TmpRoot', opts.tmpRoot],
    {
      env: {
        ...process.env,
        STUB_LOG: opts.stubLog,
        ...(opts.uninstallExit !== undefined ? { STUB_UNINSTALL_EXIT: String(opts.uninstallExit) } : {}),
        ...(opts.cleanInstallExit !== undefined ? { STUB_CLEANINSTALL_EXIT: String(opts.cleanInstallExit) } : {}),
      },
      encoding: 'utf-8',
    },
  );
  return { status: result.status ?? -1, stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
}

test.describe('tmp-install.ps1 (e2e)', () => {
  let fixtureRepo: string;

  test.beforeAll(() => {
    fixtureRepo = makeFixtureRepo();
  });

  test.afterAll(() => {
    rmSync(fixtureRepo, { recursive: true, force: true });
  });

  test('fresh install: clones repo and runs a clean install, no prior uninstall', () => {
    const tmpRoot = mkdtempSync(join(tmpdir(), 'nexus-install-'));
    const stubLog = join(tmpRoot, 'stub.log');

    const result = runInstall({ repoUrl: fixtureRepo, tmpRoot, stubLog });

    expect(result.status, result.stderr).toBe(0);
    expect(existsSync(join(tmpRoot, 'nexus', 'agents', 'runtime', 'tools', 'setup-service.ps1'))).toBe(true);
    expect(readFileSync(stubLog, 'utf-8').trim().split(/\r?\n/)).toEqual(['CleanInstall']);

    rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('reinstall: uninstalls the existing service before cloning fresh and reinstalling', () => {
    const tmpRoot = mkdtempSync(join(tmpdir(), 'nexus-install-'));
    const stubLog = join(tmpRoot, 'stub.log');

    // First run seeds an "existing install" for the second run to uninstall.
    expect(runInstall({ repoUrl: fixtureRepo, tmpRoot, stubLog }).status).toBe(0);

    const result = runInstall({ repoUrl: fixtureRepo, tmpRoot, stubLog });

    expect(result.status, result.stderr).toBe(0);
    expect(readFileSync(stubLog, 'utf-8').trim().split(/\r?\n/)).toEqual([
      'CleanInstall',
      'Uninstall',
      'CleanInstall',
    ]);

    rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('aborts and never reaches install when uninstall fails', () => {
    const tmpRoot = mkdtempSync(join(tmpdir(), 'nexus-install-'));
    const stubLog = join(tmpRoot, 'stub.log');

    expect(runInstall({ repoUrl: fixtureRepo, tmpRoot, stubLog }).status).toBe(0);

    const result = runInstall({ repoUrl: fixtureRepo, tmpRoot, stubLog, uninstallExit: 1 });

    expect(result.status).not.toBe(0);
    expect(result.stdout + result.stderr).toContain('Uninstall failed (exit 1)');
    expect(readFileSync(stubLog, 'utf-8').trim().split(/\r?\n/)).toEqual(['CleanInstall', 'Uninstall']);

    rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('aborts with the git exit code when clone fails', () => {
    const tmpRoot = mkdtempSync(join(tmpdir(), 'nexus-install-'));
    const stubLog = join(tmpRoot, 'stub.log');

    const result = runInstall({ repoUrl: join(tmpRoot, 'does-not-exist'), tmpRoot, stubLog });

    expect(result.status).not.toBe(0);
    expect(result.stdout + result.stderr).toContain('git clone failed');

    rmSync(tmpRoot, { recursive: true, force: true });
  });
});
