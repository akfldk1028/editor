'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { askLaw, RunRequestError } from './api'
import { onCommand } from './commands'
import { dismissFeed, postFeed } from './feed'
import { answerLine, askFailedLine, askLines } from './feed-lines'
import { conversationSite } from './site-context'

/**
 * The composer's send: the question is the user's bubble, the request is drawn (to the Orchestrator
 * Agent, which routes it — or to the role the user picked when it asked), and the answer replaces
 * that line: the Law Agent's turn, a handoff to a catalog goal, or the roles as choices. One question
 * at a time; the site the conversation is about rides along so 관련 법규 보기 can open its 조문.
 * A role choice comes back as an `ask` command and is sent again with that role.
 */
export function useAsk() {
  const [busy, setBusy] = useState(false)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])

  const send = useCallback(async (raw: string, role: string | null = null) => {
    const text = raw.trim()
    if (!text) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    const [bubble, asking] = askLines(text, role)
    postFeed(bubble!)
    const pending = postFeed(asking!)
    const site = conversationSite()
    try {
      const answer = await askLaw({ text, ...(site ? { pnu: site.pnu, ...(site.address ? { address: site.address } : {}) } : {}), ...(role ? { role } : {}) }, controller.signal)
      if (controller.signal.aborted) return
      postFeed(answerLine(answer, site ? { pnu: site.pnu, address: site.address } : null))
    } catch (error) {
      if (controller.signal.aborted) return
      const status = error instanceof RunRequestError ? error.status : null
      const detail = error instanceof RunRequestError ? error.detail : null
      postFeed(askFailedLine(status, detail))
    } finally {
      if (pending) dismissFeed(pending.id)
      if (!controller.signal.aborted) setBusy(false)
    }
  }, [])

  useEffect(() => onCommand((command) => {
    if (command.kind === 'ask') void send(command.text, command.role)
  }), [send])

  return { send, busy }
}
