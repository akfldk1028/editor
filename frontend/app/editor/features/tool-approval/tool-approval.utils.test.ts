import { describe, it, expect } from 'bun:test'
import { parseToolApproval, classifyToolIcon } from './tool-approval.utils'

describe('classifyToolIcon', () => {
  it('maps read-like tools', () => {
    expect(classifyToolIcon('read_file')).toBe('read')
    expect(classifyToolIcon('ReadFile')).toBe('read')
    expect(classifyToolIcon('list_files')).toBe('read')
  })

  it('maps edit-like tools', () => {
    expect(classifyToolIcon('write_file')).toBe('edit')
    expect(classifyToolIcon('edit_file')).toBe('edit')
    expect(classifyToolIcon('create_file')).toBe('edit')
  })

  it('maps execute-like tools', () => {
    expect(classifyToolIcon('execute_code')).toBe('execute')
    expect(classifyToolIcon('bash')).toBe('execute')
    expect(classifyToolIcon('python')).toBe('execute')
  })

  it('maps fetch-like tools', () => {
    expect(classifyToolIcon('web_search')).toBe('fetch')
    expect(classifyToolIcon('http')).toBe('fetch')
  })

  it('returns generic for unknown tools', () => {
    expect(classifyToolIcon('unknown_tool')).toBe('generic')
    expect(classifyToolIcon('custom')).toBe('generic')
  })
})

describe('parseToolApproval', () => {
  it('parses "Tool call: toolName(args)" format', () => {
    const result = parseToolApproval('Tool call: read_file({"path": "/tmp/foo.txt"})', 'agent_1')
    expect(result).not.toBeNull()
    expect(result!.toolName).toBe('read_file')
    expect(result!.args).toContain('/tmp/foo.txt')
    expect(result!.source).toBe('agent_1')
    expect(result!.status).toBe('pending')
    expect(result!.icon).toBe('read')
  })

  it('parses "Execute tool_name" format', () => {
    const result = parseToolApproval('Execute bash', 'coder')
    expect(result).not.toBeNull()
    expect(result!.toolName).toBe('bash')
    expect(result!.icon).toBe('execute')
  })

  it('returns null for non-tool prompts', () => {
    expect(parseToolApproval('Please enter your name', 'agent')).toBeNull()
    expect(parseToolApproval('What should I do next?', 'agent')).toBeNull()
  })

  it('generates unique IDs', () => {
    const a = parseToolApproval('Approve: read_file(a)', 'x')
    const b = parseToolApproval('Approve: read_file(b)', 'x')
    expect(a!.id).not.toBe(b!.id)
  })
})
