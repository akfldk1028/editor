const fs=require('node:fs'),path=require('node:path');
function mayOrder(pendingBytes,freeBytes){return freeBytes>21000000000 && pendingBytes<Math.min(5000000000,freeBytes-21000000000)}
function install(context,root){
  if(globalThis._ngiiOrderBudgetGuard)return {state:'already_installed'};
  const original=context.request.post.bind(context.request);
  context.request.post=async function(url,options){
    if(/\/(orderPckageResultJson|shbtInsertNRM)\.do(?:\?|$)/.test(String(url))){
      while(true){
        let allowed=false,reason='budget_unavailable',pendingBytes=null,freeBytes=null;
        try{
          const budget=JSON.parse(fs.readFileSync(path.join(root,'order-budget.json'),'utf8'));
          const stat=fs.statfsSync(root);freeBytes=stat.bavail*stat.bsize;
          const known=new Set(budget.knownManifests);let additional=0;
          for(const folder of budget.roots){
            for(const name of fs.readdirSync(folder).filter(n=>n.endsWith('-manifest.json'))){
              if(folder.replaceAll('\\','/')===root.replaceAll('\\','/')&&!/^\d{5}-manifest\.json$/.test(name))continue;
              const file=path.join(folder,name).replaceAll('\\','/');if(known.has(file))continue;
              const manifest=JSON.parse(fs.readFileSync(file,'utf8'));
              for(const row of manifest.files||[]){
                if(!fs.existsSync(path.join(folder,'files',row.name)))additional+=Number(row.bytes)||0;
              }
            }
          }
          pendingBytes=budget.pendingSelectedBytes+additional;
          allowed=Date.now()/1000-budget.at<180 && mayOrder(pendingBytes,freeBytes);
          reason=allowed?'within_budget':'waiting_for_download_backlog_or_storage';
        }catch(error){reason='budget_unavailable';}
        fs.writeFileSync(path.join(root,'order-backpressure-status.json'),JSON.stringify({at:Date.now(),state:reason,pendingBytes,freeBytes,reserveBytes:20000000000}));
        if(allowed)break;
        await new Promise(resolve=>setTimeout(resolve,5000));
      }
    }
    return original(url,options);
  };
  globalThis._ngiiOrderBudgetGuard=true;
  return {state:'installed',pendingWindowBytes:5000000000,reserveBytes:20000000000};
}
module.exports={install,mayOrder};
