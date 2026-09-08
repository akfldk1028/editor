import { FolderOpen } from "lucide-react";

import type { DrawingSession } from "@dwg/contracts";

import "./styles.css";

export interface DrawingSessionBarProps {
  sessions: DrawingSession[];
  dialogAvailable: boolean;
  busy: boolean;
  error: string | null;
  onOpen(): void;
  onActivate(sessionId: string): void;
}

export function DrawingSessionBar({
  sessions,
  dialogAvailable,
  busy,
  error,
  onOpen,
  onActivate
}: DrawingSessionBarProps) {
  // A process that cannot show a host dialog cannot open a drawing, so the
  // control is absent rather than present and permanently disabled.
  if (!dialogAvailable || sessions.length === 0) return null;

  return (
    <section aria-label="Open drawings" className="drawing-sessions">
      <button disabled={busy} onClick={onOpen} type="button">
        <FolderOpen size={13} />도면 열기
      </button>
      {error && <p className="drawing-sessions-error" role="alert">{error}</p>}
      <ul>
        {sessions.map((session) => (
          <li key={session.id}>
            <button
              aria-current={session.active ? "true" : undefined}
              className={session.active ? "active" : undefined}
              disabled={busy || session.active}
              onClick={() => onActivate(session.id)}
              title={session.displayName}
              type="button"
            >
              {session.displayName}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
