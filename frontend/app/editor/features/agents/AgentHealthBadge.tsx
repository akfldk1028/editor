export function AgentHealthBadge({ status }: { status: string }) {
  const color = status === 'available' ? 'bg-(--color-semantic-success)' :
    ['unavailable', 'error'].includes(status) ? 'bg-(--color-semantic-error)' : 'bg-(--color-text-tertiary)';
  return <span className="inline-flex items-center gap-1.5" title="마지막 기록된 연결 상태">
    <span className={`w-2 h-2 rounded-full ${color}`} />
    <span className="text-label-small text-(--color-text-tertiary)">{status}</span>
  </span>;
}
