import { expect, test } from 'bun:test';
import { fileURLToPath } from 'node:url';

test('shared client wrapper does not pull the 3D editor and plugins into every feature route', async () => {
  const result = await Bun.build({ entrypoints: [fileURLToPath(new URL('../app/client-bootstrap.tsx', import.meta.url))], target: 'browser', packages: 'external', write: false });
  expect(result.success).toBe(true);
  const code = await result.outputs[0]!.text();
  expect(code).not.toContain('@pascal-app/editor');
  expect(code).not.toContain('@pascal-app/plugin-');
  expect(code).not.toContain('loadBuiltinsSync');
});
