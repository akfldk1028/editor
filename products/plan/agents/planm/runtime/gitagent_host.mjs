import { spawnSync } from "node:child_process";
import { realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const STAGE_SKILLS = new Map([
	["normalize", "normalize-plan-request"],
	["analyze", "analyze-building-mass"],
	["alternatives", "generate-plan-alternatives"],
	["review", "review-floorplan"],
	["deliver", "deliver-planm-package"],
]);
const WORKFLOW_NAME = "planm-delivery";

function fail(message) {
	throw new Error(`PLANM GitAgent host: ${message}`);
}

function requireEnvironment(name) {
	const value = process.env[name]?.trim();
	if (!value) fail(`missing ${name}`);
	return value;
}

function assertContained(path, root, label) {
	const child = relative(root, path);
	if (child === "" || (!child.startsWith("..") && !isAbsolute(child))) return;
	fail(`${label} escapes the PLANM agent directory`);
}

function parseArguments(argv) {
	const [stage, ...rest] = argv;
	if (!STAGE_SKILLS.has(stage)) fail(`unsupported stage: ${stage ?? "<missing>"}`);
	const requiredFlags = ["--input", "--state", "--output-dir"];
	for (const flag of requiredFlags) {
		const index = rest.indexOf(flag);
		if (index < 0 || !rest[index + 1] || rest[index + 1].startsWith("--")) {
			fail(`missing ${flag}`);
		}
	}
	return { stage, forwarded: rest };
}

async function main() {
	const { stage, forwarded } = parseArguments(process.argv.slice(2));
	const agentDir = await realpath(requireEnvironment("PLANM_AGENT_DIR"));
	const runtimeEntry = await realpath(
		requireEnvironment("PLANM_GITAGENT_RUNTIME_ENTRY"),
	);
	const runtime = await import(pathToFileURL(runtimeEntry).href);
	if (
		typeof runtime.loadAgentManifest !== "function" ||
		typeof runtime.discoverWorkflows !== "function" ||
		typeof runtime.discoverSkills !== "function"
	) {
		fail("runtime entry does not expose discovery APIs");
	}
	const manifest = await runtime.loadAgentManifest(agentDir);
	if (
		manifest?.name !== "planm" ||
		manifest?.metadata?.execution_mode !== "deterministic" ||
		!Number.isInteger(manifest?.runtime?.max_turns) ||
		manifest.runtime.max_turns < 1
	) {
		fail("agent manifest is invalid for deterministic PLANM execution");
	}

	const workflows = await runtime.discoverWorkflows(agentDir);
	const workflow = workflows.find((item) => item.name === WORKFLOW_NAME);
	if (!workflow) fail(`workflow not found: ${WORKFLOW_NAME}`);
	const flow = workflow.steps
		? workflow
		: await runtime.loadFlowDefinition(workflow.filePath);
	const expectedFlow = [...STAGE_SKILLS.values()];
	const actualFlow = (flow.steps ?? []).map((step) => step.skill);
	if (JSON.stringify(actualFlow) !== JSON.stringify(expectedFlow)) {
		fail(`workflow skill order is invalid: ${actualFlow.join(",")}`);
	}

	const skillName = STAGE_SKILLS.get(stage);
	const skills = await runtime.discoverSkills(agentDir);
	const skill = skills.find((item) => item.name === skillName);
	if (!skill) fail(`skill not found: ${skillName}`);
	const skillDir = await realpath(skill.directory);
	assertContained(skillDir, agentDir, "skill directory");
	const script = await realpath(resolve(skillDir, "scripts", "run.py"));
	assertContained(script, skillDir, "skill script");

	const completed = spawnSync(
		requireEnvironment("PLANM_PYTHON_EXECUTABLE"),
		[script, ...forwarded],
		{
			cwd: agentDir,
			env: process.env,
			stdio: ["ignore", "inherit", "inherit"],
			shell: false,
		},
	);
	if (completed.error) fail(completed.error.message);
	return completed.status ?? 1;
}

try {
	process.exitCode = await main();
} catch (error) {
	console.error(error instanceof Error ? error.message : String(error));
	process.exitCode = 4;
}
