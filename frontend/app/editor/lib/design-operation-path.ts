const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
const slug = '[A-Za-z0-9_-]+'
const archiveRun = '[A-Za-z0-9][A-Za-z0-9._-]*'
const candidate = '[A-Za-z0-9][A-Za-z0-9._:+-]*'
const asset = '[\\p{L}\\p{N}_. +()-]+(?:/[\\p{L}\\p{N}_. +()-]+)*'
const readPaths = new RegExp(`^(?:jobs/${uuid}(?:/(?:stream|results(?:/\\d+(?:/evidence)?)?))?|maas/(?:language-system|outcome-graph|(?:executed-masses|geometry-shapes)(?:/\\d+(?:/passport)?)?|(?:creative-portfolios|portfolio-evaluations)(?:/${archiveRun}/candidates/${candidate}/render)?|book-assets/\\d+|single-executions/${slug}/(?:preview|thumbnail|manifest|passport|elevation/${slug}|elevation-proposals/alt-01|elevation-proposals/multi-view-alt-01/(?:evidence/)?${slug})|(?:reference-assets|aesthetic-assets)/${asset})|collaboration/(?:health|bus/log|transcript))$`, 'u')
const writePaths = new RegExp(`^(?:site-boundary|auto-constraints|floor-plan|program-floor-plans|masterplan/operations|constraints/visualize|jobs(?:/${uuid}/(?:run|cancel|validate|results/\\d+/aesthetic))?|interactive/(?:patch|preview|operation)|maas/(?:revision(?:/${uuid}/feedback)?|export-scad|delivered-mass-export|legal-variants|single-executions(?:/${slug}/vlm-review)?)|collaboration/bus/send)$`)

export function isDesignOperation(method: string, path: string): boolean {
  if (path.split('/').some((part) => part === '.' || part === '..')) return false
  return method === 'GET' ? readPaths.test(path) : method === 'POST' && writePaths.test(path)
}
