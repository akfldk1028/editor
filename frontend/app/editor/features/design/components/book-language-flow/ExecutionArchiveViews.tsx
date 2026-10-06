import type { Dispatch, SetStateAction } from 'react';

import type { ExecutedMassManifest } from '../../lib/language-system-types';
import type { RecentMassCard } from './archive-selection-policy';
import { massLabel } from './execution-graph-model';
import { executionRunCopy } from './execution-mode';

interface ExecutionRunTimelineProps {
  archive: ExecutedMassManifest;
  selectRun: (runId: string) => void;
}

export function ExecutionRunTimeline({ archive, selectRun }: ExecutionRunTimelineProps) {
  return (
    <nav className="execution-run-timeline" aria-label="MASS 실행 시간순 아카이브">
      <header><span>EXECUTION RUN TIMELINE</span><strong>{archive.editor_provenance ? 'SAVED RUNS · CLICK TO VIEW' : 'NEWEST → OLDEST · CLICK TO REPLAY'}</strong></header>
      <div>
        {[...archive.runs].reverse().map((run, runIndex) => (
          <button
            type="button"
            key={run.run_id}
            data-selected={run.run_id === archive.selected_run_id}
            data-replayable={run.replayable}
            onClick={() => selectRun(run.run_id)}
            title={run.run_id}
          >
            <span>{String(runIndex + 1).padStart(2, '0')}</span>
            <b>{run.run_id.replace('book-program-portfolios-', '')}</b>
            <em>{run.selected_mass_count} MASS · {run.replayable ? executionRunCopy(run.execution_mode) : 'NO FINAL'}</em>
          </button>
        ))}
      </div>
    </nav>
  );
}

interface MassOnlyArchiveProps {
  archive: ExecutedMassManifest;
  recentMassCards: RecentMassCard[];
  selectRun: (runId: string) => void;
  setSelectedMassIndex: Dispatch<SetStateAction<number>>;
}

export function MassOnlyArchive({ archive, recentMassCards, selectRun, setSelectedMassIndex }: MassOnlyArchiveProps) {
  return (
    <section className="mass-only-archive" aria-label="실제 MASS 결과만 보기">
      <header>
        <div>
          <span>ACTUAL MASS ARCHIVE</span>
          <strong title={archive.selected_run_id}>{archive.selected_run_id}</strong>
        </div>
        <b>{recentMassCards.length} REPLAYABLE MASS RESULTS</b>
      </header>
      <div>
        {recentMassCards.map((mass) => (
          <button
            type="button"
            key={mass.key}
            data-selected={mass.selected}
            onClick={() => {
              if (mass.runId !== archive.selected_run_id) selectRun(mass.runId);
              else setSelectedMassIndex(mass.massIndex);
            }}
          >
            <img src={mass.previewUrl} alt={`${mass.label} actual MASS`} />
            <span>{String(mass.massIndex).padStart(2, '0')}</span>
            <strong>{massLabel(mass.label)}</strong>
            <em>{mass.operationLabel}</em>
          </button>
        ))}
      </div>
    </section>
  );
}
