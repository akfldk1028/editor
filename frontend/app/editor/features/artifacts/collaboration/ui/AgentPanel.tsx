'use client'

import { Send, X } from 'lucide-react'
import { type FormEvent, useState } from 'react'

import { agentSpec, markOf, ORCHESTRATOR } from '@/lib/agents'
import { sendCommand } from '@/lib/orchestrator-runs/commands'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import type { Transcript as TranscriptRecord } from '../lib/transcript'
import { Transcript } from './Transcript'

interface Props {
  agent: string
  transcript: TranscriptRecord | null
  onClose: () => void
}

/**
 * One agent, picked on the canvas: who it is, what it answers, what it said in this run, and a line to
 * ask it something — the question goes through the conversation (the Orchestrator's ask door, with this
 * agent as the role), so the answer lands in the chat on the left.
 */
export function AgentPanel({ agent, transcript, onClose }: Props) {
  const [text, setText] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const spec = agentSpec(agent)
  const Icon = markOf(agent).icon
  const tools = Object.keys(spec?.tools ?? {}).map((tool) => toolLabel(tool))
  const hub = agent === ORCHESTRATOR
  const said = transcript ? transcript.messages.filter((message) => message.from === agent || message.to === agent).length : 0

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const question = text.trim()
    if (!question) return
    // The Orchestrator routes a plain question itself; another agent is asked as that role.
    const delivered = hub ? sendCommand({ kind: 'compose', draft: question }) : sendCommand({ kind: 'ask', text: question, role: agent })
    setSent(delivered ? (hub ? '대화 입력창에 넣었어요 — 보내기를 누르면 오케스트레이터가 답해요' : `${agentLabel(agent)}에게 물었어요 — 답은 왼쪽 대화에 와요`) : '대화 패널이 아직 열리지 않았어요')
    setText('')
  }

  return (
    <section aria-label={`${agentLabel(agent)} 자세히`} className="collab-agent">
      <header>
        <Icon aria-hidden="true" size={16} />
        <h3>{agentLabel(agent)}</h3>
        <small>{hub ? '요청을 나누고 답을 모읍니다' : tools.length ? `할 수 있는 일: ${tools.join(' · ')}` : '이 실행에서는 역할이 없었어요'}</small>
        <button aria-label="닫기" className="icon-button" onClick={onClose} type="button"><X aria-hidden="true" size={14} /></button>
      </header>
      {transcript && said > 0
        ? <Transcript onSelect={() => undefined} selected={agent} transcript={{ ...transcript, participants: [] }} />
        : <p className="collab-note">이 실행에서 {agentLabel(agent)}{hub ? '는' : '은'} 아무 말도 주고받지 않았어요.</p>}
      <form className="collab-ask" onSubmit={submit}>
        <input aria-label={`${agentLabel(agent)}에게 묻기`} onChange={(event) => setText(event.target.value)} placeholder={hub ? '오케스트레이터에게 할 말' : `${agentLabel(agent)}에게 물어볼 것`} value={text} />
        <button className="artifact-primary" disabled={!text.trim()} type="submit"><Send aria-hidden="true" size={12} /><span>{hub ? '대화에 넣기' : '묻기'}</span></button>
      </form>
      {sent && <p className="collab-note" role="status">{sent}</p>}
    </section>
  )
}
