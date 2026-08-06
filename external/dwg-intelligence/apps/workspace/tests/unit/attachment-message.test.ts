import assert from "node:assert/strict";
import test from "node:test";

import { MAX_PROVIDER_MESSAGE_CHARS } from "../../src/shared/types.js";
import { buildAttachmentMessage } from "../../src/features/agent-chat/attachmentMessage.js";

test("large attachments preserve the question within the provider message limit", () => {
  const result = buildAttachmentMessage({
    message: "도면 질문",
    previousAttachmentBlock: "",
    fileName: "large-note.txt",
    content: "x".repeat(20_000),
    sourceWasTruncated: true
  });

  assert.equal(result.message.startsWith("도면 질문\n\n[첨부: large-note.txt]\n"), true);
  assert.equal(result.message.endsWith("[내용 일부 생략]"), true);
  assert.equal(result.message.length <= MAX_PROVIDER_MESSAGE_CHARS, true);
  assert.equal(result.message.endsWith(result.attachmentBlock), true);
});
