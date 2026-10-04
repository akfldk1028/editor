import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveProductRoute } from '../src/app/routes.ts';

test('existing surfaces and exact agent routes', () => {
  for (const path of ['/dwg', '/planm', '/agents', '/land']) {
    assert.equal(resolveProductRoute(path).kind, path.slice(1));
  }
  assert.equal(resolveProductRoute('/agents/').kind, 'agents');
  assert.equal(resolveProductRoute('/agents-other').kind, 'dwg');
  assert.equal(resolveProductRoute('/planm-other').kind, 'dwg');
  assert.equal(resolveProductRoute('/editor/scenes').kind, 'editor');
});

test('project and run deep links keep their identity', () => {
  assert.deepEqual(resolveProductRoute('/projects/p-1'), {kind:'project', projectId:'p-1'});
  assert.deepEqual(resolveProductRoute('/runs/r-1'), {kind:'run', runId:'r-1'});
  assert.equal(resolveProductRoute('/projects').kind, 'projects');
  assert.equal(resolveProductRoute('/projects/p/extra').kind, 'dwg');
  assert.equal(resolveProductRoute('/projects/%2F').kind, 'dwg');
  assert.equal(resolveProductRoute('/projects/%ZZ').kind, 'dwg');
});
