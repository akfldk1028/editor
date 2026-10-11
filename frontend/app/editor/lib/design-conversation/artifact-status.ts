interface ArtifactStatus { label: string; tone: 'neutral' | 'attention' | 'confirmed' }
const STATUSES: Record<string, ArtifactStatus> = {
  proposed: { label: '제안', tone: 'neutral' },
  proposal: { label: '제안', tone: 'neutral' },
  draft: { label: '초안', tone: 'neutral' },
  stale: { label: '이전 조건 기준', tone: 'attention' },
  needs_evidence: { label: '근거 보완 필요', tone: 'attention' },
  confirmed: { label: '확인됨', tone: 'confirmed' },
  awaiting_confirmation: { label: '확인 대기', tone: 'attention' },
  valid: { label: '현재 조건에 유효', tone: 'confirmed' },
  ready: { label: '준비됨', tone: 'neutral' },
  accepted: { label: '반영됨', tone: 'confirmed' },
  invalid: { label: '재검토 필요', tone: 'attention' },
  superseded: { label: '새 결과로 대체됨', tone: 'neutral' },
}

export const artifactStatus = (status: string): ArtifactStatus => STATUSES[status] ?? { label: '상태 미확인', tone: 'neutral' }
