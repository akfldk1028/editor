/**
 * What an answer in the conversation asks the product to do ("법규·한계 검토 시작"). The slice that can
 * do it listens (`onCommand`); a command sent while nobody listens waits for the next listener, so
 * opening the artifact that owns the action is enough to have it carried out.
 */
export type Command = { kind: 'start-review'; goal: 'limits' }

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
