'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync('reportbuilder/static/reportbuilder/llm-settings.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(fetch) {
  const dom = new JSDOM(`<!doctype html><form id="llm-settings-form" data-models-url="/settings/api/external/models/" data-saved-key="false">
    <input name="csrfmiddlewaretoken" value="csrf-token"><select name="provider" required><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select>
    <input name="base_url" value="https://api.openai.com/v1" required><input name="api_key" type="password" value="private-secret">
    <select name="model" required><option value="">Load models first</option></select><input name="model_ticket" type="hidden">
    <button type="button" id="llm-load-models">Load models</button><span id="llm-model-status"></span><button type="submit">Save</button></form>
    <script type="application/json" id="llm-provider-base-urls">{"openai":"https://api.openai.com/v1","anthropic":"https://api.anthropic.com/v1"}</script>`, {runScripts: 'outside-only'});
  dom.window.fetch = fetch;
  dom.window.eval(script);
  return {dom, window: dom.window, form: dom.window.document.querySelector('form'),
    button: dom.window.document.querySelector('#llm-load-models'), status: dom.window.document.querySelector('#llm-model-status')};
}
test('model lookup uses POST and CSRF and renders untrusted labels only as text', async () => {
  let request;
  const ui = setup(async (url, options) => {
    request = {url, options};
    return {ok: true, json: async () => ({models: [{id: 'safe-model', label: '<img src=x onerror=alert(1)>'}], model_ticket: 'signed-ticket'})};
  });
  ui.button.click(); await tick();
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers['X-CSRFToken'], 'csrf-token');
  assert.equal(JSON.parse(request.options.body).api_key, 'private-secret');
  assert(!request.url.includes('private-secret'));
  assert.equal(ui.form.elements.model.value, 'safe-model');
  assert.equal(ui.form.elements.model_ticket.value, 'signed-ticket');
  assert.equal(ui.form.querySelectorAll('img').length, 0);
  ui.dom.window.close();
});
test('changed credentials discard an in-flight JSON body even when abort is ignored', async () => {
  let resolveJSON;
  const ui = setup(async () => ({ok: true, json: () => new Promise(resolve => {resolveJSON = resolve;})}));
  ui.button.click(); await tick();
  ui.form.elements.api_key.value = 'new-secret';
  ui.form.elements.api_key.dispatchEvent(new ui.window.Event('input'));
  resolveJSON({models: [{id: 'old-model', label: 'Old'}], model_ticket: 'stale-ticket'});
  await tick();
  assert.equal(ui.form.elements.model_ticket.value, '');
  assert.equal(ui.form.elements.model.options.length, 1);
  assert.equal(ui.button.disabled, false);
  ui.dom.window.close();
});
test('errors clear stale choices and provider changes replace the base URL', async () => {
  const ui = setup(async () => ({ok: false, json: async () => ({message: 'Denied'})}));
  ui.form.elements.model_ticket.value = 'old-ticket';
  ui.button.click(); await tick();
  assert.equal(ui.status.textContent, 'Denied');
  assert.equal(ui.form.elements.model_ticket.value, '');
  assert.equal(ui.form.elements.model.options.length, 1);
  ui.form.elements.provider.value = 'anthropic';
  ui.form.elements.provider.dispatchEvent(new ui.window.Event('change'));
  assert.equal(ui.form.elements.base_url.value, 'https://api.anthropic.com/v1');
  ui.dom.window.close();
});
