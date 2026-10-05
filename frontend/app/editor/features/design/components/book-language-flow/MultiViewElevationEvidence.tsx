import type { MultiViewElevationEvidence as Evidence } from './multi-view-elevation';

interface MultiViewElevationEvidenceProps {
  massLabel: string;
  proposal: Evidence;
}

function consistencyLabel(status: string): string {
  if (status === 'passed') return 'PASS';
  if (status === 'failed') return 'FAIL';
  return status.replaceAll('_', ' ').toUpperCase();
}

export function MultiViewElevationEvidence({
  massLabel,
  proposal,
}: MultiViewElevationEvidenceProps) {
  return (
    <section className="executed-mass-evidence__multi-view">
      <header>
        <span>4 / 4 CREATIVE FACADES</span>
        <strong>{proposal.status.toUpperCase()}</strong>
      </header>
      <div className="executed-mass-evidence__multi-view-status">
        <strong>
          JOINT CONSISTENCY {consistencyLabel(proposal.criticStatus)}
        </strong>
        <span>
          DETERMINISTIC GATE {consistencyLabel(proposal.deterministicStatus)}
        </span>
        <span>
          {proposal.paidRequestAttemptCount} PAID ATTEMPTS · {proposal.retryCount} TRANSPORT RETRIES
        </span>
        <span>GENERATED DESIGN PROPOSAL · NOT GEOMETRY / LEGAL AUTHORITY</span>
      </div>
      <div className="executed-mass-evidence__multi-view-grid">
        {proposal.views.map((view) => (
          <figure key={`${view.view}:${view.sha256}`}>
            <img
              src={view.previewUrl}
              alt={`${massLabel} generated ${view.view} creative facade`}
            />
            <figcaption>
              <strong>{view.view.toUpperCase()}</strong>
              <span>{view.provider} · {view.model || 'MODEL NOT RECORDED'}</span>
              <code>{view.sha256.slice(0, 16)}</code>
            </figcaption>
          </figure>
        ))}
      </div>
      {proposal.issues.length > 0 && (
        <ul className="executed-mass-evidence__multi-view-issues">
          {proposal.issues.map((issue) => (
            <li key={`${issue.code}:${issue.views.join(',')}:${issue.message}`}>
              <strong>{issue.code.replaceAll('_', ' ').toUpperCase()}</strong>
              <span>{issue.views.join(' / ') || 'ALL VIEWS'} · {issue.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
