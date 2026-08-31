import { useCallback, useRef, useState } from "react";

import { runInspection } from "../../shared/api/inspectionGatewayClient";
import type {
  InspectionCheck,
  InspectionRun
} from "../../shared/types";

export function useInspectionRun() {
  const [run, setRun] = useState<InspectionRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const start = useCallback(async (checks: InspectionCheck[]) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRun(null);
    setError(null);
    setLoading(true);
    try {
      const result = await runInspection({ checks }, controller.signal);
      setRun(result);
      return result;
    } catch (reason) {
      if (reason instanceof Error && reason.name !== "AbortError") {
        setError(reason.message);
      }
      return null;
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setLoading(false);
      }
    }
  }, []);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setRun(null);
    setError(null);
    setLoading(false);
  }, []);

  return { run, loading, error, start, cancel, reset };
}
