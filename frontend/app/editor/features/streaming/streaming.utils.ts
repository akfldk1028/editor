import { THINK_TAG_REGEX, ORPHANED_THINK_OPEN } from './streaming.constants'

/**
 * Strip <think>...</think> tags from LLM streaming content.
 * Handles both complete pairs and orphaned opening tags (mid-stream).
 */
export function stripThinkTags(content: string): string {
  // Remove complete <think>...</think> pairs
  let cleaned = content.replace(THINK_TAG_REGEX, '')
  // Remove orphaned <think> at end of stream (tag opened but not yet closed)
  cleaned = cleaned.replace(ORPHANED_THINK_OPEN, '')
  return cleaned.trim()
}
