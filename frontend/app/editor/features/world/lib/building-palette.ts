const diagnosticHeightColors = typeof location !== 'undefined'
  && new URLSearchParams(location.search).get('buildingHeightColors') === '1'

export function buildingColor(status: string, diagnostics = diagnosticHeightColors) {
  return diagnostics && status === 'u' ? '#c7c7c2' : '#fbfbf9'
}
