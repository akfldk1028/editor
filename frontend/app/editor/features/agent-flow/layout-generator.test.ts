import { expect, test } from 'bun:test';
import { generateAGLightLayout } from './layout-generator';

const input = { reviews: [], status: 'idle' as const, viewMode: 'execution' as const, settings: { direction: 'LR' as const, showLabels: true, showGrid: true } };
test('no records means no fabricated participants or configured collaboration edges', () => {
  expect(generateAGLightLayout(input)).toEqual({ nodes: [], edges: [] });
});
test('only observed request/response directions appear and unknown transport stays unknown', () => {
  const layout = generateAGLightLayout({ ...input, messages: [
    { from_agent: 'orchestrator', to_agent: 'systems', message: 'request', metadata: { transport: 'a2a' } },
    { from_agent: 'systems', to_agent: 'orchestrator', message: 'reply', metadata: { transport: 'unknown' } },
  ] });
  expect(layout.nodes.map(n => n.id)).toEqual(['orchestrator', 'systems']);
  expect(layout.edges.map(e => [e.source, e.target])).toEqual([['orchestrator', 'systems'], ['systems', 'orchestrator']]);
  expect(layout.edges[1]!.label).toContain('전송 미확인');
});
