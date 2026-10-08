'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { askLaw, RunRequestError } from './api'
import { dismissFeed, postFeed } from './feed'
import { answerLine, askFailedLine, askLines } from './feed-lines'
import { conversationSite } from './site-context'

/**
 * The composer's send: the question is the user's bubble, the Orchestrator says it is asking the
 * Law Agent, and the Law Agent's answer (or why there is none) replaces that line. One question at a
 * time; the site the conversation is about rides along so 관련 법규 보기 can open its 조문.
 */
export function useAsk() {
  const [busy, setBusy] = useState(false)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])

  const send = useCallback(async (raw: string) => {
    const text = raw.trim()
    if (!text || busy) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    const [bubble, asking] = askLines(text)
    postFeed(bubble!)
    const pending = postFeed(asking!)
    const site = conversationSite()
    try {
      const answer = await askLaw({ text, ...(site ? { pnu: site.pnu } : {}) }, controller.signal)
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
  }, [busy])

  return { send, busy }
}
