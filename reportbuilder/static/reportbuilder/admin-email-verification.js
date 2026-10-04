(() => {
  const form = document.getElementById('email-verification-batch');
  if (!form) return;
  const users = JSON.parse(document.getElementById('email-batch-recipients').textContent);
  const tbody = document.querySelector('#email-batch-results tbody');
  const status = document.getElementById('email-batch-status');
  const stopButton = document.getElementById('email-batch-stop');
  let stopped = false;
  stopButton.addEventListener('click', () => {
    stopped = true;
    stopButton.disabled = true;
    status.textContent = '현재 요청이 끝나면 나머지 발송을 중지합니다.';
  });
  const cells = users.map(user => {
    const row = document.createElement('tr');
    for (const text of [user.username, user.email, '대기']) {
      const cell = document.createElement('td');
      cell.textContent = text;
      row.appendChild(cell);
    }
    tbody.appendChild(row);
    return row.lastElementChild;
  });
  (async () => {
    let done = 0, sent = 0, skipped = 0, failed = 0;
    for (let i = 0; i < users.length; i++) {
      if (stopped) break;
      cells[i].textContent = '발송 중…';
      try {
        const body = new FormData(form);
        body.set('user_id', users[i].id);
        const response = await fetch(form.dataset.sendUrl, {
          method: 'POST', body, credentials: 'same-origin', redirect: 'error',
        });
        const result = await response.json();
        if (result.status === 'sent') sent++;
        else if (['verified', 'skipped'].includes(result.status)) skipped++;
        else failed++;
        cells[i].textContent = result.message || '발송 결과를 확인할 수 없습니다.';
        if (!response.ok) stopped = true;
      } catch {
        failed++;
        stopped = true;
        cells[i].textContent = '결과 확인 실패 · 중복 발송을 막기 위해 중지했습니다. 60초 후 다시 선택하세요.';
      }
      done++;
      status.textContent = `${done}/${users.length}명 처리 · 발송 ${sent}명 · 제외 ${skipped}명 · 실패 ${failed}명`;
    }
    if (stopped) cells.slice(done).forEach(cell => { cell.textContent = '발송하지 않음'; });
    stopButton.disabled = true;
    status.textContent += stopped ? ' · 중지됨' : ' · 처리 완료';
  })();
})();
