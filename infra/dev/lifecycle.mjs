// Editor-owned, editor-session entries: product.mjs may start them when they are down and
// stops the ones it created. Persistent ones are normally kept alive by infra/host and are
// simply reused here when their probe answers.
export function canManageService(service) {
  return service.owner_repo === 'editor' && service.management === 'editor-session';
}

export async function ensureService(service, { probe, start, wait }) {
  const current = await probe(service);
  if (!canManageService(service)) return { ...current, action: 'external' };
  if (current.state === 'healthy') return { ...current, action: 'reused' };
  if (current.state === 'occupied') throw new Error(`${service.name} port is occupied by an incompatible service (${current.detail ?? current.state}).`);
  const child = start(service);
  const readiness = await wait(service, { isExited: () => child.exitCode !== null || Boolean(child.spawnFailed) });
  if (readiness.state !== 'healthy') throw new Error(`${service.name} did not become ready (${readiness.detail ?? readiness.state}).`);
  return { ...readiness, action: 'started' };
}

export async function settleStartup(tasks) {
  // Cleanup must wait for siblings that may still create owned processes.
  const results = await Promise.allSettled(tasks.map(task => Promise.resolve().then(task)));
  const failure = results.find(result => result.status === 'rejected');
  if (failure) throw failure.reason;
  return results.map(result => result.value);
}
