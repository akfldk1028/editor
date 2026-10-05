import { expect, test } from 'bun:test';
import { agentMemoryGraph, executedMassNodeId, fullGraph, selectedRuntimeGraph } from './execution-graph-model';
import type { ExecutedMassManifest, ExecutedMassRecord, MaasLanguageSystemManifest, MassExecutionPassport, OutcomeGraphSlice } from '../../lib/language-system-types';

const mass = { run_id: 'run-a', index: 2, geometry_hash: 'geometry-123456789', preview_url: '/mass.png', book_principle_id: 'book:rule', label: 'MASS 2 ? sample' } as ExecutedMassRecord;

test('execution identities distinguish equal mass indices from different runs', () => {
  expect(executedMassNodeId(mass)).not.toBe(executedMassNodeId({ ...mass, run_id: 'run-b' }));
  expect(selectedRuntimeGraph(null, mass)).toEqual({ nodes: [], edges: [], edgeIds: [], entryId: '' });
});

test('runtime graph keeps pending evidence visible and maps result edges to the exact mass', () => {
  const passport = {
    activation_graph: {
      nodes: [
        { id: 'flow:render', kind: 'mass_render_result', column: 'render', label: 'Render', evidence: { preview_url: '/recorded.png' }, status: 'pass', activation: 1 },
        { id: 'flow:vlm', kind: 'vlm_review', column: 'vlm', label: 'VLM', evidence: {}, status: 'not_evaluated', activation: 0 },
        { id: 'result:mass', kind: 'mass_result', column: 'result', label: 'Mass', evidence: {}, status: 'pass', activation: 1 },
      ],
      edges: [
        { id: 'render-vlm', source: 'flow:render', target: 'flow:vlm', relation: 'available_for_review', activation: 0 },
        { id: 'render-result', source: 'flow:render', target: 'result:mass', relation: 'produced', activation: 1 },
      ],
    },
  } as MassExecutionPassport;
  const graph = selectedRuntimeGraph(passport, mass);
  expect(graph.nodes).toHaveLength(2);
  expect(graph.nodes[0]?.attributes.preview_url).toBe('/recorded.png');
  expect(graph.edges[0]?.scope).toBe('pending');
  expect(graph.edgeIds).toContain(graph.edges[0]!.id);
  expect(graph.edges[1]?.target).toBe(executedMassNodeId(mass));
});

test('full graph keeps selected hidden BOOK principles while omitting evidence-only links', () => {
  const manifest = { exploration_graph: {
    nodes: [
      { id: 'book:base', kind: 'base', stage: 'base_model', visible: true, label: 'Base', attributes: {} },
      { id: 'book:rule', kind: 'rule', stage: 'detail', visible: false, label: 'Selected rule', attributes: {} },
      { id: 'book:page', kind: 'page', stage: 'detail', visible: false, label: 'Page', attributes: {} },
    ],
    edges: [
      { id: 'execution', source: 'book:base', target: 'book:rule', kind: 'applies', scope: 'execution' },
      { id: 'evidence', source: 'book:base', target: 'book:rule', kind: 'cites', scope: 'evidence' },
    ],
  } } as MaasLanguageSystemManifest;
  const graph = fullGraph(manifest, { masses: [mass], runs: [] } as unknown as ExecutedMassManifest);
  expect(graph.nodes.map(node => node.id)).toEqual(['book:base', 'book:rule', executedMassNodeId(mass)]);
  expect(graph.nodes[1]?.stage).toBe('book_extension');
  expect(graph.edges.some(edge => edge.id === 'full:evidence')).toBe(false);
  expect(graph.edges.some(edge => edge.source === 'book:rule' && edge.target === executedMassNodeId(mass))).toBe(true);
});

test('memory provenance joins exact geometry hashes and ignores unrelated geometry', () => {
  const outcome = { status: 'ready', pnu: 'parcel', nodes: [
    { id: 'matching', kind: 'compiled_geometry', label: 'Match', attributes: { geometry_hash: mass.geometry_hash } },
    { id: 'other', kind: 'compiled_geometry', label: 'Other', attributes: { geometry_hash: 'different' } },
  ], edges: [] } as unknown as OutcomeGraphSlice;
  const graph = agentMemoryGraph(outcome, { masses: [mass] } as ExecutedMassManifest);
  expect(graph.edges).toHaveLength(1);
  expect(graph.edges[0]?.source).toBe(executedMassNodeId(mass));
  expect(graph.edges[0]?.target).toBe('memory:matching');
});
