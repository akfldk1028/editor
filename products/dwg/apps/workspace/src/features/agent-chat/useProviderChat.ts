import { useEffect, useRef, useState } from "react";

import {
  loadProviderStatuses,
  sendProviderChat
} from "../../shared/api/providerGatewayClient";
import type {
  ProviderChatResult,
  ProviderId,
  ProviderStatus
} from "../../shared/types";
import {
  appendWorkspaceMessage,
  browserWorkspaceSessionStore,
  createWorkspaceSession,
  type WorkspaceSession
} from "./workspaceSessionStore";

const drawingPath = "tests/fixtures/dwg/export_sample.dwg";

export function useProviderChat(workspaceStore = browserWorkspaceSessionStore) {
  const initialSessions = useRef(workspaceStore.list()).current;
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ProviderId>(
    initialSessions[0]?.provider ?? "codex"
  );
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<ProviderChatResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<WorkspaceSession[]>(
    initialSessions
  );
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    initialSessions[0]?.id ?? null
  );
  const requestController = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    loadProviderStatuses(controller.signal)
      .then((statuses) => {
        setProviders(statuses);
        setSelectedProvider((current) => {
          if (statuses.some((provider) => provider.id === current && provider.authenticated)) {
            return current;
          }
          return statuses.find((provider) => provider.authenticated)?.id ?? current;
        });
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") {
          setError("로컬 AI gateway에 연결할 수 없습니다.");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => requestController.current?.abort(), []);

  async function submit() {
    const trimmedMessage = message.trim();
    if (!trimmedMessage || loading) return;

    const now = new Date().toISOString();
    const workspaceSession = activeSessionId
      ? workspaceStore.get(activeSessionId)
      : null;
    const currentSession = workspaceSession ?? createWorkspaceSession({
      id: crypto.randomUUID(),
      provider: selectedProvider,
      drawingPath,
      now,
      firstMessage: trimmedMessage
    });
    if (!workspaceSession) {
      workspaceStore.upsert(currentSession);
      setActiveSessionId(currentSession.id);
      setSessions(workspaceStore.list());
    } else {
      workspaceStore.upsert(appendWorkspaceMessage(currentSession, {
        id: crypto.randomUUID(),
        role: "user",
        text: trimmedMessage,
        createdAt: now
      }));
      setSessions(workspaceStore.list());
    }

    const controller = new AbortController();
    const generation = ++requestGeneration.current;
    requestController.current = controller;
    setLoading(true);
    setError(null);
    try {
      const sessionId =
        currentSession.provider === selectedProvider
          ? currentSession.providerSessionId
          : null;
      const response = await sendProviderChat({
        provider: selectedProvider,
        drawingPath,
        message: trimmedMessage,
        ...(sessionId ? { sessionId } : {})
      }, controller.signal);
      if (
        controller.signal.aborted ||
        requestGeneration.current !== generation
      ) return;
      const latestSession = workspaceStore.get(currentSession.id) ?? currentSession;
      workspaceStore.upsert(appendWorkspaceMessage({
        ...latestSession,
        provider: selectedProvider,
        providerSessionId: response.sessionId ?? latestSession.providerSessionId
      }, {
        id: crypto.randomUUID(),
        role: "assistant",
        text: response.text,
        createdAt: new Date().toISOString()
      }));
      setSessions(workspaceStore.list());
      setResult(response);
      setMessage("");
    } catch (reason) {
      if (reason instanceof Error && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "AI 응답에 실패했습니다.");
    } finally {
      if (
        requestController.current === controller &&
        requestGeneration.current === generation
      ) {
        requestController.current = null;
        setLoading(false);
      }
    }
  }

  function cancel() {
    requestGeneration.current += 1;
    requestController.current?.abort();
    requestController.current = null;
    setLoading(false);
  }

  function reset() {
    cancel();
    setMessage("");
    setResult(null);
    setError(null);
    setActiveSessionId(null);
  }

  function selectSession(id: string) {
    const session = workspaceStore.get(id);
    if (!session) return;
    cancel();
    setActiveSessionId(id);
    setSelectedProvider(session.provider);
    setResult(session.messages.at(-1)?.role === "assistant"
      ? {
          provider: session.provider,
          text: session.messages.at(-1)!.text,
          sessionId: session.providerSessionId
        }
      : null);
    setMessage("");
    setError(null);
  }

  return {
    providers,
    selectedProvider,
    setSelectedProvider,
    message,
    setMessage,
    result,
    error,
    loading,
    sessions,
    activeSessionId,
    activeSession: activeSessionId ? workspaceStore.get(activeSessionId) : null,
    selectSession,
    submit,
    cancel,
    reset
  };
}
