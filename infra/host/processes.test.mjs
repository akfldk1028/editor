import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { isAlive, readEnvFile, resolveCommand, shimTarget, spawnDetached } from './processes.mjs';

const sleep = ms => new Promise(done => setTimeout(done, ms));

test('readEnvFile expands ${NAME:-default} and ${NAME} the way `source` would, from earlier keys and the given env', () => {
  const dir = mkdtempSync(join(tmpdir(), 'host-env-'));
  const file = join(dir, 'agent.env');
  writeFileSync(file, [
    '# comment',
    'export MASS_A2A_PORT="${MASS_A2A_PORT:-18331}"',
    "export MASS_A2A_URL='${MASS_A2A_URL:-http://127.0.0.1:${MASS_A2A_PORT}}'",
    'TOKEN=${A2A_TOKEN}',
    'PLAIN=value',
    'MISSING=${NOPE}',
  ].join('\n'));
  try {
    assert.deepEqual(readEnvFile(file, { A2A_TOKEN: 'secret' }), {
      MASS_A2A_PORT: '18331', MASS_A2A_URL: 'http://127.0.0.1:18331', TOKEN: 'secret', PLAIN: 'value', MISSING: '',
    });
    assert.deepEqual(readEnvFile(file, { MASS_A2A_PORT: '19000' }).MASS_A2A_PORT, '19000');
    assert.deepEqual(readEnvFile(join(dir, 'none.env')), {});
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('resolveCommand finds the Windows launcher of a bare command: a .cmd shim (npm, npm-installed bun) or an .exe', { skip: process.platform !== 'win32' && 'Windows only' }, () => {
  assert.match(resolveCommand('npm', process.cwd()), /\.cmd$/i);
  assert.match(resolveCommand('bun', process.cwd()), /\.(cmd|exe)$/i, 'bun resolves even though Node cannot spawn its npm shim bare');
  assert.equal(resolveCommand('no-such-executable-xyz', process.cwd()), 'no-such-executable-xyz');
});

test('shimTarget unwraps an npm-made .cmd shim to the program it runs: node + the .js, or the .exe; anything else is null', { skip: process.platform !== 'win32' && 'Windows only' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'host-shim-'));
  try {
    writeFileSync(join(dir, 'tool.exe'), '');
    writeFileSync(join(dir, 'tool.cmd'), '@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n"%dp0%\\tool.exe"   %*\r\n');
    writeFileSync(join(dir, 'plain.cmd'), '@echo off\r\necho hello\r\n');
    assert.deepEqual(shimTarget(join(dir, 'tool.cmd')), [join(dir, 'tool.exe')]);
    assert.equal(shimTarget(join(dir, 'plain.cmd')), null);
    assert.equal(shimTarget(join(dir, 'missing.cmd')), null);
    const npm = shimTarget(resolveCommand('npm', process.cwd()));
    assert.equal(npm?.[0], process.execPath, 'npm.cmd runs node');
    assert.match(npm?.[1] ?? '', /npm-cli\.js$/i);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('output of a service started through an npm shim reaches its log file (a detached cmd.exe would drop it)', { skip: process.platform !== 'win32' && 'Windows only' }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'host-shim-log-'));
  try {
    const logPath = join(dir, 'npm.log');
    const pid = spawnDetached('npm', ['--version'], { cwd: dir, env: process.env, logPath, errPath: join(dir, 'npm.err') });
    assert.ok(pid, 'spawned');
    for (let waited = 0; waited < 20_000 && isAlive(pid); waited += 200) await sleep(200);
    assert.match(readFileSync(logPath, 'utf8'), /^\d+\.\d+\.\d+/, 'npm --version landed in the log');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
