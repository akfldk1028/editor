import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { discoverWorkflows } from "../../runtimes/gitagent/src/workflows.ts";


const planmDir = fileURLToPath(new URL("..", import.meta.url));


test("PLANM delivery flow uses the required skill order", async () => {
	const flows = await discoverWorkflows(planmDir);
	const flow = flows.find((item) => item.name === "planm-delivery");
	assert.equal(flow?.type, "flow");
	assert.deepEqual(
		flow?.steps?.map((step) => step.skill),
		[
			"normalize-plan-request",
			"analyze-building-mass",
			"generate-plan-alternatives",
			"review-floorplan",
			"deliver-planm-package",
		],
	);
	assert.ok(
		flow?.steps?.every((step) => step.prompt.includes("planm-state.json")),
	);
});
