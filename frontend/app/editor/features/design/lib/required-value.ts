/** Reject incomplete geometry/catalog entries before they reach WebGL or SVG. */
export function requiredValue<T>(value: T | undefined): T {
  if (value === undefined) throw new Error('설계 좌표 또는 카탈로그 항목이 누락됐습니다.')
  return value
}
