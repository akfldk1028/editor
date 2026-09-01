import { useCallback, useEffect, useMemo, useState } from "react";

import type { CadLayerIndexItem } from "../../shared/types";

export function useLayerVisibility(layers: readonly CadLayerIndexItem[]) {
  const [userHiddenLayers, setUserHiddenLayers] = useState<Set<string>>(() => new Set());
  const layerAvailabilityKey = layers
    .map((layer) => `${layer.name}\u0001${layer.visible}\u0001${layer.frozen}`)
    .join("\u0000");
  const layerByName = useMemo(
    () => new Map(layers.map((layer) => [layer.name, layer])),
    [layerAvailabilityKey]
  );
  const hiddenLayers = new Set([
    ...layers
      .filter((layer) => !layer.visible || layer.frozen)
      .map((layer) => layer.name),
    ...userHiddenLayers
  ]);

  useEffect(() => {
    const available = new Set(layers.map((layer) => layer.name));
    setUserHiddenLayers((current) => {
      const next = new Set([...current].filter((name) => available.has(name)));
      return next.size === current.size ? current : next;
    });
  }, [layerByName]);

  const toggleLayer = useCallback((layerName: string) => {
    const layer = layerByName.get(layerName);
    if (!layer?.visible || layer.frozen) return;
    setUserHiddenLayers((current) => {
      const next = new Set(current);
      if (next.has(layerName)) {
        next.delete(layerName);
      } else {
        next.add(layerName);
      }
      return next;
    });
  }, [layerByName]);

  return { hiddenLayers, toggleLayer };
}
