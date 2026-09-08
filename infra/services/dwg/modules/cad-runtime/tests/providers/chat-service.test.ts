import assert from "node:assert/strict";
import test from "node:test";

import { buildCadContext } from "../../src/application/chat/cadContextBuilder.js";
import { createChatService } from "../../src/application/chat/chatService.js";
import type { CadEntityIndex } from "../../src/domain/cad-index/types.js";
import type {
  ChatProvider,
  ProviderChatRequest
} from "../../src/providers/contracts.js";

const index: CadEntityIndex = {
  schemaVersion: "cad-index/v0.1",
  drawingId: "drawing-1",
  source: {
    kind: "dwg",
    displayName: "schedule.dwg",
    parser: "acadsharp@3.6.35"
  },
  summary: {
    entityCount: 3,
    layerCount: 2,
    unsupportedCount: 0,
    modelSpaceCount: 3,
    paperSpaceCount: 0
  },
  layers: [
    { name: "A-TEXT", entityCount: 2, visible: true, frozen: false },
    { name: "A-WALL", entityCount: 1, visible: true, frozen: false }
  ],
  entities: [
    {
      id: "h:10",
      handle: "10",
      type: "TEXT",
      layer: "A-TEXT",
      space: "model",
      layout: "Model",
      bbox: { min: [10, 20, 0], max: [10, 20, 0] },
      text: "건축개요",
      blockName: null,
      attributes: {},
      geometry: {},
      warnings: []
    },
    {
      id: "h:11",
      handle: "11",
      type: "MTEXT",
      layer: "A-TEXT",
      space: "model",
      layout: "Model",
      bbox: { min: [15, 20, 0], max: [15, 20, 0] },
      text: "대지면적 500㎡",
      blockName: null,
      attributes: {},
      geometry: {},
      warnings: []
    },
    {
      id: "h:12",
      handle: "12",
      type: "LWPOLYLINE",
      layer: "A-WALL",
      space: "model",
      layout: "Model",
      bbox: { min: [0, 0, 0], max: [100, 100, 0] },
      text: null,
      blockName: null,
      attributes: {},
      geometry: {},
      warnings: []
    }
  ],
  unsupported: []
};

class CapturingProvider implements ChatProvider {
  readonly id = "codex" as const;
  request: ProviderChatRequest | null = null;

  async getStatus() {
    return {
      id: this.id,
      label: "GPT · Codex",
      installed: true,
      authenticated: true,
      authMethod: "chatgpt" as const,
      detail: "ready"
    };
  }

  async chat(request: ProviderChatRequest) {
    this.request = request;
    return {
      provider: this.id,
      text: "건축개요에서 대지면적 500㎡를 확인했습니다. [handle:11]",
      sessionId: "thread-1"
    };
  }
}

test("CAD context preserves schedule text, shapes, and stable evidence", () => {
  const context = buildCadContext(index);

  assert.match(context, /건축개요/);
  assert.match(context, /대지면적 500㎡/);
  assert.match(context, /handle=12 type=LWPOLYLINE/);
  assert.match(context, /bbox=\[0,0,0\]→\[100,100,0\]/);
});

test("CAD context retrieves a matching entity from beyond the display budget", () => {
  const filler = Array.from({ length: 201 }, (_, offset) => ({
    ...index.entities[0],
    id: `h:${1000 + offset}`,
    handle: String(1000 + offset),
    text: `일반 주석 ${offset}`
  }));
  const target = {
    ...index.entities[1],
    id: "h:TARGET",
    handle: "TARGET",
    text: "대지면적 500㎡"
  };
  const largeIndex: CadEntityIndex = {
    ...index,
    summary: {
      ...index.summary,
      entityCount: filler.length + 1
    },
    entities: [...filler, target]
  };

  const context = buildCadContext(largeIndex, "개요표의 대지면적을 알려줘");

  assert.match(context, /handle=TARGET/);
  assert.match(context, /text="대지면적 500㎡"/);
});

test("chat service sends a bounded real-index context to the selected provider", async () => {
  const provider = new CapturingProvider();
  const service = createChatService({
    providers: new Map([["codex", provider]]),
    loadActiveIndex: async () => index
  });

  const result = await service.chat({
    provider: "codex",
    drawingPath: "C:\\drawings\\schedule.dwg",
    message: "개요표 내용을 알려줘"
  });

  assert.equal(result.text.includes("[handle:11]"), true);
  assert.match(provider.request?.systemPrompt ?? "", /추측하지/);
  assert.match(provider.request?.context ?? "", /cad-index\/v0.1/);
});

test("chat service grounds against the active drawing instead of a stale browser path", async () => {
  const provider = new CapturingProvider();
  const service = createChatService({
    providers: new Map([["codex", provider]]),
    loadActiveIndex: async () => index
  });

  await service.chat({
    provider: "codex",
    drawingPath: "stale-session.dxf",
    message: "현재 도면을 설명해줘"
  });

  assert.match(provider.request?.context ?? "", /drawingId=drawing-1/);
});

test("chat service rejects unknown providers and unsupported paths", async () => {
  const service = createChatService({
    providers: new Map(),
    loadActiveIndex: async () => index
  });

  await assert.rejects(
    service.chat({
      provider: "unknown" as "codex",
      drawingPath: "drawing.dwg",
      message: "test"
    }),
    /Unknown provider/
  );
  await assert.rejects(
    service.chat({
      provider: "codex",
      drawingPath: "drawing.pdf",
      message: "test"
    }),
    /Unsupported drawing format/
  );
});
