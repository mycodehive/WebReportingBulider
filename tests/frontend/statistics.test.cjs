'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const { JSDOM, VirtualConsole } = require('jsdom');

const root = path.resolve(__dirname, '../..');
const rendered = spawnSync('uv', ['run', 'python', 'tests/frontend/fixture.py', 'library'], {
  cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' }, maxBuffer: 2 * 1024 * 1024,
});
assert.equal(rendered.status, 0, rendered.stderr);
const html = JSON.parse(rendered.stdout).html;
const script = fs.readFileSync(path.join(root, 'reportbuilder/static/reportbuilder/statistics.js'), 'utf8');

function summary(overrides = {}) {
  return {
    report: { id: '00000000-0000-0000-0000-000000000001', name: 'Test report' },
    range: { start: '2026-10-01', end: '2026-10-02', timezone: 'Asia/Seoul', days: 2 },
    filters: { event: '', country: '', device: '', browser: '' },
    total: 6, event_counts: [{ event: 'view', count: 3 }, { event: 'execute', count: 2 }, { event: 'embed', count: 1 }],
    countries: [{ country: 'KR', count: 4 }, { country: 'Unknown', count: 1 }, { country: 'Private', count: 1 }],
    devices: [{ device: 'desktop', count: 6 }], browsers: [{ browser: 'chrome', count: 6 }],
    daily: [{ date: '2026-10-01', count: 1 }, { date: '2026-10-02', count: 5 }],
    recent: [{ timestamp: '2026-10-02T12:30:00+09:00', event: 'view', country: 'KR',
      device: 'desktop', browser: 'chrome', os: '<img src=x onerror="alert(1)">' }],
    recent_limit: 100, details_total: 6, details_truncated: true,
    meta: { geolocation: { available: false, mode: 'unavailable' } },
    ...overrides,
  };
}

function response(data, status = 200, contentType = 'application/json') {
  return { ok: status >= 200 && status < 300, status,
    headers: { get: name => name.toLowerCase() === 'content-type' ? contentType : null },
    json: async () => data, blob: async () => new Blob(['test-export'], { type: contentType }) };
}

async function waitFor(condition, description) {
  const deadline = Date.now() + 2000;
  while (!condition()) {
    assert(Date.now() < deadline, `Timed out: ${description}`);
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

function harness(t, transport) {
  const errors = [], requests = [], downloads = [];
  const console = new VirtualConsole(); console.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/reports/', virtualConsole: console });
  t.after(() => dom.window.close());
  const window = dom.window, document = window.document;
  const byId = id => document.getElementById(id);
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new window.Event('close')); };
  window.URL.createObjectURL = () => 'blob:statistics-test';
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () { downloads.push({ href: this.href, filename: this.download }); };
  window.fetch = (url, options) => { requests.push({ url, options }); return transport(url, options, requests.length); };
  window.eval(script);
  const buttons = [...document.querySelectorAll('[data-report-statistics]')];
  const form = byId('statistics-filter-form');
  const submit = () => form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  return { window, document, byId, buttons, form, submit, requests, downloads, errors };
}

