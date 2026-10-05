import type { ExecutedMassManifest, ExecutedMassRecord, MaasLanguageSystemManifest, MassExecutionPassport, OutcomeGraphSlice } from '../../lib/language-system-types';
import type { NetworkEdge, NetworkNode } from './LanguageNetworkCanvas';

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

export function executedMassNodeId(mass: ExecutedMassRecord): string {
  return `executed:mass:${mass.run_id}:${mass.index}:${mass.geometry_hash.slice(0, 12)}`;
}

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

export function agentStage(nodeId: string, prefix = ''): string {
  const stage = nodeId.includes('design_orchestrator') ? 'design'
    : nodeId.includes('maas_geometry_agent') ? 'geometry'
      : nodeId.includes('law_graph_agent') ? 'law'
        : nodeId.includes('parking_agent') ? 'parking'
          : nodeId.includes('review_agent') ? 'review'
            : 'selector';
  return `${prefix}agent_${stage}`;
}

function runtimeStage(column: string, nodeId = ''): string {
  if (column === 'base' || column === 'book' || column === 'geometry') return 'execution_geometry';
  if (column === 'program') return 'execution_program';
  if (column === 'compiler') return 'execution_compiler';
  if (['gate', 'site', 'capacity', 'parking', 'program_fit'].includes(column)) return 'execution_gates';
  if (column === 'agent') return agentStage(nodeId, 'execution_');
  if (column === 'law') return 'execution_law_evidence';
  if (column === 'render') return 'execution_render';
  if (column === 'reference') return 'execution_reference';
  if (column === 'vlm') return 'execution_vlm';
  if (column === 'repair') return 'execution_repair';
  if (column === 'selector') return 'execution_selector';
  if (column === 'elevation_handoff') return 'execution_elevation_handoff';
  if (column === 'elevation_condition') return 'execution_elevation_condition';
  if (column === 'elevation_result') return 'execution_elevation_result';
  if (column === 'elevation_image_agent') return 'execution_elevation_image_agent';
  if (column === 'elevation_proposal') return 'execution_elevation_proposal';
  return 'execution_geometry';
}

