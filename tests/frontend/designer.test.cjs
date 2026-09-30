'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const { JSDOM, VirtualConsole } = require('jsdom');

const projectRoot = path.resolve(__dirname, '../..');

function pythonFixture(action, payload) {
  const result = spawnSync('uv', ['run', 'python', 'tests/frontend/fixture.py', action], {
    cwd: projectRoot,
    encoding: 'utf8',
    env: { ...process.env, PYTHONUTF8: '1' },
    input: payload === undefined ? undefined : JSON.stringify(payload),
    maxBuffer: 5 * 1024 * 1024,
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return JSON.parse(result.stdout);
}

async function waitFor(condition, description) {
  const deadline = Date.now() + 2500;
  while (!condition()) {
    assert(Date.now() < deadline, `Timed out: ${description}`);
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

test('designer interactions produce portable, backend-valid and executable reports', async t => {
  const fixture = pythonFixture('render');
  const script = fs.readFileSync(path.join(projectRoot, 'reportbuilder/static/reportbuilder/designer.js'), 'utf8');
  const virtualConsole = new VirtualConsole();
  const errors = [];
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM(fixture.html, {
    runScripts: 'outside-only',
    url: `http://localhost/reports/${fixture.report.id}/design/`,
    virtualConsole,
  });
  t.after(() => dom.window.close());
  const window = dom.window;
  const document = window.document;
  const byId = id => document.getElementById(id);
  const requests = [];
  const definitions = [];
  let revision = fixture.report.revision;
  let savedBindings = [];

  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  window.addEventListener('error', event => errors.push(event.message));
  window.fetch = async (url, config) => {
    const body = config.body ? JSON.parse(config.body) : null;
    requests.push({ url, body });
    let value;
    if (url === '/api/connections/') {
      value = fixture.connections;
    } else if (url.endsWith('/schema/')) {
      value = fixture.schema;
    } else if (config.method === 'PUT' && url.endsWith('/bindings/')) {
      savedBindings = body.bindings;
      value = { revision: ++revision };
    } else if (config.method === 'PUT') {
      assert.equal(body.expected_revision, revision, 'save must use the revision returned by binding save');
      definitions.push(body.definition);
      value = { revision: ++revision };
    } else if (url.endsWith('/preview/')) {
      value = { html: '<p>Safe report preview</p>', page_count: 2 };
    } else if (url.endsWith('/publish/')) {
      value = { publication_url: '/published/example/' };
    } else {
      value = fixture.report;
    }
    return { ok: true, json: async () => value };
  };

  function change(control, value) {
    assert(control, 'Expected an editable control');
    control.value = value;
    control.dispatchEvent(new window.Event('change', { bubbles: true }));
  }

  function property(label) {
    return [...document.querySelectorAll('#properties label.field')]
      .find(element => element.querySelector('span')?.textContent === label)
      ?.querySelector('input,select,textarea');
  }

  function dragField(source, target) {
    const values = {};
    const dataTransfer = {
      types: ['application/report-element'],
      setData: (type, value) => { values[type] = value; },
      getData: type => values[type],
    };
    for (const [element, type] of [[source, 'dragstart'], [target, 'drop']]) {
      const event = new window.Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        dataTransfer: { value: dataTransfer }, clientX: { value: 0 }, clientY: { value: 0 },
      });
      element.dispatchEvent(event);
    }
  }

  async function save() {
    const previous = requests.filter(request => request.url.endsWith('/bindings/')).length;
    byId('save').click();
    await waitFor(() => requests.filter(request => request.url.endsWith('/bindings/')).length > previous,
      'report and local bindings saved');
    await waitFor(() => byId('save-state').textContent.includes(String(revision)), 'revision status updated');
  }

  window.eval(script);
  await waitFor(() => byId('connection-select').options.length === 2, 'available connections loaded');
  assert.equal(document.querySelectorAll('.canvas-element').length, 1, 'initial title renders');
  change(byId('connection-select'), fixture.connections.connections[0].id);
  await waitFor(() => byId('object-select').options.length === 2, 'real connector schema loaded');
  change(byId('object-select'), '0');
  byId('add-dataset').click();
  assert.equal(document.querySelectorAll('.field-item').length, 2);
  document.querySelector('.field-item').click();
  assert.equal(property('데이터 범위').value, 'first', 'fixed page binds the first row');
  await save();

  document.querySelector('.printable-area').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  change(property('출력 방식'), 'flow');
  assert.equal(document.querySelectorAll('.canvas-band').length, 2, 'flow conversion preserves title in header');
  dragField(document.querySelectorAll('.field-item')[1], document.querySelectorAll('.canvas-band')[1]);
  assert.equal(property('데이터 범위').value, 'row', 'dragged field repeats in matching detail band');

  byId('open-query').click();
  byId('add-parameter').click();
  const parameterRow = document.querySelector('.parameter-row');
  change(parameterRow.children[0], 'min_salary');
  change(parameterRow.children[2], 'number');
  change(parameterRow.children[3], '100.25');
  byId('add-filter').click();
  const filterRow = document.querySelector('.filter-row');
  change(filterRow.children[0], definitions[0].datasets[0].fields[1].field_id);
  change(filterRow.children[2], 'parameter');
  change(document.querySelector('.filter-row').children[3], 'min_salary');
  byId('add-sort').click();
  byId('apply-query').click();
  assert(!byId('query-dialog').hasAttribute('open'), 'valid query settings apply');

  byId('open-mapping').click();
  assert.equal(document.querySelectorAll('#mapping-fields select[data-field-id]').length, 2);
  change(document.querySelectorAll('#mapping-fields [data-conversion-field-id]')[1], 'to_decimal');
  byId('apply-mapping').click();
  assert(!byId('mapping-dialog').hasAttribute('open'), 'local mapping applies independently from report');
  change(byId('band-type'), 'ReportFooter');
  byId('add-band').click();
  document.querySelectorAll('.field-item')[1].click();
  change(property('데이터 범위'), 'aggregate');
  change(property('집계 방식'), 'sum');
  await save();
  const salaryId = definitions.at(-1).datasets[0].fields[1].field_id;
  assert.equal(savedBindings[0].field_mappings[salaryId].conversion, 'to_decimal');
  assert.equal(definitions.at(-1).parameters[0].default, 100.25, 'numeric default is JSON numeric data');
  assert(!JSON.stringify(definitions.at(-1)).includes('connection_id'), 'connection identifiers stay outside project definition');

  byId('add-page').click();
  assert.equal(byId('page-label').textContent, '페이지 2 / 2');
  byId('copy-page').click();
  assert.equal(byId('page-label').textContent, '페이지 3 / 3');
  byId('delete-page').click();
  byId('undo').click();
  assert.equal(byId('page-label').textContent, '페이지 3 / 3');
  byId('redo').click();
  assert.equal(byId('page-label').textContent, '페이지 2 / 2');
  await save();
  byId('preview').click();
  await waitFor(() => byId('preview-count').textContent === '2페이지', 'parameterized preview');
  assert.equal(byId('preview-frame').getAttribute('sandbox'), '', 'preview has no script/navigation capabilities');
  assert.equal(requests.find(request => request.url.endsWith('/preview/')).body.parameters.min_salary, 100.25);
  byId('preview-dialog').close();
  byId('publish').click();
  await waitFor(() => requests.some(request => request.url.endsWith('/publish/')), 'report publication');
  assert.equal(requests.find(request => request.url.endsWith('/publish/')).body.parameters.min_salary, 100.25);
  assert.deepEqual(errors, [], 'no unhandled DOM/script errors');

  const validation = pythonFixture('validate', { definitions, bindings: savedBindings });
  assert(validation.definition_count >= 4);
  assert.equal(validation.row_count, 1, 'real connector honors the parameterized filter');
  t.diagnostic(`${validation.definition_count} UI definitions validated; actual Excel binding and ${validation.page_count}-page rendering passed.`);
});
