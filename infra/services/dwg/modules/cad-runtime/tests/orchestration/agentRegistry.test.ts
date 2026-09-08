import assert from "node:assert/strict";
import { test } from "node:test";

import {
  getAgentManifest,
  listAgentManifests
} from "../../src/orchestration/agentRegistry.js";

const EXPECTED_AGENT_IDS = [
  "orchestrator",
  "drawing-index-agent",
  "search-agent",
  "rule-check-agent",
  "evidence-agent",
  "viewer-agent",
  "report-agent"
] as const;

test("declares every specialist with a unique inspectable identity", () => {
  const agents = listAgentManifests();

  assert.deepEqual(
    agents.map((agent) => agent.id),
    EXPECTED_AGENT_IDS
  );
  assert.equal(new Set(agents.map((agent) => agent.id)).size, agents.length);

  for (const agent of agents) {
    assert.ok(agent.displayName);
    assert.ok(agent.purpose);
    assert.ok(agent.inputKinds.length > 0);
    assert.ok(agent.outputKinds.length > 0);
    assert.ok(agent.maxConcurrency >= 1 && agent.maxConcurrency <= 3);
  }
});

test("allows only the orchestrator to delegate one bounded layer", () => {
  const agents = listAgentManifests();

  assert.equal(getAgentManifest("orchestrator").canDelegate, true);
  assert.ok(
    agents
      .filter((agent) => agent.id !== "orchestrator")
      .every((agent) => agent.canDelegate === false)
  );
});

test("distinguishes active deterministic roles from planned dependencies", () => {
  assert.equal(getAgentManifest("orchestrator").readiness, "active");
  assert.equal(getAgentManifest("drawing-index-agent").readiness, "active");
  assert.equal(getAgentManifest("search-agent").readiness, "active");
  assert.equal(getAgentManifest("evidence-agent").readiness, "active");
  assert.equal(getAgentManifest("rule-check-agent").readiness, "planned");
  assert.equal(getAgentManifest("viewer-agent").readiness, "planned");
  assert.equal(getAgentManifest("report-agent").readiness, "planned");
  assert.equal(getAgentManifest("evidence-agent").execution, "deterministic");
});

test("bounds every active specialist to its exact CAD tool set", () => {
  assert.deepEqual(getAgentManifest("orchestrator").allowedTools, []);
  assert.deepEqual(getAgentManifest("drawing-index-agent").allowedTools, [
    "cad.open_drawing",
    "cad.build_index",
    "cad.list_unsupported"
  ]);
  assert.deepEqual(getAgentManifest("search-agent").allowedTools, [
    "cad.get_layers",
    "cad.find_entities_by_layer",
    "cad.find_entities_by_type",
    "cad.find_text",
    "cad.get_entity"
  ]);

  for (const id of [
    "rule-check-agent",
    "evidence-agent",
    "viewer-agent",
    "report-agent"
  ] as const) {
    assert.deepEqual(getAgentManifest(id).allowedTools, []);
  }
});
