import { MAX_PROVIDER_MESSAGE_CHARS } from "../../shared/types";

interface AttachmentMessageInput {
  message: string;
  previousAttachmentBlock: string;
  fileName: string;
  content: string;
  sourceWasTruncated: boolean;
}

interface AttachmentMessageResult {
  message: string;
  attachmentBlock: string;
}

const omittedMarker = "\n[내용 일부 생략]";

export function buildAttachmentMessage(
  input: AttachmentMessageInput
): AttachmentMessageResult {
  const messageWithoutPreviousAttachment = input.previousAttachmentBlock
    ? input.message.replace(input.previousAttachmentBlock, "")
    : input.message;
  const baseMessage = messageWithoutPreviousAttachment
    .trimEnd()
    .slice(0, MAX_PROVIDER_MESSAGE_CHARS);
  const safeFileName = input.fileName
    .replace(/[\r\n]/g, " ")
    .slice(0, 200);
  const header = `\n\n[첨부: ${safeFileName}]\n`;
  const available = MAX_PROVIDER_MESSAGE_CHARS - baseMessage.length - header.length;

  if (available <= 0) {
    return { message: baseMessage, attachmentBlock: "" };
  }

  const needsOmittedMarker =
    input.sourceWasTruncated || input.content.length > available;
  const suffix = needsOmittedMarker && available >= omittedMarker.length
    ? omittedMarker
    : "";
  const clippedContent = input.content.slice(
    0,
    Math.max(0, available - suffix.length)
  );
  const attachmentBlock = `${header}${clippedContent}${suffix}`;

  return {
    message: `${baseMessage}${attachmentBlock}`,
    attachmentBlock
  };
}
