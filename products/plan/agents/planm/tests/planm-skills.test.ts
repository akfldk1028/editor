import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { discoverSkills, loadSkill } from "../../../../../platform/agent-runtimes/gitagent/src/skills.ts";


const planmDir = fileURLToPath(new URL("..", import.meta.url));


test("PLANM exposes the executable vertical-slice skills", async () => {
	const skills = await discoverSkills(planmDir);
	assert.deepEqual(
		skills.map((skill) => skill.name),
		[
			"analyze-building-mass",
			"deliver-planm-package",
			"generate-plan-alternatives",
			"normalize-plan-request",
			"review-floorplan",
		],
	);
	assert.ok(skills.every((skill) => skill.description.includes("PLANM")));
	for (const skill of skills) {
		const parsed = await loadSkill(skill);
		assert.equal(parsed.hasScripts, true);
		assert.match(parsed.instructions, /planm-state\.json/);
	}
});
