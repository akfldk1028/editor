import { useMemo } from 'react';
import type { ExecutedMassManifest, ExecutedMassRecord, MaasLanguageSystemManifest, MassExecutionPassport, OutcomeGraphSlice } from '../../lib/language-system-types';
import type { NetworkEdge, NetworkNode } from './LanguageNetworkCanvas';
import { EXECUTION_STAGE_ORDER, FULL_GRAPH_STAGE_ORDER, executedMassNodeId, selectedBookSemanticPath, fullGraph, agentStage, selectedRuntimeGraph, agentMemoryGraph, evidenceImageUrl } from './execution-graph-model';

interface ExecutionGraphInput {
  languageManifest: MaasLanguageSystemManifest | null;
  archive: ExecutedMassManifest | null;
  selectedPassport: MassExecutionPassport | null;
  selectedMass: ExecutedMassRecord | null;
  outcomeGraph: OutcomeGraphSlice | null;
  graphView: 'full' | 'selected' | 'archive' | 'creative';
  selectedMassIndex: number;
  selectedNodeId: string | null;
}

export function useExecutionGraph({ languageManifest, archive, selectedPassport, selectedMass, outcomeGraph, graphView, selectedMassIndex, selectedNodeId }: ExecutionGraphInput) {
  const bookSemanticPath = useMemo(
    () => selectedBookSemanticPath(languageManifest, selectedMass),
    [languageManifest, selectedMass],
  );
  const completeGraph = useMemo(
    () => fullGraph(languageManifest, archive),
    [archive, languageManifest],
  );
  const runtimeGraph = useMemo(
    () => selectedRuntimeGraph(selectedPassport, selectedMass),
    [selectedPassport, selectedMass],
  );
  const memoryGraph = useMemo(
    () => agentMemoryGraph(outcomeGraph, archive),
    [archive, outcomeGraph],
  );
  const graphNodes = useMemo<NetworkNode[]>(() => (
    [
      ...(bookSemanticPath?.nodes ?? []),
      ...(selectedPassport?.activation_graph.nodes.map((node) => {
      const materializedMassImage = node.kind === 'mass_result'
        || node.kind === 'mass_render_result'
        || node.kind === 'elevation_result'
        || node.kind === 'elevation_image_proposal';
      const evaluatedVlmInput = node.id === 'flow:vlm' && node.status !== 'not_evaluated';
      return {
        id: node.id,
        kind: node.kind,
        stage: node.column === 'book'
          ? 'book_apply'
          : node.column === 'agent'
            ? agentStage(node.id)
            : node.column,
        label: node.label,
        authority: 'observed',
        attributes: {
          ...node.evidence,
          activation: node.activation,
          status: node.status,
          operator: node.operator,
          preview_url: node.kind === 'elevation_result'
            || node.kind === 'elevation_image_proposal'
            ? evidenceImageUrl(node.evidence)
            : materializedMassImage || evaluatedVlmInput
              ? selectedMass?.preview_url
              : evidenceImageUrl(node.evidence),
        },
      };
    }) ?? []),
    ]
  ), [bookSemanticPath, selectedPassport, selectedMass?.preview_url]);
  const graphEdges = useMemo<NetworkEdge[]>(() => (
    [
      ...(bookSemanticPath?.edges ?? []),
      ...(selectedPassport?.activation_graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      kind: edge.relation,
      scope: edge.activation > 0 ? 'execution' : 'pending',
    })) ?? []),
      ...(() => {
        if (!selectedPassport || !bookSemanticPath) return [];
        const firstBookNode = selectedPassport.activation_graph.nodes.find((node) => node.column === 'book');
        if (!firstBookNode) return [];
        const solidInput = selectedPassport.activation_graph.edges.find((edge) => edge.target === firstBookNode.id);
        return [
          ...(solidInput ? [{
            id: `book-path:solid:${solidInput.source}:${bookSemanticPath.entryId}`,
            source: solidInput.source,
            target: bookSemanticPath.entryId,
            kind: 'selects_book_base_volume',
            scope: 'execution',
          }] : []),
          {
            id: `book-path:materialize:${bookSemanticPath.targetId}:${firstBookNode.id}`,
            source: bookSemanticPath.targetId,
            target: firstBookNode.id,
            kind: 'materializes_book_rule',
            scope: 'execution',
          },
        ];
      })(),
    ]
  ), [bookSemanticPath, selectedPassport]);
  const stageOrder = useMemo(
    () => EXECUTION_STAGE_ORDER.filter((stage) => graphNodes.some((node) => node.stage === stage)),
    [graphNodes],
  );
  const runtimeBridge: NetworkEdge[] = graphView === 'full' && bookSemanticPath && runtimeGraph.entryId
    ? [{
      id: `runtime:${selectedMassIndex}:book-materialization`,
      source: bookSemanticPath.targetId,
      target: runtimeGraph.entryId,
      kind: 'materializes_selected_execution',
      scope: 'execution',
    }]
    : [];
  const displayedNodes = graphView === 'full'
    ? [...completeGraph.nodes, ...runtimeGraph.nodes, ...memoryGraph.nodes]
    : graphNodes;
  const displayedEdges = graphView === 'full'
    ? [
      ...completeGraph.edges.filter((edge) => edge.id !== `full:produced:${selectedMassIndex}`),
      ...(bookSemanticPath?.edges.filter((pathEdge) => (
        !completeGraph.edges.some((edge) => edge.source === pathEdge.source && edge.target === pathEdge.target)
      )) ?? []),
      ...runtimeBridge,
      ...runtimeGraph.edges,
      ...memoryGraph.edges,
    ]
    : graphEdges;
  const displayedStageOrder = graphView === 'full'
    ? FULL_GRAPH_STAGE_ORDER.filter((stage) => displayedNodes.some((node) => node.stage === stage))
    : stageOrder;
  const fullSelectionEdgeIds = graphView === 'full'
    && selectedMass
    && selectedNodeId === executedMassNodeId(selectedMass)
    && bookSemanticPath
    ? [
      ...bookSemanticPath.edges.map((pathEdge) => (
        displayedEdges.find((edge) => edge.source === pathEdge.source && edge.target === pathEdge.target)?.id
      )).filter((edgeId): edgeId is string => Boolean(edgeId)),
      ...runtimeBridge.map((edge) => edge.id),
      ...runtimeGraph.edgeIds,
      ...memoryGraph.edges.map((edge) => edge.id),
    ]
    : undefined;
  return { displayedNodes, displayedEdges, displayedStageOrder, fullSelectionEdgeIds };
}
