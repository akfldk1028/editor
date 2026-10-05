import { expect, test } from 'bun:test';

test('native API clients use the same mount prefix as Next routes', async () => {
  const previous = process.env.PASCAL_BASE_PATH;
  process.env.PASCAL_BASE_PATH = '/editor';
  try {
    const { default: config } = await import('../next.config');
    expect(config.basePath).toBe('/editor');
    expect(config.env?.NEXT_PUBLIC_BASE_PATH).toBe(config.basePath);
  } finally {
    if (previous === undefined) delete process.env.PASCAL_BASE_PATH;
    else process.env.PASCAL_BASE_PATH = previous;
  }
});
