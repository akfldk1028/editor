/** Truncate error messages for UI display */
export function truncateError(msg: string, max = 200): string {
  return msg.length > max ? msg.slice(0, max) + '...' : msg
}
