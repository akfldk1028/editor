import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { useInteractiveAgentReview } from './use-interactive-agent-review';

type Input = Parameters<typeof useInteractiveAgentReview>[0];
let input: Input = { jobId:'job-A', design:{id:0,uid:'uid-A',generation:0,parents:[null,null],feasible:true,
  inputs:[],objectives:[],penalty:0,rank:0,elite:0}, massGeojson:null,
  buildingType:'office',algorithm:'all',onPreviewCandidate:()=>{} };
let current: ReturnType<typeof useInteractiveAgentReview>;
let deferSend = false;
let healthRequests = 0;
const evidence: Array<{url:string; resolve:(value:unknown,status?:number)=>void}> = [];
const sends: Array<{body:Record<string,unknown>; resolve:()=>void}> = [];
const results: Record<string,Promise<unknown>> = {};
window.fetch = (url, init) => {
  if (String(url).includes('/evidence/')) return new Promise(resolve => {
    evidence.push({url:String(url),resolve:(value,status=200)=>resolve(new Response(JSON.stringify(value),{status}))});
  });
  if (String(url).includes('/bus/send')) return new Promise(resolve => {
    const done = () => resolve(new Response('{}'));
    sends.push({body:JSON.parse(String(init?.body)),resolve:done});
    if (!deferSend) done();
  });
  healthRequests += 1;
  return Promise.resolve(new Response(JSON.stringify({service:'test',status:true})));
};
function Harness() { current = useInteractiveAgentReview(input); return null; }
const root = createRoot(document.getElementById('root')!);
flushSync(() => root.render(<Harness />));
const harness = {
  run(key:string) { results[key]=current.runAgLightReview(); },
  direct(key:string) { results[key]=current.sendDirectAgentMessage('test-agent','test message'); },
  setContext(jobId:string,uid:string,id=0) {
    input={...input,jobId,design:{...input.design,uid,id}};
    flushSync(() => root.render(<Harness />));
  },
  async settle(index:number,value:unknown,key:string,status=200) {
    const request=evidence[index];
    if (!request) throw new Error('Missing evidence request');
    request.resolve(value,status);
    await results[key];
    await new Promise(requestAnimationFrame);
  },
  resolveEvidence(index:number,value:unknown) { evidence[index]?.resolve(value); },
  async resolveSend(index:number,key:string) {
    sends[index]?.resolve();
    await results[key];
    await new Promise(requestAnimationFrame);
  },
  deferSend() { deferSend=true; },
  state() { return {reviews:current.agReviews,trace:current.agTrace,error:current.agError,loading:current.agLoading}; },
  sends() { return sends.map(item=>item.body); },
  evidenceUrls() { return evidence.map(item=>item.url); },
  healthRequests() { return healthRequests; },
  unmount() { flushSync(() => root.unmount()); },
};
declare global { interface Window { agentReviewHarness:typeof harness } }
window.agentReviewHarness=harness;
