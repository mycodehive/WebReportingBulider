(() => {
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
