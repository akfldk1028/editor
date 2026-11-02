const fs = require('node:fs');
const path = require('node:path');
const BASE = 'https://map.ngii.go.kr';
let active = false;

function write(root, name, value) {
  const target = path.join(root, name);
  fs.writeFileSync(target + '.tmp', JSON.stringify(value, null, 2));
  fs.renameSync(target + '.tmp', target);
}

async function start(context, root, existingRoot) {
  if (active || globalThis._ngiiBatchActive) return {state:'already_running'};
  const login = await (await context.request.post(BASE + '/mn/loginCheck.do')).json();
  if (login.isLogin !== true) {
    const result = {state:'login_required', at:Date.now(), orderedThisRun:0, downloadedThisRun:0};
    write(root, 'batch-order-status.json', result);
    return result;
  }
  const p = context.pages().find(p => p.url().startsWith(BASE));
  if (!p) throw new Error('NGII browser page unavailable');
  const prefilled = await context.request.post(BASE + '/pd/shbtManage/dowloadRequestForm.do',
    {form:{mapType:'9', orderGb:'online', dType:''}});
  const brthdy = await p.evaluate(html => new DOMParser().parseFromString(html,'text/html')
    .querySelector('input[name=onBrthdy]')?.value, await prefilled.text());
  if (!brthdy) return {state:'required_provider_form_unavailable'};
  const regions = JSON.parse(fs.readFileSync(path.join(root,'national-package-targets.json'),'utf8')).regions;
  if (regions.some(row=>row.categoryPck !== '9')) throw new Error('OriginalTopographicCategoryRequired');
  const done = new Set();
  const deferred=[];
  for(const name of fs.readdirSync(root).filter(name=>/^\d{5}-order-journal\.json$/.test(name))){
    const entry=JSON.parse(fs.readFileSync(path.join(root,name),'utf8'));
    if(entry.state!=='manifest_saved'){
      done.add(name.slice(0,5));deferred.push({region:name.slice(0,5),state:'deferred_prior_attempt',priorState:entry.state});
    }
  }
  for (const folder of [root,existingRoot]) {
    for (const name of fs.readdirSync(folder).filter(name=>name.endsWith('-manifest.json'))) {
      const manifest = JSON.parse(fs.readFileSync(path.join(folder,name),'utf8'));
      if (manifest.files?.length && manifest.region) done.add(String(manifest.region));
      if (manifest.files?.length && /^\d{5}-manifest\.json$/.test(name)) done.add(name.slice(0,5));
    }
  }
  const priority = {'41':0, '28':1, '51':2};
  const pending = regions.filter(r => !done.has(r.sigunguCodePck))
    .sort((a,b)=>(priority[a.provinceCode]??3)-(priority[b.provinceCode]??3));
  const uncertain = pending.filter(r => fs.existsSync(path.join(root,r.sigunguCodePck + '-order-journal.json')));
  if (uncertain.length) return {state:'reconcile_prior_orders_first', regions:uncertain.map(r => r.sigunguCodePck)};
  const results = [...deferred];
  const save = state => write(root,'batch-order-status.json',{state,at:Date.now(),total:regions.length,
    skippedExisting:regions.length-pending.length,results,downloadedThisRun:0});
  active = true;
  globalThis._ngiiNationalOrderPromise = (async () => {
    save('running');
    for (const row of pending) {
      const region = row.sigunguCodePck;
      write(root,region+'-order-journal.json',{state:'request_started',at:Date.now(),region});
      try {
        const form = Object.fromEntries(['categoryPck','sidoCode','sidoNm','sigunguCodePck','sigunguNmPck'].map(k=>[k,row[k]]));
        const result = await (await context.request.post(BASE+'/ms/pcKage/orderPckageResultJson.do',
          {form:{...form,brthdy,purchsPurps:'CAAAC00003',detailCn:''},timeout:240000})).json();
        if(result.resultCode!=='1') throw new Error('OrderRejected');
        const d = result.allDataMap;
        // Persist the recovery response privately before attempting manifest delivery.
        write(root,region+'-order-response.private.json',d);
        if(!d.orderDownList){
          write(root,region+'-order-journal.json',{state:'deferred_provider_response_incomplete',at:Date.now(),region});
          results.push({region,state:'deferred_provider_response_incomplete'});save('running');continue;
        }
        const metadata = Object.values(d).filter(Array.isArray).flat().filter(x=>x.mapShtNo)
          .map(x=>({sheet:x.mapShtNo,scale:x.scale,projection:x.projection,year:x.gosiYer,
            minx:x.minx,miny:x.miny,maxx:x.maxx,maxy:x.maxy}));
        write(root,region+'-catalogue.json',metadata);
        const body=new URLSearchParams({unityOrderNo:d.unityOrderNo,prcCode:d.resultPrcCode||''});
        for(const id of d.orderDownList.split(',')) body.append('orderList',id);
        let response=await context.request.post(BASE+'/pd/purchs/download.do',
          {data:body.toString(),headers:{'Content-Type':'application/x-www-form-urlencoded'}});
        let html=await response.text();
        if(!html.includes('dataArray.push')) {
          const forms=await p.evaluate(html=>[...new DOMParser().parseFromString(html,'text/html').forms]
            .map(f=>({action:f.getAttribute('action'),fields:[...f.querySelectorAll('input[name]')].map(i=>[i.name,i.value])})),html);
          const forward=forms.find(f=>f.action?.includes('nlippd.ngii.go.kr')||f.fields.some(x=>x[0]==='orderList'));
          if(!forward) throw new Error('ManifestForwardUnavailable');
          const url=new URL(forward.action||'https://nlippd.ngii.go.kr/nlippd/pd/innorix/innorixdownLoad.do',BASE);
          if(url.protocol!=='https:' || !['map.ngii.go.kr','nlippd.ngii.go.kr'].includes(url.hostname))
            throw new Error('UnexpectedProviderHost');
          response=await context.request.post(url.href,{data:new URLSearchParams(forward.fields).toString(),
            headers:{'Content-Type':'application/x-www-form-urlencoded'}});
          html=await response.text();
        }
        const files=[...html.matchAll(/dataArray\.push\(\{([\s\S]*?)\}\);/g)].map(m=>{
          const take=key=>{const v=m[1].match(new RegExp(key+'\\s*:\\s*"([^"]*)"'));if(!v)throw new Error('ManifestFieldMissing');return v[1]};
          return {name:take('printFileName'),bytes:Number(take('fileSize')),
            url:new URL('innorixDownLoad2.do',response.url()).href+'?'+new URLSearchParams({fileName:take('printFileName'),directory:take('downloadUrl')})};
        });
        if(!files.length) throw new Error('EmptyManifest');
        write(root,region+'-manifest.json',{region,files});
        write(root,region+'-order-journal.json',{state:'manifest_saved',at:Date.now(),region});
        results.push({region,provinceCode:row.provinceCode,state:'manifest_saved',files:files.length,
          bytes:files.reduce((s,f)=>s+f.bytes,0),catalogueRecords:metadata.length});
        save('running');
      } catch(error) {
        results.push({region,state:'requires_reconciliation',errorType:error.name});
        save('requires_reconciliation');
        return;
      }
    }
    save('finished');
  })().catch(()=>save('failed')).finally(()=>{active=false});
  return {state:'started',remaining:pending.length};
}

module.exports = {start};