test('library analytics renders safe summaries and exports the applied filters', async t => {
  let pdfFailure = false;
  const h = harness(t, async url => {
    if (url.includes('/export/pdf/')) return response({ message: 'PDF 드라이버를 설치하세요.' }, pdfFailure ? 503 : 200, pdfFailure ? 'application/json' : 'application/pdf');
    if (url.includes('/export/xlsx/')) return response({}, 200, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    return response(summary());
  });
  assert.equal(h.buttons.length, 2, 'shared users do not see owner-only statistics');
  h.buttons[0].click();
  await waitFor(() => !h.byId('statistics-results').hidden, 'initial analytics response');
  assert.equal(h.document.activeElement, h.byId('statistics-close'), 'modal starts with accessible close focus');
  assert(h.byId('statistics-title').textContent.includes('<img'), 'report title is rendered as plain text');
  assert.equal(h.byId('statistics-dialog').querySelectorAll('img').length, 0, 'untrusted titles/OS strings do not become HTML');
  assert.equal(h.document.querySelector('[data-stat-kpi=total] strong').textContent, '6');
  assert.equal(h.document.querySelector('[data-stat-kpi=embed] strong').textContent, '1');
  assert.equal(h.document.querySelectorAll('#statistics-daily-chart rect').length, 2);
  assert.equal(h.byId('statistics-daily-rows').children.length, 2);
  assert(h.byId('statistics-recent-note').textContent.includes('전체 6건 중 최근 1건'));
  assert(h.document.querySelector('.statistics-footer-note').textContent.includes('Private'));

  h.form.elements.start.value = '2026-10-01'; h.form.elements.end.value = '2026-10-02';
  h.form.elements.event.value = 'view'; h.form.elements.country.value = 'kr';
  h.form.elements.device.value = 'mobile'; h.form.elements.browser.value = 'chrome'; h.submit();
  await waitFor(() => !h.byId('statistics-results').hidden, 'filtered analytics response');
  const applied = new URL(h.requests.at(-1).url, 'http://localhost');
  assert.equal(applied.searchParams.get('country'), 'KR');
  assert.equal(applied.searchParams.get('event'), 'view');
  assert.equal(h.requests.at(-1).options.credentials, 'same-origin');
  // Editing a control without submitting must not change the downloaded result set.
  h.form.elements.country.value = 'US';
  h.document.querySelector('[data-statistics-export=xlsx]').click();
  await waitFor(() => h.downloads.length === 1, 'Excel download');
  const exportUrl = new URL(h.requests.at(-1).url, 'http://localhost');
  assert.equal(exportUrl.search, applied.search, 'export uses the exact applied filter snapshot');
  assert.equal(h.downloads[0].filename, 'report-statistics-2026-10-01-2026-10-02.xlsx');
  await waitFor(() => !h.document.querySelector('[data-statistics-export=pdf]').disabled, 'download buttons restored');
  pdfFailure = true; h.document.querySelector('[data-statistics-export=pdf]').click();
  await waitFor(() => !h.byId('statistics-error').hidden, 'PDF dependency error');
  assert.equal(h.byId('statistics-error').textContent, 'PDF 드라이버를 설치하세요.');
  assert.equal(h.downloads.length, 1, 'failed exports do not save an error response as PDF');
  h.byId('statistics-dialog').dispatchEvent(new h.window.Event('cancel', { cancelable: true }));
  assert(!h.byId('statistics-dialog').open, 'Escape/cancel closes the layer');
  assert.equal(h.document.activeElement, h.buttons[0], 'focus returns to the opener');
  assert.deepEqual(h.errors, []);
});

test('analytics aborts and ignores stale responses across filters and report dialogs', async t => {
  const pending = [];
  const h = harness(t, (url, options) => new Promise(resolve => pending.push({ url, options, resolve })));
  h.buttons[0].click();
  assert(h.byId('statistics-status').textContent.includes('불러오는 중'));
  h.form.elements.event.value = 'embed'; h.submit();
  assert(pending[0].options.signal.aborted, 'filter refresh aborts prior request');
  pending[1].resolve(response(summary({ total: 2 })));
  await waitFor(() => !h.byId('statistics-results').hidden, 'new filter response');
  pending[0].resolve(response(summary({ total: 999 })));
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(h.document.querySelector('[data-stat-kpi=total] strong').textContent, '2', 'stale transport cannot overwrite current statistics');
  h.submit();
  h.byId('statistics-close').click();
  assert(pending[2].options.signal.aborted, 'closing the dialog aborts its request');
  h.buttons[1].click();
  pending[3].resolve(response(summary({ total: 4 })));
  await waitFor(() => !h.byId('statistics-results').hidden, 'second report response');
  pending[2].resolve(response(summary({ total: 888 })));
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(h.document.querySelector('[data-stat-kpi=total] strong').textContent, '4');
  assert(h.byId('statistics-title').textContent.includes('둘째 보고서'));
  assert.deepEqual(h.errors, []);
});

test('analytics handles empty data, denied access and invalid ranges without stale results', async t => {
  let denied = false;
  const h = harness(t, async () => denied
    ? response({ message: '통계를 볼 권한이 없습니다.' }, 403)
    : response(summary({ total: 0, event_counts: [], countries: [], devices: [], browsers: [], recent: [], details_total: 0, details_truncated: false })));
  h.buttons[0].click();
  await waitFor(() => !h.byId('statistics-results').hidden, 'empty analytics response');
  assert(!h.byId('statistics-empty').hidden);
  assert(h.byId('statistics-recent-rows').textContent.includes('이용 기록이 없습니다'));
  const count = h.requests.length;
  h.form.elements.start.value = '2026-10-10'; h.form.elements.end.value = '2026-10-01'; h.submit();
  assert.equal(h.requests.length, count, 'invalid ranges do not reach the API');
  assert(h.byId('statistics-error').textContent.includes('시작일'));
  assert(h.byId('statistics-results').hidden, 'invalid filters do not leave old results displayed');
  denied = true;
  h.byId('statistics-reset').click();
  await waitFor(() => h.byId('statistics-error').textContent.includes('권한'), 'access error');
  assert(h.byId('statistics-results').hidden);
  assert([...h.document.querySelectorAll('[data-statistics-export]')].every(button => button.disabled));
  assert.deepEqual(h.errors, []);
});
