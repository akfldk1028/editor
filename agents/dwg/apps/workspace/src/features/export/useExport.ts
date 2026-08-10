import { useEffect, useRef, useState } from "react";

import type {
  DestinationGrantResponse,
  DrawingFormat,
  ExportCapabilitiesResponse,
  ReportFormat
} from "@dwg/contracts";

import { loadDrawingIndex } from "../../shared/api/drawingIndexClient";
import {
  exportDrawing,
  exportReport,
  loadExportCapabilities,
  reportDownloadUrl,
  requestExportDestination
} from "../../shared/api/exportClient";

export function commitExportCapabilitiesIfActive(
  signal: AbortSignal,
  response: ExportCapabilitiesResponse,
  commit: (response: ExportCapabilitiesResponse) => void
) {
  if (!signal.aborted) commit(response);
}

export interface ExportActionLifecycle {
  begin(): AbortController;
  finish(controller: AbortController): boolean;
  isCurrent(controller: AbortController): boolean;
  abort(): void;
}

export function createExportActionLifecycle(): ExportActionLifecycle {
  let active: AbortController | null = null;
  return {
    begin() {
      active?.abort();
      active = new AbortController();
      return active;
    },
    finish(controller) {
      if (active !== controller) return false;
      active = null;
      return true;
    },
    isCurrent(controller) {
      return active === controller && !controller.signal.aborted;
    },
    abort() {
      active?.abort();
      active = null;
    }
  };
}

export function commitExportActionIfCurrent(
  lifecycle: ExportActionLifecycle,
  controller: AbortController,
  commit: () => void
): void {
  if (lifecycle.isCurrent(controller)) commit();
}

export function useExport() {
  const actionLifecycle = useRef<ExportActionLifecycle | null>(null);
  actionLifecycle.current ??= createExportActionLifecycle();
  const [capabilities, setCapabilities] = useState<ExportCapabilitiesResponse | null>(null);
  const [destination, setDestination] = useState<DestinationGrantResponse | null>(null);
  const [baseFilename, setBaseFilename] = useState("drawing-copy");
  const [status, setStatus] = useState("Destination required");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void loadExportCapabilities(controller.signal).then(
      (response) => commitExportCapabilitiesIfActive(controller.signal, response, setCapabilities),
      (reason) => {
        if (!controller.signal.aborted) fail(reason);
      }
    );
    const lifecycle = actionLifecycle.current!;
    return () => {
      controller.abort();
      lifecycle.abort();
    };
  }, []);

  const chooseDestination = () => {
    void runAction(async (signal, commit) => {
      const grant = await requestExportDestination(signal);
      commit(() => {
        setDestination(grant);
        setStatus(`Destination selected: ${grant.displayDirectory}`);
      });
    });
  };

  const saveDrawing = (format: DrawingFormat) => {
    if (!destination) {
      setStatus("Destination required");
      return;
    }
    const grantId = destination.grantId;
    setDestination(null);
    setStatus("Destination grant used — choose again for another copy");
    void runAction(async (signal, commit) => {
      const drawing = await loadDrawingIndex(signal);
      const metadata = drawing.schemaVersion === "cad-index/v0.2" ? drawing.drawing : undefined;
      const result = await exportDrawing({
        documentId: drawing.drawingId,
        expectedRevision: metadata?.revision ?? 0,
        destinationGrantId: grantId,
        baseFilename,
        format,
        version: metadata?.fileVersion ?? "AC1032"
      }, signal);
      commit(() => {
        setStatus(result.status === "passed" ? `Verified: ${result.verificationId}` : "Verification failed");
      });
    });
  };

  const downloadReport = (format: ReportFormat) => {
    void runAction(async (signal, commit) => {
      const drawing = await loadDrawingIndex(signal);
      const metadata = drawing.schemaVersion === "cad-index/v0.2" ? drawing.drawing : undefined;
      const report = await exportReport({
        documentId: drawing.drawingId,
        revision: metadata?.revision ?? 0,
        format
      }, signal);
      commit(() => {
        const anchor = document.createElement("a");
        anchor.href = reportDownloadUrl(report.downloadId);
        anchor.download = report.filename;
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
        setStatus(`Report ready: ${report.filename}`);
      });
    });
  };

  async function runAction(
    action: (
      signal: AbortSignal,
      commit: (operation: () => void) => void
    ) => Promise<void>
  ): Promise<void> {
    const lifecycle = actionLifecycle.current!;
    const controller = lifecycle.begin();
    setBusy(true);
    setError(null);
    const commit = (operation: () => void) =>
      commitExportActionIfCurrent(lifecycle, controller, operation);
    try {
      await action(controller.signal, commit);
    } catch (reason) {
      if (lifecycle.isCurrent(controller)) fail(reason);
    } finally {
      if (lifecycle.finish(controller)) setBusy(false);
    }
  }

  function fail(reason: unknown) {
    setError(reason instanceof Error ? reason.message : "Export failed.");
  }

  return {
    capabilities,
    destination,
    baseFilename,
    setBaseFilename,
    status,
    error,
    busy,
    chooseDestination,
    saveDrawing,
    downloadReport
  };
}
