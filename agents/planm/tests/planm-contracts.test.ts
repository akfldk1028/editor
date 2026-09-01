import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

async function readJson(relativePath: string): Promise<Record<string, any>> {
	return JSON.parse(
		await readFile(new URL(relativePath, import.meta.url), "utf8"),
	) as Record<string, any>;
}

test("PLANM contracts expose stable status and artifact boundaries", async () => {
	const result = await readJson(
		"../contracts/skill-result.schema.json",
	);
	assert.deepEqual(result.properties.status.enum, [
		"success",
		"needs_input",
		"retryable",
		"blocked",
	]);
	assert.deepEqual(result.required, [
		"contract_version",
		"skill_name",
		"status",
		"outputs",
		"violations",
		"artifacts",
		"provenance",
	]);
	assert.deepEqual(result.$defs.artifact.required, [
		"path",
		"media_type",
		"sha256",
		"size_bytes",
	]);
});

test("PLANM state contract preserves bounded workflow evidence", async () => {
	const state = await readJson(
		"../contracts/planm-state.schema.json",
	);
	assert.equal(state.properties.contract_version.const, "planm-state/v1");
	assert.ok(state.required.includes("attempts"));
	assert.ok(state.required.includes("unresolved_facts"));
	assert.ok(state.required.includes("accepted_alternative_ids"));
});

test("PLANM stage requests cross the process boundary as versioned JSON", async () => {
	const request = await readJson("../contracts/planm-stage-request.schema.json");
	assert.equal(request.properties.contract_version.const, "planm-stage-request/v1");
	assert.deepEqual(request.required, [
		"contract_version",
		"stage",
		"input_path",
		"state_path",
		"output_dir",
	]);
});

test("PLANM agent manifest identifies a non-coding product agent", async () => {
	const manifest = await readFile(
		new URL("../agent.yaml", import.meta.url),
		"utf8",
	);
	assert.match(manifest, /^spec_version: "0\.1\.0"/m);
	assert.match(manifest, /^name: planm$/m);
	assert.match(manifest, /^\s+max_turns: 40$/m);
});
