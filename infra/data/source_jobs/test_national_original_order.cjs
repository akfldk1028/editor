const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { start } = require('./national-original-order.cjs');

test('expired login prevents orders and reports the actual blocker', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ngii-order-test-'));
  const context = {request: {post: async url => {
    assert.equal(url, 'https://map.ngii.go.kr/mn/loginCheck.do');
    return {json: async () => ({isLogin:false})};
  }}};
  const result = await start(context, root, root);
  assert.equal(result.state, 'login_required');
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'batch-order-status.json'))).orderedThisRun, 0);
});