export function selectedRuntimeGraph(
  passport: MassExecutionPassport | null,
  mass: ExecutedMassRecord | null,
): { nodes: NetworkNode[]; edges: NetworkEdge[]; edgeIds: string[]; entryId: string } {
  if (!passport || !mass) return { nodes: [], edges: [], edgeIds: [], entryId: '' };
  const mappedId = (nodeId: string) => (
    nodeId === 'result:mass' ? executedMassNodeId(mass) : `runtime:${mass.index}:${nodeId}`
  );
  const nodes = passport.activation_graph.nodes
    .filter((node) => node.id !== 'result:mass')
    .map((node): NetworkNode => {
      const imageBacked = node.kind === 'mass_render_result'
        || node.kind === 'vlm_reference_image'
        || node.kind === 'elevation_result'
        || node.kind === 'elevation_image_proposal';
      return {
        id: mappedId(node.id),
        kind: node.kind,
        stage: node.kind === 'vlm_reference_image'
          ? 'execution_vlm_reference'
          : runtimeStage(node.column, node.id),
        label: node.label,
        authority: 'observed',
        attributes: {
          ...node.evidence,
          source_node_id: node.id,
          status: node.status,
          activation: node.activation,
          preview_url: imageBacked
            ? (evidenceImageUrl(node.evidence) || mass.preview_url)
            : undefined,
          vlm_input_truth: node.kind === 'vlm_reference_image'
            ? 'image actually submitted to recorded VLM call'
            : undefined,
        },
      };
    });
  const edges = passport.activation_graph.edges.map((edge): NetworkEdge => ({
    id: `runtime:${mass.index}:${edge.id}`,
    source: mappedId(edge.source),
    target: mappedId(edge.target),
    kind: edge.relation,
    scope: edge.activation > 0 ? 'execution' : 'pending',
  }));
  const retrieval = passport.reference_retrieval;
  const corpusNodeId = `runtime:${mass.index}:reference-corpus`;
  const queryNodeId = `runtime:${mass.index}:reference-query`;
  const distillerNodeId = `runtime:${mass.index}:reference-distiller`;
  if (retrieval) {
    nodes.push(
      {
        id: corpusNodeId,
        kind: 'reference_corpus',
        stage: 'reference_corpus',
        label: `ArchDaily · ${retrieval.image_count} images`,
        authority: 'observed',
        attributes: retrieval,
      },
      {
        id: queryNodeId,
        kind: 'program_reference_query',
        stage: 'reference_query',
        label: `${retrieval.program_id} · ${retrieval.geometry_family}`,
        authority: 'observed',
        attributes: {
          ...retrieval,
          selected_mass: mass.variant_id,
        },
      },
      {
        id: distillerNodeId,
        kind: 'reference_vlm_distiller',
        stage: 'reference_distill',
        label: 'Reference VLM · relation distiller',
        authority: 'experimental',
        attributes: {
          status: 'not_evaluated_for_this_mass',
          geometry_authority: false,
          output_contract: 'typed relations and operators, never mesh coordinates',
        },
      },
    );
    edges.push({
      id: `runtime:${mass.index}:corpus-query`,
      source: corpusNodeId,
      target: queryNodeId,
      kind: 'queries_by_program_and_geometry',
      scope: 'execution',
    });
  }
  const activeReferenceSourceIds = new Set(
    passport.activation_graph.nodes
      .filter((node) => node.kind === 'vlm_reference_image')
      .map((node) => String(node.evidence.source_id || '')),
  );
  (passport.retrieved_references ?? []).forEach((reference) => {
    if (activeReferenceSourceIds.has(reference.source_id)) return;
    const nodeId = `runtime:${mass.index}:retrieved:${reference.source_id}`;
    nodes.push({
      id: nodeId,
      kind: 'retrieved_reference_image',
      stage: 'execution_reference',
      label: reference.title,
      authority: 'experimental',
      attributes: {
        ...reference,
        preview_url: reference.preview_url,
        status: reference.used_by_vlm ? 'submitted_to_vlm' : 'retrieved_not_submitted',
        vlm_input_truth: reference.used_by_vlm
          ? 'image actually submitted to recorded VLM call'
          : 'retrieved candidate only; not a VLM input',
      },
    });
    edges.push({
      id: `runtime:${mass.index}:query-match:${reference.source_id}`,
      source: queryNodeId,
      target: nodeId,
      kind: 'retrieved_program_match',
      scope: 'execution',
    });
    edges.push({
      id: `runtime:${mass.index}:reference-distill:${reference.source_id}`,
      source: nodeId,
      target: distillerNodeId,
      kind: reference.used_by_vlm ? 'reference_vlm_input' : 'available_for_reference_vlm',
      scope: reference.used_by_vlm ? 'execution' : 'pending',
    });
    edges.push({
      id: `runtime:${mass.index}:retrieved-input:${reference.source_id}`,
      source: nodeId,
      target: mappedId('flow:vlm'),
      kind: reference.used_by_vlm ? 'visual_reference_input' : 'retrieved_reference_candidate',
      scope: reference.used_by_vlm ? 'execution' : 'pending',
    });
  });
  if (retrieval) {
    edges.push({
      id: `runtime:${mass.index}:distilled-author-context`,
      source: distillerNodeId,
      target: mappedId(passport.activation_graph.nodes[0]?.id ?? ''),
      kind: 'proposes_typed_author_context',
      scope: 'pending',
    });
  }
  return {
    nodes,
    edges,
    // Pending edges stay visible as dashed provenance: they describe retrieved
    // references and candidate images that were available but not submitted.
    edgeIds: edges.map((edge) => edge.id),
    entryId: mappedId(passport.activation_graph.nodes[0]?.id ?? ''),
  };
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

export function evidenceImageUrl(evidence: Record<string, unknown>): string {
  const keys = ['preview_url', 'image_url', 'asset_url', 'local_url'];
  for (const key of keys) {
    const value = evidence[key];
    if (typeof value === 'string' && /^(https?:|data:|\/)/.test(value)) return value;
  }
  return '';
}

export function massLabel(label: string): string {
  return label.replace(/^MASS \d+\s*[·•-]\s*/, '');
}

