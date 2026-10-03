(() => {
  const dialog = document.getElementById('share-dialog');
  if (!dialog) return;
  const el = id => document.getElementById(id);
  let reportId, opener, generation = 0;
  const api = (data, method = 'GET') => window.reportRequest(`/reports/${reportId}/shares/`, data, method);
  const formatTime = value => value ? new Intl.DateTimeFormat('ko-KR', {dateStyle:'medium', timeStyle:'short', timeZone:'Asia/Seoul'}).format(new Date(value)) : '';
  function renderList(rows) {
    el('share-list').replaceChildren();
    if (!rows.length) { el('share-list').textContent = '생성한 공유 링크가 없습니다.'; return; }
    for (const row of rows) {
      const item = document.createElement('div'); item.className = 'card'; item.style.marginBottom = '8px';
      const text = document.createElement('p');
      text.textContent = `${row.status} · ${row.password_protected ? '비밀번호 보호' : '비밀번호 없음'} · ${formatTime(row.starts_at) || '즉시'} ~ ${formatTime(row.ends_at) || '기간 제한 없음'} (한국 시간)`;
      item.append(text);
      if (!row.revoked) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'button button-danger'; button.textContent = '공유 해제';
        button.addEventListener('click', async () => {
          const current = generation; button.disabled = true;
          try { await api({id:row.id}, 'DELETE'); if (current !== generation) return; el('share-result').hidden = true; el('share-status').textContent = '공유를 해제했습니다.'; await refresh(current); }
          catch (_) { if (current === generation) { el('share-status').textContent = '공유 해제에 실패했습니다. 다시 시도하세요.'; button.disabled = false; } }
        }); item.append(button);
      }
      el('share-list').append(item);
    }
  }
  async function refresh(current, parameters = false) {
    const data = await api(); if (current !== generation) return;
    renderList(data.shares);
    if (parameters) {
      el('share-parameters').replaceChildren();
      for (const p of data.parameters) {
        const label = document.createElement('label'); label.className = 'field'; label.textContent = p.label || p.name;
        const input = document.createElement('input'); input.className = 'input'; input.name = p.name;
        input.type = p.type === 'date' ? 'date' : ['integer','decimal','number'].includes(p.type) ? 'number' : 'text';
        input.step = p.type === 'integer' ? '1' : 'any'; input.required = !!p.required; input.value = p.default ?? '';
        label.append(input); el('share-parameters').append(label);
      }
    }
  }
  for (const button of document.querySelectorAll('[data-share-report]')) button.addEventListener('click', async () => {
    reportId = button.dataset.shareReport; opener = button; const current = ++generation;
    el('share-form').reset(); el('share-dates').hidden = true; el('share-end').required = false;
    el('share-result').hidden = true; el('share-url').value = ''; el('share-parameters').replaceChildren(); el('share-list').replaceChildren();
    el('share-name').textContent = button.dataset.shareName; el('share-status').textContent = '공유 정보를 불러오는 중…';
    el('share-create').disabled = true; dialog.showModal();
    try { await refresh(current, true); if (current === generation) { el('share-create').disabled = false; el('share-status').textContent = ''; } }
    catch (_) { if (current === generation) el('share-status').textContent = '공유 정보를 불러오지 못했습니다. 창을 다시 열어 주세요.'; }
  });
  el('share-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { ++generation; el('share-url').value = ''; el('share-password').value = ''; if (opener) opener.focus(); });
  el('share-period').addEventListener('change', () => { const range = el('share-period').value === 'range'; el('share-dates').hidden = !range; el('share-end').required = range; });
  el('share-form').addEventListener('submit', async event => {
    event.preventDefault(); const current = generation; el('share-create').disabled = true;
    const range = el('share-period').value === 'range';
    const kst = id => range && el(id).value ? el(id).value + ':00+09:00' : null;
    try {
      const data = await api({starts_at:kst('share-start'), ends_at:kst('share-end'), password:el('share-password').value, parameters:Object.fromEntries(new FormData(event.currentTarget))}, 'POST');
      el('share-password').value = '';
      if (current !== generation) return;
      el('share-url').value = data.url; el('share-result').hidden = false; el('share-status').textContent = '공유 링크를 생성했습니다.';
      await refresh(current);
    } catch (error) { if (current === generation) el('share-status').textContent = error.message; }
    finally { if (current === generation) el('share-create').disabled = false; }
  });
  el('share-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(el('share-url').value); el('share-status').textContent = '링크를 복사했습니다.'; }
    catch (_) { el('share-url').focus(); el('share-url').select(); el('share-status').textContent = '선택한 링크를 Ctrl+C 또는 복사 메뉴로 복사하세요.'; }
  });
})();
