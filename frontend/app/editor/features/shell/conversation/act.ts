import { sendCommand } from '@/lib/orchestrator-runs/commands'
import type { FeedAction } from '@/lib/orchestrator-runs/feed'

import type { ShellApi } from '../artifact-types'

/**
 * Carries out an answer button: an artifact opens through the shell; a command goes to the slice
 * that owns it — when none is mounted (the site card lives in the site map), the site map opens and
 * the waiting command is taken on mount.
 */
export function act(action: FeedAction, shell: ShellApi): void {
  if (action.command && !sendCommand(action.command)) {
    shell.openArtifact('site-map')
    return
  }
  if (action.artifact) shell.openArtifact(action.artifact, action.params)
}
