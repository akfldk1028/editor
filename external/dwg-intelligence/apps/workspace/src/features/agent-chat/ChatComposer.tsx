import {
  AtSign,
  Paperclip,
  Send,
  Square,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  MAX_PROVIDER_MESSAGE_CHARS,
  type ProviderId
} from "../../shared/types";
import { buildAttachmentMessage } from "./attachmentMessage";

interface Props {
  provider: ProviderId;
  message: string;
  loading: boolean;
  onMessageChange(message: string): void;
  onSubmit(): void;
  onCancel(): void;
}

export function ChatComposer({
  provider,
  message,
  loading,
  onMessageChange,
  onSubmit,
  onCancel
}: Props) {
  const [attachmentName, setAttachmentName] = useState<string | null>(null);
  const [attachmentBlock, setAttachmentBlock] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!message && attachmentName) {
      setAttachmentName(null);
      setAttachmentBlock("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [attachmentName, message]);

  function insertMention() {
    const separator = message && !message.endsWith(" ") ? " " : "";
    onMessageChange(`${message}${separator}@drawing-index-agent `);
    window.setTimeout(() => messageInputRef.current?.focus(), 0);
  }

  async function attachFile(file: File | undefined) {
    if (!file) return;
    const readableSlice = file.slice(0, MAX_PROVIDER_MESSAGE_CHARS * 4);
    const content = await readableSlice.text();
    const next = buildAttachmentMessage({
      message,
      previousAttachmentBlock: attachmentBlock,
      fileName: file.name,
      content,
      sourceWasTruncated: readableSlice.size < file.size
    });
    if (!next.attachmentBlock) return;
    setAttachmentName(file.name);
    setAttachmentBlock(next.attachmentBlock);
    onMessageChange(next.message);
  }

  function removeAttachment() {
    onMessageChange(message.replace(attachmentBlock, "").trimEnd());
    setAttachmentName(null);
    setAttachmentBlock("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <form className="composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      <input
        aria-label="AI 질문"
        disabled={loading}
        maxLength={MAX_PROVIDER_MESSAGE_CHARS}
        onChange={(event) => onMessageChange(event.target.value)}
        placeholder="도면에 대해 질문하세요…"
        ref={messageInputRef}
        value={message}
      />
      <input
        accept=".dxf,.json,.txt"
        aria-label="첨부 파일 선택"
        hidden
        onChange={(event) => void attachFile(event.target.files?.[0])}
        ref={fileInputRef}
        type="file"
      />
      {attachmentName && (
        <span className="attachment-chip">
          <Paperclip size={11} />
          <span>{attachmentName}</span>
          <button aria-label="첨부 제거" onClick={removeAttachment} type="button"><X size={11} /></button>
        </span>
      )}
      <div className="composer-actions">
        <span>
          <button aria-label="에이전트 멘션" onClick={insertMention} type="button"><AtSign size={14} /></button>
          <button aria-label="파일 첨부" onClick={() => fileInputRef.current?.click()} type="button"><Paperclip size={14} /></button>
        </span>
        <span className="composer-provider">{provider === "codex" ? "GPT" : "CLAUDE"} · OAUTH</span>
        {loading ? (
          <button
            className="send-button cancel-button"
            aria-label="응답 취소"
            onClick={onCancel}
            onPointerDown={(event) => {
              event.preventDefault();
              onCancel();
            }}
            type="button"
          >
            <Square size={11} />
          </button>
        ) : (
          <button className="send-button" aria-label="전송" disabled={!message.trim()}>
            <Send size={13} />
          </button>
        )}
      </div>
    </form>
  );
}
