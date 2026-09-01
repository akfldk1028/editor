import { createHash } from "node:crypto";
import { extname, resolve } from "node:path";

import {
  composeCadCapabilityModules,
  createDestinationGrantStore,
  createEditCapabilityComposition,
  createReadCapabilityModule,
  createSaveCapabilityModule,
  createSaveCoordinator,
  CadSaveError,
  type CadCapabilityModule,
  type CadCapabilityRuntime,
  type DestinationGrantStore,
  type ReadCapabilityDependencies
} from "@dwg/cad-capabilities";
import { exportCadReport, type CadReportChangeSet } from "@dwg/cad-export";
import {
  createAcadSharpCadIoClient,
  type CadProcessRunner
} from "@dwg/cad-io-acadsharp";
import { createDocumentSnapshot } from "@dwg/cad-document";
import {
  createCadEditHistory,
  type CadCommittedTransactionStore,
  type CadEditHistory
} from "@dwg/cad-edit";
import {
  parseCadDrawingExportRequest,
  parseCadReportExportRequest,
  type CadEntityIndex,
  type CadReportExportResponse,
  type DrawingFormat
} from "@dwg/contracts";

import {
  buildIndexForPath,
  createVerificationDocumentReader,
  readParsedDocumentEvidence,
  readSourceSha256
} from "./drawing-access/parsedDocumentEvidence.js";
import { isDrawingExportAvailable } from "./drawingExportPolicy.js";
import { createConfiguredSourceDocumentResolver } from "./drawing-access/sourceDocumentResolver.js";
import { resolveWorkspaceCadPath } from "./drawing-access/workspacePath.js";
import { createCadReportDownloadStore } from "./reportDownloadStore.js";

export const CAD_APPLICATION_CAPABILITY_NAMES = [
  "document.open",
  "document.describe",
  "query.layers",
  "query.entities",
  "query.text",
  "edit.preview",
  "edit.apply",
  "edit.undo",
  "edit.redo",
  "export.report",
  "export.drawing",
  "verification.get"
] as const;

export interface DestinationSelectionProvider {
  request(signal?: AbortSignal): Promise<{
    canonicalDirectory: string;
    displayDirectory: string;
  } | null>;
}

export class CadActiveDocumentError extends Error {
  readonly code = "ACTIVE_DOCUMENT_CONFLICT";

  constructor() {
    super("Another CAD document is already active.");
    this.name = "CadActiveDocumentError";
  }
}

export interface CadApplicationConfig {
  workspaceRoot: string;
  drawingPath: string;
  exportRoot: string;
  dwgVersionManifestPath: string;
  processRunner: CadProcessRunner;
  destinationSelector: DestinationSelectionProvider;
  clock: () => number;
}

export interface CadApplication {
  capabilities: CadCapabilityRuntime;
  transactions: CadCommittedTransactionStore;
  capabilityNames: readonly (typeof CAD_APPLICATION_CAPABILITY_NAMES)[number][];
  /** Returns the immutable source-derived index with the active edit snapshot applied. */
  currentIndex(): CadEntityIndex;
  /** Opens a drawing through the application read port, preserving the active snapshot. */
  readIndex(path: string, signal?: AbortSignal): Promise<CadEntityIndex>;
  /** The format the active drawing was read as, or null when none is open. */
  activeDrawingFormat(): DrawingFormat | null;
  /** Canonical source path for internal adapters that must follow session switches. */
  currentDrawingPath(): string | null;
  requestDestinationGrant(signal?: AbortSignal): Promise<{
    grantId: string;
    displayDirectory: string;
    expiresAt: number;
  } | null>;
  createReportDownload(input: unknown, signal?: AbortSignal): Promise<CadReportExportResponse>;
  consumeReportDownload(downloadId: string): {
    format: "json" | "csv" | "pdf" | "svg";
    mediaType: string;
    filename: string;
    bytes: Uint8Array;
    sha256: string;
  } | null;
}

export interface CadApplicationOptions {
  workspaceRoot?: string;
  drawingPath?: string;
  loadInitialIndex?: (signal?: AbortSignal) => Promise<CadEntityIndex>;
  read?: ReadCapabilityDependencies;
  sourceSha256?: string;
  exportRoot?: string;
  dwgVersionManifestPath?: string;
  cadIoHostProjectPath?: string;
  processRunner?: CadProcessRunner;
  destinationSelector?: DestinationSelectionProvider;
  clock?: () => number;
}

