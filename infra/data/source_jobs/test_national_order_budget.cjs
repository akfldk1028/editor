const test=require('node:test'),assert=require('node:assert/strict');
const {mayOrder}=require('./national-order-budget-guard.cjs');
test('orders wait for downloads and retain the storage reserve',()=>{
  assert.equal(mayOrder(1000000000,100000000000),true);
  assert.equal(mayOrder(5000000000,100000000000),false);
  assert.equal(mayOrder(0,20000000000),false);
  assert.equal(mayOrder(2000000000,22000000000),false);
});
