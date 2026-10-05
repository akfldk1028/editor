import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { useDesignJob } from './use-design-job';

type Hook = ReturnType<typeof useDesignJob>;
const requests: Array<{ url: string; signal?: AbortSignal | null; resolve: (value: unknown, status?: number) => void }> = [];
const results: Record<string, Promise<unknown>> = {};
let current: Hook;

// Deliberately ignore AbortSignal to exercise ownership even when cancellation
// races a completed HTTP response or a transport does not honor abort.
window.fetch = (url, init) => new Promise(resolve => {
  requests.push({ url: String(url), signal: init?.signal,
    resolve: (value, status = 200) => resolve(new Response(JSON.stringify(value), { status })) });
});

function Harness() {
  current = useDesignJob();
  return null;
}
const root = createRoot(document.getElementById('root')!);
flushSync(() => root.render(<Harness />));

const harness = {
  start(key: string, action: 'loadSiteBoundary' | 'loadConstraints' | 'startJob', params: unknown) {
    results[key] = (current[action] as (params: unknown) => Promise<unknown>)(params);
  },
  async settle(index: number, value: unknown, key: string, status = 200) {
    const request = requests[index];
    if (!request) throw new Error(`No pending request at index ${index}`);
    request.resolve(value, status);
    const result = await results[key];
    await new Promise(requestAnimationFrame);
    return result;
  },
  async result(key: string) { return results[key]; },
  state() {
    const { loadSiteBoundary, loadConstraints, startJob, reset, ...state } = current;
    return state;
  },
  requests() { return requests.map(request => ({ url: request.url, aborted: request.signal?.aborted ?? false })); },
  reset() { flushSync(() => current.reset()); },
  unmount() { flushSync(() => root.unmount()); },
};
declare global { interface Window { designJobHarness: typeof harness } }
window.designJobHarness = harness;