export async function createCadApplication(
  options: CadApplicationOptions = {}
): Promise<CadApplication> {
  const workspaceRoot = options.workspaceRoot ?? process.cwd();
  const initialIndex = await (options.loadInitialIndex
    ? options.loadInitialIndex()
    : options.drawingPath
      ? loadDefaultIndex(workspaceRoot, options.drawingPath)
      : createUnopenedIndex());
  let activePath = options.drawingPath
    ? resolveWorkspaceCadPath(workspaceRoot, options.drawingPath)
    : null;
  let activePathKey: string | null = activePath;
  const sourceSha256 = options.sourceSha256 ??
    (activePath
      ? await readSourceSha256(activePath)
      : createHash("sha256").update(JSON.stringify(initialIndex)).digest("hex"));
  let activeHistory = createCadEditHistory(createDocumentSnapshot(initialIndex, sourceSha256));
  const history = createSwitchableHistory(() => activeHistory);
  const edit = createEditCapabilityComposition(history);
  const currentIndex = () => projectCurrentIndex(history.current());
  const sourceRead = options.read ?? createDefaultReadDependencies(workspaceRoot);
  let activeDrawingId = initialIndex.drawingId;
  const clock = options.clock ?? Date.now;
  const grants = createDestinationGrantStore({ now: clock });
  let drawingModule = createDrawingSaveModule({
    history,
    grants,
    activePath,
    documentId: activeDrawingId,
    processRunner: options.processRunner,
    dwgVersionManifestPath: options.dwgVersionManifestPath,
    cadIoHostProjectPath: options.cadIoHostProjectPath,
    workspaceRoot
  });
  const read: ReadCapabilityDependencies = {
    async open(path, signal) {
      if (signal?.aborted) throw signal.reason;
      const resolvedPath = options.read && activePath === null
        ? null
        : resolveWorkspaceCadPath(workspaceRoot, path);
      const pathKey = resolvedPath ?? path;
      if (activePathKey !== null) {
        if (pathKey === activePathKey) return currentIndex();
        throw new CadActiveDocumentError();
      }
      const opened = await sourceRead.open(path, signal);
      if (activeDrawingId === "cad:unopened") {
        if (signal?.aborted) throw signal.reason;
        const openedSha256 = options.sourceSha256 ??
          (resolvedPath
            ? await readSourceSha256(resolvedPath, signal)
            : createHash("sha256").update(JSON.stringify(opened)).digest("hex"));
        activeHistory = createCadEditHistory(createDocumentSnapshot(opened, openedSha256));
        activeDrawingId = opened.drawingId;
        activePath = resolvedPath;
        activePathKey = pathKey;
        drawingModule = createDrawingSaveModule({
          history,
          grants,
          activePath,
          documentId: activeDrawingId,
          processRunner: options.processRunner,
          dwgVersionManifestPath: options.dwgVersionManifestPath,
          cadIoHostProjectPath: options.cadIoHostProjectPath,
          workspaceRoot
        });
        return currentIndex();
      }
      if (opened.drawingId !== activeDrawingId) {
        throw new CadActiveDocumentError();
      }
      activePathKey = pathKey;
      return currentIndex();
    },
    get(drawingId) {
      return drawingId === activeDrawingId ? currentIndex() : sourceRead.get(drawingId);
    }
  };
  const save = createSaveModule({
    history,
    sourceFormat: () => activeDrawingFormat(activePath),
    drawingModule: () => drawingModule
  });
  const capabilities = composeCadCapabilityModules([
    createReadCapabilityModule(read),
    edit.module,
    save
  ]);
  const reportDownloads = createCadReportDownloadStore({
    generate: (input, signal) => capabilities.execute("export.report", input, signal),
    clock
  });

  return {
    capabilities,
    transactions: edit.transactions,
    capabilityNames: CAD_APPLICATION_CAPABILITY_NAMES,
    currentIndex,
    currentDrawingPath: () => activePath,
    activeDrawingFormat: () => activeDrawingFormat(activePath),
    async readIndex(path, signal) {
      if (signal?.aborted) throw signal.reason;
      const resolvedPath = options.read && activePath === null
        ? null
        : resolveWorkspaceCadPath(workspaceRoot, path);
      const pathKey = resolvedPath ?? path;
      if (activePathKey !== null && pathKey === activePathKey) {
        return currentIndex();
      }
      const opened = await sourceRead.open(path, signal);
      return opened.drawingId === activeDrawingId ? currentIndex() : opened;
    },
    async requestDestinationGrant(signal) {
      const selection = options.destinationSelector
        ? await options.destinationSelector.request(signal)
        : options.exportRoot
          ? {
              canonicalDirectory: resolve(options.exportRoot),
              displayDirectory: "Exports"
            }
          : null;
      if (!selection) return null;
      const expiresAt = clock() + 10 * 60 * 1000;
      const grantId = await grants.issue(selection.canonicalDirectory, expiresAt);
      return { grantId, displayDirectory: selection.displayDirectory, expiresAt };
    },
    createReportDownload: (input, signal) => reportDownloads.create(input, signal),
    consumeReportDownload: (downloadId) => reportDownloads.consume(downloadId)
  };
}

function activeDrawingFormat(path: string | null): DrawingFormat | null {
  if (path === null) return null;
  const extension = extname(path).toLowerCase();
  if (extension === ".dwg") return "dwg";
  if (extension === ".dxf") return "dxf";
  return null;
}

