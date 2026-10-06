import type { ExecutedMassRecord, MassExecutionPassport } from '../../lib/language-system-types';
import { evidenceImageUrl, executedMassNodeId } from './execution-graph-ids';
import type { NetworkEdge, NetworkNode } from './LanguageNetworkCanvas';

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
