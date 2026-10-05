import { useEffect, useMemo, useRef, useState } from 'react';
import { getExecutedMassManifest, getExecutedMassPassport, executeArchivedMassAndLoad, getMaasOutcomeGraphSlice } from '../../lib/api-client';
import type { ExecutedMassManifest, MassExecutionPassport, OutcomeGraphSlice } from '../../lib/language-system-types';
import { buildRecentMassCards, latestReplayableRunId, reconcileExecutedMassArchive, resolveSelectedMassIndex } from './archive-selection-policy';
import { LatestRunRequest } from './run-selection-request';
import { bindSelectedRuntimePassport, publishablePortfolioRunId } from './selected-runtime-passport';
import { useSingleMassVlmReview } from './useSingleMassVlmReview';

export function useExecutionArchive() {
  const runRequestsRef = useRef(new LatestRunRequest());
  const [archive, setArchive] = useState<ExecutedMassManifest | null>(null);
  const [passport, setPassport] = useState<MassExecutionPassport | null>(null);
  const [outcomeGraph, setOutcomeGraph] = useState<OutcomeGraphSlice | null>(null);
  const [selectedMassIndex, setSelectedMassIndex] = useState(1);
  const [archiveError, setArchiveError] = useState('');
  const [passportError, setPassportError] = useState('');
  const [lastSyncAt, setLastSyncAt] = useState('');
  const [executionState, setExecutionState] = useState<'idle' | 'running' | 'complete' | 'failed'>('idle');
  const [executionError, setExecutionError] = useState('');

  useEffect(() => () => runRequestsRef.current.abort(), []);

  useEffect(() => {
    if (!archive?.pnu) return undefined;
    const geometryHash = archive.masses.find((mass) => mass.index === selectedMassIndex)?.geometry_hash;
    let active = true;
    let inFlight = false;
    const controller = new AbortController();
    const refresh = () => {
      if (inFlight) return;
      inFlight = true;
      getMaasOutcomeGraphSlice(
        archive.pnu,
        controller.signal,
        geometryHash,
        archive.selected_run_id,
      )
        .then((payload) => { if (active) setOutcomeGraph(payload); })
        .catch(() => undefined)
        .finally(() => { inFlight = false; });
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [archive?.pnu, archive?.selected_run_id, selectedMassIndex]);

  useEffect(() => {
    const controller = new AbortController();
    getExecutedMassManifest(controller.signal)
      .then(async (payload) => {
        if (publishablePortfolioRunId(payload)) return payload;
        const latestRunId = latestReplayableRunId(payload);
        return latestRunId !== payload.selected_run_id
          ? getExecutedMassManifest(controller.signal, latestRunId)
          : payload;
      })
      .then((payload) => {
        setArchive(payload);
        setSelectedMassIndex(payload.masses[0]?.index ?? 1);
        setLastSyncAt(new Date().toLocaleTimeString('ko-KR', { hour12: false }));
        setArchiveError('');
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setArchiveError(reason instanceof Error ? reason.message : '실행 MASS 아카이브를 불러오지 못했습니다.');
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let currentController: AbortController | null = null;
    const refresh = () => {
      if (inFlight) return;
      inFlight = true;
      currentController = new AbortController();
      getExecutedMassManifest(currentController.signal)
        .then((payload) => {
          if (!active) return;
          setArchive((current) => reconcileExecutedMassArchive(current, payload));
          setArchiveError('');
          setLastSyncAt(new Date().toLocaleTimeString('ko-KR', { hour12: false }));
        })
        .catch(() => undefined)
        .finally(() => { inFlight = false; });
    };
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      currentController?.abort();
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!archive) return undefined;
    setExecutionState('idle');
    setExecutionError('');
    if (archive.masses.length === 0) {
      setPassport(null);
      setPassportError('');
      return undefined;
    }
    const controller = new AbortController();
    setPassport(null);
    setPassportError('');
    getExecutedMassPassport(selectedMassIndex, controller.signal, archive.selected_run_id)
      .then((payload) => {
        setPassport(payload);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setPassportError(reason instanceof Error ? reason.message : 'MASS 실행 passport를 불러오지 못했습니다.');
        }
      });
    return () => controller.abort();
  }, [archive?.mass_count, archive?.selected_run_id, selectedMassIndex]);

  useEffect(() => {
    if (!archive) return;
    const resolvedIndex = resolveSelectedMassIndex(archive, selectedMassIndex);
    if (resolvedIndex !== selectedMassIndex) setSelectedMassIndex(resolvedIndex);
  }, [archive, selectedMassIndex]);

  const selectedMass = archive?.masses.find((mass) => mass.index === selectedMassIndex) ?? null;
  const passportBinding = useMemo(
    () => bindSelectedRuntimePassport(
      passport,
      selectedMass,
      {
        requireCertifiedIdentity: Boolean(
          archive && publishablePortfolioRunId(archive),
        ),
      },
    ),
    [archive, passport, selectedMass],
  );
  const selectedPassport = passportBinding.passport;
  const selectedPassportError = passportBinding.error || passportError;
  const recentMassCards = useMemo(
    () => archive ? buildRecentMassCards(archive, selectedMassIndex) : [],
    [archive, selectedMassIndex],
  );
  const vlmReview = useSingleMassVlmReview({
    archive,
    mass: selectedMass,
    onPassport: setPassport,
    onSync: () => setLastSyncAt(new Date().toLocaleTimeString('ko-KR', { hour12: false })),
  });
  const selectRun = (runId: string) => {
    const request = runRequestsRef.current;
    const signal = request.start();
    getExecutedMassManifest(signal, runId)
      .then((payload) => {
        if (!request.isCurrent(signal)) return;
        setArchive(payload);
        setSelectedMassIndex(payload.masses[0]?.index ?? 1);
        setArchiveError('');
      })
      .catch((reason: unknown) => {
        if (!request.isCurrent(signal)) return;
        setArchiveError(reason instanceof Error ? reason.message : '실행 run을 불러오지 못했습니다.');
      })
      .finally(() => request.finish(signal));
  };

  const executeMass = async (onExecuted: () => void) => {
    if (!archive || !selectedMass || executionState === 'running') return;
    setExecutionState('running');
    setExecutionError('');
    try {
      const result = await executeArchivedMassAndLoad(
        archive.selected_run_id,
        selectedMass.index,
      );
      setArchive(result.archive);
      setSelectedMassIndex(result.archive.masses[0]?.index ?? 1);
      onExecuted();
      setExecutionState('complete');
      setLastSyncAt(new Date().toLocaleTimeString('ko-KR', { hour12: false }));
    } catch (reason: unknown) {
      setExecutionState('failed');
      setExecutionError(reason instanceof Error ? reason.message : 'Selected MASS execution failed');
    }
  };

  return { archive, outcomeGraph, selectedMassIndex, setSelectedMassIndex, archiveError, lastSyncAt, executionState, executionError, selectedMass, passportBinding, selectedPassport, selectedPassportError, recentMassCards, vlmReview, selectRun, executeMass };
}
