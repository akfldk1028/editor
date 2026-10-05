import { useCallback, useEffect, useState } from 'react';

import { getExecutedMassPassport, reviewSingleMassWithVlm } from '../../lib/api-client';
import type {
  ExecutedMassManifest,
  ExecutedMassRecord,
  MassExecutionPassport,
} from '../../lib/language-system-types';

type ReviewState = 'idle' | 'running' | 'complete' | 'failed';

interface Options {
  archive: ExecutedMassManifest | null;
  mass: ExecutedMassRecord | null;
  onPassport: (passport: MassExecutionPassport) => void;
  onSync: () => void;
}

export function useSingleMassVlmReview({ archive, mass, onPassport, onSync }: Options) {
  const [state, setState] = useState<ReviewState>('idle');
  const [error, setError] = useState('');

  useEffect(() => {
    setState('idle');
    setError('');
  }, [archive?.selected_run_id, mass?.index]);

  const review = useCallback(async () => {
    if (!archive || !mass || state === 'running') return;
    const prefix = 'single-execution:';
    if (!archive.selected_run_id.startsWith(prefix)) {
      setState('failed');
      setError('먼저 EXECUTE SELECTED MASS로 불변 단일 실행을 생성해야 합니다.');
      return;
    }
    setState('running');
    setError('');
    try {
      await reviewSingleMassWithVlm(archive.selected_run_id.slice(prefix.length), 3);
      const passport = await getExecutedMassPassport(
        mass.index,
        undefined,
        archive.selected_run_id,
      );
      onPassport(passport);
      onSync();
      setState('complete');
    } catch (reason: unknown) {
      setState('failed');
      setError(reason instanceof Error ? reason.message : 'Bounded paid VLM review failed');
    }
  }, [archive, mass, onPassport, onSync, state]);

  return { state, error, review };
}
