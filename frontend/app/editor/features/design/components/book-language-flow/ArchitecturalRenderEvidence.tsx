import type { ElevationProposalEvidence } from './elevation-proposal';

interface ArchitecturalRenderEvidenceProps {
  massLabel: string;
  proposal: ElevationProposalEvidence;
}

export function ArchitecturalRenderEvidence({
  massLabel,
  proposal,
}: ArchitecturalRenderEvidenceProps) {
  return (
    <section className="executed-mass-evidence__proposal">
      <header>
        <span>ARCHITECTURAL RENDER AGENT · RENDER ALT 01</span>
        <strong>{proposal.status.toUpperCase()}</strong>
      </header>
      <figure>
        <img
          src={proposal.previewUrl}
          alt={`${massLabel} generated architectural render ALT 01`}
        />
        <figcaption>
          <strong>{proposal.primarySystem || proposal.strategyId}</strong>
          <span>GENERATED DESIGN PROPOSAL · NOT GEOMETRY / LEGAL AUTHORITY</span>
          <span>{proposal.provider} · {proposal.model || 'MODEL NOT RECORDED'}</span>
          <span>{proposal.requestCount} REQUEST · {proposal.retryCount} RETRIES</span>
          <span>ROOF GUARD {proposal.roofGuardStatus.toUpperCase()} · {proposal.roofGuardChangedPixels} PX</span>
          <code>{proposal.sha256.slice(0, 16)}</code>
        </figcaption>
      </figure>
    </section>
  );
}
