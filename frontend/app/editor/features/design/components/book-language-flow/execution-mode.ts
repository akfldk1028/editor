import type { MassExecutionMode } from '../../lib/language-system-types';

export function executionActionCopy(): { label: string; detail: string } {
  return {
    label: 'REPLAY EXACT AST',
    detail: 'SAME GEOMETRY PROGRAM · NEW EXECUTION EVIDENCE',
  };
}

export function executionRunCopy(mode?: MassExecutionMode): string {
  if (mode === 'exact_replay') return 'EXACT REPLAY';
  if (mode === 'fresh_synthesis') return 'NEW SYNTHESIS';
  if (mode === 'explicit_program') return 'EXPLICIT AST';
  return 'LEGACY RUN';
}
