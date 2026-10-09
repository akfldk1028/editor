import type { ReviewRef } from './review'
import type { ReferenceText } from '../api/reference'

export function sourceLink(ref: ReviewRef, result?: ReferenceText): { url: string; label: string } {
  const verified = result?.url ?? ref.url
  if (verified) return { url: verified, label: '공식 원문' }
  const category = ref.kind === 'ordinance' ? '자치법규' : '법령'
  return {
    url: `https://www.law.go.kr/${category}/${encodeURIComponent(ref.instrument.replace(/\s/g, ''))}`,
    label: '공식 법령 페이지 · 현행',
  }
}
