import {
  Bot,
  Check,
  ChevronRight,
  LoaderCircle,
  MessageSquarePlus,
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
import { ProviderSwitch } from "./ProviderSwitch";
import type { WorkspaceSession } from "./workspaceSessionStore";
import "./styles.css";

interface Props {
  drawingDisplayName: string;
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
  onNewChat(): void;
  chatLoading: boolean;
  chatResult: ProviderChatResult | null;
  chatError: string | null;
  activeSession?: WorkspaceSession | null;
}

export function AgentWorkspace({
  drawingDisplayName,
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
  onNewChat,
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
      <div className="agent-tabs">
        <div className="conversation-title"><Bot size={14} /> Drawing inspection</div>
        <button className="agent-tab icon-tab" aria-label="새 대화" onClick={onNewChat}>
          <MessageSquarePlus size={15} />
        </button>
      </div>

      <div className="agent-context">
        <span className="agent-avatar">DI</span>
        <div>
          <strong>{activeSession?.title ?? "새 검사 대화"}</strong>
          <span>{drawingDisplayName} · OAuth CLI</span>
        </div>
        <ProviderSwitch
          providers={providers}
          selectedProvider={selectedProvider}
          onProviderChange={onProviderChange}
        />
      </div>

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
              {entry.role === "user" ? "YOU" : <><Bot size={12} /> ASSISTANT</>}
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
            <Bot size={22} />
            <strong>도면에 대해 질문하세요</strong>
            <span>레이어, 객체, handle과 검사 근거를 함께 확인합니다.</span>
          </div>
        )}

        {inspectionLoading && (
          <div className="tool-stack" aria-label="에이전트 실행 상태">
            <ToolStep label="orchestrator" tool="POST /api/inspections" state="running" />
          </div>
        )}
        {inspectionRun?.events.length ? (
          <div className="tool-stack" aria-label="에이전트 실행 상태">
            {inspectionRun.events.map((event) => (
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
          </div>
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
      <em>{state === "running" ? "RUNNING" : state === "done" ? "DONE" : state === "rejected" ? "REJECTED" : state === "planned" ? "PLANNED" : "QUEUED"}</em>
    </div>
  );
}
