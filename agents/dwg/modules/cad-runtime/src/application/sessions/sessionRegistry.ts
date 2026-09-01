import type { CadApplication } from "../createCadApplication.js";

export const MAX_DRAWING_SESSIONS = 8;

export class DrawingSessionError extends Error {
  constructor(readonly code: "SESSION_UNKNOWN" | "SESSION_LIMIT" | "SESSION_LAST") {
    super("Drawing session request failed.");
    this.name = "DrawingSessionError";
  }
}

export interface DrawingSessionRecord {
  id: string;
  displayName: string;
  application: CadApplication;
}

export interface DrawingSessionSummary {
  id: string;
  displayName: string;
  drawingId: string;
  active: boolean;
}

export interface DrawingSessionRegistry {
  /** The application every gateway route resolves through. Never null once seeded. */
  active(): CadApplication;
  activeId(): string;
  summaries(): DrawingSessionSummary[];
  /** Adds a session and makes it active. Throws SESSION_LIMIT at the cap. */
  add(record: Omit<DrawingSessionRecord, "id">): DrawingSessionSummary;
  activate(id: string): DrawingSessionSummary;
  close(id: string): void;
}

export function createDrawingSessionRegistry(options: {
  first: Omit<DrawingSessionRecord, "id">;
  createId?: () => string;
}): DrawingSessionRegistry {
  let counter = 0;
  const createId = options.createId ?? (() => `session-${++counter}`);
  const sessions: DrawingSessionRecord[] = [
    { id: createId(), ...options.first }
  ];
  let activeId = sessions[0]!.id;

  const find = (id: string) => {
    const session = sessions.find((item) => item.id === id);
    if (!session) throw new DrawingSessionError("SESSION_UNKNOWN");
    return session;
  };
  const summarize = (session: DrawingSessionRecord): DrawingSessionSummary => ({
    id: session.id,
    displayName: session.displayName,
    drawingId: session.application.currentIndex().drawingId,
    active: session.id === activeId
  });

  return {
    active: () => find(activeId).application,
    activeId: () => activeId,
    summaries: () => sessions.map(summarize),
    add(record) {
      if (sessions.length >= MAX_DRAWING_SESSIONS) {
        throw new DrawingSessionError("SESSION_LIMIT");
      }
      const session: DrawingSessionRecord = { id: createId(), ...record };
      sessions.push(session);
      activeId = session.id;
      return summarize(session);
    },
    activate(id) {
      const session = find(id);
      activeId = session.id;
      return summarize(session);
    },
    close(id) {
      const session = find(id);
      // Closing the only session would leave every route without a document.
      if (sessions.length === 1) throw new DrawingSessionError("SESSION_LAST");
      sessions.splice(sessions.indexOf(session), 1);
      if (activeId === id) activeId = sessions[0]!.id;
    }
  };
}

/**
 * A stable CadApplication that forwards to whichever session is active, so the
 * gateway's route factories keep their existing signatures and follow session
 * switches without being rebuilt.
 */
export function createActiveApplicationProxy(
  registry: DrawingSessionRegistry
): CadApplication {
  return {
    capabilities: {
      execute: (name, input, signal) =>
        registry.active().capabilities.execute(name, input, signal)
    },
    get transactions() {
      return registry.active().transactions;
    },
    get capabilityNames() {
      return registry.active().capabilityNames;
    },
    currentIndex: () => registry.active().currentIndex(),
    currentDrawingPath: () => registry.active().currentDrawingPath(),
    readIndex: (path, signal) => registry.active().readIndex(path, signal),
    activeDrawingFormat: () => registry.active().activeDrawingFormat(),
    requestDestinationGrant: (signal) => registry.active().requestDestinationGrant(signal),
    createReportDownload: (input, signal) =>
      registry.active().createReportDownload(input, signal),
    consumeReportDownload: (downloadId) =>
      registry.active().consumeReportDownload(downloadId)
  };
}
