import React from 'react';
import { createRoot } from 'react-dom/client';
import { useOptimizationStream } from '../features/design/hooks/use-optimization-stream';

function Harness() {
  const hook = useOptimizationStream();
  Object.assign(window, { optimizationHarness: hook });
  return <output id="state">{JSON.stringify(hook)}</output>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
