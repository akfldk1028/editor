import assert from "node:assert/strict";
import { test } from "node:test";

import { createCadToolRuntime } from "../../src/application/cad-tools/runtime.js";
import { createCadApplication } from "../../src/application/createCadApplication.js";
import {
  createInspectionOrchestrator,
  type OrchestrationCadRuntime
} from "../../src/orchestration/orchestrator.js";

test("runs a real layer inspection through named specialist agents", async () => {
  const application = await createCadApplication();
  const orchestrator = createInspectionOrchestrator(
    createCadToolRuntime(application.capabilities)
  );

  const run = await orchestrator.run({
    path: "tests/fixtures/dxf/minimal-architectural.dxf",
    checks: [{ kind: "layer", value: "A-WALL" }]
  });

  assert.deepEqual(
    run.events.map((event) => event.agentId),
    [
      "orchestrator",
      "drawing-index-agent",
      "drawing-index-agent",
      "search-agent",
      "evidence-agent",
      "orchestrator"
    ]
  );
  assert.equal(run.status, "completed");
  assert.equal(run.findings.length, 2);
  assert.deepEqual(run.issues, []);

  for (const finding of run.findings) {
    assert.ok(finding.id);
    assert.ok(finding.handle);
    assert.ok(finding.type);
    assert.ok(finding.layer);
    assert.ok(finding.bbox);
  }
});

test("limits independent search checks to three while preserving request order", async () => {
  let activeSearchCalls = 0;
  let peakActiveSearchCalls = 0;
  const completionOrder: string[] = [];
  const delays = new Map([
    ["cad.find_entities_by_layer:A-WALL", 30],
    ["cad.find_entities_by_type:LINE", 20],
    ["cad.find_text:ROOM", 10],
    ["cad.find_entities_by_layer:A-TEXT", 1]
  ]);

  const runtime: OrchestrationCadRuntime = {
    async call(name, args) {
      if (name === "cad.open_drawing") {
        return { drawingId: "drawing-1", warnings: [] };
      }
      if (name === "cad.build_index") {
        return { drawingId: "drawing-1" };
      }
      if (name === "cad.list_unsupported") {
        return { unsupported: [] };
      }

      activeSearchCalls += 1;
      peakActiveSearchCalls = Math.max(
        peakActiveSearchCalls,
        activeSearchCalls
      );
      const value = String(args.layer ?? args.type ?? args.query);
      const key = `${name}:${value}`;
      await new Promise((resolve) => setTimeout(resolve, delays.get(key) ?? 1));
      completionOrder.push(key);
      activeSearchCalls -= 1;

      return {
        matches: [
          {
            id: `id:${value}`,
            handle: `handle:${value}`,
            type: name === "cad.find_text" ? "TEXT" : "LINE",
            layer: value,
            bbox: { min: [0, 0, 0], max: [1, 1, 0] },
            reason: key,
            confidence: 1
          }
        ]
      };
    }
  };

  const run = await createInspectionOrchestrator(runtime).run({
    path: "fixture.dxf",
    checks: [
      { kind: "layer", value: "A-WALL" },
      { kind: "type", value: "LINE" },
      { kind: "text", value: "ROOM" },
      { kind: "layer", value: "A-TEXT" }
    ]
  });

  assert.equal(peakActiveSearchCalls, 3);
  assert.notDeepEqual(completionOrder, [
    "cad.find_entities_by_layer:A-WALL",
    "cad.find_entities_by_type:LINE",
    "cad.find_text:ROOM",
    "cad.find_entities_by_layer:A-TEXT"
  ]);
  assert.deepEqual(
    run.findings.map((finding) => finding.id),
    ["id:A-WALL", "id:LINE", "id:ROOM", "id:A-TEXT"]
  );
});

test("rejects the complete run when a specialist returns ungrounded evidence", async () => {
  const runtime: OrchestrationCadRuntime = {
    async call(name) {
      if (name === "cad.open_drawing") {
        return { drawingId: "drawing-1", warnings: [] };
      }
      if (name === "cad.build_index") {
        return { drawingId: "drawing-1" };
      }
      if (name === "cad.list_unsupported") {
        return { unsupported: [] };
      }
      return {
        matches: [
          {
            id: "h:10",
            handle: null,
            type: "LINE",
            layer: "A-WALL",
            bbox: null,
            reason: "invalid fixture",
            confidence: 0.5
          }
        ]
      };
    }
  };

  const run = await createInspectionOrchestrator(runtime).run({
    path: "fixture.dxf",
    checks: [{ kind: "layer", value: "A-WALL" }]
  });

  assert.equal(run.status, "rejected");
  assert.deepEqual(run.findings, []);
  assert.deepEqual(run.issues, [
    { entityId: "h:10", missing: ["handle", "bbox"] }
  ]);
  assert.deepEqual(run.events.at(-1), {
    sequence: 6,
    agentId: "orchestrator",
    action: "reject",
    status: "rejected"
  });
});
