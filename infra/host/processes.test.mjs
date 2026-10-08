import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { readEnvFile } from './processes.mjs';

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
