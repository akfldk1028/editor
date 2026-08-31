import { useCallback, useEffect, useRef, useState } from "react";

import { loadDrawingIndex } from "../../shared/api/drawingIndexClient";
import type { CadIndex } from "../../shared/types";

export function useDrawingIndex() {
  const [index, setIndex] = useState<CadIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const generation = useRef(0);

  const refresh = useCallback(async (): Promise<CadIndex | null> => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestGeneration = ++generation.current;
    setError(null);
    try {
      const next = await loadDrawingIndex(controller.signal);
      if (generation.current !== requestGeneration || controller.signal.aborted) return null;
      setIndex(next);
      return next;
    } catch (reason) {
      if (generation.current !== requestGeneration || controller.signal.aborted) return null;
      setError(reason instanceof Error ? reason.message : "Unable to load drawing index.");
      return null;
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      generation.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [refresh]);

  return { index, error, refresh };
}