function createSaveModule(options: {
  history: CadEditHistory;
  sourceFormat: () => DrawingFormat | null;
  drawingModule: () => CadCapabilityModule | null;
}): CadCapabilityModule {
  return {
    names: ["export.report", "export.drawing", "verification.get"],
    async execute(name, input, signal) {
      if (name === "export.report") {
        const request = parseCadReportExportRequest(input);
        const state = options.history.getSaveState(request.documentId, request.revision);
        if (!state) throw new CadSaveError("CAD_SAVE_STALE");
        const changeSet: CadReportChangeSet | null = state.lineage.length === 0
          ? null
          : {
              documentId: state.documentId,
              revision: state.revision,
              transactionIds: state.lineage.map((item) => item.batch.transactionId),
              changes: state.lineage.flatMap((item) => item.changes)
            };
        return exportCadReport({
          document: state.current,
          findings: null,
          changeSet,
          verification: null
        }, request.format);
      }
      // The advertised capability list is not a boundary on its own; a caller
      // can reach this capability directly over loopback or MCP.
      if (name === "export.drawing") {
        const requested = parseCadDrawingExportRequest(input);
        if (!isDrawingExportAvailable(options.sourceFormat(), requested.format)) {
          throw new CadSaveError("CAD_SAVE_DESTINATION_UNSUPPORTED");
        }
      }
      const drawingModule = options.drawingModule();
      if (!drawingModule) throw new CadSaveError("CAD_SAVE_DESTINATION_UNSUPPORTED");
      return drawingModule.execute(name, input, signal);
    }
  };
}

function createDrawingSaveModule(options: {
  history: CadEditHistory;
  grants: DestinationGrantStore;
  activePath: string | null;
  documentId: string;
  processRunner?: CadProcessRunner;
  dwgVersionManifestPath?: string;
  cadIoHostProjectPath?: string;
  workspaceRoot: string;
}): CadCapabilityModule | null {
  if (!options.activePath || !options.processRunner) return null;
  const sources = createConfiguredSourceDocumentResolver({
    documentId: options.documentId,
    configuredPath: options.activePath,
    readSha256: readSourceSha256,
    readEvidence: readParsedDocumentEvidence
  });
  const coordinator = createSaveCoordinator({
    cadIo: createAcadSharpCadIoClient({
      projectPath: options.cadIoHostProjectPath
        ? resolve(options.cadIoHostProjectPath)
        : resolve(
            options.workspaceRoot,
            "modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj"
          ),
      processRunner: options.processRunner,
      dwgVersionManifestPath: options.dwgVersionManifestPath
    }),
    sources,
    readDocument: createVerificationDocumentReader(options.activePath ?? ""),
    transactions: options.history,
    grants: options.grants
  });
  return createSaveCapabilityModule(coordinator, exportCadReport);
}

function createSwitchableHistory(active: () => CadEditHistory): CadEditHistory {
  return {
    current: () => active().current(),
    preview: (batch) => active().preview(batch),
    apply: (preview) => active().apply(preview),
    undo: (revision) => active().undo(revision),
    redo: (revision) => active().redo(revision),
    undoWithTransaction: (revision) => active().undoWithTransaction(revision),
    redoWithTransaction: (revision) => active().redoWithTransaction(revision),
    entries: () => active().entries(),
    getCommittedTransaction: (transactionId) => active().getCommittedTransaction(transactionId),
    getSaveState: (documentId, revision) => active().getSaveState(documentId, revision)
  };
}

function projectCurrentIndex(
  current: ReturnType<ReturnType<typeof createCadEditHistory>["current"]>
): CadEntityIndex {
  return {
    ...current.index,
    drawing: {
      fileVersion: current.drawingVersion,
      units: current.units,
      revision: current.revision
    }
  };
}

function createDefaultReadDependencies(workspaceRoot: string): ReadCapabilityDependencies {
  const drawings = new Map<string, CadEntityIndex>();
  return {
    async open(path, signal) {
      const fullPath = resolveWorkspaceCadPath(workspaceRoot, path);
      const index = await buildIndexForPath(fullPath, signal);
      drawings.set(index.drawingId, index);
      return index;
    },
    get(drawingId) {
      return drawings.get(drawingId) ?? null;
    }
  };
}

async function loadDefaultIndex(workspaceRoot: string, drawingPath?: string): Promise<CadEntityIndex> {
  if (!drawingPath) throw new Error("CadApplication requires a drawing path.");
  return buildIndexForPath(resolveWorkspaceCadPath(workspaceRoot, drawingPath));
}

function createUnopenedIndex(): CadEntityIndex {
  return {
    schemaVersion: "cad-index/v0.1",
    drawingId: "cad:unopened",
    source: { kind: "dxf", displayName: "unopened.dxf", parser: "application" },
    summary: {
      entityCount: 0,
      layerCount: 0,
      unsupportedCount: 0,
      modelSpaceCount: 0,
      paperSpaceCount: 0
    },
    layers: [],
    entities: [],
    unsupported: []
  };
}
