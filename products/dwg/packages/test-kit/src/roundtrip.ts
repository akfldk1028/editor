import type { CadEntityIndex } from "@dwg/contracts";

export interface CadIndexInvariantSummary {
  schemaVersion: CadEntityIndex["schemaVersion"];
  entityCount: number;
  layerCount: number;
  unsupportedCount: number;
  handles: string[];
}

export function summarizeIndex(index: CadEntityIndex): CadIndexInvariantSummary {
  return {
    schemaVersion: index.schemaVersion,
    entityCount: index.entities.length,
    layerCount: index.layers.length,
    unsupportedCount: index.unsupported.reduce(
      (total, unsupported) => total + unsupported.count,
      0
    ),
    handles: index.entities
      .flatMap((entity) => (entity.handle === null ? [] : [entity.handle]))
      .sort()
  };
}
