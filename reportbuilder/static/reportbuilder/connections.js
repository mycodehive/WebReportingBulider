(() => {
 document.addEventListener('submit', event => {
  const button = event.target.querySelector('[data-connection-delete]');
  if (!button) return;
  const name = button.dataset.connectionDelete;
  if (!window.confirm(`“${name}” 연결을 삭제할까요? 이 연결을 사용하는 보고서는 데이터 연결을 다시 매핑해야 합니다.`)) {
   event.preventDefault();
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
