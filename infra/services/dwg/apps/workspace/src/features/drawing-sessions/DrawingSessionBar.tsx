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

/**
 * Opens another drawing. A process that cannot show a host dialog cannot open
 * a drawing, so the control is absent rather than present and disabled.
 */
export function OpenDrawingButton({ dialogAvailable, busy, sessions, onOpen }: DrawingSessionBarProps) {
  if (!dialogAvailable || sessions.length === 0) return null;
  return (
    <button aria-label="도면 열기" className="icon-button" disabled={busy} onClick={onOpen} title="도면 열기" type="button">
      <FolderOpen size={16} />
    </button>
  );
}

/**
 * Switches between open drawings. With a single drawing the project tree
 * already names it, so only an error (if any) is shown.
 */
export function DrawingSessionBar({
  sessions,
  dialogAvailable,
  busy,
  error,
  onActivate
}: DrawingSessionBarProps) {
  if (!dialogAvailable || sessions.length === 0) return null;
  if (sessions.length < 2 && !error) return null;

  return (
    <section aria-label="Open drawings" className="drawing-sessions">
      {error && <p className="drawing-sessions-error" role="alert">{error}</p>}
      {sessions.length > 1 && (
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
      )}
    </section>
  );
}
