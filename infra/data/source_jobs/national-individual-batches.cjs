const fs=require('node:fs'),path=require('node:path');
const {run}=require('./national-individual-order.cjs');
let active=false;
function start(context,root){
  if(active)return {state:'already_running'};
  const plan=JSON.parse(fs.readFileSync(path.join(root,'plan.json'),'utf8'));
  const results=[];
  const save=state=>fs.writeFileSync(path.join(root,'batch-order-status.json'),JSON.stringify({state,at:Date.now(),results,totalBatches:plan.batches.length}));
  active=true;
  globalThis._ngiiIndividualBatchPromise=(async()=>{
    save('running');
    for(const batch of plan.batches){
      const journal=path.join(root,batch.stem+'-order-journal.json');
      if(fs.existsSync(journal)){
        const prior=JSON.parse(fs.readFileSync(journal,'utf8'));
        if(prior.state==='manifest_saved'||prior.state==='provider_pending_or_rejected'){results.push({...prior,stem:batch.stem});continue;}
        save('requires_reconciliation');return;
      }
      const result=await run(context,root,batch.stem,path.join(root,batch.candidates));
      results.push({...result,stem:batch.stem});save('running');
      if(result.state!=='manifest_saved' && !(result.state==='provider_pending_or_rejected' && result.resultCode==='1')){save('requires_reconciliation');return;}
    }
    save('finished');
  })().catch(e=>{results.push({state:'error',errorType:e.name});save('requires_reconciliation')}).finally(()=>{active=false});
  return {state:'started',batches:plan.batches.length,sheets:plan.sheets};
}
module.exports={start};
