import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const runtimeSrc = fileURLToPath(
	new URL("../../../external/gitagent-runtime/src/", import.meta.url),
);

async function sourceFiles(directory: string): Promise<string[]> {
	const entries = await readdir(directory, { withFileTypes: true });
	const files = await Promise.all(
		entries.map((entry) => {
			const path = join(directory, entry.name);
			return entry.isDirectory() ? sourceFiles(path) : [path];
		}),
	);
	return files.flat().filter((path) => path.endsWith(".ts"));
}

test("generic runtime does not depend on PLANM or DWG product code", async () => {
	const violations: string[] = [];
	for (const path of await sourceFiles(runtimeSrc)) {
		const source = await readFile(path, "utf8");
		if (/backend\.app|agents[\\/]planm|dwg-intelligence/i.test(source)) {
			violations.push(path.slice(dirname(runtimeSrc).length + 1));
		}
	}
	assert.deepEqual(violations, []);
});

test("Backend launches the PLANM GitAgent host instead of the bridge directly", async () => {
	const adapter = await readFile(
		new URL("../../../backend/app/adapters/planm_agent.py", import.meta.url),
		"utf8",
	);
	assert.match(adapter, /gitagent_host\.mjs/);
	assert.doesNotMatch(adapter, /runtime["']\s*\/\s*["']planm_bridge\.py/);
});
