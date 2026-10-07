import { cadArtifact } from '../artifacts/cad/manifest'
import type { ArtifactManifest } from './artifact-types'

/** Every artifact the shell can open, in sidebar order. */
export const artifacts: readonly ArtifactManifest[] = [cadArtifact]

export const defaultArtifactId = 'cad'

export function artifactById(id: string | null | undefined): ArtifactManifest | undefined {
  return artifacts.find((artifact) => artifact.id === id)
}
