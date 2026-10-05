/** Distance from bottom (px) to keep auto-scroll active */
export const SCROLL_THRESHOLD = 150

/** Regex to match <think>...</think> blocks (including orphaned tags) */
export const THINK_TAG_REGEX = /<think>[\s\S]*?<\/think>/g
export const ORPHANED_THINK_OPEN = /<think>[\s\S]*$/
export const ORPHANED_THINK_CLOSE = /^[\s\S]*?<\/think>/
