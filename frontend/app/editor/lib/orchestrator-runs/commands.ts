/**
 * What an answer in the conversation asks the product to do ("법규·한계 검토 시작"). The slice that can
 * do it listens (`onCommand`); a command sent while nobody listens waits for the next listener, so
 * opening the artifact that owns the action is enough to have it carried out.
 */
/**
 * `start-review`: `goal` is a catalog id (`lib/goals`); the owning slice refuses one the door does not take.
 * `ask`: send a question again to the role the user picked when the router asked.
 */
export type Command =
  | { kind: 'start-review'; goal: string }
  | { kind: 'ask'; text: string; role: string; clause?: AskClause; site?: { pnu: string; address?: string; assessmentDate?: string } }

/** The review item a question is about (law artifact → 이 조항 질문하기); the backend asks the Law Agent about exactly it. */
export interface AskClause {
  item_id: string
  title: string
  refs: { instrument: string; kind: string; article: string | null; clause: string | null; hang_id?: string; edition_id?: string }[]
  reason: string
  status: string
  basis: string
}

type Listener = (command: Command) => void

const listeners = new Set<Listener>()
let pending: Command | null = null

/** Delivers to the listeners; true when at least one took it, else the command waits. */
export function sendCommand(command: Command): boolean {
  if (listeners.size === 0) {
    pending = command
    return false
  }
  pending = null
  for (const listener of listeners) listener(command)
  return true
}

/** Subscribes; a waiting command is delivered at once. Returns the unsubscribe. */
export function onCommand(listener: Listener): () => void {
  listeners.add(listener)
  if (pending) {
    const command = pending
    pending = null
    listener(command)
  }
  return () => {
    listeners.delete(listener)
  }
}

/** Test seam. */
export function resetCommands(): void {
  listeners.clear()
  pending = null
}
