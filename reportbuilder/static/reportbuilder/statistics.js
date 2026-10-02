/* Report analytics dialog. API values are always text, never executable HTML. */
(() => {
  'use strict';
  const dialog = document.getElementById('statistics-dialog');
  if (!dialog) return;
  const byId = id => document.getElementById(id);
  const form = byId('statistics-filter-form');
  const exports = [...dialog.querySelectorAll('[data-statistics-export]')];
  const events = { view: '조회', execute: '실행', embed: '임베드' };
  const devices = { desktop: '데스크톱', mobile: '모바일', tablet: '태블릿', bot: '봇', unknown: '미확인' };
  const browsers = { chrome: 'Chrome', edge: 'Edge', firefox: 'Firefox', safari: 'Safari', opera: 'Opera', other: '기타', unknown: '미확인' };
  let reportId = null, opener = null, sequence = 0, downloadSequence = 0;
  let requestController = null, downloadController = null, appliedQuery = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function count(value) {
    const result = Number(value);
    return Number.isFinite(result) && result >= 0 ? result : 0;
  }

  const number = value => count(value).toLocaleString('ko-KR');
  let regionNames = null;
  try { regionNames = new Intl.DisplayNames(['ko'], { type: 'region' }); } catch { /* Code labels remain usable. */ }
  function countryLabel(value) {
    if (value === 'Unknown' || !value) return '미확인';
    if (value === 'Private') return '사설·예약 주소';
    if (/^[A-Z]{2}$/.test(value)) {
      const name = regionNames?.of(value);
      return name && name !== value ? `${name} (${value})` : value;
    }
    return String(value);
  }

  function showError(message) {
    byId('statistics-error').textContent = String(message);
    byId('statistics-error').hidden = false;
  }

  function clearError() {
    byId('statistics-error').hidden = true;
    byId('statistics-error').textContent = '';
  }

  function setExportState(enabled) {
    exports.forEach(button => { button.disabled = !enabled; });
  }

  function todayInSeoul() {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(new Date());
    const value = name => parts.find(part => part.type === name).value;
    return `${value('year')}-${value('month')}-${value('day')}`;
  }

  function resetFilters() {
    form.reset();
    const end = todayInSeoul();
    const start = new Date(`${end}T12:00:00Z`);
    start.setUTCDate(start.getUTCDate() - 29);
    form.elements.start.value = start.toISOString().slice(0, 10);
    form.elements.end.value = end;
  }

  function filterQuery() {
    const query = new URLSearchParams();
    for (const name of ['start', 'end', 'event', 'country', 'device', 'browser']) {
      let value = form.elements[name].value.trim();
      if (name === 'country' && value && !['Unknown', 'Private'].includes(value)) value = value.toUpperCase();
      if (value) query.set(name, value);
    }
    const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '')
      && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
      && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
    if (!validDate(query.get('start')) || !validDate(query.get('end'))) throw new Error('시작일과 종료일을 올바르게 입력하세요.');
    if (query.get('start') > query.get('end')) throw new Error('시작일은 종료일보다 늦을 수 없습니다.');
    if (query.has('country') && !/^(?:[A-Z]{2}|Unknown|Private)$/.test(query.get('country'))) {
      throw new Error('국가는 두 자리 코드(KR 등), Unknown 또는 Private을 입력하세요.');
    }
    return query;
  }

  async function responseError(response, fallback) {
    const data = await response.json().catch(() => ({}));
    const message = data.message || data.error?.message || data.detail || data.error;
    return new Error(typeof message === 'string' ? message : `${fallback} (${response.status})`);
  }

  function renderKPIs(data) {
    const eventCounts = Object.fromEntries((data.event_counts || []).map(item => [item.event, item.count]));
    const container = byId('statistics-kpis');
    container.replaceChildren();
    for (const [key, label, value] of [
      ['total', '전체 이용 건수', data.total], ['view', '조회', eventCounts.view],
      ['execute', '실행', eventCounts.execute], ['embed', '임베드', eventCounts.embed],
    ]) {
      const card = element('div', 'statistics-kpi');
      card.dataset.statKpi = key;
      card.append(element('span', 'statistics-kpi-label', label), element('strong', '', number(value)));
      container.append(card);
    }
  }

  function renderDaily(data) {
    const items = Array.isArray(data.daily) ? data.daily : [];
    const container = byId('statistics-daily-chart');
    const rows = byId('statistics-daily-rows');
    container.replaceChildren();
    rows.replaceChildren();
    for (const item of items) {
      const row = element('tr');
      row.append(element('td', '', item.date), element('td', 'statistics-number', number(item.count)));
      rows.append(row);
    }
    if (!items.length) { container.append(element('p', 'statistics-muted', '표시할 일별 기록이 없습니다.')); return; }
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 760 185');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `일별 이용 추이. ${items.length}일, ${number(data.total)}건. 아래 일별 수치 보기에서 상세 값을 확인하세요.`);
    const max = Math.max(1, ...items.map(item => count(item.count)));
    const graphLeft = 38, graphWidth = 710, graphTop = 18, graphHeight = 130;
    const step = graphWidth / items.length;
    const svgElement = (tag, attributes, text) => {
      const result = document.createElementNS(ns, tag);
      Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, String(value)));
      if (text !== undefined) result.textContent = String(text);
      return result;
    };
    for (const ratio of [0, .5, 1]) {
      const y = graphTop + graphHeight * (1 - ratio);
      svg.append(svgElement('line', { x1: graphLeft, y1: y, x2: graphLeft + graphWidth, y2: y, class: 'statistics-grid-line' }));
      svg.append(svgElement('text', { x: graphLeft - 7, y: y + 3, 'text-anchor': 'end', class: 'statistics-axis-label' }, number(Math.round(max * ratio))));
    }
    items.forEach((item, index) => {
      const height = count(item.count) / max * graphHeight;
      const rect = svgElement('rect', { x: graphLeft + index * step + step * .18,
        y: graphTop + graphHeight - height, width: Math.max(.2, step * .64), height,
        rx: Math.min(3, step * .15), class: 'statistics-chart-bar' });
      rect.append(svgElement('title', {}, `${item.date}: ${number(item.count)}건`));
      svg.append(rect);
    });
    for (const index of [...new Set([0, Math.floor((items.length - 1) / 2), items.length - 1])]) {
      svg.append(svgElement('text', { x: graphLeft + (index + .5) * step, y: 171,
        'text-anchor': index === 0 ? 'start' : index === items.length - 1 ? 'end' : 'middle',
        class: 'statistics-axis-label' }, String(items[index].date).slice(5)));
    }
    container.append(svg);
  }

  function renderBreakdown(containerId, items, key, label) {
    const container = byId(containerId);
    container.replaceChildren();
    if (!Array.isArray(items) || !items.length) {
      container.append(element('p', 'statistics-muted', '이용 기록이 없습니다.'));
      return;
    }
    const total = items.reduce((sum, item) => sum + count(item.count), 0);
    const list = element('ul', 'statistics-breakdown-list');
    for (const item of items) {
      const row = element('li', 'statistics-breakdown-item');
      const heading = element('div', 'statistics-breakdown-heading');
      heading.append(element('span', '', label(item[key])), element('strong', '', `${number(item.count)}건`));
      const track = element('div', 'statistics-breakdown-track');
      const bar = element('div', 'statistics-breakdown-bar');
      bar.style.width = `${total ? Math.min(100, count(item.count) / total * 100) : 0}%`;
      track.setAttribute('aria-hidden', 'true');
      track.append(bar);
      row.append(heading, track);
      list.append(row);
    }
    container.append(list);
  }

  function timestamp(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value || '미확인');
    return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
  }

  function renderResults(data, query) {
    renderKPIs(data);
    renderDaily(data);
    renderBreakdown('statistics-country-breakdown', data.countries, 'country', countryLabel);
    renderBreakdown('statistics-device-breakdown', data.devices, 'device', value => devices[value] || String(value));
    renderBreakdown('statistics-browser-breakdown', data.browsers, 'browser', value => browsers[value] || String(value));
    const recent = Array.isArray(data.recent) ? data.recent : [];
    const rows = byId('statistics-recent-rows');
    rows.replaceChildren();
    for (const item of recent) {
      const row = element('tr');
      for (const value of [timestamp(item.timestamp), events[item.event] || item.event, countryLabel(item.country),
        devices[item.device] || item.device, browsers[item.browser] || item.browser, item.os || '미확인']) {
        row.append(element('td', '', value));
      }
      rows.append(row);
    }
    if (!recent.length) {
      const cell = element('td', 'statistics-muted', '조회 조건에 해당하는 이용 기록이 없습니다.');
      cell.colSpan = 6;
      const row = element('tr'); row.append(cell); rows.append(row);
    }
    byId('statistics-empty').hidden = count(data.total) !== 0;
    byId('statistics-recent-note').textContent = data.details_truncated
      ? `전체 ${number(data.details_total)}건 중 최근 ${number(recent.length)}건 표시`
      : `${number(recent.length)}건 표시`;
    byId('statistics-range').textContent = `${data.range?.start || query.get('start')} — ${data.range?.end || query.get('end')} · 한국 시간`;
    const countryOptions = new Set(['KR', 'Unknown', 'Private', ...(data.countries || []).map(item => item.country)]);
    byId('statistics-countries').replaceChildren(...[...countryOptions].filter(value => /^(?:[A-Z]{2}|Unknown|Private)$/.test(value))
      .map(value => { const option = element('option', '', countryLabel(value)); option.value = value; return option; }));
    const geoUnavailable = data.meta?.geolocation?.available === false;
    dialog.querySelector('.statistics-footer-note').textContent = '다운로드에는 현재 조회된 조건이 동일하게 적용됩니다. 이용 건수는 고유 사용자 수가 아닙니다. Private은 사설·예약 주소, Unknown은 공인 주소의 국가를 확인하지 못한 접속입니다.'
      + (geoUnavailable ? ' 국가 정보 데이터가 설치되지 않아 공인 주소의 국가 분류가 제공되지 않습니다.' : '');
  }

  async function loadStatistics() {
    const requestNumber = ++sequence;
    requestController?.abort(); downloadController?.abort(); downloadSequence++;
    appliedQuery = null;
    clearError();
    setExportState(false);
    byId('statistics-results').hidden = true;
    const controller = new AbortController();
    requestController = controller;
    const currentReport = reportId;
    let query;
    try { query = filterQuery(); } catch (error) {
      byId('statistics-status').textContent = ''; showError(error.message); return;
    }
    byId('statistics-status').textContent = '이용 기록을 불러오는 중입니다…';
    byId('statistics-results').setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(`/reports/${encodeURIComponent(currentReport)}/statistics/?${query}`, {
        credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal,
      });
      if (!response.ok) throw await responseError(response, '통계를 조회하지 못했습니다.');
      const data = await response.json().catch(() => { throw new Error('통계 데이터를 읽지 못했습니다. 로그인 상태를 확인하고 다시 조회하세요.'); });
      if (requestNumber !== sequence || !dialog.open || controller.signal.aborted) return;
      renderResults(data, query);
      appliedQuery = query.toString();
      byId('statistics-results').hidden = false;
      byId('statistics-status').textContent = `${number(data.total)}건의 이용 기록을 조회했습니다.`;
      setExportState(true);
    } catch (error) {
      if (requestNumber !== sequence || controller.signal.aborted || error.name === 'AbortError') return;
      byId('statistics-status').textContent = '';
      showError(error.message || '통계 조회 중 오류가 발생했습니다. 다시 조회해 주세요.');
    } finally {
      if (requestNumber === sequence) byId('statistics-results').setAttribute('aria-busy', 'false');
    }
  }

  async function download(format) {
    if (!appliedQuery || !dialog.open) return;
    const downloadNumber = ++downloadSequence, currentSequence = sequence;
    downloadController?.abort();
    const controller = new AbortController(); downloadController = controller;
    setExportState(false); clearError();
    byId('statistics-status').textContent = `${format === 'xlsx' ? 'Excel' : 'PDF'} 파일을 만드는 중입니다…`;
    try {
      const response = await fetch(`/reports/${encodeURIComponent(reportId)}/statistics/export/${format}/?${appliedQuery}`, {
        credentials: 'same-origin', signal: controller.signal,
      });
      if (!response.ok) throw await responseError(response, '통계 파일을 다운로드하지 못했습니다.');
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('json') || contentType.includes('text/html')) throw await responseError(response, '올바른 통계 파일을 받지 못했습니다.');
      const blob = await response.blob();
      if (downloadNumber !== downloadSequence || currentSequence !== sequence || !dialog.open || controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const query = new URLSearchParams(appliedQuery);
      const anchor = element('a');
      anchor.href = url;
      anchor.download = `report-statistics-${query.get('start')}-${query.get('end')}.${format}`;
      document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      byId('statistics-status').textContent = '조회된 조건의 통계 파일을 다운로드했습니다.';
    } catch (error) {
      if (downloadNumber !== downloadSequence || controller.signal.aborted || error.name === 'AbortError') return;
      byId('statistics-status').textContent = '';
      showError(error.message || '파일 생성 중 오류가 발생했습니다. 다시 시도해 주세요.');
    } finally {
      if (downloadNumber === downloadSequence && currentSequence === sequence && dialog.open) setExportState(Boolean(appliedQuery));
    }
  }

  function cleanup() {
    sequence++; downloadSequence++;
    requestController?.abort(); downloadController?.abort();
    appliedQuery = null;
    byId('statistics-results').setAttribute('aria-busy', 'false');
    if (opener?.isConnected) opener.focus();
  }

  function closeDialog() { dialog.close(); cleanup(); }
  byId('statistics-close').addEventListener('click', closeDialog);
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
  dialog.addEventListener('close', () => { if (!dialog.open) cleanup(); });
  form.addEventListener('submit', event => { event.preventDefault(); loadStatistics(); });
  byId('statistics-reset').addEventListener('click', () => { resetFilters(); loadStatistics(); });
  exports.forEach(button => button.addEventListener('click', () => download(button.dataset.statisticsExport)));
  document.querySelectorAll('[data-report-statistics]').forEach(button => {
    button.addEventListener('click', () => {
      opener = button; reportId = button.dataset.reportStatistics;
      byId('statistics-title').textContent = `${button.dataset.reportName || '보고서'} · 이용 통계`;
      resetFilters();
      if (!dialog.open) dialog.showModal();
      byId('statistics-close').focus();
      loadStatistics();
    });
  });
})();
