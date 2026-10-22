// Read-only comparison of the registry with what the Orchestrator actually launches and
// routes to. A failure here is a finding for the Orchestrator session; nothing under
// agents/ or ops/ is edited from the editor.
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

import { agents, byId } from './registry.mjs';

const editorRoot = resolve(import.meta.dirname, '../..');
const aceRoot = resolve(editorRoot, '..');
const agentsRoot = process.env.ORCHESTRATOR_AGENT_DIR ? resolve(process.env.ORCHESTRATOR_AGENT_DIR, '..') : resolve(aceRoot, 'agents');
const orchestratorRoot = resolve(agentsRoot, 'OrchestratorAgent');
const launcherPath = resolve(orchestratorRoot, 'scripts/services/a2a.ps1');
const catalogRoot = resolve(orchestratorRoot, 'config');

/** The @{ ... } hashtables of a2a.ps1, keyed by Directory. */
function readLauncher() {
  const source = readFileSync(launcherPath, 'utf8');
  const entries = new Map();
  for (const [, block] of source.matchAll(/@\{([^}]*)\}/g)) {
    const entry = Object.fromEntries([...block.matchAll(/(\w+)\s*=\s*'([^']*)'/g)].map(([, key, value]) => [key, value]));
    const entrypoint = block.match(/Entrypoint\s*=\s*\(Join-Path \$agentsRoot '([^']+)'\)/);
    if (entrypoint) entry.Entrypoint = entrypoint[1];
    if (entry.Directory) entries.set(entry.Directory, entry);
  }
  return entries;
}

/** The port the owner's own start path declares (a2a-preflight.ps1 proves the same thing). */
function ownerPort(agent, launcher) {
  if (launcher.Arguments) return Number(launcher.Arguments.match(/--port (\d+)$/)[1]);
  const serve = readFileSync(resolve(agentsRoot, launcher.Directory, launcher.Serve), 'utf8');
  const inline = serve.match(/_A2A_PORT:-(\d+)\}/);
  if (inline) return Number(inline[1]);
  const envFile = readFileSync(resolve(agentsRoot, launcher.Directory, agent.start.env_file), 'utf8');
  return Number(envFile.match(/^[A-Z]+_A2A_PORT="(\d+)"/m)[1]);
}

const available = existsSync(launcherPath) && existsSync(catalogRoot);

test('(b) a2a.ps1 and the registry name the same agents, start them the same way, on the same ports', { skip: !available && 'agents checkout not beside editor' }, () => {
  const launcher = readLauncher();
  const registered = new Map(agents().map(agent => [agent.launcher.directory, agent]));
  assert.deepEqual([...registered.keys()].sort(), [...launcher.keys()].sort(), 'agent set differs');
  for (const [directory, entry] of launcher) {
    const agent = registered.get(directory);
    assert.deepEqual(
      { directory, catalog: entry.Catalog, name: entry.Name, skill: entry.Skill },
      agent.launcher, `${directory}: launcher keys`);
    assert.equal(agent.start.cwd, `agents/${directory}`, `${directory}: cwd`);
    if (entry.Serve) {
      // The host may add a mode for itself (MassAgent's `fg`: a script that backgrounds its server and exits read
      // as a crash to the supervisor); the script it runs is the launcher's.
      assert.deepEqual(agent.start.cmd.slice(0, 2), ['bash', entry.Serve], `${directory}: serve script`);
      assert.ok(agent.start.cmd.slice(2).every(arg => arg === 'fg'), `${directory}: serve mode`);
      if (entry.Config) assert.equal(agent.start.env_file, entry.Config, `${directory}: env file`);
    } else {
      const command = [entry.Entrypoint.replace(`${directory}/`, ''), ...entry.Arguments.replace(/--port \d+$/, '--port {port}').split(' ')];
      assert.deepEqual(agent.start.cmd, command, `${directory}: entrypoint`);
    }
    assert.equal(agent.port, ownerPort(agent, entry), `${directory}: port the owner starts on`);
  }
});

test('(c) every catalog *_agent.json routes to the registered port, and every registered agent has a catalog', { skip: !available && 'agents checkout not beside editor' }, () => {
  const catalogs = readdirSync(catalogRoot).filter(name => name.endsWith('_agent.json')).sort();
  assert.deepEqual(agents().map(agent => agent.launcher.catalog).sort(), catalogs, 'catalog set differs');
  for (const agent of agents()) {
    const catalog = JSON.parse(readFileSync(resolve(catalogRoot, agent.launcher.catalog), 'utf8'));
    const url = new URL(catalog.config.a2a_server_url);
    assert.equal(Number(url.port), agent.port, `${agent.id}: catalog ${agent.launcher.catalog} routes to ${url.port}`);
    assert.equal(catalog.name, agent.launcher.name, `${agent.id}: catalog name`);
  }
});

test('the Orchestrator editor API and Neo4j listen where the registry says', { skip: !available && 'agents checkout not beside editor' }, () => {
  const editorApi = readFileSync(resolve(orchestratorRoot, 'orchestrator/editor_api.py'), 'utf8');
  assert.equal(Number(editorApi.match(/'--port', type=int, default=(\d+)/)[1]), byId('orchestrator').port);
  const compose = resolve(aceRoot, byId('neo4j').start.cwd, 'compose.yml');
  if (!existsSync(compose)) return;
  assert.match(readFileSync(compose, 'utf8'), new RegExp(`127\\.0\\.0\\.1:${byId('neo4j').port}:${byId('neo4j').port}`));
});
