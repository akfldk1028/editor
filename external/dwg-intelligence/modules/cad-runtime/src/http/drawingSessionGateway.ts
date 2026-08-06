import type { IncomingMessage, ServerResponse } from "node:http";

import {
  parseDrawingSessionErrorResponse,
  parseDrawingSessionListResponse,
  type DrawingSessionErrorCode
} from "@dwg/contracts";
import type { HostDialogProvider } from "@dwg/host-dialogs";

import {
  DrawingSessionError,
  type DrawingSessionRegistry
} from "../application/sessions/sessionRegistry.js";

export interface DrawingSessionRoutes {
  handle(
    request: IncomingMessage,
    response: ServerResponse,
    pathname: string,
    signal?: AbortSignal
  ): Promise<boolean>;
}

export interface DrawingSessionDependencies {
  registry: DrawingSessionRegistry;
  dialogs?: HostDialogProvider;
  /** Opens the chosen drawing and returns the session entry to register. */
  openSession(
    canonicalPath: string,
    displayName: string,
    signal?: AbortSignal
  ): Promise<void>;
}

const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/u;

export function createDrawingSessionRoutes(
  dependencies: DrawingSessionDependencies
): DrawingSessionRoutes {
  return {
    async handle(request, response, pathname, signal) {
      if (!pathname.startsWith("/api/drawings")) return false;
      try {
        if (request.method === "GET" && pathname === "/api/drawings/sessions") {
          sendSessions(response, dependencies.registry, dependencies.dialogs !== undefined);
          return true;
        }
        if (request.method === "POST" && pathname === "/api/drawings/open") {
          await open(dependencies, response, signal);
          return true;
        }
        if (request.method === "POST" && pathname.startsWith("/api/drawings/sessions/")) {
          const id = sessionId(pathname, "/activate");
          if (id === null) return false;
          dependencies.registry.activate(id);
          sendSessions(response, dependencies.registry, dependencies.dialogs !== undefined);
          return true;
        }
        if (request.method === "DELETE" && pathname.startsWith("/api/drawings/sessions/")) {
          const id = sessionId(pathname, "");
          if (id === null) return false;
          dependencies.registry.close(id);
          sendSessions(response, dependencies.registry, dependencies.dialogs !== undefined);
          return true;
        }
        return false;
      } catch (error) {
        const failure = toFailure(error);
        sendError(response, failure.status, failure.code, failure.message);
        return true;
      }
    }
  };
}

async function open(
  dependencies: DrawingSessionDependencies,
  response: ServerResponse,
  signal?: AbortSignal
): Promise<void> {
  if (!dependencies.dialogs) {
    sendError(response, 501, "DIALOG_UNAVAILABLE", "No host dialog is available in this process.");
    return;
  }
  const selection = await dependencies.dialogs.openDrawingFile(signal);
  if (!selection) {
    sendError(response, 409, "DRAWING_OPEN_CANCELLED", "Drawing selection was cancelled.");
    return;
  }
  await dependencies.openSession(selection.canonicalPath, selection.displayName, signal);
  sendSessions(response, dependencies.registry, dependencies.dialogs !== undefined);
}

function sessionId(pathname: string, suffix: string): string | null {
  const rest = pathname.slice("/api/drawings/sessions/".length);
  const id = suffix.length === 0 ? rest : rest.endsWith(suffix)
    ? rest.slice(0, -suffix.length)
    : null;
  return id !== null && SESSION_ID_PATTERN.test(id) ? id : null;
}

function toFailure(error: unknown): {
  status: number;
  code: DrawingSessionErrorCode;
  message: string;
} {
  if (error instanceof DrawingSessionError) {
    switch (error.code) {
      case "SESSION_UNKNOWN":
        return { status: 404, code: "SESSION_UNKNOWN", message: "Drawing session is unknown." };
      case "SESSION_LIMIT":
        return { status: 409, code: "SESSION_LIMIT", message: "Too many drawings are open." };
      default:
        return { status: 409, code: "SESSION_LAST", message: "The last open drawing cannot be closed." };
    }
  }
  const message = error instanceof Error ? error.message : "";
  if (/Unsupported drawing format/u.test(message)) {
    return { status: 415, code: "DRAWING_UNSUPPORTED", message: "That file is not a supported drawing." };
  }
  return { status: 404, code: "DRAWING_NOT_FOUND", message: "The drawing could not be opened." };
}

function sendSessions(
  response: ServerResponse,
  registry: DrawingSessionRegistry,
  dialogAvailable: boolean
): void {
  sendJson(response, 200, parseDrawingSessionListResponse({
    sessions: registry.summaries(),
    activeSessionId: registry.activeId(),
    dialogAvailable
  }));
}

function sendError(
  response: ServerResponse,
  status: number,
  code: DrawingSessionErrorCode,
  message: string
): void {
  sendJson(response, status, parseDrawingSessionErrorResponse({ error: { code, message } }));
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  if (response.destroyed || response.writableEnded) return;
  response.statusCode = status;
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.end(JSON.stringify(value));
}
