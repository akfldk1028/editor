import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdirSync, mkdtempSync, writeFileSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkWorkspaceLinks } from './workspace-links.mjs';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'editor-workspace-links-'));
  mkdirSync(join(root, 'packages/core'), { recursive: true });
  mkdirSync(join(root, 'node_modules/@test'), { recursive: true });
  writeFileSync(join(root, 'package.json'), JSON.stringify({ workspaces: ['packages/*'] }));
  writeFileSync(join(root, 'packages/core/package.json'), JSON.stringify({ name: '@test/core' }));
  return root;
}

test('accepts links to the actual workspace and reports missing packages', () => {
  const root = fixture();
  assert.throws(() => checkWorkspaceLinks(root), /@test\/core/);
  symlinkSync(join(root, 'packages/core'), join(root, 'node_modules/@test/core'), 'junction');
  assert.equal(checkWorkspaceLinks(root).length, 1);
});

test('rejects a workspace link into a different checkout', () => {
  const root = fixture();
  const backup = fixture();
  symlinkSync(join(backup, 'packages/core'), join(root, 'node_modules/@test/core'), 'junction');
  assert.throws(() => checkWorkspaceLinks(root), /different checkout/);
});

test('rejects a nested dependency alias into a backup checkout', () => {
  const root = fixture();
  const backup = fixture();
  symlinkSync(join(root, 'packages/core'), join(root, 'node_modules/@test/core'), 'junction');
  mkdirSync(join(root, 'packages/core/node_modules'), { recursive: true });
  writeFileSync(join(root, 'packages/core/package.json'), JSON.stringify({ name: '@test/core', dependencies: { react: '*' } }));
  symlinkSync(join(backup, 'packages/core'), join(root, 'packages/core/node_modules/react'), 'junction');
  assert.throws(() => checkWorkspaceLinks(root), /dependency react/);
});
