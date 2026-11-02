const fs=require('node:fs'),path=require('node:path');
async function run(context,root){
  const output=path.join(root,'individual-old-missing'),stem='history-available';
  if(fs.existsSync(path.join(output,stem+'-manifest.json')))return {state:'already_recovered'};
  const records=JSON.parse(fs.readFileSync(path.join(root,'pending-history-download.private.json'),'utf8'));
  const candidates=new Map(JSON.parse(fs.readFileSync(path.join(root,'national-catalogue.json'),'utf8')).map(r=>[r.num,r]));
  const p=context.pages().find(p=>p.url().startsWith('https://map.ngii.go.kr'));
  const body=new URLSearchParams({unityOrderNo:'',airmap:'',oldmap:'',rstctPrint:''});
  for(const row of records)body.append('orderList',row.value);
  let response=await context.request.post('https://map.ngii.go.kr/pd/purchs/download.do',
    {data:body.toString(),headers:{'Content-Type':'application/x-www-form-urlencoded'}});
  let html=await response.text();
  if(!html.includes('dataArray.push')){
    const forms=await p.evaluate(html=>[...new DOMParser().parseFromString(html,'text/html').forms].map(f=>({action:f.getAttribute('action'),fields:[...f.querySelectorAll('input[name]')].map(i=>[i.name,i.value])})),html);
    const forward=forms.find(f=>f.action?.includes('nlippd.ngii.go.kr')||f.fields.some(x=>x[0]==='orderList'));
    if(!forward)throw new Error('History download forwarding unavailable');
    const url=new URL(forward.action||'https://nlippd.ngii.go.kr/nlippd/pd/innorix/innorixdownLoad.do','https://map.ngii.go.kr');
    if(url.protocol!=='https:'||!['map.ngii.go.kr','nlippd.ngii.go.kr'].includes(url.hostname))throw new Error('Unexpected provider host');
    response=await context.request.post(url.href,{data:new URLSearchParams(forward.fields).toString(),headers:{'Content-Type':'application/x-www-form-urlencoded'}});html=await response.text();
  }
  const files=[...html.matchAll(/dataArray\.push\(\{([\s\S]*?)\}\);/g)].map(m=>{
    const take=key=>{const v=m[1].match(new RegExp(key+'\\s*:\\s*"([^"]*)"'));if(!v)throw new Error('Manifest field absent');return v[1]};
    return {name:take('printFileName'),bytes:Number(take('fileSize')),url:new URL('innorixDownLoad2.do',response.url()).href+'?'+new URLSearchParams({fileName:take('printFileName'),directory:take('downloadUrl')})};
  });
  if(!files.length)throw new Error('Empty history manifest');
  fs.writeFileSync(path.join(output,stem+'-catalogue.json'),JSON.stringify(records.map(row=>{const r=candidates.get(row.sheet);return {...r,sheet:r.num,year:r.makeYer||''}})));
  fs.writeFileSync(path.join(output,stem+'-manifest.json'),JSON.stringify({files,source:'Existing provider order history; no new order'}));
  return {state:'manifest_recovered',sheets:records.length,files:files.length,newOrders:0};
}
module.exports={run};
