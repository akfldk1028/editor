'use client'

import { useMemo, useState } from 'react'

import { fullHopText } from '@/lib/ledger'
import { agentLabel } from '@/lib/orchestrator-runs/labels'

import { agentTaskReader, readAgentTask } from '../api/tasks'
import { describeMessage } from '../lib/describe'
import { fullRecordFor } from '../lib/tasks'
import type { CollaborationMessage, Transcript as TranscriptRecord } from '../lib/transcript'

interface Props {
  transcript: TranscriptRecord
  selected: string | null
  onSelect: (agent: string | null) => void
  /** Labels for agents the conversation's folders do not know. */
  names?: Readonly<Record<string, string>>
}

/** What the agent's own record gave for a cut reply: the full message, or why there is none. */
type Full = { kind: 'loading' } | { kind: 'found'; message: CollaborationMessage } | { kind: 'missing' } | { kind: 'error'; text: string }

/** The record as a chat: requests on the left, answers on the right, each in the user's words with the recorded text one click away; a cut reply can be completed from the agent's own record (A2A ListTasks). */
export function Transcript({ transcript, selected, onSelect, names = {} }: Props) {
  const label = (id: string) => names[id] ?? agentLabel(id)
  const shown = selected ? transcript.messages.filter((message) => message.from === selected || message.to === selected) : transcript.messages
  const readTasks = useMemo(() => agentTaskReader(), [])
  const [full, setFull] = useState<Record<string, Full>>({})

  const complete = async (message: CollaborationMessage) => {
    setFull((current) => ({ ...current, [message.id]: { kind: 'loading' } }))
    try {
      // A ledger call the list cut is read whole from the ledger, which keeps it.
      const whole = await fullHopText(message.id)
      if (whole !== null) {
        setFull((current) => ({ ...current, [message.id]: { kind: 'found', message: { ...message, text: whole, truncated: false } } }))
        return
      }
      // The recorded A2A task id is the exact key; without one, the agent's list is matched by the recorded text.
      const task = message.a2a_task_id ? await readAgentTask(message.from, message.a2a_task_id) : fullRecordFor(message, await readTasks(message.from))
      setFull((current) => ({ ...current, [message.id]: task ? { kind: 'found', message: { ...message, text: task.response_text, truncated: false } } : { kind: 'missing' } }))
    } catch (error) {
      setFull((current) => ({ ...current, [message.id]: { kind: 'error', text: error instanceof Error ? error.message : '에이전트에 닿지 못했어요' } }))
    }
  }

  return (
    <>
      {transcript.participants.length > 1 && (
        <div aria-label="참여자" className="collab-filter" role="group">
          <button aria-pressed={selected === null} onClick={() => onSelect(null)} type="button">전체</button>
          {transcript.participants.map((id) => <button aria-pressed={selected === id} key={id} onClick={() => onSelect(selected === id ? null : id)} type="button">{label(id)}</button>)}
        </div>
      )}
      {!transcript.available && <p className="collab-note">이 실행의 대화 기록을 제공받지 못했어요.</p>}
      {transcript.truncated && <p className="collab-note">일부 긴 답은 오케스트레이터 기록에 8,000자까지만 남아 있어요. 에이전트가 아직 보관 중이면 전체를 가져올 수 있어요.</p>}
      {shown.length === 0
        ? <p className="collab-note">아직 주고받은 요청·응답이 없어요.</p>
        : (
          <ol className="collab-log">
            {shown.map((message) => {
              const state = full[message.id]
              const described = describeMessage(state?.kind === 'found' ? state.message : message, names)
              return (
                <li data-direction={message.direction} key={message.id}>
                  <header><span>{described.headline}</span><small>#{message.step}{state?.kind === 'found' ? ' · 에이전트 기록 전체' : ''}</small></header>
                  {described.lines.length > 0 && <ul>{described.lines.map((line, index) => <li key={index}>{line}</li>)}</ul>}
                  {message.truncated && message.direction === 'response' && (!state || state.kind === 'error') && (
                    <p className="collab-note">
                      <button className="collab-link" onClick={() => void complete(message)} type="button">{label(message.from)}의 기록에서 전체 보기</button>
                      {state?.kind === 'error' && <span> · {state.text}</span>}
                    </p>
                  )}
                  {state?.kind === 'loading' && <p className="collab-note"><span aria-hidden="true" className="loading-mark" /> {label(message.from)}에게 묻는 중</p>}
                  {state?.kind === 'missing' && <p className="collab-note">{label(message.from)}이(가) 이 답을 더는 보관하지 않아요 — 그 뒤에 다시 시작됐어요</p>}
                  {described.raw && <details><summary>기록 원문{state?.kind === 'found' ? ' (전체)' : ''}</summary><pre>{described.raw}</pre></details>}
                </li>
              )
            })}
          </ol>
        )}
    </>
  )
}
