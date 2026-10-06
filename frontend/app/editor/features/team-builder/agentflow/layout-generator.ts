/**
 * Layout Generator - 6 layout types for agent team patterns
 * Ported from AutoGen Studio layout-generator.ts
 */

import { generateChainLayout, generateForkJoinLayout, generateTreeLayout } from './layout-linear'
import { generateHubSpokeLayout, generateMeshLayout, generateRingLayout } from './layout-radial'
import type { LayoutType, Participant, PatternDefinition, PatternLayoutResult } from './types'

// --- Main Router ---

export function generateLayoutFromPattern(
  pattern: PatternDefinition,
  participants: Participant[],
  activeAgents: Set<string>,
  isProcessing: boolean,
  isComplete: boolean,
  runStatus?: string,
): PatternLayoutResult {
  const generators: Record<LayoutType, () => PatternLayoutResult> = {
    chain: () =>
      generateChainLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    'hub-spoke': () =>
      generateHubSpokeLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    mesh: () =>
      generateMeshLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    'fork-join': () =>
      generateForkJoinLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    tree: () =>
      generateTreeLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
    ring: () =>
      generateRingLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      ),
  }

  const gen = generators[pattern.visual.layout]
  return gen
    ? gen()
    : generateChainLayout(
        participants,
        pattern.visual,
        activeAgents,
        isProcessing,
        isComplete,
        runStatus,
      )
}
