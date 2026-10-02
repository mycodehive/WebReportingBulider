'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');
const script = fs.readFileSync(path.resolve(__dirname, '../../reportbuilder/static/reportbuilder/connections.js'), 'utf8');
const turn = () => new Promise(resolve => setTimeout(resolve, 0));

function fixture(t) {
 const dom = new JSDOM(`<div class="connections-page">
  ${['one', 'two'].map(id => `<span data-status="${id}">테스트 필요</span>
   <button data-test-connection="${id}" data-connection-name="${id}">연결 테스트</button>
   <p id="connection-result-${id}" role="status"></p>`).join('')}
  <details open><summary tabindex="0">수정</summary><form><input name="name" value="Original">
   <button type="button" data-cancel-edit>취소</button></form></details>
  <form class="connection-delete-form"><button type="submit" data-connection-delete="Warehouse">삭제</button></form>
 </div>`, { runScripts: 'outside-only' });
 t.after(() => dom.window.close());
 dom.window.eval(script);
 return dom.window;
}

test('concurrent tests keep pending and results local to each connection and allow retry', async t => {
 const w = fixture(t), d = w.document;
 const pending = {};
 w.reportRequest = url => new Promise((resolve, reject) => { pending[url.split('/')[3]] = { resolve, reject }; });
 const first = d.querySelector('[data-test-connection="one"]');
 const second = d.querySelector('[data-test-connection="two"]');
 first.click(); second.click();
 assert.equal(first.disabled, true);
 assert.equal(first.textContent, '테스트 중…');
 assert.equal(first.getAttribute('aria-busy'), 'true');
 pending.one.resolve({});
 pending.two.reject(new Error('접근 권한 없음'));
 await turn();
 assert.equal(d.querySelector('[data-status="one"]').textContent, '연결 확인됨');
 assert.equal(d.querySelector('[data-status="two"]').textContent, '테스트 실패');
 assert.match(d.getElementById('connection-result-two').textContent, /접근 권한 없음/);
 assert.equal(first.disabled, false);
 assert.equal(second.textContent, '연결 테스트');
 assert.equal(second.hasAttribute('aria-busy'), false);
 second.click(); pending.two.resolve({}); await turn();
 assert.equal(d.getElementById('connection-result-two').dataset.state, 'success');
});

test('cancel restores saved values, closes editor and returns focus', t => {
 const w = fixture(t), d = w.document;
 d.querySelector('[name="name"]').value = 'Unsaved';
 d.querySelector('[data-cancel-edit]').click();
 assert.equal(d.querySelector('[name="name"]').value, 'Original');
 assert.equal(d.querySelector('details').open, false);
 assert.equal(d.activeElement, d.querySelector('summary'));
});

test('delete cancellation preserves controls; confirmation blocks duplicate submission', t => {
 const w = fixture(t), d = w.document;
 const form = d.querySelector('.connection-delete-form'), button = form.querySelector('button');
 function submit() {
  const event = new w.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: button });
  form.dispatchEvent(event);
  return event;
 }
 w.confirm = () => false;
 assert.equal(submit().defaultPrevented, true);
 assert.equal(button.disabled, false);
 w.confirm = () => true;
 assert.equal(submit().defaultPrevented, false);
 assert.equal(button.disabled, true);
 assert.equal(button.textContent, '삭제 중…');
 assert.equal(submit().defaultPrevented, true);
});
