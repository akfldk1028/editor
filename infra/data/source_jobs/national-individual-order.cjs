const fs=require('node:fs'),path=require('node:path');
async function run(context,root,stem,candidatesFile){
  const journal=path.join(root,stem+'-order-journal.json');
  if(fs.existsSync(journal))return {state:'existing_order_journal_requires_reconciliation'};
  const rows=JSON.parse(fs.readFileSync(candidatesFile,'utf8'));
  if(!rows.length || rows.length>100)throw new Error('Bounded batch required');
  const p=context.pages().find(p=>p.url().startsWith('https://map.ngii.go.kr'));
  const formResponse=await context.request.post('https://map.ngii.go.kr/pd/shbtManage/dowloadRequestForm.do',
    {form:{mapType:'1',orderGb:'online',dType:''}});
  const brthdy=await p.evaluate(html=>new DOMParser().parseFromString(html,'text/html')
    .querySelector('input[name=onBrthdy]')?.value,await formResponse.text());
  if(!brthdy)return {state:'login_required'};
  const form={orderGb:'online',brthdy,purchsPurps:'CAAAC00003',detailCn:''};
  rows.forEach((r,i)=>Object.entries({orderTp:r.type,mapScale:r.scale,mapNo:r.num,mapName:r.name,
    mapHistoryNo:r.historyNo,mapKind:'0'}).forEach(([k,v])=>{form[`data[${i}][${k}]`]=String(v)}));
  fs.writeFileSync(journal,JSON.stringify({state:'request_started',sheets:rows.map(r=>r.num),at:Date.now()}));
  const result=await(await context.request.post('https://map.ngii.go.kr/pd/shbtManage/shbtInsertNRM.do',
    {form,timeout:240000})).json();
  fs.writeFileSync(path.join(root,stem+'-order-response.private.json'),JSON.stringify(result));
  const d=result.allDataMap;
  if(result.resultCode!=='1'||!d?.orderDownList){
    fs.writeFileSync(journal,JSON.stringify({state:'provider_pending_or_rejected',resultCode:result.resultCode,at:Date.now()}));
    return {state:'provider_pending_or_rejected',resultCode:result.resultCode,hasDownloadList:!!d?.orderDownList};
  }
  const body=new URLSearchParams({unityOrderNo:d.unityOrderNo,prcCode:d.resultPrcCode||result.resultPrcCode||''});
  for(const id of d.orderDownList.split(','))body.append('orderList',id);
  let response=await context.request.post('https://map.ngii.go.kr/pd/purchs/download.do',
    {data:body.toString(),headers:{'Content-Type':'application/x-www-form-urlencoded'}});
  let html=await response.text();
  if(!html.includes('dataArray.push')){
    const forms=await p.evaluate(html=>[...new DOMParser().parseFromString(html,'text/html').forms]
      .map(f=>({action:f.getAttribute('action'),fields:[...f.querySelectorAll('input[name]')].map(i=>[i.name,i.value])})),html);
    const forward=forms.find(f=>f.action?.includes('nlippd.ngii.go.kr')||f.fields.some(x=>x[0]==='orderList'));
    if(!forward)throw new Error('Manifest forwarding unavailable');
    const url=new URL(forward.action||'https://nlippd.ngii.go.kr/nlippd/pd/innorix/innorixdownLoad.do','https://map.ngii.go.kr');
    if(url.protocol!=='https:'||!['map.ngii.go.kr','nlippd.ngii.go.kr'].includes(url.hostname))throw new Error('Unexpected host');
    response=await context.request.post(url.href,{data:new URLSearchParams(forward.fields).toString(),headers:{'Content-Type':'application/x-www-form-urlencoded'}});html=await response.text();
  }
  const files=[...html.matchAll(/dataArray\.push\(\{([\s\S]*?)\}\);/g)].map(m=>{
    const take=key=>{const v=m[1].match(new RegExp(key+'\\s*:\\s*"([^"]*)"'));if(!v)throw new Error('Missing field');return v[1]};
    return {name:take('printFileName'),bytes:Number(take('fileSize')),url:new URL('innorixDownLoad2.do',response.url()).href+'?'+new URLSearchParams({fileName:take('printFileName'),directory:take('downloadUrl')})};
  });
  if(!files.length)throw new Error('Empty manifest');
  fs.writeFileSync(path.join(root,stem+'-catalogue.json'),JSON.stringify(rows.map(r=>({...r,sheet:r.num,year:r.makeYer||''}))));
  fs.writeFileSync(path.join(root,stem+'-manifest.json'),JSON.stringify({files,scope:'individual_sheet_order',sheets:rows.map(r=>r.num)}));
  const status={state:'manifest_saved',sheets:rows.length,files:files.length,bytes:files.reduce((n,r)=>n+r.bytes,0),at:Date.now()};
  fs.writeFileSync(journal,JSON.stringify(status));return status;
}
module.exports={run};
