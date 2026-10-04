'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync('reportbuilder/static/reportbuilder/admin-email-verification.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(fetch) {
  const users = [{id: '1', username: '<img src=x onerror=alert(1)>', email: 'one@example.com'},
    {id: '2', username: 'two', email: 'two@example.com'}, {id: '3', username: 'three', email: ''}];
  const dom = new JSDOM(`<!doctype html><form id="email-verification-batch" data-send-url="/admin/auth/user/email-verification-send/">
    <input name="csrfmiddlewaretoken" value="csrf-token"><input name="ticket" value="signed-ticket"><button type="button" id="email-batch-stop">Stop</button></form>
    <p id="email-batch-status"></p><table id="email-batch-results"><tbody></tbody></table>
    <script type="application/json" id="email-batch-recipients">${JSON.stringify(users)}</script>`, {runScripts: 'outside-only'});
  dom.window.fetch = fetch;
  dom.window.eval(script);
  return {dom, doc: dom.window.document};
}
test('selected-user requests carry POST, CSRF and ticket; per-user errors continue and labels are safe', async () => {
  const calls = [];
  const statuses = ['error', 'sent', 'verified'];
  const ui = setup(async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({status: statuses[calls.length - 1], message: '<svg onload=alert(1)>'})};
  });
  await tick();
  assert.equal(calls.length, 3);
  for (let i = 0; i < calls.length; i++) {
    assert.equal(calls[i].options.method, 'POST');
    assert.equal(calls[i].options.redirect, 'error');
    assert.equal(calls[i].options.body.get('csrfmiddlewaretoken'), 'csrf-token');
    assert.equal(calls[i].options.body.get('ticket'), 'signed-ticket');
    assert.equal(calls[i].options.body.get('user_id'), String(i + 1));
  }
  assert.equal(ui.doc.querySelectorAll('img, svg').length, 0);
  assert.match(ui.doc.querySelector('#email-batch-status').textContent, /발송 1명.*제외 1명.*실패 1명.*처리 완료/);
  ui.dom.window.close();
});
test('stop waits for the in-flight response and leaves remaining recipients unsent', async () => {
  let resolve, calls = 0;
  const ui = setup(() => {
    calls++;
    return new Promise(done => {resolve = done;});
  });
  ui.doc.querySelector('#email-batch-stop').click();
  resolve({ok: true, json: async () => ({status: 'sent', message: 'accepted'})});
  await tick();
  assert.equal(calls, 1);
  assert.equal(ui.doc.querySelectorAll('tbody td:last-child')[1].textContent, '발송하지 않음');
  assert.match(ui.doc.querySelector('#email-batch-status').textContent, /중지됨/);
  ui.dom.window.close();
});
test('permission failure or unknown network result stops further requests', async () => {
  for (const network of [false, true]) {
    let calls = 0;
    const ui = setup(async () => {
      calls++;
      if (network) throw Error('network lost');
      return {ok: false, json: async () => ({status: 'error', message: 'denied'})};
    });
    await tick();
    assert.equal(calls, 1);
    assert.match(ui.doc.querySelector('#email-batch-status').textContent, /중지됨/);
    ui.dom.window.close();
  }
});
