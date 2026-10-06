import type { ExecutedMassManifest, ExecutedMassRecord, MaasLanguageSystemManifest, OutcomeGraphSlice } from '../../lib/language-system-types';
import { executedMassNodeId, massLabel } from './execution-graph-ids';
import type { NetworkEdge, NetworkNode } from './LanguageNetworkCanvas';

export { evidenceImageUrl, executedMassNodeId, massLabel } from './execution-graph-ids';
export { agentStage, selectedRuntimeGraph } from './execution-graph-runtime';

export const EXECUTION_STAGE_ORDER = [
  'base', 'book_scope', 'book_orientation', 'book_family', 'book_cardinality',
  'book_rule', 'book_apply', 'geometry', 'program', 'compiler', 'gate', 'site', 'capacity',
  'law', 'parking', 'program_fit', 'render', 'reference', 'vlm', 'repair',
  'agent_design', 'agent_geometry', 'agent_law', 'agent_parking', 'agent_review', 'agent_selector',
  'selector', 'result', 'elevation_handoff', 'elevation_condition', 'elevation_result',
  'elevation_image_agent', 'elevation_proposal',
];

export const FULL_GRAPH_STAGE_ORDER = [
  'base_model', 'derived_volume', 'orientation', 'operation_family', 'cardinality', 'operation',
  'book_extension', 'variation', 'reference_corpus', 'reference_query',
  'execution_reference', 'execution_vlm_reference', 'reference_distill', 'execution_geometry', 'execution_program',
  'execution_compiler', 'execution_gates', 'execution_render', 'execution_law_evidence',
  'execution_agent_design', 'execution_agent_geometry', 'execution_agent_law',
  'execution_agent_parking', 'execution_agent_review', 'execution_agent_selector',
  'execution_vlm', 'execution_repair', 'execution_selector', 'execution_run', 'executed_mass',
  'execution_elevation_handoff', 'execution_elevation_condition', 'execution_elevation_result',
  'execution_elevation_image_agent', 'execution_elevation_proposal',
  'memory_geometry', 'memory_render', 'memory_portfolio', 'memory_vlm', 'memory_outcome',
];

interface BookSemanticPath {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  entryId: string;
  targetId: string;
}

function bookStage(stage: string): string {
  if (stage === 'base_model') return 'base';
  if (stage === 'derived_volume') return 'book_scope';
  if (stage === 'orientation') return 'book_orientation';
  if (stage === 'operation_family') return 'book_family';
  if (stage === 'cardinality') return 'book_cardinality';
  return 'book_rule';
}

