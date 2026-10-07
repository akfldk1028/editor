import { SquarePen } from "lucide-react";

import { AgentWorkspace, ConversationHeading } from "../../features/agent-chat/AgentWorkspace";
import { useDwgChatInput, useDwgWorkspace } from "./DwgWorkspaceProvider";

/** The conversation's identity block, for the host's header row. */
export function DwgConversationHeading() {
  const { chat, index } = useDwgWorkspace();
  return (
    <div className="dwg-workspace dwg-heading">
      <ConversationHeading activeSession={chat.activeSession} drawingDisplayName={index?.source.displayName ?? "도면 불러오는 중"} />
    </div>
  );
}

/** Conversation controls for the host's header row (new conversation). */
export function DwgConversationActions() {
  const { chat } = useDwgWorkspace();
  return (
    <button aria-label="새 대화" className="icon-button" onClick={chat.reset} title="새 대화">
      <SquarePen size={17} />
    </button>
  );
}

/** Extra rows for the host's settings popover. */
export function DwgSettings() {
  const { gridVisible, setGridVisible } = useDwgWorkspace();
  return <label><span>격자</span><input checked={gridVisible} onChange={(event) => setGridVisible(event.target.checked)} type="checkbox" /></label>;
}

/** Messages and composer, filling the host's conversation cell. */
export function DwgConversation() {
  const { chat, inspection } = useDwgWorkspace();
  const { message, setMessage } = useDwgChatInput();
  return (
    <div className="dwg-workspace dwg-conversation">
      <AgentWorkspace
        activeSession={chat.activeSession}
        chatError={chat.error}
        chatLoading={chat.loading}
        chatResult={chat.result}
        inspectionError={inspection.error}
        inspectionLoading={inspection.loading}
        inspectionRun={inspection.run}
        message={message}
        onCancel={chat.cancel}
        onMessageChange={setMessage}
        onProviderChange={chat.setSelectedProvider}
        onSubmit={chat.submit}
        providers={chat.providers}
        selectedProvider={chat.selectedProvider}
      />
    </div>
  );
}
