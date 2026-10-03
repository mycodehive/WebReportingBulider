(() => {
 const dialog = document.getElementById('cover-dialog');
 if (!dialog) return;
 const form = document.getElementById('cover-form'), image = document.getElementById('cover-preview');
 const file = document.getElementById('cover-file');
 let opener, previewUrl;
 for (const button of document.querySelectorAll('[data-report-cover]')) button.addEventListener('click', () => {
  opener = button; form.reset();
  form.action = `/reports/${button.dataset.reportCover}/cover/`;
  document.getElementById('cover-name').textContent = button.dataset.reportName;
  image.hidden = !button.dataset.coverUrl; image.src = button.dataset.coverUrl || '';
  document.getElementById('cover-remove').hidden = !button.dataset.coverUrl;
  dialog.showModal();
 });
 file.addEventListener('change', () => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  if (!file.files[0]) { image.hidden = true; return; }
  previewUrl = URL.createObjectURL(file.files[0]); image.src = previewUrl; image.hidden = false;
 });
 document.getElementById('cover-close').onclick = () => dialog.close();
 document.getElementById('cover-remove').onclick = () => { file.required = false; };
 dialog.addEventListener('close', () => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null; image.removeAttribute('src'); form.reset(); file.required = true; opener?.focus();
 });
})();
