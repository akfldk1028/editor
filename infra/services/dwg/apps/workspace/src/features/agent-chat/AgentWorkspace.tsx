import {
  Bot,
  Check,
  ChevronRight,
  LoaderCircle,
  TerminalSquare
} from "lucide-react";
import { useEffect, useRef } from "react";

import type {
  InspectionRun,
  ProviderChatResult,
  ProviderId,
  ProviderStatus
} from "../../shared/types";
import { ChatComposer } from "./ChatComposer";
import { PendingResponse } from "./PendingResponse";
import type { WorkspaceSession } from "./workspaceSessionStore";
import "./styles.css";

interface Props {
  inspectionRun: InspectionRun | null;
  inspectionLoading: boolean;
  inspectionError: string | null;
  providers: ProviderStatus[];
  selectedProvider: ProviderId;
  onProviderChange(provider: ProviderId): void;
  message: string;
  onMessageChange(message: string): void;
  onSubmit(): void;
  onCancel(): void;
  chatLoading: boolean;
  chatResult: ProviderChatResult | null;
  chatError: string | null;
  activeSession?: WorkspaceSession | null;
}

/**
 * The conversation's identity block. The workspace places it in its single
 * header row, so the conversation itself carries no title rows.
 */
export function ConversationHeading({ activeSession, drawingDisplayName }: {
  activeSession?: WorkspaceSession | null;
  drawingDisplayName: string;
}) {
  return (
    <div className="agent-context">
      <span aria-hidden="true" className="agent-avatar">DI</span>
      <div>
        <strong>{activeSession?.title ?? "새 검사 대화"}</strong>
        <span>Drawing review · {drawingDisplayName} · OAuth CLI</span>
      </div>
    </div>
  );
}

export function AgentWorkspace({
  inspectionRun,
  inspectionLoading,
  inspectionError,
  providers,
  selectedProvider,
  onProviderChange,
  message,
  onMessageChange,
  onSubmit,
  onCancel,
  chatLoading,
  chatResult,
  chatError,
  activeSession
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeSession?.messages.length, chatResult]);

  return (
    <main className="panel agent-workspace conversation-panel" aria-label="대화" data-modal-background>
      <div className="conversation">
        {activeSession?.messages.map((entry, entryIndex) => (
          <div
            className={`message ${entry.role === "user" ? "user-message" : "agent-message"}`}
            data-testid={
              entry.role === "assistant" &&
              entryIndex === activeSession.messages.length - 1
                ? "live-response"
                : undefined
            }
            key={entry.id}
          >
            <div className="message-label">
              {entry.role === "user" ? "나" : <><Bot aria-hidden="true" size={12} /> AI 응답</>}
            </div>
            <p>{entry.text}</p>
            {entry.role === "assistant" &&
              entryIndex === activeSession.messages.length - 1 &&
              activeSession.providerSessionId &&
              <code>{activeSession.providerSessionId}</code>}
          </div>
        ))}
        {chatLoading && <PendingResponse onCancel={onCancel} />}
        {!activeSession && !inspectionRun && !inspectionLoading && !chatLoading && (
          <div className="conversation-empty">
            <strong>도면에 대해 질문하세요</strong>
            <span>레이어, 객체, handle과 검사 근거를 함께 확인합니다.</span>
          </div>
        )}

        {(inspectionLoading || inspectionRun?.events.length) ? (
          <details aria-label="에이전트 실행 상태" className="tool-stack">
            <summary>
              {inspectionLoading ? <LoaderCircle aria-hidden="true" className="spin" size={14} /> : <TerminalSquare aria-hidden="true" size={14} />}
              <span>{toolSummary(inspectionLoading, inspectionRun)}</span>
              <ChevronRight aria-hidden="true" className="tool-stack-chevron" size={14} />
            </summary>
            {inspectionLoading && <ToolStep label="orchestrator" tool="POST /api/inspections" state="running" />}
            {inspectionRun?.events.map((event) => (
              <ToolStep
                key={`${event.sequence}:${event.agentId}:${event.action}`}
                label={event.agentId}
                tool={event.action}
                state={
                  event.status === "completed"
                    ? "done"
                    : event.status === "rejected"
                      ? "rejected"
                      : event.status === "planned"
                        ? "planned"
                        : "idle"
                }
              />
            ))}
          </details>
        ) : null}
        {inspectionRun?.status === "completed" && (
          <div className="message agent-message response-message">
            <div className="message-label"><Check size={12} /> VERIFIED RESULT</div>
            <p><strong>{inspectionRun.findings.length}개 주요 객체</strong>를 handle, type, layer, bbox 근거로 확인했습니다.</p>
          </div>
        )}
        {inspectionError && <div className="chat-error" role="alert">{inspectionError}</div>}
        {chatError && <div className="chat-error" role="alert">{chatError}</div>}
        <div ref={endRef} />
      </div>

      <ChatComposer
        providers={providers}
        onProviderChange={onProviderChange}
        provider={selectedProvider}
        message={message}
        loading={chatLoading}
        onMessageChange={onMessageChange}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />
    </main>
  );
}

function toolSummary(loading: boolean, run: InspectionRun | null) {
  if (loading) return "에이전트 실행 중";
  const events = run?.events ?? [];
  const done = events.filter((event) => event.status === "completed").length;
  return `에이전트 ${events.length}단계 · 완료 ${done}`;
}

function ToolStep({ label, tool, state }: {
  label: string;
  tool: string;
  state: "idle" | "planned" | "running" | "done" | "rejected";
}) {
  return (
    <div className={`tool-step ${state}`}>
      {state === "running"
        ? <LoaderCircle className="spin" size={14} />
        : state === "done"
          ? <Check size={14} />
          : <ChevronRight size={14} />}
      <div><strong>{label}</strong><span><TerminalSquare size={11} /> {tool}</span></div>
      <em>{state === "running" ? "진행 중" : state === "done" ? "완료" : state === "rejected" ? "거절됨" : state === "planned" ? "계획됨" : "대기 중"}</em>
    </div>
  );
}
