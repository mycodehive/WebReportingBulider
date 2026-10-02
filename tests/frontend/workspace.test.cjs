'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const { JSDOM } = require('jsdom');
const projectRoot = path.resolve(__dirname, '../..');
const fixture = spawnSync('uv', ['run', 'python', 'tests/frontend/fixture.py', 'render'], {
  cwd: projectRoot, encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' },
});
assert.equal(fixture.status, 0, fixture.stderr || fixture.error?.message);
const template = JSON.parse(fixture.stdout).html;
const script = fs.readFileSync(path.join(projectRoot, 'reportbuilder/static/reportbuilder/workspace.js'), 'utf8');

function workspace(t, options = {}) {
  const dom = new JSDOM(template, { runScripts: 'outside-only', url: 'http://localhost/reports/example/design/' });
  t.after(() => dom.window.close());
  const { window } = dom;
  let mediaListener;
  window.matchMedia = () => ({ matches: Boolean(options.systemDark), addEventListener: (_event, fn) => { mediaListener = fn; } });
  if (options.theme) window.localStorage.setItem('webreport.theme', options.theme);
  if (options.sidebar) window.localStorage.setItem('webreport.sidebar', options.sidebar);
  if (options.blockStorage) Object.defineProperty(window, 'localStorage', { get() { throw new window.DOMException('Unavailable', 'SecurityError'); } });
  window.eval(script);
  window.document.dispatchEvent(new window.Event('DOMContentLoaded'));
  return { window, document: window.document, mediaChange: matches => mediaListener({ matches }) };
}
const turn = () => new Promise(resolve => setTimeout(resolve, 0));

function nativeFullscreen(document, designer, reject = false) {
  let active = null;
  Object.defineProperty(document, 'fullscreenElement', { get: () => active, configurable: true });
  designer.requestFullscreen = async () => {
    if (reject) throw new Error('Fullscreen permission denied');
    active = designer;
    document.dispatchEvent(new document.defaultView.Event('fullscreenchange'));
  };
  document.exitFullscreen = async () => {
    active = null;
    document.dispatchEvent(new document.defaultView.Event('fullscreenchange'));
  };
  return { browserEscape: () => { active = null; document.dispatchEvent(new document.defaultView.Event('fullscreenchange')); } };
}

test('theme follows system initially, persists user choice and preserves report content', t => {
  const { window, document, mediaChange } = workspace(t, { systemDark: true });
  const button = document.getElementById('theme-toggle');
  const definition = document.getElementById('report-definition').textContent;
  assert.equal(document.documentElement.dataset.theme, 'dark');
  assert.equal(button.getAttribute('aria-label'), '라이트 모드 사용');
  button.click();
  assert.equal(document.documentElement.dataset.theme, 'light');
  assert.equal(window.localStorage.getItem('webreport.theme'), 'light');
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  mediaChange(true);
  assert.equal(document.documentElement.dataset.theme, 'light', 'explicit preference takes priority over system');
  assert.equal(document.getElementById('report-definition').textContent, definition, 'theme never rewrites report definition');
  const next = workspace(t, { theme: window.localStorage.getItem('webreport.theme'), systemDark: true });
  assert.equal(next.document.documentElement.dataset.theme, 'light', 'theme survives navigation/reload');
});

test('sidebar collapses with accessible links and reopens from persistent preference', t => {
  const { window, document } = workspace(t, { sidebar: 'collapsed' });
  const toggle = document.getElementById('sidebar-toggle');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.documentElement.dataset.sidebar, 'collapsed');
  const links = [...document.querySelectorAll('#global-sidebar nav a')];
  assert(links.length >= 4);
  assert(links.every(link => link.getAttribute('aria-label') && link.getAttribute('href') && link.querySelector('.nav-icon')));
  toggle.click();
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(window.localStorage.getItem('webreport.sidebar'), 'expanded');
  toggle.click();
  const next = workspace(t, { sidebar: window.localStorage.getItem('webreport.sidebar') });
  assert.equal(next.document.getElementById('sidebar-toggle').getAttribute('aria-expanded'), 'false');
});

test('workspace preferences operate without storage access and synchronize across tabs', t => {
  const denied = workspace(t, { blockStorage: true });
  denied.document.getElementById('theme-toggle').click();
  denied.document.getElementById('sidebar-toggle').click();
  assert.equal(denied.document.documentElement.dataset.theme, 'dark');
  assert.equal(denied.document.documentElement.dataset.sidebar, 'collapsed');
  const shared = workspace(t);
  shared.window.dispatchEvent(new shared.window.StorageEvent('storage', { key: 'webreport.theme', newValue: 'dark' }));
  shared.window.dispatchEvent(new shared.window.StorageEvent('storage', { key: 'webreport.sidebar', newValue: 'collapsed' }));
  assert.equal(shared.document.documentElement.dataset.theme, 'dark');
  assert.equal(shared.document.getElementById('theme-toggle').getAttribute('aria-pressed'), 'true');
  assert.equal(shared.document.documentElement.dataset.sidebar, 'collapsed');
});

test('native fullscreen includes save, preview and modal dialogs; browser Escape restores state', async t => {
  const { document } = workspace(t);
  const designer = document.getElementById('designer');
  const button = document.getElementById('workspace-fullscreen');
  const browser = nativeFullscreen(document, designer);
  button.click();
  assert.equal(button.disabled, true, 'duplicate fullscreen requests are blocked');
  await turn();
  assert.equal(document.fullscreenElement, designer);
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  assert.equal(button.disabled, false);
  for (const id of ['save', 'preview', 'preview-dialog', 'query-dialog', 'mapping-dialog', 'designer-workspace']) {
    assert(designer.contains(document.getElementById(id)), `${id} remains within the fullscreen root`);
  }
  browser.browserEscape();
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  assert.equal(document.activeElement, button, 'focus returns to the exit/enter action');
  button.click();
  await turn();
  button.click();
  await turn();
  assert.equal(document.fullscreenElement, null);
  assert.equal(designer.classList.contains('is-fullscreen'), false);
});

test('fallback fullscreen remains usable when unsupported or denied; Escape respects open dialogs', async t => {
  for (const denied of [false, true]) {
    const { window, document } = workspace(t);
    const designer = document.getElementById('designer');
    const button = document.getElementById('workspace-fullscreen');
    if (denied) nativeFullscreen(document, designer, true);
    button.click();
    await turn();
    assert(document.body.classList.contains('workspace-fullscreen-fallback'));
    assert.equal(button.getAttribute('aria-pressed'), 'true');
    const dialog = document.getElementById('preview-dialog');
    dialog.setAttribute('open', '');
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert(document.body.classList.contains('workspace-fullscreen-fallback'), 'dialog Escape does not exit the workspace');
    dialog.removeAttribute('open');
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(button.getAttribute('aria-pressed'), 'false');
    assert.equal(document.body.classList.contains('workspace-fullscreen-fallback'), false);
    assert.equal(document.activeElement, button);
  }
});
