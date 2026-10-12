'use client'

import { agentLabel } from '@/lib/orchestrator-runs/labels'

import { describeMessage } from '../lib/describe'
import type { Transcript as TranscriptRecord } from '../lib/transcript'

interface Props {
  transcript: TranscriptRecord
  selected: string | null
  onSelect: (agent: string | null) => void
  /** Labels for agents the conversation's folders do not know. */
  names?: Readonly<Record<string, string>>
}

/** The record as a chat: requests on the left, answers on the right, each in the user's words with the recorded text one click away. */
export function Transcript({ transcript, selected, onSelect, names = {} }: Props) {
  const label = (id: string) => names[id] ?? agentLabel(id)
  const shown = selected ? transcript.messages.filter((message) => message.from === selected || message.to === selected) : transcript.messages
  return (
    <>
      {transcript.participants.length > 1 && (
        <div aria-label="참여자" className="collab-filter" role="group">
          <button aria-pressed={selected === null} onClick={() => onSelect(null)} type="button">전체</button>
          {transcript.participants.map((id) => <button aria-pressed={selected === id} key={id} onClick={() => onSelect(selected === id ? null : id)} type="button">{label(id)}</button>)}
        </div>
      )}
      {!transcript.available && <p className="collab-note">이 실행의 대화 기록을 제공받지 못했어요.</p>}
      {transcript.truncated && <p className="collab-note">일부 긴 답은 8,000자까지만 남아 있어요.</p>}
      {shown.length === 0
        ? <p className="collab-note">아직 주고받은 요청·응답이 없어요.</p>
        : (
          <ol className="collab-log">
            {shown.map((message) => {
              const described = describeMessage(message, names)
              return (
                <li data-direction={message.direction} key={message.id}>
                  <header><span>{described.headline}</span><small>#{message.step}</small></header>
                  {described.lines.length > 0 && <ul>{described.lines.map((line, index) => <li key={index}>{line}</li>)}</ul>}
                  {described.raw && <details><summary>기록 원문</summary><pre>{described.raw}</pre></details>}
                </li>
              )
            })}
          </ol>
        )}
    </>
  )
}
