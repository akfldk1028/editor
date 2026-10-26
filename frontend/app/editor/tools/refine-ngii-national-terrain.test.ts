import {describe,test,expect} from 'bun:test'
import {refineAnchors,assertPassedResumeReceipt,type Anchor} from './refine-ngii-national-terrain'
describe('adaptive native detail',()=>{
 test('rechecks neighbours and refines only failed anchors without replacing tiles',async()=>{
  const a:Anchor[]=[{id:'failed',point:[127,37],native:10},{id:'neighbour',point:[127.00001,37],native:10},{id:'nodata',point:[128,38],native:null}]
  let level=15;const added:number[]=[];let calls=0
  const r=await refineAnchors(a,{sample:async p=>{calls++;return {height:p[0]===128?99:level===15?(p[0]===127?12:10):level===16?(p[0]===127?10:11):10,sourceLevels:[level],ellipsoidZero:false}},exists:async()=>false,add:async k=>{level=k.level;added.push(level)},reset:()=>{}})
  expect(added).toEqual([16,17]);expect(r.passed).toBe(true);expect(r.current.nativeNoData).toBe(1);expect(calls).toBe(9)
 })
 test('never invents a correction for native NoData',async()=>{
  const r=await refineAnchors([{id:'unknown',point:[127,37],native:null}],{sample:async()=>({height:14,sourceLevels:[12],ellipsoidZero:false}),exists:async()=>{throw Error('unexpected')},add:async()=>{throw Error('unexpected')},reset:()=>{}})
  expect(r.added).toBe(0);expect(r.current.nativeNoData).toBe(1)
 })
 test('existing finest data cannot be silently overwritten or declared passing',async()=>{
  let adds=0;const r=await refineAnchors([{id:'bad',point:[127,37],native:10}],{sample:async()=>({height:12,sourceLevels:[20],ellipsoidZero:false}),exists:async()=>true,add:async()=>{adds++},reset:()=>{}})
  expect(r.passed).toBe(false);expect(r.current.errors).toHaveLength(1);expect(adds).toBe(0)
 })
})

test('confirmed empty ancestors still permit native finite detail recovery',async()=>{
 let has=false
 const result=await refineAnchors([{id:'recovered',point:[127,37],native:30}],{sample:async()=>({height:has?30:0,sourceLevels:has?[16]:[],ellipsoidZero:!has}),exists:async()=>false,add:async()=>{has=true},reset:()=>{}})
 expect(result.added).toBe(1);expect(result.passed).toBe(true)
})


test('resume never skips committed failed or malformed region receipts',()=>{
 expect(assertPassedResumeReceipt(JSON.stringify({passed:true})).passed).toBe(true)
 for(const passed of [false,undefined,null,"true",1])expect(()=>assertPassedResumeReceipt(JSON.stringify({passed}))).toThrow('Previous refinement failed')
})
