import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import test from 'node:test';
import * as runtime from './runtime.mjs';

test('native backend uses its platform venv, while an explicit interpreter wins', t => {
  const temporary = resolve(tmpdir());
  const root = mkdtempSync(resolve(temporary, 'editor-native-python-'));
  const previous = process.env.EDITOR_PYTHON;
  t.after(() => {
    if (previous === undefined) delete process.env.EDITOR_PYTHON;
    else process.env.EDITOR_PYTHON = previous;
    assert.ok(root.startsWith(temporary + '/') || root.startsWith(temporary + '\\'));
    rmSync(root, { recursive: true });
  });
  delete process.env.EDITOR_PYTHON;
  assert.equal(runtime.createNativeServiceDefinitions(root, 'win32').backend.command, 'python');
  assert.equal(runtime.createNativeServiceDefinitions(root, 'linux').backend.command, 'python');
  for (const [platform, directory, binary] of [['win32', 'Scripts', 'python.exe'], ['linux', 'bin', 'python']]) {
    mkdirSync(resolve(root, '.venv', directory), { recursive: true });
    const interpreter = resolve(root, '.venv', directory, binary);
    writeFileSync(interpreter, 'test executable identity');
    assert.equal(runtime.createNativeServiceDefinitions(root, platform).backend.command, interpreter);
  }
  process.env.EDITOR_PYTHON = 'explicit-python';
  assert.equal(runtime.createNativeServiceDefinitions(root, 'win32').backend.command, 'explicit-python');
  assert.equal(runtime.createNativeServiceDefinitions(root, 'linux').backend.command, 'explicit-python');
});

test('native profile makes Editor the public app and aligns all backend bindings', () => {
  assert.equal(typeof runtime.createNativeServiceDefinitions, 'function');
  const root = resolve(import.meta.dirname, '../..');
  const services = runtime.createNativeServiceDefinitions(root, 'win32');
  assert.equal(services.frontend, undefined);
  assert.equal(services.arr, undefined);
  assert.equal(services.dwg, undefined);
  assert.equal(services.editor.publicUrl, 'http://127.0.0.1:3002');
  assert.equal(services.editor.env.EDITOR_BACKEND_URL, 'http://127.0.0.1:8000');
  assert.equal(services.editor.env.PASCAL_BASE_PATH, '');
  assert.equal(services.editor.env.PORT, '3002');
  assert.equal(services.backend.env.EDITOR_PUBLIC_URL, services.editor.publicUrl);
  assert.equal(services.backend.env.EDITOR_SCENE_URL, services.editor.publicUrl);
  assert.equal(services.backend.env.PASCAL_EDITOR_URL, services.editor.publicUrl);
  assert.ok(services.backend.env.EDITOR_PLATFORM_DATA_DIR);
  assert.ok(services.backend.env.EDITOR_DESIGN_DATA_DIR);
  assert.equal(services.orchestrator.command, undefined);
  assert.equal(services.backend.healthUrl, 'http://127.0.0.1:8000/api/v1/platform/health');
  assert.ok(services.backend.validate({ body: { service: 'editor-platform', public_origin: services.editor.publicUrl,
    scene_url: services.editor.publicUrl, storage_configured: true, owner_configured: true } }));
  assert.ok(!services.backend.validate({ body: { service: 'editor-platform', public_origin: 'http://127.0.0.1:5173',
    scene_url: services.editor.publicUrl, storage_configured: true, owner_configured: true } }));
});
