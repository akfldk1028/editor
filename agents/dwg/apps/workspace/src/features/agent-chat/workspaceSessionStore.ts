import {
  isProviderSessionId,
  type ProviderId
} from "@dwg/contracts";

export interface WorkspaceMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
}

export interface WorkspaceSession {
  id: string;
  provider: ProviderId;
  providerSessionId: string | null;
  drawingPath: string;
  title: string;
  updatedAt: string;
  messages: WorkspaceMessage[];
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

interface CreateSessionInput {
  id: string;
  provider: ProviderId;
  drawingPath: string;
  now: string;
  firstMessage?: string;
}

const storageKey = "dwg.workspace-sessions.v1";
const maximumSessions = 20;
const maximumMessages = 20;
const maximumMessageCharacters = 10_000;
const maximumTitleCharacters = 48;

export function createWorkspaceSession(
  input: CreateSessionInput
): WorkspaceSession {
  const firstMessage = input.firstMessage?.trim() ?? "";
  const messages = firstMessage
    ? [{
        id: `${input.id}:user:0`,
        role: "user" as const,
        text: firstMessage.slice(0, maximumMessageCharacters),
        createdAt: input.now
      }]
    : [];
  return {
    id: input.id,
    provider: input.provider,
    providerSessionId: null,
    drawingPath: input.drawingPath,
    title: firstMessage.slice(0, maximumTitleCharacters) || "New inspection",
    updatedAt: input.now,
    messages
  };
}

export function appendWorkspaceMessage(
  session: WorkspaceSession,
  message: WorkspaceMessage
): WorkspaceSession {
  const nextMessage = {
    ...message,
    text: message.text.slice(0, maximumMessageCharacters)
  };
  return {
    ...session,
    updatedAt: message.createdAt,
    messages: [...session.messages, nextMessage].slice(-maximumMessages)
  };
}

export function createWorkspaceSessionStore(storage: StorageLike) {
  let memorySessions: WorkspaceSession[] = [];

  function read() {
    try {
      const raw = storage.getItem(storageKey);
      if (!raw) return memorySessions;
      const parsed: unknown = JSON.parse(raw);
      const sessions = validateStoredSessions(parsed);
      memorySessions = sessions;
      return sessions;
    } catch {
      return memorySessions;
    }
  }

  function write(sessions: WorkspaceSession[]) {
    memorySessions = [...sessions]
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
      .slice(0, maximumSessions);
    try {
      storage.setItem(storageKey, JSON.stringify({
        sessions: memorySessions
      }));
    } catch {
      // Restricted browsers still keep sessions for the current runtime.
    }
  }

  return {
    list() {
      return read();
    },
    get(id: string) {
      return read().find((session) => session.id === id) ?? null;
    },
    upsert(session: WorkspaceSession) {
      const existing = read().filter((candidate) => candidate.id !== session.id);
      write([normalizeSession(session), ...existing]);
    },
    clear() {
      write([]);
    }
  };
}

export const browserWorkspaceSessionStore = createWorkspaceSessionStore(
  getBrowserStorage()
);

function getBrowserStorage(): StorageLike {
  try {
    if (typeof window !== "undefined") {
      return window.localStorage;
    }
  } catch {
    // Fall through to the in-memory session store.
  }
  return {
    getItem: () => null,
    setItem: () => undefined
  };
}

function validateStoredSessions(value: unknown): WorkspaceSession[] {
  if (!value || typeof value !== "object") return [];
  const sessions = (value as Record<string, unknown>).sessions;
  if (!Array.isArray(sessions)) return [];
  return sessions
    .map(validateSession)
    .filter((session): session is WorkspaceSession => session !== null)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, maximumSessions);
}

function validateSession(value: unknown): WorkspaceSession | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.id !== "string" ||
    (record.provider !== "codex" && record.provider !== "claude") ||
    typeof record.drawingPath !== "string" ||
    typeof record.title !== "string" ||
    typeof record.updatedAt !== "string" ||
    !Array.isArray(record.messages) ||
    !(
      record.providerSessionId === null ||
      isProviderSessionId(record.providerSessionId)
    )
  ) {
    return null;
  }
  const messages = record.messages
    .map(validateMessage)
    .filter((message): message is WorkspaceMessage => message !== null)
    .slice(-maximumMessages);
  return normalizeSession({
    id: record.id,
    provider: record.provider,
    providerSessionId: record.providerSessionId,
    drawingPath: record.drawingPath,
    title: record.title,
    updatedAt: record.updatedAt,
    messages
  });
}

function validateMessage(value: unknown): WorkspaceMessage | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.id !== "string" ||
    (record.role !== "user" && record.role !== "assistant") ||
    typeof record.text !== "string" ||
    typeof record.createdAt !== "string"
  ) {
    return null;
  }
  return {
    id: record.id,
    role: record.role,
    text: record.text.slice(0, maximumMessageCharacters),
    createdAt: record.createdAt
  };
}

function normalizeSession(session: WorkspaceSession): WorkspaceSession {
  return {
    ...session,
    title: session.title.slice(0, maximumTitleCharacters) || "New inspection",
    messages: session.messages.slice(-maximumMessages)
  };
}
