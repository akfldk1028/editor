import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

import { validate } from './schema-check.mjs';
import {
  REGISTRY_PATH, SCHEMA_PATH, agents, baseUrl, byId, cardUrl, healthUrl, loadRegistry, persistent, services, startCommand,
} from './registry.mjs';
import { createServiceDefinitions } from '../dev/runtime.mjs';

const repositoryRoot = resolve(import.meta.dirname, '../..');
const schema = JSON.parse(readFileSync(SCHEMA_PATH, 'utf8'));

test('(a) services.json satisfies its schema, and the checker rejects a broken entry', () => {
  const document = loadRegistry();
  assert.ok(document.services.length >= 18, `expected 18+ entries, got ${document.services.length}`);
  const broken = structuredClone(document);
  broken.services[0].port = 'eighteen';
  broken.services[1].kind = 'daemon';
  delete broken.services[2].notes;
  broken.services[3].extra = true;
  const errors = validate(broken, schema);
  assert.equal(errors.length, 4, errors.join('\n'));
  assert.match(errors[0], /port.*expected integer\|null/);
  assert.match(errors[1], /kind.*not one of/);
  assert.match(errors[2], /missing required "notes"/);
  assert.match(errors[3], /unknown property "extra"/);
});

test('(e) ids and ports are unique, depends_on resolve, agents carry launcher keys', () => {
  const all = services();
  const ids = all.map(service => service.id);
  assert.equal(new Set(ids).size, ids.length, 'duplicate id');
  const ports = all.map(service => service.port).filter(port => port !== null);
  assert.equal(new Set(ports).size, ports.length, 'two services on one port');
  for (const service of all) {
    for (const dependency of service.depends_on) assert.ok(ids.includes(dependency), `${service.id} depends on unknown ${dependency}`);
    assert.notEqual(service.depends_on.includes(service.id), true, `${service.id} depends on itself`);
    assert.equal('launcher' in service, service.kind === 'agent', `${service.id}: launcher present iff kind=agent`);
    if (service.kind === 'agent') assert.equal(service.card_url, '{base}/.well-known/agent-card.json', service.id);
  }
  const launchers = agents().map(agent => agent.launcher.directory);
  assert.equal(new Set(launchers).size, launchers.length, 'two agents claim one directory');
});

test('(d) no module in infra/dev carries a port: they all ask the registry', () => {
  const directory = resolve(repositoryRoot, 'infra/dev');
  const modules = readdirSync(directory).filter(name => name.endsWith('.mjs') && !name.endsWith('.test.mjs'));
  assert.ok(modules.includes('runtime.mjs') && modules.includes('product.mjs'));
  const portLiteral = /(?<![\w.])\d{4,5}(?![\w.])/g;
  for (const name of modules) {
    const source = readFileSync(resolve(directory, name), 'utf8');
    const found = [...source.matchAll(portLiteral)].map(match => match[0]);
    assert.deepEqual(found, [], `${name} carries numeric literals ${found.join(', ')}; move them to infra/config/services.json`);
  }
});

test('(f) runtime.mjs definitions are the registry start commands and listen on registry ports', () => {
  const definitions = createServiceDefinitions(repositoryRoot, 'linux');
  for (const [id, definition] of Object.entries(definitions)) {
    const entry = byId(id);
    assert.ok(definition.healthUrl.startsWith(baseUrl(entry, {}) + '/'), `${id}: health URL off the registered port`);
    if (entry.management !== 'editor-session') {
      assert.equal(definition.command, undefined, `${id} is not started from the editor`);
      continue;
    }
    assert.deepEqual([definition.command, ...definition.args], startCommand(entry), `${id}: start command drifted`);
    assert.equal(definition.cwd, resolve(repositoryRoot, '..', entry.start.cwd), `${id}: cwd drifted`);
  }
});

test('helpers: env override wins over loopback; templates fill; persistence filters', () => {
  const law = byId('law');
  assert.equal(baseUrl(law, {}), 'http://127.0.0.1:8301');
  assert.equal(baseUrl(law, { LAW_A2A_URL: 'http://law.example:9000/' }), 'http://law.example:9000');
  assert.equal(healthUrl(law, {}), 'http://127.0.0.1:8301/health');
  assert.equal(cardUrl(law, { LAW_A2A_URL: 'http://law.example:9000' }), 'http://law.example:9000/.well-known/agent-card.json');
  assert.equal(healthUrl(byId('neo4j')), null);
  assert.deepEqual(startCommand(byId('masterplan')).slice(-2), ['--port', '18312']);
  assert.throws(() => byId('arr'), /Unknown service/);
  assert.ok(persistent().every(service => service.lifecycle === 'persistent'));
  assert.ok(persistent().some(service => service.id === 'orchestrator'));
  assert.equal(agents().length, 15);
  assert.ok(REGISTRY_PATH.endsWith('services.json'));
});
