import type { ToolIcon } from './tool-approval.types'

export const TOOL_ICON_MAP: Record<string, ToolIcon> = {
  // File read operations
  read_file: 'read',
  read: 'read',
  get_file: 'read',
  list_files: 'read',
  search: 'read',
  // File write / edit operations
  write_file: 'edit',
  write: 'edit',
  edit_file: 'edit',
  create_file: 'edit',
  delete_file: 'edit',
  // Code execution
  execute: 'execute',
  run: 'execute',
  bash: 'execute',
  shell: 'execute',
  python: 'execute',
  execute_code: 'execute',
  // Network / fetch
  fetch: 'fetch',
  http: 'fetch',
  request: 'fetch',
  web_search: 'fetch',
  browse: 'fetch',
}

export const APPROVAL_OPTIONS = {
  APPROVE_ONCE: 'approve_once',
  APPROVE_ALWAYS: 'approve_always',
  REJECT: 'reject',
} as const

// Regex to detect tool approval prompts from AutoGen input_request
// Matches patterns like: "Tool call: tool_name({...})" or "Execute tool_name?"
export const TOOL_APPROVAL_PATTERN = /(?:tool\s*call|execute|run|approve)\s*:?\s*(\w+)\s*\(?([\s\S]*?)\)?$/i
