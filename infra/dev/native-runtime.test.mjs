import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import test from 'node:test';
import * as runtime from './runtime.mjs';

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
