// A small JSON Schema checker for infra/config/services.schema.json: node built-ins only.
// It understands exactly the keywords that schema uses and refuses any other one, so the
// schema can never promise more than this file verifies.

const ANNOTATIONS = new Set(['$schema', '$id', 'title', 'description']);
const KEYWORDS = new Set([
  'type', 'enum', 'required', 'properties', 'additionalProperties', 'items',
  'minItems', 'pattern', 'minimum', 'maximum',
]);

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
  return typeof value;
}

function matchesType(value, declared) {
  const actual = typeOf(value);
  return [declared].flat().some(type => type === actual || (type === 'number' && actual === 'integer'));
}

/** Returns a list of "path: message" strings; empty when the value satisfies the schema. */
export function validate(value, schema, path = '$') {
  const errors = [];
  for (const keyword of Object.keys(schema)) {
    if (!KEYWORDS.has(keyword) && !ANNOTATIONS.has(keyword)) throw new Error(`unsupported schema keyword "${keyword}" at ${path}`);
  }
  if (schema.type !== undefined && !matchesType(value, schema.type)) {
    return [`${path}: expected ${[schema.type].flat().join('|')}, got ${typeOf(value)}`];
  }
  if (schema.enum !== undefined && !schema.enum.includes(value)) {
    errors.push(`${path}: ${JSON.stringify(value)} is not one of ${JSON.stringify(schema.enum)}`);
  }
  if (typeof value === 'string' && schema.pattern !== undefined && !new RegExp(schema.pattern).test(value)) {
    errors.push(`${path}: ${JSON.stringify(value)} does not match /${schema.pattern}/`);
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path}: ${value} < ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path}: ${value} > ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) errors.push(`${path}: fewer than ${schema.minItems} items`);
    if (schema.items !== undefined) value.forEach((item, index) => errors.push(...validate(item, schema.items, `${path}[${index}]`)));
  }
  if (typeOf(value) === 'object') {
    for (const key of schema.required ?? []) {
      if (!(key in value)) errors.push(`${path}: missing required "${key}"`);
    }
    const properties = schema.properties ?? {};
    for (const [key, child] of Object.entries(value)) {
      if (key in properties) errors.push(...validate(child, properties[key], `${path}.${key}`));
      else if (schema.additionalProperties === false) errors.push(`${path}: unknown property "${key}"`);
    }
  }
  return errors;
}
