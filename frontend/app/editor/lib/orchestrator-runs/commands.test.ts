import { beforeEach, expect, test } from 'bun:test'

import { type Command, onCommand, resetCommands, sendCommand } from './commands'

const start: Command = { kind: 'start-review', goal: 'limits' }

beforeEach(resetCommands)

test('a command reaches every listener and reports delivery', () => {
  const got: Command[] = []
  const off = onCommand((command) => got.push(command))
  onCommand((command) => got.push(command))
  expect(sendCommand(start)).toBe(true)
  expect(got).toEqual([start, start])
  off()
  expect(sendCommand(start)).toBe(true)
  expect(got).toHaveLength(3)
})

test('a command sent with no listener waits for the next one, once', () => {
  expect(sendCommand(start)).toBe(false)
  const got: Command[] = []
  onCommand((command) => got.push(command))
  expect(got).toEqual([start])
  onCommand((command) => got.push(command))
  expect(got).toEqual([start])
})
