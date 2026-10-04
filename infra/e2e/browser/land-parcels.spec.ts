import {test, expect} from '@playwright/test';

const polygon = [[[127,37],[127.01,37],[127.01,37.01],[127,37.01],[127,37]],
  [[127.002,37.002],[127.004,37.002],[127.004,37.004],[127.002,37.004],[127.002,37.002]]];
test.beforeEach(async ({page}) => {
  await page.route('**/api/v1/land/zones',r=>r.fulfill({json:{zones:[]}}));
  await page.route('**/api/v1/land/stats',r=>r.fulfill({json:{total_queries:0,error_count:0,avg_response_time_ms:0,by_input_type:[]}}));
});

test('PNU boundary preview keeps holes and clears when input changes',async ({page})=>{
  await page.route('**/api/v1/land/parcel-geometry',r=>{
    expect(r.request().postDataJSON()).toEqual({pnu:'1168011200101280003'});
    return r.fulfill({json:{success:true,geometry:{type:'Polygon',coordinates:polygon}}});
  });
  await page.goto('/land');
  await page.getByLabel('주소 또는 PNU').fill('11680-11200-10128-0003');
  await page.getByRole('button',{name:'PNU 경계 조회',exact:true}).click();
  const preview=page.getByRole('img',{name:'필지 경계 미리보기'});
  await expect(preview).toBeVisible();
  await expect(preview.locator('path')).toHaveAttribute('fill-rule','evenodd');
  expect((await preview.locator('path').getAttribute('d'))?.match(/M/g)).toHaveLength(2);
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280004');
  await expect(preview).toHaveCount(0);
});

test('coordinate lookup displays multiple polygons and failure clears prior preview',async ({page})=>{
  let calls=0;
  await page.route('**/api/v1/land/reverse',r=>{
    expect(r.request().postDataJSON()).toEqual({x:127,y:37});
    return r.fulfill({json:++calls===1?{success:true,pnu:null,address:'조회 주소',coordinates:{x:127,y:37},
      geometry:{type:'MultiPolygon',coordinates:[polygon,[[[127.02,37],[127.03,37],[127.03,37.01],[127.02,37]]]]}}:
      {success:false,pnu:null,address:null,coordinates:{x:127,y:37},geometry:null,error:'Parcel lookup is not configured'}});
  });
  await page.goto('/land');
  await page.getByLabel('경도').fill('127');await page.getByLabel('위도').fill('37');
  await page.getByRole('button',{name:'좌표 경계 조회',exact:true}).click();
  await expect(page.getByRole('img',{name:'필지 경계 미리보기'}).locator('path')).toHaveCount(2);
  await expect(page.getByText('조회 주소',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'좌표 경계 조회',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('설정');
  await expect(page.getByRole('img',{name:'필지 경계 미리보기'})).toHaveCount(0);
});

test('malformed geometry cannot become a preview',async ({page})=>{
  await page.route('**/api/v1/land/parcel-geometry',r=>r.fulfill({json:{success:true,geometry:{type:'Polygon',coordinates:[[[127,37]]]}}}));
  await page.goto('/land');await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  await page.getByRole('button',{name:'PNU 경계 조회',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('응답 형식');
  await expect(page.getByRole('img',{name:'필지 경계 미리보기'})).toHaveCount(0);
});

test('input changes abort an in-flight boundary lookup',async ({page})=>{
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/v1/land/parcel-geometry',async r=>{
    await gate;
    await r.fulfill({json:{success:true,geometry:{type:'Polygon',coordinates:polygon}}}).catch(()=>{});
  });
  await page.goto('/land');await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  const sent=page.waitForRequest('**/api/v1/land/parcel-geometry');
  await page.getByRole('button',{name:'PNU 경계 조회',exact:true}).click();await sent;
  await page.getByLabel('주소 또는 PNU').fill('1168011200101280004');
  release();
  await expect(page.getByRole('button',{name:'PNU 경계 조회',exact:true})).toBeEnabled();
  await expect(page.getByRole('img',{name:'필지 경계 미리보기'})).toHaveCount(0);
});

test('browser reaches real Editor parcel routes with provider fixture',async ({page})=>{
  test.skip(!process.env.EDITOR_PARCEL_FIXTURE,'Requires isolated fixture backend');
  await page.goto('/land');await page.getByLabel('주소 또는 PNU').fill('1168011200101280003');
  const parcel=page.waitForResponse('**/api/v1/land/parcel-geometry');
  await page.getByRole('button',{name:'PNU 경계 조회',exact:true}).click();
  expect((await parcel).status()).toBe(200);
  await expect(page.getByRole('img',{name:'필지 경계 미리보기'})).toBeVisible();
  await page.getByLabel('경도').fill('127');await page.getByLabel('위도').fill('37');
  const reverse=page.waitForResponse('**/api/v1/land/reverse');
  await page.getByRole('button',{name:'좌표 경계 조회',exact:true}).click();
  expect((await reverse).status()).toBe(200);
  await expect(page.getByText('Fixture parcel address',{exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/editor-parcel-preview.png',fullPage:true});
});
