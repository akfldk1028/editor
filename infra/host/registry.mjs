// The service registry: infra/config/services.json read once, checked against its schema,
// and turned into URLs. Nothing else in the editor may carry a port; it asks here.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { validate } from './schema-check.mjs';

export const REGISTRY_PATH = fileURLToPath(new URL('../config/services.json', import.meta.url));
export const SCHEMA_PATH = fileURLToPath(new URL('../config/services.schema.json', import.meta.url));

const LOOPBACK = '127.0.0.1';
let cached = null;

/** Parse and validate a registry document; throws listing every schema violation. */
export function loadRegistry(path = REGISTRY_PATH, schemaPath = SCHEMA_PATH) {
  const schema = JSON.parse(readFileSync(schemaPath, 'utf8'));
  const document = JSON.parse(readFileSync(path, 'utf8'));
  const errors = validate(document, schema);
  if (errors.length) throw new Error(`services.json does not satisfy its schema:\n  ${errors.join('\n  ')}`);
  return document;
}

export function services() {
  cached ??= loadRegistry().services;
  return cached;
}

export function byId(id) {
  const entry = services().find(service => service.id === id);
  if (!entry) throw new Error(`Unknown service "${id}" (not in infra/config/services.json)`);
  return entry;
}

export function persistent() {
  return services().filter(service => service.lifecycle === 'persistent');
}

export function agents() {
  return services().filter(service => service.kind === 'agent');
}

/** The env override named by host_env wins; otherwise loopback on the registered port. */
export function baseUrl(entry, env = process.env) {
  const override = entry.host_env ? env[entry.host_env] : undefined;
  if (override) return override.replace(/\/$/, '');
  if (entry.port === null) throw new Error(`Service "${entry.id}" has no port and ${entry.host_env ?? 'no env override'} is unset`);
  return `http://${LOOPBACK}:${entry.port}`;
}

function fill(template, entry, env) {
  return template === null ? null : template.replace('{base}', baseUrl(entry, env));
}

export function healthUrl(entry, env = process.env) {
  return fill(entry.health_url, entry, env);
}

export function cardUrl(entry, env = process.env) {
  return fill(entry.card_url, entry, env);
}

/** The owner's start command with {port} filled in; null for services nobody starts from here. */
export function startCommand(entry) {
  if (!entry.start) return null;
  return entry.start.cmd.map(part => part.replace('{port}', String(entry.port)));
}
