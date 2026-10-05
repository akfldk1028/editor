import { useEffect, useState } from 'react';
import { getMassPortfolioEvaluations } from '../../lib/api-client';
import type { MassPortfolioManifest } from '../../lib/mass-portfolio-types';

export function useMassPortfolio() {
  const [manifest, setManifest] = useState<MassPortfolioManifest | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const readLocation = () => setRunId(new URLSearchParams(window.location.search).get('evaluation_run') || '');
    readLocation();
    window.addEventListener('popstate', readLocation);
    return () => window.removeEventListener('popstate', readLocation);
  }, []);

  useEffect(() => {
    if (runId === null) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    getMassPortfolioEvaluations(runId || undefined, controller.signal)
      .then((payload) => { if (!controller.signal.aborted) setManifest(payload); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Evaluation archive fetch failed');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId]);

  const selectRun = (selected: string) => {
    const url = new URL(window.location.href);
    if (selected) url.searchParams.set('evaluation_run', selected);
    else url.searchParams.delete('evaluation_run');
    window.history.replaceState(window.history.state, '', url);
    setRunId(selected);
  };
  return { manifest, runId, selectRun, loading, error };
}
