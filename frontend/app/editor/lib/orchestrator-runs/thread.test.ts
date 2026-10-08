import { expect, test } from 'bun:test'

import type { FeedEntry } from './feed'
import { leadOf, threadOf } from './thread'

let n = 0
const entry = (kind: FeedEntry['kind'], text: string, agent?: string, run_id?: string): FeedEntry => ({
  id: ++n, kind, text, at: 1000 + n, ...(agent ? { agent } : {}), ...(run_id ? { run_id } : {}),
})

test('user and system lines stay single; each agent speaks in its own turn; a prompt is its own turn', () => {
  const selected = entry('user', '대지 선택')
  const connected = entry('system', '연결됨', 'orchestrator')
  const started = entry('user', '검토 시작')
  const sending = entry('progress', '전달하는 중', 'orchestrator')
  const submitted = entry('system', '접수', 'orchestrator', 'r1')
  const siteRun = entry('progress', '대지 사실 확인: 진행 중', 'site_context', 'r1')
  const siteDone = entry('progress', '대지 사실 확인: 근거 부족', 'site_context', 'r1')
  const law = entry('progress', '법규 한계: 성공', 'law', 'r1')
  const lawNumbers = entry('progress', '법규 한계: 대지 …', 'law', 'r1')
  const revision = entry('progress', '재검토 판정: 근거 부족', 'revision', 'r1')
  const result = entry('result', '검토 결과: 보류', 'orchestrator', 'r1')
  const prompt = entry('prompt', '법규를 보시겠어요?', 'orchestrator', 'r1')
  const turns = threadOf([selected, connected, started, sending, submitted, siteRun, siteDone, law, lawNumbers, revision, result, prompt])
  expect(turns.map((turn) => (turn.kind === 'agent' ? `agent:${turn.agent}` : turn.kind))).toEqual([
    'user', 'system', 'user', 'agent:orchestrator', 'system', 'agent:site_context', 'agent:law', 'agent:revision', 'agent:orchestrator', 'prompt',
  ])
  const site = turns[5]
  if (site.kind !== 'agent') throw new Error('expected an agent turn')
  expect(site.steps.map((step) => step.text)).toEqual(['대지 사실 확인: 진행 중', '대지 사실 확인: 근거 부족'])
  expect(leadOf(site).text).toBe('대지 사실 확인: 근거 부족')
  const verdict = turns[8]
  if (verdict.kind !== 'agent') throw new Error('expected an agent turn')
  expect(verdict).toEqual({ kind: 'agent', id: result.id, at: result.at, agent: 'orchestrator', run_id: 'r1', steps: [result], error: false })
})

test('a line without an agent is the Orchestrator; a second run starts a new turn; an error marks and leads it', () => {
  const a = entry('progress', 'a', undefined, 'r1')
  const b = entry('progress', 'b', undefined, 'r2')
  const failed = entry('error', '검토 결과: 실패', 'orchestrator', 'r2')
  const turns = threadOf([a, b, failed])
  expect(turns).toHaveLength(2)
  const second = turns[1]
  if (second.kind !== 'agent') throw new Error('expected an agent turn')
  expect(second.agent).toBe('orchestrator')
  expect(second.steps.map((step) => step.text)).toEqual(['b', '검토 결과: 실패'])
  expect(second.error).toBe(true)
  expect(leadOf(second).text).toBe('검토 결과: 실패')
})
