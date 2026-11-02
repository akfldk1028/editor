const fs=require('node:fs');
async function main(){
  const [mode,root]=process.argv.slice(2);
  if(!['package','individual'].includes(mode)||!root)throw new Error('Expected mode and state root');
  const targets=await(await fetch('http://127.0.0.1:9229/json/list')).json();
  const ws=new WebSocket(targets[0].webSocketDebuggerUrl);
  await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
  const script=mode==='package'?'national-original-order.cjs':'national-individual-batches.cjs';
  const guardPath=__dirname.replaceAll('\\','/')+'/national-order-budget-guard.cjs';
  const expression=`(async()=>{const r=process.mainModule.require('node:module').createRequire(process.mainModule.filename),fs=r('node:fs'),root=${JSON.stringify(root)};const status=JSON.parse(fs.readFileSync(root+'/batch-order-status.json','utf8'));if(status.state==='running'||status.state==='finished')return {state:status.state};const c=[...r('playwright-core').chromium._contexts][0];r(${JSON.stringify(guardPath)}).install(c,${mode==='package'?'root':"r('node:path').dirname(root)"});const modulePath=${JSON.stringify(__dirname.replaceAll('\\','/')+'/'+script)};delete r.cache[r.resolve(modulePath)];return ${mode==='package'?"r(modulePath).start(c,root,'C:/Data/25_ACE/ngii-original-batch')":"r(modulePath).start(c,root)"};})()`;
  const output=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Inspector timeout')),20000);
    ws.addEventListener('message',event=>{const data=JSON.parse(event.data);if(data.id===1){clearTimeout(timer);resolve(data)}});
  });
  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}));
  const result=await output;ws.close();
  if(result.result?.exceptionDetails)throw new Error('Browser control evaluation failed');
  console.log(JSON.stringify(result.result?.result?.value||{state:'unknown'}));
}
main().catch(error=>{console.error(error.name);process.exitCode=1});
