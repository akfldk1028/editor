import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const host = fileURLToPath(new URL("../runtime/gitagent_host.mjs", import.meta.url));
const stages = [
	["normalize", "normalize-plan-request"],
	["analyze", "analyze-building-mass"],
	["alternatives", "generate-plan-alternatives"],
	["review", "review-floorplan"],
	["deliver", "deliver-planm-package"],
];

async function fixture({ escapeSkill = false } = {}) {
	const root = await mkdtemp(join(tmpdir(), "planm-host-"));
	const agent = join(root, "agent");
	const skill = escapeSkill ? join(root, "outside-skill") : join(agent, "skills", stages[0][1]);
	const evidence = join(root, "evidence.txt");
	await mkdir(agent, { recursive: true });
	await mkdir(join(skill, "scripts"), { recursive: true });
	await writeFile(
		join(skill, "scripts", "run.py"),
		`const fs=require("node:fs");fs.appendFileSync(process.env.EVIDENCE,"skill\\n");console.log(JSON.stringify({contract_version:"skill-result/v1",status:"success"}));`,
	);
	const runtime = join(root, "runtime.mjs");
	await writeFile(
		runtime,
		`import {appendFileSync} from "node:fs";
const steps=${JSON.stringify(stages.map(([, skillName]) => ({ skill: skillName })))};
export async function discoverWorkflows(){appendFileSync(process.env.EVIDENCE,"workflows\\n");return [{name:"planm-delivery",steps}]}
export async function discoverSkills(){appendFileSync(process.env.EVIDENCE,"skills\\n");return [{name:"normalize-plan-request",directory:${JSON.stringify(skill)}}]}
export async function loadFlowDefinition(){throw new Error("unexpected flow load")}`,
	);
	return { agent, evidence, root, runtime };
}

function runHost(paths) {
	return spawnSync(
		process.execPath,
		[host, "normalize", "--input", join(paths.root, "input.json"), "--state", join(paths.root, "state.json"), "--output-dir", paths.root],
		{
			encoding: "utf8",
			env: {
				...process.env,
				EVIDENCE: paths.evidence,
				PLANM_AGENT_DIR: paths.agent,
				PLANM_GITAGENT_RUNTIME_ENTRY: paths.runtime,
				PLANM_PYTHON_EXECUTABLE: process.execPath,
			},
		},
	);
}

test("discovers the PLANM workflow and skill before executing its script", async () => {
	const paths = await fixture();
	const completed = runHost(paths);

	assert.equal(completed.status, 0, completed.stderr);
	assert.equal(JSON.parse(completed.stdout).contract_version, "skill-result/v1");
	assert.equal(await import("node:fs/promises").then((fs) => fs.readFile(paths.evidence, "utf8")), "workflows\nskills\nskill\n");
});

test("rejects a discovered skill outside the PLANM agent directory", async () => {
	const paths = await fixture({ escapeSkill: true });
	const completed = runHost(paths);

	assert.equal(completed.status, 4);
	assert.match(completed.stderr, /escapes the PLANM agent directory/);
});
