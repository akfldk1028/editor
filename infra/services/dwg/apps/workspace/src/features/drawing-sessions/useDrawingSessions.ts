import { useCallback, useEffect, useRef, useState } from "react";

import type { DrawingSession } from "@dwg/contracts";

import {
  activateDrawingSession,
  loadDrawingSessions,
  openDrawing
} from "../../shared/api/drawingSessionClient";

export interface DrawingSessionsState {
  sessions: DrawingSession[];
  /** False where the gateway can show no host dialog; the control stays hidden. */
  dialogAvailable: boolean;
  activeSessionId: string | null;
  busy: boolean;
  error: string | null;
  open(): Promise<void>;
  activate(sessionId: string): Promise<void>;
}

export function useDrawingSessions(onActiveChanged: () => void): DrawingSessionsState {
  const [sessions, setSessions] = useState<DrawingSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [dialogAvailable, setDialogAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const changed = useRef(onActiveChanged);
  changed.current = onActiveChanged;

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    loadDrawingSessions(controller.signal)
      .then((list) => {
        if (!mounted.current) return;
        setSessions(list.sessions);
        setActiveSessionId(list.activeSessionId);
        setDialogAvailable(list.dialogAvailable);
      })
      .catch(() => {
        // A gateway without the session routes leaves the control hidden
        // rather than showing an error the person cannot act on.
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, []);

  const run = useCallback(async (
    action: () => Promise<{
      sessions: DrawingSession[];
      activeSessionId: string;
      dialogAvailable: boolean;
    } | null>
  ) => {
    setBusy(true);
    setError(null);
    try {
      const list = await action();
      if (!mounted.current || list === null) return;
      setSessions(list.sessions);
      setActiveSessionId(list.activeSessionId);
      setDialogAvailable(list.dialogAvailable);
      changed.current();
    } catch (reason) {
      if (mounted.current) {
        setError(reason instanceof Error ? reason.message : "The drawing could not be opened.");
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, []);

  return {
    sessions,
    dialogAvailable,
    activeSessionId,
    busy,
    error,
    open: () => run(() => openDrawing()),
    activate: (sessionId) => run(() => activateDrawingSession(sessionId))
  };
}
