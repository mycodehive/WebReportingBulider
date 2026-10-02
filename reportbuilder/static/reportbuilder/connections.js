(() => {
 for (const badge of document.querySelectorAll('[data-status]')) {
  if (badge.textContent.trim() === '연결 확인됨') badge.dataset.state = 'success';
 }
 for (const button of document.querySelectorAll('[data-test-connection]')) {
  button.addEventListener('click', async () => {
   if (button.disabled) return;
   const id = button.dataset.testConnection;
   const area = document.getElementById(`connection-result-${id}`);
   const badge = document.querySelector(`[data-status="${id}"]`);
   const label = button.textContent;
   button.disabled = true;
   button.setAttribute('aria-busy', 'true');
   button.textContent = '테스트 중…';
   area.dataset.state = 'pending';
   area.textContent = `${button.dataset.connectionName}: 연결을 확인하고 있습니다.`;
   try {
    await window.reportRequest(`/api/connections/${id}/test/`, {});
    badge.textContent = '연결 확인됨';
    badge.dataset.state = 'success';
    area.dataset.state = 'success';
    area.textContent = '연결 및 데이터 접근을 확인했습니다.';
   } catch (error) {
    badge.textContent = '테스트 실패';
    badge.dataset.state = 'error';
    area.dataset.state = 'error';
    area.textContent = `${error.message} 연결 설정을 확인한 뒤 다시 테스트하세요.`;
   } finally {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = label;
   }
  });
 }
 for (const button of document.querySelectorAll('[data-cancel-edit]')) {
  button.addEventListener('click', () => {
   const details = button.closest('details');
   details.querySelector('form').reset();
   details.open = false;
   details.querySelector('summary').focus();
  });
 }
 document.addEventListener('submit', event => {
  const form = event.target;
  const button = event.target.querySelector('[data-connection-delete]');
  if (form.dataset.submitting) {
   event.preventDefault();
   return;
  }
  if (button && !window.confirm(`“${button.dataset.connectionDelete}” 연결을 삭제할까요? 이 연결을 사용하는 보고서는 데이터 연결을 다시 매핑해야 합니다.`)) {
   event.preventDefault();
   return;
  }
  if (!form.closest('.connections-page')) return;
  form.dataset.submitting = 'true';
  const submit = event.submitter || form.querySelector('button[type="submit"]');
  if (submit) {
   submit.disabled = true;
   submit.setAttribute('aria-busy', 'true');
   submit.dataset.submitLabel = submit.textContent;
   submit.textContent = button ? '삭제 중…' : '처리 중…';
  }
 });
 window.addEventListener('pageshow', () => {
  for (const form of document.querySelectorAll('.connections-page form[data-submitting]')) {
   delete form.dataset.submitting;
   for (const button of form.querySelectorAll('[data-submit-label]')) {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent = button.dataset.submitLabel;
    delete button.dataset.submitLabel;
   }
  }
 });
 const kind = document.getElementById('connection-kind');
 if (!kind) return;
 function update() {
  const sheets = kind.value === 'sheets';
  document.getElementById('sheets-options').hidden = !sheets;
  document.getElementById('sheet-url').required = sheets;
  document.getElementById('connection-json').hidden = sheets;
  for (const input of document.querySelectorAll('#sheets-options input, #sheets-options select')) input.disabled = !sheets;
 }
 kind.addEventListener('change', update);
 update();
})();
