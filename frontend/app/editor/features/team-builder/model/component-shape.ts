export function assertTeamShape(value: unknown): void {
  check(value, ['team'], 0)
}

function check(value: unknown, kinds: string[], depth: number): void {
  if (!value || typeof value !== 'object' || Array.isArray(value) || depth > 32)
    throw new Error('Invalid component object or nesting depth')
  const component = value as Record<string, unknown>
  if (
    !kinds.includes(String(component.component_type)) ||
    typeof component.provider !== 'string' ||
    !component.provider.trim()
  )
    throw new Error('Component type and provider are required')
  for (const key of ['label', 'description']) {
    if (component[key] != null && typeof component[key] !== 'string')
      throw new Error(`${key} must be text`)
  }
  if (!component.config || typeof component.config !== 'object' || Array.isArray(component.config))
    throw new Error('Component config must be an object')
  const config = component.config as Record<string, unknown>
  if (config.name != null && typeof config.name !== 'string')
    throw new Error('Component name must be text')
  for (const [key, types] of [
    ['participants', ['agent', 'team']],
    ['tools', ['tool']],
    ['conditions', ['termination']],
  ] as const) {
    if (!(key in config)) continue
    const children = config[key]
    if (!Array.isArray(children)) throw new Error(`${key} must be a list`)
    for (const child of children) check(child, [...types], depth + 1)
  }
  for (const [key, types] of [
    ['model_client', ['model']],
    ['termination_condition', ['termination']],
  ] as const) {
    if (config[key] != null) check(config[key], [...types], depth + 1)
  }
}
