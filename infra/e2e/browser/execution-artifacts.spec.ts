import {test,expect,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aIZkAAAAASUVORK5CYII=','base64');
const passport=JSON.stringify({status:'historical',source_path:'D:/historic/private/passport.json'});
const hash=(bytes:Buffer|string)=>createHash('sha256').update(bytes).digest('hex');
const first={catalog_id:'catalog-a',source_namespace:'service-cache',snapshot_sha256:'a'.repeat(64),execution_id:'recorded-run',
  execution_state:'archived',source_status:'running',metadata_status:'available',has_preview:true,has_passport:true,
  geometry_ready:true,replay_reference:{source_run_id:'historical-missing-run',status:'unresolved'}};
const missing={...first,catalog_id:'catalog-b',source_namespace:'portfolio',snapshot_sha256:'b'.repeat(64),execution_id:null,
  source_status:null,metadata_status:'missing',has_preview:false,has_passport:false};
const artifacts=[{artifact_id:'preview-id',role:'preview',media_type:'image/png',inline:true,size:png.length,sha256:hash(png)},
  {artifact_id:'front-id',role:'elevation_front',media_type:'image/png',inline:true,size:png.length,sha256:hash(png)},
  {artifact_id:'passport-id',role:'passport',media_type:'application/json',inline:false,size:Buffer.byteLength(passport),sha256:hash(passport)}];

async function setup(page:Page,options:{conflict?:boolean;delayed?:Promise<void>;corruptImage?:boolean;attachedCount?:number}={}){
  let attached:typeof first[]=Array.from({length:options.attachedCount||0},(_,i)=>({...first,catalog_id:`attached-${i}`,execution_id:`historical-${i}`,has_preview:false,has_passport:false}));
  const writes:string[]=[];
  await page.route('**/api/v1/platform/projects/artifact-project',r=>r.fulfill({json:{project_id:'artifact-project',owner_project_id:'archive-reference',
    branch_id:'main',scene_id:'scene',scene_revision:4,scene_project_id:null}}));
  await page.route('**/api/v1/platform/projects/artifact-project/context',r=>r.fulfill({json:{scene_revision:4,source_versions:{}}}));
  await page.route('**/api/v1/platform/projects/artifact-project/runs',r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/platform/projects/artifact-project/design/**',async r=>{
    const url=new URL(r.request().url());const path=url.pathname.split('/design')[1];
    if(r.request().method()==='POST')writes.push(path);
    if(path==='/jobs')return r.fulfill({json:{items:[]}});
    if(path==='/selection')return r.fulfill({json:null});
    if(path==='/executions'&&r.request().method()==='POST'){
      expect(r.request().postDataJSON().scene_revision).toBe(4);
      if(options.conflict)return r.fulfill({status:409,json:{detail:'stale_revision'}});
      const id=r.request().postDataJSON().catalog_id;
      const value=id===first.catalog_id?first:missing;
      if(!attached.some(item=>item.catalog_id===id))attached.push(value as typeof first);
      return r.fulfill({status:201,json:value});
    }
    if(path==='/executions'){
      const offset=Number(url.searchParams.get('offset'));
      return r.fulfill({json:{items:attached.slice(offset,offset+20),limit:20,offset}});
    }
    if(path==='/archive/executions'){
      const offset=Number(url.searchParams.get('offset'));
      return r.fulfill({json:{items:offset?[]:[first,missing,...Array.from({length:18},(_,i)=>({...first,catalog_id:`other-${i}`,execution_id:`other-${i}`}))],limit:20,offset}});
    }
    if(path.endsWith('/download')){
      const json=path.includes('passport-id');return r.fulfill({body:json?passport:png,contentType:json?'application/json':'image/png',
        headers:{'Content-Disposition':`attachment; filename="saved-artifact.${json?'json':'png'}"`,'X-Content-Type-Options':'nosniff'}});
    }
    if(path.includes('/artifacts/'))return options.corruptImage?r.fulfill({status:503,body:'unavailable'}):r.fulfill({body:png,contentType:'image/png'});
    if(path==='/executions/catalog-a'){
      if(options.delayed)await options.delayed;
      return r.fulfill({json:{execution:first,items:artifacts,limit:20,offset:0}}).catch(()=>{});
    }
    if(path==='/executions/catalog-b')return r.fulfill({json:{execution:missing,items:[],limit:20,offset:0}});
    const seeded=attached.find(item=>path===`/executions/${item.catalog_id}`);
    if(seeded)return r.fulfill({json:{execution:seeded,items:[],limit:20,offset:0}});
    return r.fulfill({status:404,json:{detail:'unexpected request'}});
  });
  return writes;
}
const panel=(page:Page)=>page.getByRole('region',{name:'보관된 실행 자료',exact:true});
async function attachFirst(page:Page){
  await page.goto('/projects/artifact-project');
  await panel(page).getByRole('button',{name:'실행 자료 찾아보기',exact:true}).click();
  await panel(page).getByRole('button',{name:'실행 자료를 프로젝트에 연결 · recorded-run',exact:true}).click();
}

test('copied execution attaches explicitly, restores pinned identity and serves original images and passport',async({page})=>{
  const writes=await setup(page);await attachFirst(page);
  await expect(panel(page).getByText('보관됨 · 원본 상태: running',{exact:true}).first()).toBeVisible();
  await expect(panel(page).getByRole('img',{name:'보관된 매스 미리보기'})).toBeVisible();
  await expect.poll(()=>panel(page).getByRole('img',{name:'보관된 매스 미리보기'}).evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBeGreaterThan(0);
  await panel(page).getByRole('button',{name:'정면 입면 보기',exact:true}).click();
  await expect(panel(page).getByRole('img',{name:'보관된 정면 입면'})).toBeVisible();
  await expect(panel(page).getByText('원본 기록의 형상 판정: 준비됨',{exact:true})).toBeVisible();
  await expect(panel(page).getByText('원본 재실행 참조 미확인: historical-missing-run',{exact:true})).toBeVisible();
  const link=panel(page).getByRole('link',{name:'원본 패스포트 다운로드',exact:true});
  await expect(link).toHaveAttribute('download','');
  const url=await link.getAttribute('href');expect(url).toMatch(/\/artifacts\/passport-id\/download$/);
  // Real download completion and byte hashes are checked against the HTTP fixture below.
  const copied=await page.evaluate(async url=>{const r=await fetch(url!);return {body:await r.text(),disposition:r.headers.get('content-disposition')};},url);
  expect(copied.body).toBe(passport);expect(copied.disposition).toContain('attachment');
  await expect(panel(page)).not.toContainText('D:/historic');
  await panel(page).getByRole('button',{name:'다음 실행',exact:true}).click();
  await expect(panel(page).getByText('이 범위에 보관된 실행 자료가 없습니다.',{exact:true})).toBeVisible();
  await page.reload();
  await expect(panel(page).getByRole('button',{name:'실행 자료 보기 · recorded-run',exact:true})).toBeVisible();
  await expect(panel(page).locator('.execution-detail > small')).toHaveAttribute('title','a'.repeat(64));
  await expect(panel(page).getByRole('img',{name:'보관된 매스 미리보기'})).toBeVisible();
  expect(writes).toEqual(['/executions']);
});

test('missing execution evidence stays unavailable and a delayed older detail cannot replace it',async({page})=>{
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
  await setup(page,{delayed:gate});await attachFirst(page);
  await panel(page).getByRole('button',{name:'실행 자료를 프로젝트에 연결 · catalog-b',exact:true}).click();
  await expect(panel(page).getByText('보관된 매스 미리보기가 없습니다.',{exact:true})).toBeVisible();
  await expect(panel(page).getByText('보관된 패스포트가 없습니다.',{exact:true})).toBeVisible();
  release();
  await expect(panel(page).locator('.execution-detail > small')).toHaveAttribute('title','b'.repeat(64));
  await expect(panel(page).getByRole('img')).toHaveCount(0);
  await expect(panel(page).getByRole('link',{name:'원본 패스포트 다운로드'})).toHaveCount(0);
});

test('stale attachment and unavailable storage never become an empty successful catalog',async({page})=>{
  await setup(page,{conflict:true});await attachFirst(page);
  await expect(panel(page).getByRole('alert')).toContainText('409');
  await expect(panel(page).getByRole('button',{name:'실행 자료 보기 · recorded-run',exact:true})).toHaveCount(0);
  await page.route('**/api/v1/platform/projects/artifact-project/design/executions*',r=>r.fulfill({status:503,json:{detail:'unavailable'}}));
  await page.reload();
  await expect(panel(page).getByRole('alert')).toContainText('503');
  await expect(panel(page).getByText('연결된 실행 자료가 없습니다.',{exact:true})).toHaveCount(0);
});

test('a missing PNG is reported without a generated replacement',async({page})=>{
  const writes=await setup(page,{corruptImage:true});await attachFirst(page);
  await expect(panel(page).getByText('이 이미지를 불러올 수 없습니다. 보관본의 누락 또는 손상을 확인해야 합니다.',{exact:true})).toBeVisible();
  await expect(panel(page).getByRole('img')).toHaveCount(0);expect(writes).toEqual(['/executions']);
});

test('more than twenty attached executions remain reachable after reload',async({page})=>{
  await setup(page,{attachedCount:25});await page.goto('/projects/artifact-project');
  await expect(panel(page).getByRole('button',{name:'실행 자료 보기 · historical-19',exact:true})).toBeVisible();
  await panel(page).getByRole('button',{name:'다음 연결 자료',exact:true}).click();
  await expect(panel(page).getByRole('button',{name:'실행 자료 보기 · historical-24',exact:true})).toBeVisible();
  await panel(page).getByRole('button',{name:'실행 자료 보기 · historical-24',exact:true}).click();
  await expect(panel(page).locator('.execution-detail')).toContainText('historical-24');
  await expect(panel(page).getByRole('button',{name:'다음 연결 자료',exact:true})).toBeDisabled();
  await page.reload();
  await panel(page).getByRole('button',{name:'다음 연결 자료',exact:true}).click();
  await expect(panel(page).getByRole('button',{name:'실행 자료 보기 · historical-24',exact:true})).toBeVisible();
});

test('isolated copied execution displays elevation bytes and downloads the pinned passport without generation',async({page,request})=>{
  test.skip(!process.env.EDITOR_EXECUTION_ARTIFACTS||!process.env.EDITOR_ARTIFACT_PROJECT||!process.env.EDITOR_ARTIFACT_CATALOG,'Requires copied artifact catalog and project binding');
  const projectId=process.env.EDITOR_ARTIFACT_PROJECT!;const catalogId=process.env.EDITOR_ARTIFACT_CATALOG!;
  const base=`/api/v1/platform/projects/${encodeURIComponent(projectId)}`;
  const binding=await request.get(base);expect(binding.ok()).toBeTruthy();
  const attached=await request.post(`${base}/design/executions`,{data:{catalog_id:catalogId,scene_revision:(await binding.json()).scene_revision}});
  expect(attached.ok()).toBeTruthy();
  const response=await request.get(`${base}/design/executions/${encodeURIComponent(catalogId)}?limit=100&offset=0`);
  expect(response.ok()).toBeTruthy();const detail=await response.json();
  const writes:string[]=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
  await page.goto(`/projects/${encodeURIComponent(projectId)}`);
  await panel(page).locator(`li[data-catalog-id="${catalogId}"]`).getByRole('button').click();
  await expect(panel(page).locator('.execution-detail > small')).toHaveAttribute('title',detail.execution.snapshot_sha256);
  for(const role of ['preview','elevation_front','elevation_right']){
    const item=detail.items.find((value:{role:string})=>value.role===role);expect(item).toBeTruthy();
    const row=panel(page).locator(`li[data-artifact-id="${item.artifact_id}"]`);
    await row.getByRole('button').click();
    await expect.poll(()=>panel(page).getByRole('img').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBeGreaterThan(0);
    const bytes=await request.get(`${base}/design/executions/${catalogId}/artifacts/${item.artifact_id}`);
    expect(bytes.ok()).toBeTruthy();expect(hash(await bytes.body())).toBe(item.sha256);
  }
  const passportItem=detail.items.find((value:{role:string})=>value.role==='passport');expect(passportItem).toBeTruthy();
  const downloading=page.waitForEvent('download');
  await panel(page).locator(`li[data-artifact-id="${passportItem.artifact_id}"]`).getByRole('link').click();
  const download=await downloading;expect(await download.failure()).toBeNull();
  expect(hash(await readFile((await download.path())!))).toBe(passportItem.sha256);
  await page.reload();
  await expect(panel(page).locator(`li[data-catalog-id="${catalogId}"]`)).toBeVisible();
  await panel(page).locator(`li[data-catalog-id="${catalogId}"]`).getByRole('button').click();
  await expect(panel(page).locator('.execution-detail > small')).toHaveAttribute('title',detail.execution.snapshot_sha256);
  if(detail.execution.replay_reference) {
    const reference=panel(page).getByText(`원본 재실행 참조 미확인: ${detail.execution.replay_reference.source_run_id}`,{exact:true});
    await expect(reference).toBeVisible();
    await reference.scrollIntoViewIfNeeded();
    await page.screenshot({path:'test-results/execution-artifacts-reference.png'});
  }
  const front=detail.items.find((value:{role:string})=>value.role==='elevation_front');
  await panel(page).locator(`li[data-artifact-id="${front.artifact_id}"]`).getByRole('button').click();
  await expect.poll(()=>panel(page).getByRole('img').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBeGreaterThan(0);
  expect(writes).toEqual([]);
  await panel(page).locator('.execution-preview').scrollIntoViewIfNeeded();
  await panel(page).locator('.execution-preview').screenshot({path:'test-results/execution-artifacts-actual.png'});
});
