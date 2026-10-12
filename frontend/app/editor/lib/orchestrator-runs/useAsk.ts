'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { currentConversation } from '@/lib/design-conversation/session'
import { hostStatus, prewarm } from '@/lib/goals/activation'
import { availableGoal, loadCapabilities } from '@/lib/goals'

import { askLaw, RunRequestError } from './api'
import { type AskClause, type Command, onCommand } from './commands'
import { dismissFeed, projectFeed } from './feed'
import { answerLine, askFailedLine, askLines, siteLocateParams, siteLocatedLine } from './feed-lines'
import { conversationSite } from './site-context'

/**
 * The composer's send: the question is the user's bubble, the request is drawn (to the Orchestrator
 * Agent, which routes it — or to the role the user picked when it asked), and the answer replaces
 * that line: the Law Agent's turn, a handoff to a catalog goal, or the roles as choices. One question
 * at a time; the site the conversation is about rides along so 관련 법규 보기 can open its 조문.
 * A role choice comes back as an `ask` command and is sent again with that role.
 * A message that was an address comes back located: the map opens on that parcel through `open`
 * (the shell's openArtifact) and selects it, so the conversation's site follows without a click.
 */
export function useAsk(open?: (artifact: string, params?: Record<string, string>) => void) {
  const [busy, setBusy] = useState(false)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])

  const send = useCallback(async (raw: string, role: string | null = null, about: Pick<Extract<Command, { kind: 'ask' }>, 'clause' | 'site'> = {}) => {
    const postFeed = projectFeed(currentConversation().projectId)
    const text = raw.trim()
    if (!text) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    const [bubble, asking] = askLines(text, role, about.clause?.title ?? null)
    postFeed(bubble!)
    const pending = postFeed(asking!)
    // A question from the law artifact names its own site and date; otherwise the conversation's site.
    const site = about.site ? { pnu: about.site.pnu, address: about.site.address ?? '' } : conversationSite()
    const clause: AskClause | undefined = about.clause
    try {
      const answer = await askLaw({ text, conversation_id: currentConversation().conversationId, ...(site ? { pnu: site.pnu, ...(site.address ? { address: site.address } : {}) } : {}), ...(role ? { role } : {}),
        ...(clause ? { clause } : {}), ...(about.site?.assessmentDate ? { assessment_date: about.site.assessmentDate } : {}) }, controller.signal)
      if (controller.signal.aborted) return
      if (answer.answer?.kind === 'site') {
        postFeed(siteLocatedLine(answer.answer))
        const params = siteLocateParams(answer.answer)
        if (params) open?.('site-map', params)
        return
      }
      // A handoff to an open goal: say which owners are off, and wake them now with a short lease (the
      // user may press 시작 in a moment; the host's start takes 7–40 s, the lease expires if they do not).
      let needed: string[] = []
      if (answer.route.kind === 'goal' && answer.handoff?.available) {
        const goal = availableGoal(await loadCapabilities(controller.signal), answer.handoff.goal)
        if (goal) needed = prewarm(goal, await hostStatus(controller.signal))
      }
      if (controller.signal.aborted) return
      postFeed(answerLine(answer, site ? { pnu: site.pnu, address: site.address } : null, needed))
    } catch (error) {
      if (controller.signal.aborted) return
      const status = error instanceof RunRequestError ? error.status : null
      const detail = error instanceof RunRequestError ? error.detail : null
      postFeed(askFailedLine(status, detail))
    } finally {
      if (pending) dismissFeed(pending.id)
      if (!controller.signal.aborted) setBusy(false)
    }
  }, [open])

  useEffect(() => onCommand((command) => {
    if (command.kind === 'ask') void send(command.text, command.role, { clause: command.clause, site: command.site })
  }), [send])

  return { send, busy }
}
