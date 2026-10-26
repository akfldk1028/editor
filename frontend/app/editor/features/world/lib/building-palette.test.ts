import {expect,test} from 'bun:test'
import {buildingColor} from './building-palette'

test('default masses share one opaque colour without changing height classification',()=>{
  expect(['m','e','u'].map(s=>buildingColor(s,false))).toEqual(['#fbfbf9','#fbfbf9','#fbfbf9'])
  expect(buildingColor('u',true)).toBe('#c7c7c2')
  expect(buildingColor('m',true)).toBe('#fbfbf9')
})
