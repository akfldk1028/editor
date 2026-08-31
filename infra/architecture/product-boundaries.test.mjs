import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const ROOT = resolve(import.meta.dirname, "../..");
const at = (...parts) => resolve(ROOT, ...parts);

const REQUIRED_DIRECTORIES = [
	["products", "plan", "frontend"],
	["products", "plan", "backend"],
	["products", "plan", "agents", "planm"],
	["products", "plan", "infra"],
	["products", "plan", "docs"],
	["products", "plan", "resources"],
	["products", "dwg"],
	["platform", "agent-runtimes", "gitagent"],
	["shared", "contracts", "plan-dwg"],
];

const LEGACY_DIRECTORIES = [
	["backend"],
	["frontend"],
	["resources"],
	["agents", "planm"],
	["agents", "dwg"],
	["agents", "runtimes"],
];

function sourceFiles(directory) {
	if (!existsSync(directory)) return [];
	const files = [];
	for (const entry of readdirSync(directory)) {
		if (["node_modules", "dist", "build", ".git"].includes(entry)) continue;
		const path = resolve(directory, entry);
		if (statSync(path).isDirectory()) files.push(...sourceFiles(path));
		else if (/\.(?:cjs|js|mjs|py|ts|tsx)$/.test(entry)) files.push(path);
	}
	return files;
}

function assertSourcesDoNotMatch(directory, expressions) {
	for (const file of sourceFiles(directory)) {
		const source = readFileSync(file, "utf8");
		for (const expression of expressions) {
			assert.doesNotMatch(source, expression, `${file} violates ${expression}`);
		}
	}
}

test("repository uses product-first canonical directories", () => {
	for (const parts of REQUIRED_DIRECTORIES) {
		assert.equal(existsSync(at(...parts)), true, `missing ${parts.join("/")}`);
	}
	for (const parts of LEGACY_DIRECTORIES) {
		assert.equal(existsSync(at(...parts)), false, `legacy path remains: ${parts.join("/")}`);
	}
});

test("products and platform do not deep-import one another", () => {
	for (const directory of [
		at("products", "plan", "backend", "app"),
		at("products", "plan", "frontend", "src"),
		at("products", "plan", "agents", "planm", "runtime"),
		at("products", "plan", "agents", "planm", "skills"),
	]) {
		assertSourcesDoNotMatch(directory, [
			/from\s+["'].*products[\\/]dwg/,
			/require\(["'].*products[\\/]dwg/,
			/from\s+["']@dwg\/(?!contracts["'])/,
		]);
	}
	for (const directory of [
		at("products", "dwg", "apps"),
		at("products", "dwg", "modules"),
		at("products", "dwg", "packages"),
	]) {
		assertSourcesDoNotMatch(directory, [
			/from\s+["'].*products[\\/]plan/,
			/\bbackend\.app\b/,
		]);
	}
	assertSourcesDoNotMatch(at("platform", "agent-runtimes", "gitagent", "src"), [
		/from\s+["'].*products[\\/]/,
	]);
});
