import { expect, test } from 'bun:test';
import { readPendingHealth, savePendingHealth, clearPendingHealth } from './pending-health';

test('uncertain submission survives a new client instance with its original key and versions', () => {
  const data = new Map<string, string>();
  const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v); }, removeItem: (k: string) => { data.delete(k); } };
  const attempt = { key: 'stable-key', context: { scene_revision: 2, source_versions: { site: 3 } } };
  savePendingHealth(storage, 'p1', attempt);
  expect(readPendingHealth(storage, 'p1')).toEqual(attempt);
  expect(readPendingHealth(storage, 'p2')).toBeNull();
  clearPendingHealth(storage, 'p1');
  expect(readPendingHealth(storage, 'p1')).toBeNull();
});

test('invalid saved identity is surfaced instead of silently creating a duplicate request', () => {
  const storage = { getItem: () => '{broken' };
  expect(() => readPendingHealth(storage, 'p1')).toThrow();
});
