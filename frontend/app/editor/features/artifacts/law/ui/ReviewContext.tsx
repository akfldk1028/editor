'use client'

import type { ReviewItem } from '../lib/review'

/** What the review says about the selected item: why the lot meets it and on what basis. Questions belong to the conversation panel. */
export function ReviewContext({ item }: { item: ReviewItem }) {
  return <div className="law-reader-context">
    <section><h2>관련 내용</h2>{item.value && <p>검토 기준값 <strong>{item.value}</strong></p>}<p>{item.reason}</p></section>
    <section><h2>판단 근거</h2><p>{item.basis || '판단 근거 확보 필요'}</p></section>
  </div>
}
