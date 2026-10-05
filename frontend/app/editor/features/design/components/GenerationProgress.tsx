import React from 'react';

interface Props {
  status: string;
  generation: number;
  maxGenerations: number;
  progress: number;
  feasibleCount: number;
  paretoCount: number;
  totalEvaluated: number;
  error: string | null;
}

const GenerationProgress: React.FC<Props> = React.memo(({
  status, generation, maxGenerations, progress, feasibleCount, paretoCount, totalEvaluated, error,
}) => {
  const isRunning = status === 'running';
  const isComplete = status === 'complete';

  const statusMap = {
    idle: { label: 'IDLE', color: '#64748b' },
    connecting: { label: 'CONNECTING', color: '#f59e0b' },
    running: { label: 'OPTIMIZING', color: '#3b82f6' },
    complete: { label: 'COMPLETE', color: '#22c55e' },
    error: { label: 'ERROR', color: '#ef4444' },
    cancelled: { label: 'CANCELLED', color: '#94a3b8' },
  };

  const { label: statusLabel, color: statusColor } = statusMap[status as keyof typeof statusMap] || statusMap.idle;

  return (
    <div style={{
      background: '#111827',
      borderRadius: 10,
      padding: 14,
      marginBottom: 10,
      border: '1px solid #1e293b',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <h3 style={{
          color: '#64748b', fontSize: 10, fontWeight: 600,
          margin: 0, letterSpacing: '0.08em',
        }}>
          OPTIMIZATION
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isRunning && (
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: statusColor,
              animation: 'pulse 1.5s ease-in-out infinite',
              display: 'inline-block',
            }} />
          )}
          <span style={{
            color: statusColor,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.08em',
          }}>
            {statusLabel}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{
        height: 6,
        background: '#0c1322',
        borderRadius: 3,
        overflow: 'hidden',
        marginBottom: 12,
        position: 'relative',
      }}>
        <div style={{
          height: '100%',
          width: `${progress}%`,
          background: isComplete
            ? 'linear-gradient(90deg, #059669, #22c55e)'
            : `linear-gradient(90deg, #1d4ed8, ${statusColor})`,
          borderRadius: 3,
          transition: 'width 0.3s ease',
          position: 'relative',
        }}>
          {isRunning && (
            <div style={{
              position: 'absolute', inset: 0,
              background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent)',
              animation: 'shimmer 1.5s ease-in-out infinite',
            }} />
          )}
        </div>
      </div>

      {/* Progress text */}
      <div style={{
        display: 'flex', justifyContent: 'center', marginBottom: 10,
        fontSize: 22, fontWeight: 700, fontFamily: 'monospace',
        color: '#e2e8f0',
      }}>
        {progress}%
      </div>

      {/* Stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6 }}>
        <div style={{
          padding: '6px 8px', background: '#0c1322', borderRadius: 6,
          textAlign: 'center' as const,
        }}>
          <div style={{ color: '#475569', fontSize: 9, marginBottom: 2 }}>세대</div>
          <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 700, fontFamily: 'monospace' }}>
            {generation}<span style={{ color: '#475569', fontSize: 10 }}>/{maxGenerations}</span>
          </div>
        </div>
        <div style={{
          padding: '6px 8px', background: '#0c1322', borderRadius: 6,
          textAlign: 'center' as const,
        }}>
          <div style={{ color: '#475569', fontSize: 9, marginBottom: 2 }}>적합</div>
          <div style={{ color: '#4ade80', fontSize: 14, fontWeight: 700, fontFamily: 'monospace' }}>
            {feasibleCount}
          </div>
        </div>
        <div style={{
          padding: '6px 8px', background: '#0c1322', borderRadius: 6,
          textAlign: 'center' as const,
        }}>
          <div style={{ color: '#475569', fontSize: 9, marginBottom: 2 }}>파레토</div>
          <div style={{ color: '#fbbf24', fontSize: 14, fontWeight: 700, fontFamily: 'monospace' }}>
            {paretoCount}
          </div>
        </div>
        <div style={{
          padding: '6px 8px', background: '#0c1322', borderRadius: 6,
          textAlign: 'center' as const,
        }}>
          <div style={{ color: '#475569', fontSize: 9, marginBottom: 2 }}>총평가</div>
          <div style={{ color: '#94a3b8', fontSize: 14, fontWeight: 700, fontFamily: 'monospace' }}>
            {totalEvaluated}
          </div>
        </div>
      </div>

      {error && (
        <div style={{
          marginTop: 8,
          padding: '6px 10px',
          background: 'rgba(69,10,10,0.6)',
          borderRadius: 6,
          border: '1px solid rgba(239,68,68,0.2)',
          color: '#fca5a5',
          fontSize: 12,
        }}>
          {error}
        </div>
      )}

      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(200%); } }
      `}</style>
    </div>
  );
});

GenerationProgress.displayName = 'GenerationProgress';
export default GenerationProgress;