export function selectedBookSemanticPath(
  manifest: MaasLanguageSystemManifest | null,
  mass: ExecutedMassRecord | null,
): BookSemanticPath | null {
  if (!manifest || !mass) return null;
  const graph = manifest.exploration_graph;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const rootId = 'book:base-model:1-1';
  const scopeId = mass.book_scope === '1/1'
    ? rootId
    : `book:derived-volume:${mass.book_scope.replace('/', '-')}`;
  const orientationId = `book:orientation:${mass.book_orientation || 'long_axis'}`;
  const principleId = mass.book_principle_id;
  if (!nodesById.has(scopeId) || !nodesById.has(orientationId) || !nodesById.has(principleId)) return null;
  const usableEdges = graph.edges.filter((edge) => (
    !edge.source.startsWith('book:page:')
    && !edge.source.startsWith('book:document:')
    && (edge.scope === 'execution' || edge.kind === 'participates_in')
  ));

  const findPath = (startId: string, targetId: string) => {
    const queue = [startId];
    const previous = new Map<string, typeof usableEdges[number]>();
    const visited = new Set(queue);
    while (queue.length > 0 && !visited.has(targetId)) {
      const current = queue.shift()!;
      usableEdges.forEach((edge) => {
        if (edge.source !== current || visited.has(edge.target)) return;
        visited.add(edge.target);
        previous.set(edge.target, edge);
        queue.push(edge.target);
      });
    }
    if (!visited.has(targetId)) return [];
    const path: typeof usableEdges = [];
    let cursor = targetId;
    while (cursor !== startId) {
      const edge = previous.get(cursor);
      if (!edge) return [];
      path.unshift(edge);
      cursor = edge.source;
    }
    return path;
  };

  let semanticEdges = findPath(orientationId, principleId);
  if (semanticEdges.length === 0 && principleId.startsWith('book:case:')) {
    const verbs = principleId.split(':').at(-1)?.split('+') ?? [];
    const operativeId = [...verbs]
      .reverse()
      .map((verb) => `book:operative:${verb}`)
      .find((nodeId) => nodesById.has(nodeId));
    if (operativeId) {
      semanticEdges = findPath(orientationId, operativeId);
      semanticEdges.push({
        id: `semantic:${operativeId}:${principleId}`,
        source: operativeId,
        target: principleId,
        kind: 'case_application',
        scope: 'execution',
        authority: 'book',
      });
    }
  }
  if (semanticEdges.length === 0) return null;
  const baseEdge = graph.edges.find((edge) => (
    edge.source === scopeId && edge.target === orientationId && edge.scope === 'execution'
  )) ?? {
    id: `semantic:${scopeId}:${orientationId}`,
    source: scopeId,
    target: orientationId,
    kind: 'orients_base_volume',
    scope: 'execution',
    authority: 'book',
  };
  const rootEdge = scopeId === rootId ? null : graph.edges.find((edge) => (
    edge.source === rootId && edge.target === scopeId && edge.kind === 'derives_volume'
  )) ?? {
    id: `semantic:${rootId}:${scopeId}`,
    source: rootId,
    target: scopeId,
    kind: 'derives_volume',
    scope: 'execution',
    authority: 'book',
  };
  const pathEdges = [...(rootEdge ? [rootEdge] : []), baseEdge, ...semanticEdges];
  const pathNodeIds = new Set([rootId, scopeId, orientationId, principleId]);
  pathEdges.forEach((edge) => {
    pathNodeIds.add(edge.source);
    pathNodeIds.add(edge.target);
  });
  const nodes = [...pathNodeIds]
    .map((id) => nodesById.get(id))
    .filter((node): node is NonNullable<typeof node> => Boolean(node))
    .map((node) => ({
      id: node.id,
      kind: `book_semantic_${node.kind}`,
      stage: bookStage(node.stage),
      label: node.label,
      authority: 'book',
      attributes: {
        ...node.attributes,
        source_authority: 'BOOK typed language graph',
        selected_for_mass: true,
      },
    }));
  return {
    nodes,
    edges: pathEdges.map((edge) => ({
      id: `book-path:${edge.id}`,
      source: edge.source,
      target: edge.target,
      kind: edge.kind,
      scope: 'execution',
    })),
    entryId: rootId,
    targetId: principleId,
  };
}

