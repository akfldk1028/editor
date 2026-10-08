import { cadArtifact } from '../artifacts/cad/manifest'
import { siteMapArtifact } from '../artifacts/site-map/manifest'
import { systemArtifact } from '../artifacts/system/manifest'
import type { ArtifactManifest } from './artifact-types'

/** Every artifact the shell can open, in sidebar order. */
export const artifacts: readonly ArtifactManifest[] = [siteMapArtifact, cadArtifact, systemArtifact]

export const defaultArtifactId = 'site-map'

export function artifactById(id: string | null | undefined): ArtifactManifest | undefined {
  return artifacts.find((artifact) => artifact.id === id)
}
