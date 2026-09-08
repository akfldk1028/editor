import { Download, FolderOpen, Save } from "lucide-react";

import type { DrawingFormat, ReportFormat } from "@dwg/contracts";

import { useExport } from "./useExport";
import "./styles.css";

export function ExportPanel() {
  const {
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
  } = useExport();
  const reports = capabilities?.capabilities.filter((item) => item.kind === "report") ?? [];
  const drawings = capabilities?.capabilities.filter((item) => item.kind === "drawing") ?? [];
  const destinationLabel = destination?.displayDirectory ??
    (status.startsWith("Verified:") || status.startsWith("Destination grant used")
      ? "Destination grant used — choose again for another copy"
      : "No destination selected");

  return (
    <section aria-label="Export" className="export-panel" role="region">
      <header><strong>Export</strong><span>Verified copies</span></header>
      {error && <p className="export-error" role="alert">{error}</p>}
      {!capabilities && !error && <p className="export-loading" role="status">Loading export capabilities…</p>}
      <section aria-labelledby="report-export-heading" className="export-group">
        <h2 id="report-export-heading">Report export</h2>
        <p>Download a bounded report from the active document revision.</p>
        <div className="export-actions">
          {reports.map((item) => (
            <button disabled={busy || !item.available} key={item.format} onClick={() => void downloadReport(item.format as ReportFormat)}>
              <Download size={13} />Download {item.format.toUpperCase()} report
            </button>
          ))}
        </div>
      </section>
      <section aria-labelledby="drawing-save-heading" className="export-group drawing-save">
        <h2 id="drawing-save-heading">Drawing Save As</h2>
        <p>The source stays read-only. A one-use host grant selects the copy destination.</p>
        <button disabled={busy} onClick={() => void chooseDestination()}><FolderOpen size={13} />Choose destination</button>
        <p>{destinationLabel}</p>
        <label>
          <span>Base filename</span>
          <input aria-label="Base filename" disabled={busy} onChange={(event) => setBaseFilename(event.target.value)} value={baseFilename} />
        </label>
        <p className="destination-status" role="status">{status}</p>
        <div className="export-actions">
          {drawings.map((item) => (
            <button disabled={busy || !item.available || !destination} key={item.format} onClick={() => void saveDrawing(item.format as DrawingFormat)} title={item.reason ?? undefined}>
              <Save size={13} />Save As {item.format.toUpperCase()}
            </button>
          ))}
        </div>
      </section>
    </section>
  );
}