export function fullGraph(
  manifest: MaasLanguageSystemManifest | null,
  archive: ExecutedMassManifest | null,
): { nodes: NetworkNode[]; edges: NetworkEdge[] } {
  if (!manifest) return { nodes: [], edges: [] };
  const graph = manifest.exploration_graph;
  const resultPrincipleIds = new Set(archive?.masses.map((mass) => mass.book_principle_id) ?? []);
  const allowedStages = new Set(FULL_GRAPH_STAGE_ORDER);
  const includedBookNodes = graph.nodes.filter((node) => (
    (node.visible && allowedStages.has(node.stage)) || resultPrincipleIds.has(node.id)
  ));
  const includedIds = new Set(includedBookNodes.map((node) => node.id));
  const nodes: NetworkNode[] = includedBookNodes.map((node) => ({
    id: node.id,
    kind: node.kind,
    stage: allowedStages.has(node.stage) ? node.stage : 'book_extension',
    label: node.label,
    authority: node.authority,
    attributes: {
      ...node.attributes,
      source_authority: 'BOOK typed language graph',
    },
  }));
  const edges: NetworkEdge[] = graph.edges
    .filter((edge) => (
      includedIds.has(edge.source)
      && includedIds.has(edge.target)
      && edge.scope !== 'evidence'
      && edge.scope !== 'detail'
    ))
    .map((edge) => ({
      id: `full:${edge.id}`,
      source: edge.source,
      target: edge.target,
      kind: edge.kind,
      scope: edge.scope,
    }));

  archive?.runs.forEach((run, runIndex) => {
    const runNodeId = `execution:run:${run.run_id}`;
    nodes.push({
      id: runNodeId,
      kind: 'execution_run_archive',
      stage: 'execution_run',
      label: `${String(runIndex + 1).padStart(2, '0')} · ${run.run_id.replace('book-program-portfolios-', '')}`,
      authority: 'observed',
      attributes: {
        ...run,
        chronological_order: runIndex + 1,
        selected_run: run.run_id === archive.selected_run_id,
      },
    });
    const previous = archive.runs[runIndex - 1];
    if (previous) {
      edges.push({
        id: `execution:run-order:${previous.run_id}:${run.run_id}`,
        source: `execution:run:${previous.run_id}`,
        target: runNodeId,
        kind: 'followed_by_execution',
        scope: 'feedback',
      });
    }
  });

  archive?.masses.forEach((mass) => {
    const resultId = executedMassNodeId(mass);
    nodes.push({
      id: resultId,
      kind: 'executed_mass_result',
      stage: 'executed_mass',
      label: `${String(mass.index).padStart(2, '0')} · ${massLabel(mass.label)}`,
      authority: 'observed',
      attributes: {
        preview_url: mass.preview_url,
        variant_id: mass.variant_id,
        run_id: mass.run_id,
        program_hash: mass.program_hash,
        geometry_hash: mass.geometry_hash,
        book_principle_id: mass.book_principle_id,
        base_volume: mass.book_scope,
        orientation: mass.book_orientation || 'long_axis',
        capacity_alternative_id: mass.capacity_alternative_id,
        far_pct: mass.far_pct,
        hard_pass: mass.hard_pass,
        vlm_evaluated: mass.vlm_evaluated,
      },
    });
    if (includedIds.has(mass.book_principle_id)) {
      edges.push({
        id: `full:produced:${mass.index}`,
        source: mass.book_principle_id,
        target: resultId,
        kind: 'produced_executed_mass',
        scope: 'execution',
      });
    }
    edges.push({
      id: `execution:run-produced:${mass.archive_key}`,
      source: `execution:run:${mass.run_id}`,
      target: resultId,
      kind: 'archived_mass_in_run',
      scope: 'execution',
    });
  });
  return { nodes, edges };
}

function memoryStage(kind: string): string {
  if (kind === 'compiled_geometry' || kind === 'projected_geometry_program') return 'memory_geometry';
  if (kind === 'render_artifact') return 'memory_render';
  if (kind === 'geometry_portfolio') return 'memory_portfolio';
  if (kind.includes('vlm')) return 'memory_vlm';
  return 'memory_outcome';
}

export function agentMemoryGraph(
  outcome: OutcomeGraphSlice | null,
  archive: ExecutedMassManifest | null,
): { nodes: NetworkNode[]; edges: NetworkEdge[] } {
  if (!outcome || outcome.status !== 'ready') return { nodes: [], edges: [] };
  const nodes: NetworkNode[] = outcome.nodes.map((node) => ({
    id: `memory:${node.id}`,
    kind: `agent_memory_${node.kind}`,
    stage: memoryStage(node.kind),
    label: node.label,
    authority: 'observed',
    attributes: {
      ...node.attributes,
      source_graph: 'GeometryOutcomeGraph',
      pnu: outcome.pnu,
    },
  }));
  const edges: NetworkEdge[] = outcome.edges.map((edge) => ({
    id: `memory:${edge.id}`,
    source: `memory:${edge.source}`,
    target: `memory:${edge.target}`,
    kind: edge.kind,
    scope: 'feedback',
  }));
  const memoryNodeByHash = new Map(
    outcome.nodes
      .filter((node) => Boolean(node.attributes.geometry_hash))
      .map((node) => [String(node.attributes.geometry_hash || ''), node.id]),
  );
  archive?.masses.forEach((mass) => {
    const memoryNodeId = memoryNodeByHash.get(mass.geometry_hash);
    if (!memoryNodeId) return;
    edges.push({
      id: `memory:join:${mass.geometry_hash}`,
      source: executedMassNodeId(mass),
      target: `memory:${memoryNodeId}`,
      kind: 'persisted_by_exact_geometry_hash',
      scope: 'feedback',
    });
  });
  return { nodes, edges };
}
