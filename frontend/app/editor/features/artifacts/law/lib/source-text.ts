/** Add reading breaks at 항/호 markers without rewriting or shortening the source. */
export function sourceParagraphs(text: string): string[] {
  return text.replace(/\s*([①-⑳])/gu, '\n\n$1')
    .replace(/(?<![\d.])(?=\d{1,2}\.\s*[가-힣])/gu, '\n\n')
    .replace(/\n(?=[가-힣]\.\s)/gu, '\n\n')
    .split(/\n\s*\n/).map(part => part.trim()).filter(Boolean)
}

export function sourceUnit(text: string): 'paragraph' | 'item' | 'subitem' | 'body' {
  if (/^[①-⑳]/u.test(text)) return 'paragraph'
  if (/^\d{1,2}\.\s*/u.test(text)) return 'item'
  if (/^[가-힣]\.\s/u.test(text)) return 'subitem'
  return 'body'
}
